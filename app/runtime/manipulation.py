"""Jumps and market events (Phase 3 SD23; AC19, AC26, AC27).

A **jump** is `schedule_jump` (version + 1, no `tick_index` move) and its `jump`
tick, in one transaction. It broadcasts nothing: the price moves from the next
tick, which carries a higher version (plan PD13).

A **market event** is one transaction that:

1. ends any active event at `now` (its `t_end_ms` rewritten), emitting its end;
2. schedules a jump per active drink (never a removed one) to its `p_min`, `p_max` or `p0`
   (`target_cents`), writing one `jump` tick per jump -- each `schedule_jump` is
   an accepted transition with its own version (Phase 2 SD10, one row each);
3. inserts the `market_event` row;
4. inserts v1's Dutch news item, level lowercased (`NEWS_FOR_KIND`).

It emits `MarketEventStarted` and `NewsChanged` after commit. Any failure
writes none of it (AC27).

Targets are cents; the engine takes euros, `cents / 100` -- the same exact
float `spec_from_rows` builds the bounds from.
"""

from __future__ import annotations

import dataclasses
from typing import Final, cast

from app.db.codec import tick_prices
from app.db.engine_state import compare_and_set, insert_tick
from app.db.market_events import end_event, insert_event
from app.db.news import NewsItem, NewsLevel, create_news
from app.db.runs import active_drinks
from app.runtime.clock import Clock
from app.runtime.history import TickEntry
from app.runtime.holder import (
    MarketEventEnded,
    MarketEventStarted,
    MarketHolder,
    MarketView,
    NewsChanged,
    Outcome,
)
from app.runtime.market_events import NEWS_FOR_KIND, ActiveEvent, EventKind, target_cents
from exchange import schedule_jump

DEFAULT_EVENT_MS: Final = 30_000


async def schedule(
    holder: MarketHolder, drink_id: int, target_cents_: int, duration_ms: int, *, clock: Clock
) -> int:
    """One jump; the new version. The caller has validated the bounds (T25's route)."""
    engine = holder.engine

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id is not None and view.spec is not None and view.state is not None
        now_ms = clock.wall_ms()
        candidate = schedule_jump(
            view.spec,
            view.state,
            drink=view.drink_ids.index(drink_id),
            p_target=target_cents_ / 100,
            duration_ms=duration_ms,
            now_ms=now_ms,
        )
        entry = TickEntry(
            version=candidate.version,
            wall_ts_ms=now_ms,
            source="jump",
            prices=tick_prices(view.spec, candidate, view.drink_ids),
        )
        async with engine.begin() as conn:
            await compare_and_set(
                conn,
                run_id=view.run_id,
                expected_version=view.state.version,
                state=candidate,
                drink_ids=view.drink_ids,
                wall_ts_ms=now_ms,
            )
            await insert_tick(
                conn,
                run_id=view.run_id,
                state=candidate,
                spec=view.spec,
                drink_ids=view.drink_ids,
                source="jump",
                wall_ts_ms=now_ms,
            )
        return Outcome(
            result=candidate.version,
            view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
            ticks=(entry,),
        )

    return await holder.mutate("jump", step)


async def start_event(
    holder: MarketHolder, kind: EventKind, duration_ms: int, *, clock: Clock
) -> ActiveEvent:
    """One market event, replacing any active one; the new event."""
    engine = holder.engine

    async def step(view: MarketView) -> Outcome[ActiveEvent]:
        assert view.run_id is not None and view.spec is not None and view.state is not None
        run_id, spec = view.run_id, view.spec
        now_ms = clock.wall_ms()
        state = view.state
        # A removed drink keeps its slot but takes no jump (Phase 6 SD13).
        targets = tuple(d for d, on in zip(view.drink_ids, spec.active, strict=True) if on)
        ticks: list[TickEntry] = []
        async with engine.begin() as conn:
            ended = []
            for active in view.market_events:
                # Ends after it started even if the wall clock has not moved past its start.
                t_end_ms = max(now_ms, active.t_start_ms + 1)
                await end_event(conn, active.event_id, t_end_ms=t_end_ms)
                ended.append(dataclasses.replace(active, t_end_ms=t_end_ms))
            rows = {row.drink_id: row for row in await active_drinks(conn, run_id)}
            for drink_id in targets:
                before = state
                state = schedule_jump(
                    spec,
                    state,
                    drink=view.drink_ids.index(drink_id),
                    p_target=target_cents(kind, rows[drink_id]) / 100,
                    duration_ms=duration_ms,
                    now_ms=now_ms,
                )
                await compare_and_set(
                    conn,
                    run_id=run_id,
                    expected_version=before.version,
                    state=state,
                    drink_ids=view.drink_ids,
                    wall_ts_ms=now_ms,
                )
                await insert_tick(
                    conn,
                    run_id=run_id,
                    state=state,
                    spec=spec,
                    drink_ids=view.drink_ids,
                    source="jump",
                    wall_ts_ms=now_ms,
                )
                ticks.append(
                    TickEntry(
                        state.version, now_ms, "jump", tick_prices(spec, state, view.drink_ids)
                    )
                )
            event_id = await insert_event(
                conn,
                run_id=run_id,
                kind=kind,
                drink_ids=targets,
                t_start_ms=now_ms,
                t_end_ms=now_ms + duration_ms,
            )
            news = NEWS_FOR_KIND[kind]
            level = cast(NewsLevel, news.level)
            news_id = await create_news(conn, run_id, ts_ms=now_ms, level=level, text=news.text)
        event = ActiveEvent(
            event_id=event_id,
            kind=kind,
            drink_ids=targets,
            t_start_ms=now_ms,
            t_end_ms=now_ms + duration_ms,
        )
        item = NewsItem(news_id=news_id, ts_ms=now_ms, level=level, text=news.text)
        return Outcome(
            result=event,
            view=dataclasses.replace(
                view,
                state=state,
                last_commit_wall_ms=now_ms,
                market_events=(event,),
                news=(*view.news, item),
            ),
            events=(
                *(MarketEventEnded(run_id=run_id, version=state.version, event=e) for e in ended),
                MarketEventStarted(run_id=run_id, version=state.version, event=event),
                NewsChanged(run_id=run_id, version=state.version, op="add", item=item),
            ),
            ticks=tuple(ticks),
        )

    return await holder.mutate("market_event", step)
