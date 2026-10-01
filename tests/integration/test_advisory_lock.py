"""The single-writer advisory lock (Phase 3 T9: SD11 lock half; AC18 lock half; PD4, PD5)."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.advisory_lock import ADVISORY_LOCK_KEY, acquire, release, watchdog
from app.db.session import create_engine
from tests.support.clock import FakeClock

START_MS = 1_759_312_800_000


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _holders(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted "
                "AND objid = :key AND database = (SELECT oid FROM pg_database "
                "WHERE datname = current_database())"
            ),
            {"key": ADVISORY_LOCK_KEY},
        )
        return int(result.scalar_one())


def test_the_key_is_a_fixed_named_constant() -> None:
    assert int.from_bytes(b"bbv3", "big") == ADVISORY_LOCK_KEY


def test_a_second_acquire_while_the_first_holds_returns_none(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> tuple[bool, bool, int, bool]:
        first_engine = _engine(settings, database_url)
        second_engine = _engine(settings, database_url)
        try:
            first = await acquire(first_engine)
            second = await acquire(second_engine)
            held = await _holders(second_engine)
            assert first is not None
            await release(first)
            third = await acquire(second_engine)
            reacquired = third is not None
            if third is not None:
                await release(third)
            return first is not None, second is None, held, reacquired
        finally:
            await first_engine.dispose()
            await second_engine.dispose()

    assert asyncio.run(scenario()) == (True, True, 1, True)


def test_a_dropped_lock_connection_trips_the_watchdog_within_one_interval(
    settings: Settings, database_url: str
) -> None:
    """PD5: `pg_terminate_backend` on the holder; `on_lost` fires on the next probe."""

    async def scenario() -> tuple[list[str], list[str]]:
        engine = _engine(settings, database_url)
        killer = _engine(settings, database_url)
        clock = FakeClock(START_MS)
        lost: list[str] = []
        try:
            conn = await acquire(engine)
            assert conn is not None
            pid: int = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            await conn.commit()
            task = asyncio.create_task(
                watchdog(conn, clock=clock, interval_ms=1_000, on_lost=lambda: lost.append("lost"))
            )
            await asyncio.sleep(0)
            clock.advance(1_000)
            await asyncio.sleep(0.2)
            before = list(lost)  # a healthy probe passes

            async with killer.connect() as other:
                await other.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
                await other.commit()
            clock.advance(1_000)
            await asyncio.wait_for(task, timeout=10)
            await release(conn)
            return before, lost
        finally:
            await engine.dispose()
            await killer.dispose()

    before, after = asyncio.run(scenario())
    assert before == []
    assert after == ["lost"]


def test_release_frees_the_lock_for_another_holder(settings: Settings, database_url: str) -> None:
    async def scenario() -> int:
        engine = _engine(settings, database_url)
        try:
            conn = await acquire(engine)
            assert conn is not None
            await release(conn)
            return await _holders(engine)
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == 0
