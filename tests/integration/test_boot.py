"""Boot and shutdown of the runtime (Phase 3 T20: SD11, SD16; AC18 in-process half, AC18c, AC4).

Phase 7 T11 (AC6, PD9): boot fails the exports a stopped process left
unfinished before it starts the export worker.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

import app.runtime.boot as boot
from app.core.config import Settings, get_settings
from app.db.advisory_lock import ADVISORY_LOCK_KEY, acquire, release, watchdog
from app.db.exports import interrupt_unfinished
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.schema_compat import DbState, read_db_state
from app.db.session import create_engine
from app.jobs.export_xlsx import run_worker
from app.runtime.boot import BootFailure, start_runtime
from app.runtime.clock import AppClock
from app.runtime.rehydrate import rehydrate
from app.runtime.ticker import Ticker
from tests.integration.conftest import RunAlembic, head_and_previous
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """`get_settings()` -- which `db/migrations/env.py` reads -- on the scratch database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _settings(settings: Settings, url: str) -> Settings:
    return settings.model_copy(update={"database_url": url})


async def _go_live(settings: Settings, url: str) -> int:
    engine = create_engine(_settings(settings, url))
    try:
        async with engine.begin() as conn:
            from exchange import Params

            run_id = await create_draft_run(
                conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
            )
            await add_drink(
                conn,
                run_id,
                name="Bier",
                slot=0,
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
        return run_id
    finally:
        await engine.dispose()


def test_a_held_lock_fails_boot_fast_naming_the_lock_and_never_migrates(
    on: str, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """AC18 (in-process half), SD11: lock before migrate; fail within 5 s."""
    migrated: list[bool] = []
    monkeypatch.setattr(boot, "upgrade_to_head", lambda: migrated.append(True))

    async def scenario() -> float:
        holder_engine = create_engine(_settings(settings, on))
        held = await acquire(holder_engine)
        assert held is not None
        app = FastAPI()
        started = time.monotonic()
        try:
            with pytest.raises(BootFailure, match="advisory lock"):
                async with start_runtime(
                    app, _settings(settings, on), clock=AppClock(FakeClock(T0)), run_migrations=True
                ):
                    pass
            return time.monotonic() - started
        finally:
            await release(held)
            await holder_engine.dispose()

    with caplog.at_level(logging.ERROR, logger="app.runtime.boot"):
        elapsed = asyncio.run(scenario())
    assert elapsed < 5
    assert migrated == []
    assert any("advisory lock" in str(r.__dict__.get("reason", "")) for r in caplog.records)


def test_boot_runs_in_sd11s_order_and_shutdown_releases_the_lock(
    on: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    def spy(name: str, real: Any) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            order.append(name)
            return await real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(boot, "acquire", spy("lock", acquire))
    monkeypatch.setattr(boot, "upgrade_to_head", lambda: order.append("migrate"))
    monkeypatch.setattr(boot, "rehydrate", spy("rehydrate", rehydrate))
    real_start = Ticker.start

    def start(self: Any) -> Any:
        order.append("ticker")
        return real_start(self)

    monkeypatch.setattr(Ticker, "start", start)
    monkeypatch.setattr(boot, "watchdog", spy("watchdog", watchdog))
    monkeypatch.setattr(boot, "interrupt_unfinished", spy("interrupt", interrupt_unfinished))
    monkeypatch.setattr(boot, "run_worker", spy("worker", run_worker))

    async def scenario() -> tuple[bool, bool]:
        app = FastAPI()
        app.state.ready = False
        async with start_runtime(
            app, _settings(settings, on), clock=AppClock(FakeClock(T0)), run_migrations=True
        ):
            await asyncio.sleep(0)
            order.append("ready" if app.state.ready else "not-ready")
        after = app.state.ready
        probe = create_engine(_settings(settings, on))
        try:
            again = await acquire(probe)
            free = again is not None
            if again is not None:
                await release(again)
        finally:
            await probe.dispose()
        return after, free

    after, lock_free = asyncio.run(scenario())
    assert order == [
        "lock",
        "migrate",
        "rehydrate",
        "interrupt",
        "ticker",
        "watchdog",
        "worker",
        "ready",
    ]
    assert after is False
    assert lock_free


def test_boot_fails_the_exports_a_stopped_process_left_unfinished(
    on: str, settings: Settings
) -> None:
    """AC6, PD9: a `queued` and a `running` export become `failed`, `onderbroken`."""
    run_id = asyncio.run(_go_live(settings, on))

    async def scenario() -> list[tuple[str, str, str | None, bool]]:
        engine = create_engine(_settings(settings, on))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO export (run_id, kind, status, requested_by) VALUES"
                        " (:r, 'final', 'running', 't'), (:r, 'manual', 'queued', 't'),"
                        " (:r, 'manual', 'failed', 't')"
                    ),
                    {"r": run_id},
                )
            app = FastAPI()
            async with start_runtime(
                app, _settings(settings, on), clock=AppClock(FakeClock(T0)), run_migrations=False
            ):
                await asyncio.sleep(0.2)  # the worker's first scan finds nothing to build
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT kind, status, error, finished_at IS NOT NULL FROM export"
                        " ORDER BY export_id"
                    )
                )
                return [tuple(row) for row in rows]  # type: ignore[misc]
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == [
        ("final", "failed", "onderbroken", True),
        ("manual", "failed", "onderbroken", True),
        ("manual", "failed", None, False),
    ]


