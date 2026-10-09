"""Jumps and market events in the runtime (Phase 3 T25: SD23; AC19, AC26, AC27)."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import save_transition
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.history import TickEntry
from app.runtime.holder import (
    DomainEvent,
    MarketEventEnded,
    MarketEventStarted,
    MarketHolder,
    MarketView,
    NewsChanged,
    Outcome,
    PersistenceUnavailable,
)
from app.runtime.manipulation import InvalidJump, schedule, start_event
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import Params, advance
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000


class Market:
    def __init__(self, engine: AsyncEngine, holder: MarketHolder, clock: FakeClock) -> None:
        self.engine, self.holder, self.clock = engine, holder, clock
        self.events: list[DomainEvent] = []

    async def tick(self) -> TickEntry:
        self.clock.advance(1_000)
        now_ms = self.clock.wall_ms()
        engine = self.engine

        async def step(view: MarketView) -> Outcome[TickEntry]:
            assert view.run_id is not None and view.spec is not None and view.state is not None
            candidate = advance(view.spec, view.state, now_ms=now_ms, run_seed=view.run_seed).state
            await save_transition(
                engine,
                run_id=view.run_id,
                expected_version=view.state.version,
                state=candidate,
                spec=view.spec,
                drink_ids=view.drink_ids,
                source="tick",
                wall_ts_ms=now_ms,
            )
            entry = TickEntry(
                candidate.version, now_ms, "tick", tick_prices(view.spec, candidate, view.drink_ids)
            )
            return Outcome(
                entry,
                dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
                ticks=(entry,),
            )

        return await self.holder.mutate("tick", step)

    async def counts(self) -> tuple[Any, ...]:
        async with self.engine.connect() as conn:
            return tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT (SELECT count(*) FROM price_tick),"
                            " (SELECT count(*) FROM market_event),"
                            " (SELECT count(*) FROM news),"
                            " (SELECT row_to_json(e)::text FROM engine_state e)"
                        )
                    )
                ).one()
            )


@asynccontextmanager
async def _market(settings: Settings, url: str) -> AsyncIterator[Market]:
    engine = create_engine(settings.model_copy(update={"database_url": url}))
    clock = FakeClock(T0)
    try:
        async with engine.begin() as conn:
            run_id = await create_draft_run(
                conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
            )
            for slot, (name, lo, p0, hi) in enumerate(
                (("Bier", 150, 260, 500), ("Wijn", 200, 350, 700))
            ):
                await add_drink(
                    conn,
                    run_id,
                    name=name,
                    slot=slot,
                    p_min_cents=lo,
                    p0_cents=p0,
                    p_max_cents=hi,
                    a=1.0,
                    d=0.1,
                    s0=1.0,
                    c=0.1,
                    bar_price_cents=p0,
                )
        await go_live(engine, run_id, now_ms=T0)
        run = await rehydrate(engine, now_ms=T0)
        assert isinstance(run, RehydratedRun)
        market: Market

        def sink(batch: Sequence[DomainEvent]) -> None:
            assert not market.holder.lock.locked()
            market.events.extend(batch)

        market = Market(
            engine, MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=sink), clock
        )
        yield market
    finally:
        await engine.dispose()


def test_a_jump_writes_one_jump_row_at_the_next_version_and_moves_the_price_from_the_next_tick(
    settings: Settings, database_url: str
) -> None:
    """AC26: version + 1, tick_index unchanged, no broadcast; the next tick differs from no-jump."""

    async def scenario() -> tuple[int, int, int, int, float, float]:
        # The no-jump path first, on its own market.
        async with _market(settings, database_url) as plain:
            bier = plain.holder.drink_ids[0]
            no_jump = (await plain.tick()).prices[bier]["p_cont"]
        cleaner = create_engine(settings.model_copy(update={"database_url": database_url}))
        try:
            async with cleaner.begin() as conn:
                await conn.execute(
                    text(
                        'TRUNCATE "order", order_line, price_tick, engine_state, news,'
                        " market_event, drink, run RESTART IDENTITY CASCADE"
                    )
                )
        finally:
            await cleaner.dispose()

        async with _market(settings, database_url) as m:
            bier = m.holder.drink_ids[0]
            assert m.holder.state is not None
            before_version, before_tick = m.holder.state.version, m.holder.state.tick_index
            version = await schedule(m.holder, bier, 480, 5_000, clock=m.clock)
            assert m.holder.state is not None
            tick_index = m.holder.state.tick_index
            async with m.engine.connect() as conn:
                jumps = (
                    await conn.execute(text("SELECT version FROM price_tick WHERE source = 'jump'"))
                ).all()
            assert [int(r[0]) for r in jumps] == [version]
            assert m.events == []  # PD13: a jump broadcasts nothing
            with_jump = (await m.tick()).prices[bier]["p_cont"]
            return before_version, version, before_tick, tick_index, no_jump, with_jump

    before_version, version, before_tick, tick_index, no_jump, with_jump = asyncio.run(scenario())
    assert version == before_version + 1
    assert tick_index == before_tick
    assert with_jump != no_jump


def test_an_event_writes_its_row_the_jumps_and_lowercase_dutch_news(
    settings: Settings, database_url: str
) -> None:
    """AC27, AC19: one jump tick per drink, the event row, the news item; broadcast start + news."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            assert m.holder.state is not None
            before = m.holder.state.version
            ev = await start_event(m.holder, "crash", 30_000, clock=m.clock)

            assert (ev.kind, ev.t_start_ms, ev.t_end_ms) == ("crash", T0, T0 + 30_000)
            assert ev.drink_ids == m.holder.drink_ids
            assert m.holder.state is not None and m.holder.state.version == before + 2
            assert m.holder.market_events == (ev,)
            async with m.engine.connect() as conn:
                ticks = (
                    await conn.execute(
                        text("SELECT version, source FROM price_tick ORDER BY version")
                    )
                ).all()
                events = (
                    await conn.execute(
                        text(
                            "SELECT kind, t_start_ms, t_end_ms, ended_at IS NULL FROM market_event"
                        )
                    )
                ).all()
                news = (await conn.execute(text("SELECT level, text FROM news"))).all()
            assert [(int(r[0]), r[1]) for r in ticks] == [(0, "reset"), (1, "jump"), (2, "jump")]
            assert [tuple(r) for r in events] == [("crash", T0, T0 + 30_000, True)]
            assert [tuple(r) for r in news] == [
                ("danger", "MARKTCRASH! Alle prijzen kelderen naar hun minimum!")
            ]
            assert [type(e).__name__ for e in m.events] == ["MarketEventStarted", "NewsChanged"]
            started = m.events[0]
            assert isinstance(started, MarketEventStarted) and started.event.t_end_ms == T0 + 30_000
            assert m.holder.state.jumps and {j.i for j in m.holder.state.jumps} == {0, 1}

    asyncio.run(scenario())


