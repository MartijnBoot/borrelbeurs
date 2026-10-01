"""Boot: rebuild the live run's in-memory market from Postgres (D-01, D-30).

`rehydrate` reads, in one REPEATABLE READ transaction so every read sees the
same snapshot: the live run, its active drinks, the engine state keyed by
`drink_id`, the price ticks in the history window, the earnings aggregate and
the news. Then it applies the gap rule (SD2). Only if that returns a state is
anything written: one compare-and-set `save_transition` with `source = 'gap'`,
in its own transaction, so a concurrent writer surfaces as `StaleState`. The gap
tick joins the ring only after that commits.

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
from app.db.engine_state import load_state, load_ticks_in_window, save_transition
from app.db.mapping import spec_from_rows
from app.db.models import Run
from app.db.news import NewsItem, list_news
from app.db.orders import earnings_by_drink
from app.db.runs import active_drinks
from app.runtime.earnings import EarningsAggregate
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS, apply_gap_rule
from app.runtime.history import HistoryRing, TickEntry
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


async def rehydrate(
    engine: AsyncEngine, *, now_ms: int, budget_ms: int = DEFAULT_CATCH_UP_BUDGET_MS
) -> RehydratedRun | NoLiveRun:
    """The live run as it was last committed, with the gap rule applied at `now_ms`."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="REPEATABLE READ")
        async with conn.begin():
            run = (
                await conn.execute(
                    select(Run.run_id, Run.run_seed, Run.params).where(Run.status == "live")
                )
            ).one_or_none()
            if run is None:
                return NoLiveRun()
            run_id = int(run.run_id)
            params = Params.from_dict(run.params)

            drinks = await active_drinks(conn, run_id)
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

    shifted = apply_gap_rule(state, last_wall_ts_ms=wall_ts_ms, now_ms=now_ms, budget_ms=budget_ms)
    if shifted is not None:
        await save_transition(
            engine,
            run_id=run_id,
            expected_version=state.version,
            state=shifted,
            spec=spec,
            drink_ids=drink_ids,
            source="gap",
            wall_ts_ms=now_ms,
        )
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
    )