def test_with_no_live_run_the_app_is_ready_and_the_holder_empty(
    on: str, settings: Settings
) -> None:
    """AC18c (boot half), SD16."""

    async def scenario() -> tuple[bool, bool, int]:
        app = FastAPI()
        async with start_runtime(
            app, _settings(settings, on), clock=AppClock(FakeClock(T0)), run_migrations=False
        ):
            return app.state.ready, app.state.holder.is_empty, app.state.tick_interval_ms

    assert asyncio.run(scenario()) == (True, True, 1_000)


def test_boot_builds_a_heavy_read_engine_with_its_own_connections_and_timeout(
    on: str, settings: Settings
) -> None:
    """Phase 7 SD11, PD2: a distinct NullPool engine whose statements outlive the 5 s bound."""

    # The live bound at its 5 s default and the heavy one at its 60 s default.
    bounded = _settings(settings, on).model_copy(
        update={"database_timeout_seconds": 5.0, "heavy_read_timeout_seconds": 60.0}
    )

    async def scenario() -> tuple[bool, bool, str, str]:
        app = FastAPI()
        async with start_runtime(app, bounded, clock=AppClock(FakeClock(T0)), run_migrations=False):
            engine, heavy = app.state.engine, app.state.heavy_engine
            async with heavy.connect() as conn:
                slept = await conn.execute(text("SELECT pg_sleep(6)::text"))
                heavy_result = str(slept.scalar_one())
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT pg_sleep(6)"))
                live_result = "completed"
            except Exception as error:  # the asyncpg timeout, wrapped by SQLAlchemy
                live_result = type(error).__name__
            return (
                heavy is not engine,
                isinstance(heavy.pool, pool.NullPool),
                heavy_result,
                live_result,
            )

    distinct, null_pool, heavy_result, live_result = asyncio.run(scenario())
    assert distinct
    assert null_pool
    assert heavy_result == ""
    assert live_result != "completed"


def test_a_live_run_is_rehydrated_and_its_tick_interval_used(on: str, settings: Settings) -> None:
    async def scenario() -> tuple[int | None, int]:
        run_id = await _go_live(settings, on)
        engine = create_engine(_settings(settings, on))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE run SET tick_interval_ms = 2000 WHERE run_id = :r"), {"r": run_id}
                )
        finally:
            await engine.dispose()
        app = FastAPI()
        async with start_runtime(
            app, _settings(settings, on), clock=AppClock(FakeClock(T0)), run_migrations=False
        ):
            assert app.state.holder.run_id == run_id
            return app.state.holder.run_id, app.state.tick_interval_ms

    _, interval = asyncio.run(scenario())
    assert interval == 2_000