def test_an_event_skips_a_removed_drink(settings: Settings, database_url: str) -> None:
    """Phase 6 AC18, SD13: jumps and `market_event.drink_ids` cover the active drinks only."""

    async def scenario() -> None:
        async with _market(settings, database_url) as booted:
            bier, wijn = booted.holder.drink_ids
            async with booted.engine.begin() as conn:
                await conn.execute(
                    text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": wijn}
                )
            run = await rehydrate(booted.engine, now_ms=T0)
            assert isinstance(run, RehydratedRun)
            holder = MarketHolder.from_rehydrated(
                run, engine=booted.engine, clock=booted.clock, sink=booted.events.extend
            )
            assert holder.state is not None
            before = holder.state.version

            ev = await start_event(holder, "bubble", 30_000, clock=booted.clock)

            assert ev.drink_ids == (bier,)
            assert holder.state is not None and holder.state.version == before + 1
            assert {j.i for j in holder.state.jumps} == {0}
            async with booted.engine.connect() as conn:
                stored: list[int] = (
                    await conn.execute(text("SELECT drink_ids FROM market_event"))
                ).scalar_one()
            assert stored == [bier]

    asyncio.run(scenario())


def test_a_jump_is_checked_under_the_lock_against_the_live_spec(
    settings: Settings, database_url: str
) -> None:
    """AC6: a removed drink or a target outside the bounds is refused, with nothing written."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier, wijn = m.holder.drink_ids
            before = await m.counts()
            for target in (149, 501):  # Bier's bounds are 150-500, inclusive
                with pytest.raises(InvalidJump):
                    await schedule(m.holder, bier, target, 5_000, clock=m.clock)
            with pytest.raises(InvalidJump):
                await schedule(m.holder, 10_000, 300, 5_000, clock=m.clock)  # not a drink here
            await schedule(m.holder, bier, 500, 5_000, clock=m.clock)  # the bound itself

            async with m.engine.begin() as conn:
                await conn.execute(
                    text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": wijn}
                )
            run = await rehydrate(m.engine, now_ms=T0)
            assert isinstance(run, RehydratedRun)
            holder = MarketHolder.from_rehydrated(
                run, engine=m.engine, clock=m.clock, sink=m.events.extend
            )
            mid = await m.counts()
            with pytest.raises(InvalidJump):
                await schedule(holder, wijn, 300, 5_000, clock=m.clock)
            assert await m.counts() == mid
            assert before[1:3] == mid[1:3]

    asyncio.run(scenario())


def test_each_kind_jumps_to_its_bound(settings: Settings, database_url: str) -> None:
    """Crash to p_min, bubble to p_max, correction to p0: the jumps' end points, in y."""

    async def scenario() -> list[tuple[str, list[int]]]:
        out = []
        async with _market(settings, database_url) as m:
            for kind in ("crash", "bubble", "correction"):
                m.clock.advance(1_000)
                await start_event(m.holder, kind, 1_000, clock=m.clock)
                for _ in range(3):
                    await m.tick()
                out.append(
                    (
                        kind,
                        [
                            round(m.holder.ring[-1].prices[d]["p_q"] * 100)
                            for d in m.holder.drink_ids
                        ],
                    )
                )
        return out

    assert asyncio.run(scenario()) == [
        ("crash", [150, 200]),
        ("bubble", [500, 700]),
        ("correction", [260, 350]),
    ]


