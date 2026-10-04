"""The ticker (Phase 3 T16: SD13, SD14, SD23 event end; AC18a, AC18b, AC19 end half, AC17)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.engine_state import load_state
from app.db.market_events import active_events, insert_event
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS
from app.runtime.holder import DomainEvent, MarketEventEnded, MarketHolder, TickCommitted
from app.runtime.rehydrate import RehydratedRun, rehydrate
from app.runtime.ticker import Ticker
from exchange import Params
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
INTERVAL = 1_000


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _live(engine: AsyncEngine) -> RehydratedRun:
    async with engine.begin() as conn:
        run_id = await create_draft_run(conn, params=Params(step_quant=0.1), run_seed=7)
        for slot, name in enumerate(("Bier", "Wijn")):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=150,
                p0_cents=260,
                p_max_cents=500,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )
    await go_live(engine, run_id, now_ms=T0)
    result = await rehydrate(engine, now_ms=T0)
    assert isinstance(result, RehydratedRun)
    return result


class Harness:
    def __init__(
        self, engine: AsyncEngine, holder: MarketHolder, ticker: Ticker, clock: FakeClock
    ) -> None:
        self.engine = engine
        self.holder = holder
        self.ticker = ticker
        self.clock = clock
        self.events: list[DomainEvent] = []

    async def settle(self) -> None:
        """Wait (in real time) until the ticker is asleep on the fake clock again."""
        for _ in range(2_000):
            await asyncio.sleep(0.005)
            if self.clock.sleepers == 1 and not self.ticker.busy:
                return
        raise AssertionError("the ticker did not settle")

    async def advance(self, ms: int) -> None:
        self.clock.advance(ms)
        await self.settle()

    async def ticks(self) -> list[tuple[int, str, int]]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT version, source, wall_ts_ms FROM price_tick ORDER BY version")
            )
            return [(int(r[0]), str(r[1]), int(r[2])) for r in rows]


@asynccontextmanager
async def _running(settings: Settings, url: str, *, empty: bool = False) -> AsyncIterator[Harness]:
    engine = _engine(settings, url)
    clock = FakeClock(T0)
    events: list[DomainEvent] = []

    def sink(batch: Sequence[DomainEvent]) -> None:
        events.extend(batch)

    try:
        if empty:
            holder = MarketHolder.empty(engine=engine, clock=clock, sink=sink)
        else:
            holder = MarketHolder.from_rehydrated(
                await _live(engine), engine=engine, clock=clock, sink=sink
            )
        ticker = Ticker(holder, clock=clock, interval_ms=INTERVAL)
        harness = Harness(engine, holder, ticker, clock)
        harness.events = events
        ticker.start()
        await harness.settle()
        try:
            yield harness
        finally:
            await ticker.stop()
    finally:
        await engine.dispose()


def test_sixty_seconds_write_sixty_tick_rows_on_the_grid(
    settings: Settings, database_url: str
) -> None:
    """AC18a: one row per slot, stamped on the grid, versions without a gap."""

    async def scenario() -> list[tuple[int, str, int]]:
        async with _running(settings, database_url) as h:
            for _ in range(60):
                await h.advance(INTERVAL)
            assert h.holder.state is not None and h.holder.state.version == 60
            assert sum(isinstance(e, TickCommitted) for e in h.events) == 60
            return await h.ticks()

    rows = asyncio.run(scenario())
    ticks = [r for r in rows if r[1] == "tick"]
    assert len(ticks) == 60
    assert [r[0] for r in rows] == list(range(61))  # the reset tick at 0, then 1..60
    assert [r[2] for r in ticks] == [T0 + k * INTERVAL for k in range(1, 61)]


def test_a_stall_within_the_budget_catches_up_with_each_slots_own_stamp(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> list[tuple[int, str, int]]:
        async with _running(settings, database_url) as h:
            for _ in range(5):
                await h.advance(INTERVAL)
            await h.advance(20 * INTERVAL)
            return await h.ticks()

    ticks = [r for r in asyncio.run(scenario()) if r[1] == "tick"]
    assert len(ticks) == 25
    assert [r[2] for r in ticks[5:]] == [T0 + k * INTERVAL for k in range(6, 26)]


def test_a_stall_beyond_the_budget_writes_one_gap_row_and_moves_no_price(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> tuple[list[tuple[int, str, int]], Any, Any]:
        async with _running(settings, database_url) as h:
            for _ in range(5):
                await h.advance(INTERVAL)
            before = h.holder.ring[-1]
            await h.advance(45 * INTERVAL)
            gap = h.holder.ring[-1]
            await h.advance(INTERVAL)
            rows = await h.ticks()
            return rows, before, gap

    rows, before, gap = asyncio.run(scenario())
    assert [r[1] for r in rows].count("gap") == 1
    assert gap.source == "gap" and gap.version == before.version + 1
    assert gap.wall_ts_ms == T0 + 50 * INTERVAL
    assert {d: p["p_cont"] for d, p in gap.prices.items()} == {
        d: p["p_cont"] for d, p in before.prices.items()
    }
    assert rows[-1][1:] == ("tick", T0 + 51 * INTERVAL)  # re-anchored on the gap


def test_a_failed_gap_commit_is_retried_on_the_next_slot_and_moves_no_price(
    settings: Settings, database_url: str
) -> None:
    """AC18a, SD14: a gap that did not commit is still a gap on the next slot, not a tick."""

    async def scenario() -> tuple[list[tuple[int, str, int]], Any, Any]:
        async with _running(settings, database_url) as h:
            for _ in range(5):
                await h.advance(INTERVAL)
            before = h.holder.ring[-1]
            fail = {"armed": True}

            def drop_connection(*args: Any) -> None:
                if fail["armed"] and args[2].startswith("INSERT INTO price_tick"):
                    fail["armed"] = False
                    raise OSError("injected: connection lost")

            event.listen(h.engine.sync_engine, "before_cursor_execute", drop_connection)
            try:
                await h.advance(45 * INTERVAL)
            finally:
                event.remove(h.engine.sync_engine, "before_cursor_execute", drop_connection)
            await h.advance(INTERVAL)
            gap = h.holder.ring[-1]
            await h.advance(INTERVAL)
            return await h.ticks(), before, gap

    rows, before, gap = asyncio.run(scenario())
    assert [r[1] for r in rows[6:]] == ["gap", "tick"]
    assert gap.source == "gap" and gap.version == before.version + 1
    assert gap.wall_ts_ms == T0 + 51 * INTERVAL
    assert {d: p["p_cont"] for d, p in gap.prices.items()} == {
        d: p["p_cont"] for d, p in before.prices.items()
    }


def test_a_wall_clock_jump_re_anchors(settings: Settings, database_url: str) -> None:
    """SD13: wall and monotonic diverging past the budget is treated as a gap."""

    async def scenario() -> list[tuple[int, str, int]]:
        async with _running(settings, database_url) as h:
            await h.advance(INTERVAL)
            h.clock.set_wall(h.clock.wall_ms() + 10 * 60_000)
            await h.advance(INTERVAL)
            await h.advance(INTERVAL)
            return await h.ticks()

    rows = asyncio.run(scenario())
    assert [r[1] for r in rows] == ["reset", "tick", "gap", "tick"]
    assert rows[2][2] == T0 + 2 * INTERVAL + 10 * 60_000
    assert rows[3][2] == rows[2][2] + INTERVAL


def test_a_failed_commit_is_skipped_and_the_next_slot_proceeds(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """AC18b, SD14: memory stays at the last committed row; no retry."""

    async def scenario() -> tuple[int, int, list[tuple[int, str, int]]]:
        async with _running(settings, database_url) as h:
            await h.advance(INTERVAL)
            fail = {"armed": True}

            def drop_connection(*args: Any) -> None:
                if fail["armed"] and args[2].startswith("INSERT INTO price_tick"):
                    fail["armed"] = False
                    raise OSError("injected: connection lost")

            event.listen(h.engine.sync_engine, "before_cursor_execute", drop_connection)
            try:
                await h.advance(INTERVAL)
            finally:
                event.remove(h.engine.sync_engine, "before_cursor_execute", drop_connection)
            assert h.holder.state is not None
            after_failure = h.holder.state.version
            async with h.engine.connect() as conn:
                stored = await load_state(conn, h.holder.run_id or 0, h.holder.drink_ids)
            assert stored is not None
            await h.advance(INTERVAL)
            return after_failure, stored[0].version, await h.ticks()

    with caplog.at_level(logging.ERROR, logger="app.runtime.ticker"):
        memory, stored, rows = asyncio.run(scenario())
    assert memory == stored == 1
    assert [(r[0], r[2]) for r in rows if r[1] == "tick"] == [(1, T0 + 1_000), (2, T0 + 3_000)]
    (record,) = [r for r in caplog.records if r.getMessage() == "tick_commit_failed"]
    assert record.__dict__["version"] == 1


def test_an_event_ending_within_the_next_interval_ends_on_that_slot(
    settings: Settings, database_url: str
) -> None:
    """AC19 (end half): `MarketEventEnded` on the first slot at or after `t_end_ms`."""

    async def scenario() -> tuple[list[DomainEvent], int, int]:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            async with engine.begin() as conn:
                event_id = await insert_event(
                    conn,
                    run_id=run.run_id,
                    kind="crash",
                    drink_ids=run.drink_ids,
                    t_start_ms=T0 - 10_000,
                    t_end_ms=T0 + 2_500,
                )
        finally:
            await engine.dispose()
        async with _running_rehydrated(settings, database_url) as h:
            await h.advance(INTERVAL)
            await h.advance(INTERVAL)
            ended_before = sum(isinstance(e, MarketEventEnded) for e in h.events)
            await h.advance(INTERVAL)
            async with h.engine.connect() as conn:
                still_active = len(await active_events(conn, h.holder.run_id or 0))
            assert ended_before == 0
            assert h.holder.market_events == ()
            return h.events, event_id, still_active

    events, event_id, still_active = asyncio.run(scenario())
    (ended,) = [e for e in events if isinstance(e, MarketEventEnded)]
    assert ended.event.event_id == event_id
    assert ended.event.t_end_ms == T0 + 2_500
    assert still_active == 0


@asynccontextmanager
async def _running_rehydrated(settings: Settings, url: str) -> AsyncIterator[Harness]:
    """A ticker over the live run already in the database."""
    engine = _engine(settings, url)
    clock = FakeClock(T0)
    events: list[DomainEvent] = []
    try:
        run = await rehydrate(engine, now_ms=T0)
        assert isinstance(run, RehydratedRun)
        holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=events.extend)
        ticker = Ticker(holder, clock=clock, interval_ms=INTERVAL)
        harness = Harness(engine, holder, ticker, clock)
        harness.events = events
        ticker.start()
        await harness.settle()
        try:
            yield harness
        finally:
            await ticker.stop()
    finally:
        await engine.dispose()


def test_an_empty_holder_idles_on_the_grid(settings: Settings, database_url: str) -> None:
    """SD16: no live run; the loop still completes iterations (for /healthz) and writes nothing."""

    async def scenario() -> tuple[float | None, list[tuple[int, str, int]]]:
        async with _running(settings, database_url, empty=True) as h:
            for _ in range(3):
                await h.advance(INTERVAL)
            return h.ticker.last_iteration_monotonic, await h.ticks()

    last, rows = asyncio.run(scenario())
    assert last == 3.0
    assert rows == []


def test_stop_during_a_slot_lets_that_slot_commit(settings: Settings, database_url: str) -> None:
    """`stop()` is requested from inside the slot's own INSERT, so the slot is mid-commit."""

    async def scenario() -> tuple[bool, int, list[tuple[int, str, int]]]:
        async with _running(settings, database_url) as h:
            requested: dict[str, Any] = {}

            def stop_mid_slot(*args: Any) -> None:
                if args[2].startswith("INSERT INTO price_tick") and "task" not in requested:
                    requested["busy"] = h.ticker.busy
                    requested["task"] = asyncio.get_running_loop().create_task(h.ticker.stop())

            event.listen(h.engine.sync_engine, "before_cursor_execute", stop_mid_slot)
            try:
                h.clock.advance(INTERVAL)
                for _ in range(2_000):
                    await asyncio.sleep(0.005)
                    if "task" in requested and requested["task"].done():
                        break
            finally:
                event.remove(h.engine.sync_engine, "before_cursor_execute", stop_mid_slot)
            h.clock.advance(INTERVAL)
            await asyncio.sleep(0.05)
            assert h.holder.state is not None
            return requested["busy"], h.holder.state.version, await h.ticks()

    busy, version, rows = asyncio.run(scenario())
    assert busy
    assert version == 1
    assert [r[1] for r in rows] == ["reset", "tick"]  # that slot committed; no later one ran


def test_the_budget_is_adr_0003s() -> None:
    assert DEFAULT_CATCH_UP_BUDGET_MS == 30_000