def test_a_failing_migration_fails_boot_and_releases_the_lock(
    on: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise RuntimeError("migration 0042 exploded")

    monkeypatch.setattr(boot, "upgrade_to_head", broken)

    async def scenario() -> bool:
        app = FastAPI()
        with pytest.raises(BootFailure, match="migration failed"):
            async with start_runtime(
                app, _settings(settings, on), clock=AppClock(FakeClock(T0)), run_migrations=True
            ):
                pass
        assert app.state.ready is False
        probe = create_engine(_settings(settings, on))
        try:
            again = await acquire(probe)
            if again is not None:
                await release(again)
            return again is not None
        finally:
            await probe.dispose()

    assert asyncio.run(scenario())


def test_boot_migrates_a_database_one_revision_behind_to_head(
    empty_database: str, settings: Settings, alembic: RunAlembic, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan R9: the real `to_thread` migration path, against a real schema one behind.
    Phase 8 AC8: the SD3 rule finds that revision known, and migrates as before."""
    head, previous = head_and_previous()
    assert alembic(empty_database, "upgrade", previous).returncode == 0
    monkeypatch.setenv("DATABASE_URL", empty_database)
    get_settings.cache_clear()

    async def scenario() -> str:
        app = FastAPI()
        async with start_runtime(
            app,
            _settings(settings, empty_database),
            clock=AppClock(FakeClock(T0)),
            run_migrations=True,
        ):
            pass
        engine = create_async_engine(empty_database, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                return str(
                    (
                        await conn.execute(text("SELECT version_num FROM alembic_version"))
                    ).scalar_one()
                )
        finally:
            await engine.dispose()

    try:
        assert asyncio.run(scenario()) == head
    finally:
        get_settings.cache_clear()


def test_a_lost_lock_connection_calls_on_lock_lost(on: str, settings: Settings) -> None:
    """PD5 wired at boot: the watchdog runs on the tick interval of the injected clock."""

    async def scenario() -> list[str]:
        lost: list[str] = []
        clock = FakeClock(T0)
        app = FastAPI()
        async with start_runtime(
            app,
            _settings(settings, on),
            clock=AppClock(clock),
            run_migrations=False,
            on_lock_lost=lambda: lost.append("lost"),
        ):
            killer = create_engine(_settings(settings, on))
            try:
                async with killer.connect() as conn:
                    # pg_locks is cluster-wide: only this database's app lock.
                    await conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_locks"
                            " WHERE locktype = 'advisory' AND granted AND pid <> pg_backend_pid()"
                            " AND database = (SELECT oid FROM pg_database"
                            " WHERE datname = current_database())"
                            " AND classid = 0 AND objid = :key"
                        ),
                        {"key": ADVISORY_LOCK_KEY},
                    )
                    await conn.commit()
            finally:
                await killer.dispose()
            for _ in range(3):
                clock.advance(1_000)
                for _ in range(50):
                    await asyncio.sleep(0.01)
                    if lost:
                        break
        return lost

    assert asyncio.run(scenario()) == ["lost"]


def test_a_diverged_state_calls_on_lock_lost(on: str, settings: Settings) -> None:
    """Memory no longer matches the committed row (a lost commit acknowledgement): the
    process cannot recover in place, so it takes the lost-lock exit and rehydrates on boot."""

    async def scenario() -> list[str]:
        await _go_live(settings, on)
        lost: list[str] = []
        clock = FakeClock(T0)
        app = FastAPI()
        async with start_runtime(
            app,
            _settings(settings, on),
            clock=AppClock(clock),
            run_migrations=False,
            on_lock_lost=lambda: lost.append("lost"),
        ):
            async with app.state.engine.begin() as conn:
                await conn.execute(text("UPDATE engine_state SET version = version + 1"))
            clock.advance(1_000)
            for _ in range(300):
                await asyncio.sleep(0.01)
                if lost:
                    break
        return lost

    assert asyncio.run(scenario()) == ["lost"]


# --- Phase 8 T3: the SD3 boot rule (PD2; AC8, AC9 in-process half, AC10) ---------
#
# Each case gets its own `empty_database` migrated to head, then made to look like a
# schema a newer image left: `alembic_version` stamped to a revision these scripts do
# not know. The session's scratch database is never stamped.

AHEAD_FIXTURE = "ci_ahead_fixture"
FLOOR = "0011"


async def _execute(url: str, *statements: str) -> list[tuple[Any, ...]]:
    """Run statements in one transaction; return the rows of the last."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            rows: list[tuple[Any, ...]] = []
            for statement in statements:
                result = await conn.execute(text(statement))
                rows = [tuple(row) for row in result] if result.returns_rows else []
            return rows
    finally:
        await engine.dispose()


async def _row_counts(url: str) -> dict[str, int]:
    """Every table in the schema, `alembic_version` and `schema_compat` included."""
    tables = await _execute(
        url,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
    )
    counts = {}
    for (table,) in tables:
        ((count,),) = await _execute(url, f'SELECT count(*) FROM "{table}"')
        counts[str(table)] = int(count)
    return counts


@pytest.fixture
def at_head(
    empty_database: str, alembic: RunAlembic, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """A database of its own, migrated to head, that `get_settings()` points at."""
    migrated = alembic(empty_database, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    monkeypatch.setenv("DATABASE_URL", empty_database)
    get_settings.cache_clear()
    yield empty_database
    get_settings.cache_clear()


def test_read_db_state_sees_the_revision_and_the_floor(at_head: str) -> None:
    """`0011` seeds the rollback floor; the state is read with plain SQL."""

    async def scenario() -> DbState:
        engine = create_async_engine(at_head, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                return await read_db_state(conn)
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == DbState(
        db_revision=head_and_previous()[0], min_code_revision=FLOOR
    )


def test_read_db_state_on_an_empty_database_is_all_none(empty_database: str) -> None:
    """No `alembic_version` at all: a fresh database, which boot migrates."""

    async def scenario() -> DbState:
        engine = create_async_engine(empty_database, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                return await read_db_state(conn)
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == DbState(db_revision=None, min_code_revision=None)


def test_a_schema_ahead_but_declared_compatible_boots_without_migrating(
    at_head: str, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """AC9 (in-process): an unknown revision whose `min_code_revision` this image knows.
    The real `upgrade_to_head` is left in place: called, it would fail on the unknown
    revision, so a boot that comes up ready did not call it."""
    asyncio.run(_execute(at_head, f"UPDATE alembic_version SET version_num = '{AHEAD_FIXTURE}'"))

    async def scenario() -> bool:
        app = FastAPI()
        async with start_runtime(
            app, _settings(settings, at_head), clock=AppClock(FakeClock(T0)), run_migrations=True
        ):
            return bool(app.state.ready)

    with caplog.at_level(logging.WARNING, logger="app.runtime.boot"):
        ready = asyncio.run(scenario())

    assert ready
    (ahead,) = [r for r in caplog.records if r.getMessage() == "schema_ahead"]
    assert ahead.levelno == logging.WARNING
    assert ahead.__dict__["db_revision"] == AHEAD_FIXTURE
    assert ahead.__dict__["min_code_revision"] == FLOOR
    assert asyncio.run(_execute(at_head, "SELECT version_num FROM alembic_version")) == [
        (AHEAD_FIXTURE,)
    ]


@pytest.mark.parametrize(
    "incompatible",
    [
        pytest.param(
            f"UPDATE schema_compat SET min_code_revision = '{AHEAD_FIXTURE}'", id="unknown-floor"
        ),
        pytest.param("DELETE FROM schema_compat", id="row-missing"),
        pytest.param("DROP TABLE schema_compat", id="table-missing"),
    ],
)
def test_a_schema_ahead_and_incompatible_is_refused_having_written_nothing(
    at_head: str, settings: Settings, caplog: pytest.LogCaptureFixture, incompatible: str
) -> None:
    """AC10: refused under the lock, before anything is migrated, rehydrated or ticked --
    with a live run present, so a boot that went on would have written a tick."""
    asyncio.run(_go_live(settings, at_head))
    asyncio.run(
        _execute(
            at_head, f"UPDATE alembic_version SET version_num = '{AHEAD_FIXTURE}'", incompatible
        )
    )
    before = asyncio.run(_row_counts(at_head))
    clock = FakeClock(T0 + 60_000)

    async def scenario() -> FastAPI:
        app = FastAPI()
        with pytest.raises(BootFailure, match="schema ahead of image"):
            async with start_runtime(
                app, _settings(settings, at_head), clock=AppClock(clock), run_migrations=True
            ):
                pass  # pragma: no cover - the boot above is expected to raise
        return app

    with caplog.at_level(logging.ERROR, logger="app.runtime.boot"):
        app = asyncio.run(scenario())

    assert getattr(app.state, "ready", False) is False
    (failed,) = [r for r in caplog.records if r.getMessage() == "boot_failed"]
    assert failed.__dict__["reason"] == "schema ahead of image"
    assert failed.__dict__["db_revision"] == AHEAD_FIXTURE
    assert asyncio.run(_row_counts(at_head)) == before
    assert before["price_tick"] >= 1  # the go-live's tick, and no other
    assert asyncio.run(_execute(at_head, "SELECT version_num FROM alembic_version")) == [
        (AHEAD_FIXTURE,)
    ]


# --- Phase 8 T5: rehydrating behind the last commit (SD15, PD4) -------------------

HOUR = 3_600_000


def test_booting_with_the_wall_clock_behind_the_last_commit_raises_the_app_clock(
    on: str, settings: Settings
) -> None:
    """SD15: boot lifts the app clock to the stored commit, writing no gap (no time
    evolved), so the first tick is stamped after it -- not an hour of frozen ticks."""

    async def scenario() -> tuple[int, int, list[tuple[Any, ...]]]:
        await _go_live(settings, on)  # its last commit is at T0
        fake = FakeClock(T0 - HOUR)
        clock = AppClock(fake)
        app = FastAPI()
        async with start_runtime(app, _settings(settings, on), clock=clock, run_migrations=False):
            offset_ms = clock.offset_ms
            for _ in range(200):
                if fake.sleepers >= 2:
                    break
                await asyncio.sleep(0.005)
            fake.advance(1_000)
            for _ in range(200):
                await asyncio.sleep(0.005)
                if app.state.ticker.last_iteration_monotonic is not None:
                    break
            rows = await _execute(on, "SELECT source, wall_ts_ms FROM price_tick ORDER BY version")
        return offset_ms, clock.wall_ms(), rows

    offset_ms, now, rows = asyncio.run(scenario())
    assert offset_ms == HOUR
    assert now == T0 + 1_000
    assert [source for source, _ in rows] == ["reset", "tick"]
    assert rows[1][1] == T0 + 1_000