def test_a_second_event_first_ends_the_first_with_its_rewritten_end(
    settings: Settings, database_url: str
) -> None:
    """AC19: a new event ends an active one at `now`, and broadcasts that end first."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            first = await start_event(m.holder, "crash", 30_000, clock=m.clock)
            m.clock.advance(5_000)
            m.events.clear()
            second = await start_event(m.holder, "bubble", 10_000, clock=m.clock)

            assert [type(e).__name__ for e in m.events] == [
                "MarketEventEnded",
                "MarketEventStarted",
                "NewsChanged",
            ]
            ended = m.events[0]
            assert isinstance(ended, MarketEventEnded)
            assert (ended.event.event_id, ended.event.t_end_ms) == (first.event_id, T0 + 5_000)
            assert m.holder.market_events == (second,)
            async with m.engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT event_id, t_end_ms, ended_at IS NOT NULL FROM market_event"
                            " ORDER BY event_id"
                        )
                    )
                ).all()
            assert [tuple(r) for r in rows] == [
                (first.event_id, T0 + 5_000, True),
                (second.event_id, T0 + 15_000, False),
            ]

    asyncio.run(scenario())


def test_a_second_event_in_the_same_millisecond_ends_the_first_one_ms_after_its_start(
    settings: Settings, database_url: str
) -> None:
    """AC19: an event always ends after it started, even when `now` has not moved past it."""

    async def scenario() -> tuple[int, int]:
        async with _market(settings, database_url) as m:
            first = await start_event(m.holder, "crash", 30_000, clock=m.clock)
            second = await start_event(m.holder, "bubble", 10_000, clock=m.clock)
            assert m.holder.market_events == (second,)
            async with m.engine.connect() as conn:
                t_end_ms: int = (
                    await conn.execute(
                        text("SELECT t_end_ms FROM market_event WHERE event_id = :id"),
                        {"id": first.event_id},
                    )
                ).scalar_one()
            return first.t_start_ms, t_end_ms

    t_start_ms, t_end_ms = asyncio.run(scenario())
    assert t_end_ms == t_start_ms + 1


@pytest.mark.parametrize(
    "statement", ["INSERT INTO news", "INSERT INTO market_event", "INSERT INTO price_tick"]
)
def test_a_failure_anywhere_in_an_event_writes_none_of_it(
    settings: Settings, database_url: str, statement: str
) -> None:
    """AC27: event row, jump state, ticks and news are one transaction."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            before, state, news = await m.counts(), m.holder.state, m.holder.news

            def fail(*args: Any) -> None:
                if args[2].startswith(statement):
                    raise OSError(f"injected at {statement}")

            event.listen(m.engine.sync_engine, "before_cursor_execute", fail)
            try:
                with pytest.raises(PersistenceUnavailable):
                    await start_event(m.holder, "bubble", 30_000, clock=m.clock)
            finally:
                event.remove(m.engine.sync_engine, "before_cursor_execute", fail)
            assert await m.counts() == before
            assert (
                m.holder.state is state and m.holder.news == news and m.holder.market_events == ()
            )
            assert not any(isinstance(e, MarketEventStarted | NewsChanged) for e in m.events)

    asyncio.run(scenario())
