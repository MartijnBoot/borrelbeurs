"""Boot and shutdown of the runtime (Phase 3 T20: SD11, SD16; AC18 in-process half, AC18c, AC4)."""

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
from app.db.advisory_lock import acquire, release, watchdog
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.boot import BootFailure, start_runtime
from app.runtime.rehydrate import rehydrate
from app.runtime.ticker import Ticker
from tests.integration.conftest import RunAlembic
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

            run_id = await create_draft_run(conn, params=Params(step_quant=0.1), run_seed=7)
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
                    app, _settings(settings, on), clock=FakeClock(T0), run_migrations=True
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

    async def scenario() -> tuple[bool, bool]:
        app = FastAPI()
        app.state.ready = False
        async with start_runtime(
            app, _settings(settings, on), clock=FakeClock(T0), run_migrations=True
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
    assert order == ["lock", "migrate", "rehydrate", "ticker", "watchdog", "ready"]
    assert after is False
    assert lock_free


def test_with_no_live_run_the_app_is_ready_and_the_holder_empty(
    on: str, settings: Settings
) -> None:
    """AC18c (boot half), SD16."""

    async def scenario() -> tuple[bool, bool, int]:
        app = FastAPI()
        async with start_runtime(
            app, _settings(settings, on), clock=FakeClock(T0), run_migrations=False
        ):
            return app.state.ready, app.state.holder.is_empty, app.state.tick_interval_ms

    assert asyncio.run(scenario()) == (True, True, 1_000)


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
            app, _settings(settings, on), clock=FakeClock(T0), run_migrations=False
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
                app, _settings(settings, on), clock=FakeClock(T0), run_migrations=True
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
    """Plan R9: the real `to_thread` migration path, against a real schema one behind."""
    assert alembic(empty_database, "upgrade", "0006").returncode == 0
    monkeypatch.setenv("DATABASE_URL", empty_database)
    get_settings.cache_clear()

    async def scenario() -> str:
        app = FastAPI()
        async with start_runtime(
            app, _settings(settings, empty_database), clock=FakeClock(T0), run_migrations=True
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
        assert asyncio.run(scenario()) == "0007"
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
            clock=clock,
            run_migrations=False,
            on_lock_lost=lambda: lost.append("lost"),
        ):
            killer = create_engine(_settings(settings, on))
            try:
                async with killer.connect() as conn:
                    await conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_locks"
                            " WHERE locktype = 'advisory' AND granted AND pid <> pg_backend_pid()"
                        )
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
