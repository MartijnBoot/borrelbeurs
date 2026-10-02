"""`MarketHolder` (Phase 3 T13: SD12, SD22; AC14; PD11, PD21)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Sequence

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import load_state, save_transition
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.history import TickEntry
from app.runtime.holder import (
    DomainEvent,
    MarketHolder,
    MarketView,
    NoLiveRunError,
    Outcome,
    PersistenceUnavailable,
    TickCommitted,
)
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import Params, advance
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000


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


class RecordingSink:
    """AC14: fails the test if it is ever called while the holder's lock is held."""

    def __init__(self) -> None:
        self.holder: MarketHolder | None = None
        self.calls: list[tuple[DomainEvent, ...]] = []

    def __call__(self, events: Sequence[DomainEvent]) -> None:
        assert self.holder is not None
        assert not self.holder.lock.locked(), "the sink was called under the lock"
        self.calls.append(tuple(events))


def _holder(
    engine: AsyncEngine, run: RehydratedRun, clock: FakeClock
) -> tuple[MarketHolder, RecordingSink]:
    sink = RecordingSink()
    holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=sink)
    sink.holder = holder
    return holder, sink


def _tick_step(
    holder: MarketHolder, now_ms: int, *, before_commit: float = 0.0
) -> Callable[[MarketView], Awaitable[Outcome[int]]]:
    """A tick as the ticker (T16) will run it: advance, one transaction, the new view."""

    async def step(view: MarketView) -> Outcome[int]:
        assert view.spec is not None and view.state is not None and view.run_id is not None
        candidate = advance(view.spec, view.state, now_ms=now_ms, run_seed=view.run_seed).state
        if before_commit:
            async with holder.engine.connect() as conn:
                await conn.execute(text("SELECT pg_sleep(:s)"), {"s": before_commit})
        await save_transition(
            holder.engine,
            run_id=view.run_id,
            expected_version=view.state.version,
            state=candidate,
            spec=view.spec,
            drink_ids=view.drink_ids,
            source="tick",
            wall_ts_ms=now_ms,
        )
        entry = TickEntry(
            version=candidate.version,
            wall_ts_ms=now_ms,
            source="tick",
            prices=tick_prices(view.spec, candidate, view.drink_ids),
        )
        return Outcome(
            result=candidate.version,
            view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
            events=(TickCommitted(run_id=view.run_id, entry=entry),),
            ticks=(entry,),
        )

    return step


def test_a_mutation_commits_then_publishes_then_calls_the_sink_outside_the_lock(
    settings: Settings, database_url: str
) -> None:
    """SD12, AC14: memory moves only after commit; the sink runs after release."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            holder, sink = _holder(engine, run, FakeClock(T0))
            before = holder.state

            version = await holder.mutate("tick", _tick_step(holder, T0 + 1_000))

            assert before is not None and holder.state is not None and holder.run_id is not None
            assert holder.state is not before
            assert version == holder.state.version == before.version + 1
            assert holder.last_commit_wall_ms == T0 + 1_000
            assert holder.ring[-1].version == version
            async with engine.connect() as conn:
                stored = await load_state(conn, holder.run_id, holder.drink_ids)
            assert stored is not None and stored[0].version == version
            assert [[type(e).__name__ for e in call] for call in sink.calls] == [["TickCommitted"]]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_step_that_raises_leaves_memory_unchanged_and_releases_the_lock(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            holder, sink = _holder(engine, run, FakeClock(T0))
            before_state, before_ring = holder.state, holder.ring

            async def failing(view: MarketView) -> Outcome[None]:
                raise ValueError("domain says no")

            with pytest.raises(ValueError, match="domain says no"):
                await holder.mutate("order", failing)

            assert holder.state is before_state
            assert holder.ring == before_ring
            assert not holder.lock.locked()
            assert sink.calls == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_stale_state_becomes_persistence_unavailable_and_memory_is_unchanged(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """PD21: a second writer moved the row; fail closed with 503, log both versions."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            holder, sink = _holder(engine, run, FakeClock(T0))
            before = holder.state
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE engine_state SET version = version + 5"))

            with pytest.raises(PersistenceUnavailable) as excinfo:
                await holder.mutate("tick", _tick_step(holder, T0 + 1_000))

            assert excinfo.value.status_code == 503
            assert excinfo.value.code == "persistence_unavailable"
            assert holder.state is before
            assert sink.calls == []
        finally:
            await engine.dispose()

    with caplog.at_level(logging.ERROR, logger="app.runtime.holder"):
        asyncio.run(scenario())
    (record,) = [r for r in caplog.records if r.getMessage() == "stale_state"]
    assert record.__dict__["op"] == "tick"
    assert record.__dict__["memory_version"] == 0


