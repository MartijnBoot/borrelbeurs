"""Boot: rebuild the live run's in-memory market from Postgres (D-01, D-30).

`rehydrate` reads, in one REPEATABLE READ transaction so every read sees the
same snapshot: the live run, all its drinks (a removed one is an inactive
slot, SD15), the engine state keyed by
`drink_id`, the price ticks in the history window, the earnings aggregate, the
news and the active market events. Then it applies the gap rule (SD2). Only if
that returns a state is anything written, in one transaction of its own: the
compare-and-set of the state, its `gap` tick, and the active events' start and
end moved by the same `gap_shift_ms` as the jump anchors (Phase 3 SD23, AC19a).
A concurrent writer surfaces as `StaleState`. The gap tick joins the ring only
after that commits. An event whose shifted end is already past stays active:
the ticker's first slot ends it.

Nothing here reads a file (AC18), takes a lock, starts a ticker or advances the
engine; those are Phase 3's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.codec import tick_prices
from app.db.engine_state import compare_and_set, insert_tick, load_state, load_ticks_in_window
from app.db.mapping import spec_from_rows
from app.db.market_events import active_events, shift_active_events
from app.db.models import Run
from app.db.news import NewsItem, list_news
from app.db.orders import earnings_by_drink
from app.db.runs import all_drinks
from app.runtime.earnings import EarningsAggregate
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS, apply_gap_rule, gap_shift_ms
from app.runtime.history import HistoryRing, TickEntry
from app.runtime.market_events import ActiveEvent, shift_events
from exchange import EngineState, MarketSpec, Params


@dataclass(frozen=True)
class NoLiveRun:
    """There is no live run to rehydrate (AC7); nothing was written."""


@dataclass(frozen=True)
class RehydratedRun:
    run_id: int
    run_seed: int
    spec: MarketSpec
    state: EngineState
    drink_ids: tuple[int, ...]
    bar_price_cents: Mapping[int, int]
    wall_ts_ms: int
    ring: HistoryRing
    earnings: EarningsAggregate
    news: tuple[NewsItem, ...]
    market_events: tuple[ActiveEvent, ...]
    quote_grace_versions: int
    candle_interval_ms: int


async def rehydrate(
    engine: AsyncEngine, *, now_ms: int, budget_ms: int = DEFAULT_CATCH_UP_BUDGET_MS
) -> RehydratedRun | NoLiveRun:
    """The live run as it was last committed, with the gap rule applied at `now_ms`."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="REPEATABLE READ")
        async with conn.begin():
            run = (
                await conn.execute(
                    select(
                        Run.run_id,
                        Run.run_seed,
                        Run.params,
                        Run.quote_grace_versions,
                        Run.candle_interval_ms,
                    ).where(Run.status == "live")
                )
            ).one_or_none()
            if run is None:
                return NoLiveRun()
            run_id = int(run.run_id)
            params = Params.from_dict(run.params)

            drinks = await all_drinks(conn, run_id)
            spec, drink_ids = spec_from_rows(drinks, params)
            loaded = await load_state(conn, run_id, drink_ids)
            if loaded is None:
                raise LookupError(f"live run {run_id} has no engine_state row")
            state, wall_ts_ms = loaded

            window_ms = round(params.history_window_minutes * 60_000)
            ring = HistoryRing(window_ms)
            ring.load(await load_ticks_in_window(conn, run_id, window_ms))
            earnings = EarningsAggregate.from_rows(await earnings_by_drink(conn, run_id))
            news = await list_news(conn, run_id)
            events = await active_events(conn, run_id)

    gap = {"last_wall_ts_ms": wall_ts_ms, "now_ms": now_ms, "budget_ms": budget_ms}
    shifted = apply_gap_rule(state, **gap)
    shift_ms = gap_shift_ms(**gap)
    if shifted is not None and shift_ms is not None:
        async with engine.begin() as conn:
            await compare_and_set(
                conn,
                run_id=run_id,
                expected_version=state.version,
                state=shifted,
                drink_ids=drink_ids,
                wall_ts_ms=now_ms,
            )
            await insert_tick(
                conn,
                run_id=run_id,
                state=shifted,
                spec=spec,
                drink_ids=drink_ids,
                source="gap",
                wall_ts_ms=now_ms,
            )
            await shift_active_events(conn, run_id, shift_ms)
        events = shift_events(events, shift_ms)
        ring.append(
            TickEntry(
                version=shifted.version,
                wall_ts_ms=now_ms,
                source="gap",
                prices=tick_prices(spec, shifted, drink_ids),
            )
        )
        state, wall_ts_ms = shifted, now_ms

    return RehydratedRun(
        run_id=run_id,
        run_seed=int(run.run_seed),
        spec=spec,
        state=state,
        drink_ids=drink_ids,
        bar_price_cents=MappingProxyType({d.drink_id: d.bar_price_cents for d in drinks}),
        wall_ts_ms=wall_ts_ms,
        ring=ring,
        earnings=earnings,
        news=news,
        market_events=events,
        quote_grace_versions=int(run.quote_grace_versions),
        candle_interval_ms=int(run.candle_interval_ms),
    )