def test_a_database_error_becomes_persistence_unavailable(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            holder, _ = _holder(engine, run, FakeClock(T0))
            before = holder.state

            async def broken(view: MarketView) -> Outcome[None]:
                async with holder.engine.begin() as conn:
                    await conn.execute(text("SELECT * FROM no_such_table"))
                raise AssertionError("unreachable")

            with pytest.raises(PersistenceUnavailable):
                await holder.mutate("tick", broken)
            assert holder.state is before
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_long_hold_logs_exactly_one_warning_naming_the_op(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """SD22, AC14: 60 ms on the fake clock and a real pg_sleep(0.06) inside the transaction."""
    clock = FakeClock(T0)

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            holder, _ = _holder(engine, run, clock)
            await holder.mutate("quick", _tick_step(holder, T0 + 1_000))
            slow = _tick_step(holder, T0 + 2_000, before_commit=0.06)

            async def slow_step(view: MarketView) -> Outcome[int]:
                clock.advance(60)
                return await slow(view)

            await holder.mutate("order", slow_step)
        finally:
            await engine.dispose()

    with caplog.at_level(logging.WARNING, logger="app.runtime.holder"):
        asyncio.run(scenario())
    warnings = [r for r in caplog.records if r.getMessage() == "lock_hold_ms"]
    assert len(warnings) == 1
    assert warnings[0].__dict__["op"] == "order"
    assert warnings[0].__dict__["lock_hold_ms"] == 60


def test_mutations_queued_behind_the_lock_run_in_arrival_order(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> list[str]:
        engine = _engine(settings, database_url)
        order: list[str] = []
        try:
            run = await _live(engine)
            holder, _ = _holder(engine, run, FakeClock(T0))

            def step_named(name: str):  # type: ignore[no-untyped-def]
                async def step(view: MarketView) -> Outcome[None]:
                    order.append(name)
                    await asyncio.sleep(0)
                    return Outcome(result=None, view=view)

                return step

            await holder.lock.acquire()
            tasks = []
            for name in ("a", "b", "c", "d", "e"):
                tasks.append(asyncio.create_task(holder.mutate(name, step_named(name))))
                await asyncio.sleep(0)
            holder.lock.release()
            await asyncio.gather(*tasks)
            return order
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == ["a", "b", "c", "d", "e"]


def test_every_mutation_on_an_empty_holder_is_no_live_run(
    settings: Settings, database_url: str
) -> None:
    """SD16: no live run is a valid state; mutating it is 409 `no_live_run`."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            holder = MarketHolder.empty(
                engine=engine, clock=FakeClock(T0), sink=lambda events: None
            )
            assert holder.is_empty and holder.run_id is None and holder.state is None

            async def never(view: MarketView) -> Outcome[None]:
                raise AssertionError("a step ran on an empty holder")

            with pytest.raises(NoLiveRunError) as excinfo:
                await holder.mutate("order", never)
            assert (excinfo.value.status_code, excinfo.value.code) == (409, "no_live_run")
            assert not holder.lock.locked()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_the_holder_exposes_the_rehydrated_market_read_only(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run = await _live(engine)
            holder, _ = _holder(engine, run, FakeClock(T0))
            assert (holder.run_id, holder.drink_ids, holder.spec) == (
                run.run_id,
                run.drink_ids,
                run.spec,
            )
            assert holder.state is run.state
            assert holder.quote_grace_versions == 2
            assert holder.candle_interval_ms == 60_000
            assert holder.news == run.news
            assert holder.market_events == ()
            assert holder.earnings == {}
            assert holder.last_commit_wall_ms == T0
            assert [e.source for e in holder.ring] == ["reset"]
            with pytest.raises(AttributeError):
                holder.state = run.state  # type: ignore[misc]
        finally:
            await engine.dispose()

    asyncio.run(scenario())
