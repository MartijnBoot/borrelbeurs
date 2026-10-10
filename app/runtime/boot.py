"""Boot and shutdown of the runtime (Phase 3 SD11, SD15, SD16; ADR 0011).

Startup, in this order, and nothing is served until the end:

1. the engine, and the heavy-read engine for exports and analytics (Phase 7
   SD11: no pool, the longer timeout);
2. **the advisory lock** on its own connection (`app/db/advisory_lock.py`) --
   before anything is migrated, so a second instance never touches the schema.
   Held elsewhere, the instance waits in **standby** (Phase 8 SD4, PD1): it
   serves `/healthz` (`standby`), 503 on `/api`, retries every second and logs
   `lock_wait` every 30 s, then runs steps 3-9 in a task. A failure there exits 3;
3. **migrate** to head, in a worker thread (plan PD3: `db/migrations/env.py`
   calls `asyncio.run`, which cannot nest in this loop). A failure fails boot.
   The Alembic config is built without a file name, so `env.py` does not call
   `fileConfig` and reset the application's logging. First, Phase 8 SD3
   (`app/db/schema_compat.py`): a schema a newer image migrated is served as it
   is when it declares this image compatible (`schema_ahead`), and refused with
   `BootFailure("schema ahead of image")`, having written nothing, when not;
4. **the theme** (Phase 4 PD5): the stored row, or Blauw at revision 0, with
   or without a live run;
5. **rehydrate** the live run (with the gap rule), or an empty holder (SD16);
   a wall clock behind its last commit raises the app clock to it (Phase 8 SD15);
6. the hub and the publisher (the holder's sink);
7. **interrupted exports** (Phase 7 PD9): every `queued` or `running` export a
   stopped process left becomes `failed`, `onderbroken` (AC6);
8. the ticker, the lock watchdog and the export worker, woken through
   `app.state.export_wakeup`;
9. ready.

Shutdown (SD10): not ready, draining, the ticker finishes its slot, the
watchdog and the export worker are cancelled (its build process is
terminated, not waited for), every socket is closed with 1012, the lock is released, the
engines disposed. Nothing is written on the way out.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db.advisory_lock import acquire, release, watchdog
from app.db.exports import interrupt_unfinished
from app.db.models import Run
from app.db.schema_compat import Decision, decide, read_db_state
from app.db.session import create_engine, create_heavy_read_engine
from app.db.theme import get_theme
from app.jobs.export_xlsx import run_worker
from app.realtime.hub import Hub
from app.realtime.publish import Publisher, active_drink_ids, seeded_book
from app.runtime.clock import AppClock
from app.runtime.holder import DomainEvent, MarketHolder
from app.runtime.rehydrate import RehydratedRun, rehydrate
from app.runtime.theme import DEFAULT_PRESET, Theme, resolve
from app.runtime.ticker import Ticker

logger = logging.getLogger(__name__)

MIGRATIONS_DIR: Final = Path(__file__).resolve().parents[2] / "db" / "migrations"
DEFAULT_TICK_INTERVAL_MS: Final = 1_000
DEFAULT_REPLAY_WINDOW_MS: Final = 15 * 60_000
# "Service restart": the client should reconnect (SD10).
CLOSE_SERVICE_RESTART: Final = 1012
# EX_SOFTWARE: the process can no longer prove it is the single writer (plan PD5).
LOCK_LOST_EXIT: Final = 70
# uvicorn's own exit code for a startup failure: a boot that fails after standby
# exits as one that failed in the lifespan, for `restart: on-failure` (Phase 8 PD1).
BOOT_FAILED_EXIT: Final = 3
# Standby (SD4): how often to retry the lock, and to log that it is still held.
LOCK_RETRY_S: Final = 1.0
LOCK_WAIT_LOG_S: Final = 30


class BootFailure(RuntimeError):
    """The runtime cannot start; the process must exit non-zero without serving."""


def exit_process(code: int = LOCK_LOST_EXIT) -> None:
    """Production's reaction to a lost lock or a diverged state: no graceful path that
    might write; the next boot rehydrates from what was committed."""
    os._exit(code)


def exit_boot_failed() -> None:
    """A boot that failed after standby (PD1): `boot_failed` is logged, exit 3."""
    exit_process(BOOT_FAILED_EXIT)


def upgrade_to_head() -> None:
    """`alembic upgrade head`, blocking; run it in a worker thread."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")


def known_revisions() -> frozenset[str]:
    """Every revision this image's scripts hold (SD3); blocking, it imports them."""
    script = ScriptDirectory(str(MIGRATIONS_DIR))
    return frozenset(entry.revision for entry in script.walk_revisions())


async def migrate(engine: AsyncEngine) -> None:
    """SD3, under the lock: migrate, serve a newer schema declared compatible, or refuse."""
    async with engine.connect() as conn:
        state = await read_db_state(conn)
    known = await asyncio.to_thread(known_revisions)
    decision = decide(known, state.db_revision, state.min_code_revision)
    revisions = {"db_revision": state.db_revision, "min_code_revision": state.min_code_revision}
    if decision is Decision.REFUSE:
        logger.error("boot_failed", extra={"reason": "schema ahead of image", **revisions})
        raise BootFailure("schema ahead of image")
    if decision is Decision.AHEAD:
        logger.warning("schema_ahead", extra=revisions)
        return
    try:
        await asyncio.to_thread(upgrade_to_head)
    except Exception as error:
        logger.error("boot_failed", extra={"reason": "migration failed"})
        raise BootFailure(f"migration failed: {type(error).__name__}") from error


async def run_tick_interval_ms(engine: AsyncEngine, run_id: int) -> int:
    async with engine.connect() as conn:
        value = (
            await conn.execute(select(Run.tick_interval_ms).where(Run.run_id == run_id))
        ).scalar_one()
    return int(value)


async def _stored_theme(engine: AsyncEngine) -> Theme:
    """The stored theme, or Blauw at revision 0 when none was ever stored (SD5)."""
    async with engine.connect() as conn:
        row = await get_theme(conn)
    if row is None:
        return resolve(DEFAULT_PRESET, 0)
    return resolve(row.preset, row.revision, custom=row.custom, images=row.images)


class _LateSink:
    """The holder needs its sink at construction; the publisher needs the holder."""

    def __init__(self) -> None:
        self.target: Callable[[Sequence[DomainEvent]], None] | None = None

    def __call__(self, events: Sequence[DomainEvent]) -> None:
        if self.target is not None:
            self.target(events)


class _Booted:
    """What a boot has started so far, for the one shutdown path to stop."""

    def __init__(self) -> None:
        self.lock: AsyncConnection | None = None
        self.tasks: list[asyncio.Task[None]] = []
        self.ticker: Ticker | None = None
        self.hub: Hub | None = None


async def _boot(
    app: FastAPI,
    settings: Settings,
    engine: AsyncEngine,
    booted: _Booted,
    *,
    clock: AppClock,
    run_migrations: bool,
    on_lock_lost: Callable[[], None],
) -> None:
    """Steps 3-9, under the lock `booted` already holds; a failure raises."""
    assert booted.lock is not None
    if run_migrations:
        await migrate(engine)

    app.state.theme = await _stored_theme(engine)

    sink = _LateSink()
    # Room for a statement to hit the engine's own timeout and report it first.
    step_timeout_s = 2 * settings.database_timeout_seconds
    run = await rehydrate(engine, now_ms=clock.wall_ms())
    if isinstance(run, RehydratedRun):
        # SD15: a wall clock behind the stored commit continues from it. No gap
        # row: no time evolved, and the ticker's first slot stamps after it.
        clock.raise_to(run.wall_ts_ms)
        holder = MarketHolder.from_rehydrated(
            run,
            engine=engine,
            clock=clock,
            sink=sink,
            on_diverged=on_lock_lost,
            step_timeout_s=step_timeout_s,
        )
        tick_interval_ms = await run_tick_interval_ms(engine, run.run_id)
        replay_window_ms = round(run.spec.params.history_window_minutes * 60_000)
    else:
        # A go-live in this process (Phase 6 SD3) fills it, so it needs both.
        holder = MarketHolder.empty(
            engine=engine,
            clock=clock,
            sink=sink,
            on_diverged=on_lock_lost,
            step_timeout_s=step_timeout_s,
        )
        tick_interval_ms = DEFAULT_TICK_INTERVAL_MS
        replay_window_ms = DEFAULT_REPLAY_WINDOW_MS

    hub = booted.hub = Hub(clock=clock, replay_window_ms=replay_window_ms)
    publisher = Publisher(
        hub, seeded_book(holder), active=active_drink_ids(holder), ring=lambda: holder.ring
    )
    sink.target = publisher
    ticker = booted.ticker = Ticker(holder, clock=clock, interval_ms=tick_interval_ms)

    async with engine.begin() as conn:
        interrupted = await interrupt_unfinished(conn)
    if interrupted:
        logger.warning("exports_interrupted", extra={"count": interrupted})
    export_wakeup = asyncio.Event()

    app.state.holder = holder
    app.state.hub = hub
    app.state.publisher = publisher
    app.state.ticker = ticker
    app.state.tick_interval_ms = tick_interval_ms
    app.state.export_wakeup = export_wakeup
    app.state.draining = False
    # /healthz measures from here until the ticker's first iteration (SD15).
    app.state.runtime_started_monotonic = clock.monotonic()

    booted.tasks.append(ticker.start())
    booted.tasks.append(
        asyncio.get_running_loop().create_task(
            watchdog(
                booted.lock,
                clock=clock,
                interval_ms=tick_interval_ms,
                on_lost=on_lock_lost,
                timeout_s=step_timeout_s,
            )
        )
    )
    booted.tasks.append(
        asyncio.get_running_loop().create_task(
            run_worker(engine=engine, settings=settings, clock=clock, wakeup=export_wakeup)
        )
    )
    app.state.standby = False
    app.state.ready = True
    logger.info(
        "runtime_started",
        extra={"run_id": holder.run_id, "tick_interval_ms": tick_interval_ms},
    )


async def _wait_then_boot(
    app: FastAPI,
    settings: Settings,
    engine: AsyncEngine,
    booted: _Booted,
    *,
    clock: AppClock,
    run_migrations: bool,
    on_lock_lost: Callable[[], None],
    on_boot_failed: Callable[[], None],
) -> None:
    """Standby (SD4): retry the lock every second, then boot as the fast path does.

    Nothing is migrated, ticked or written until the lock is held. Any failure from
    here on -- the database gone, a migration, `schema ahead of image` -- has no
    lifespan left to raise out of, so it takes `on_boot_failed`: production's exit 3,
    the code uvicorn gives a startup failure (PD1).
    """
    try:
        started = clock.monotonic()
        logged = 0
        while booted.lock is None:
            await clock.sleep_until(clock.monotonic() + LOCK_RETRY_S)
            booted.lock = await acquire(engine)
            waited_s = int(clock.monotonic() - started)
            if booted.lock is None and waited_s >= logged + LOCK_WAIT_LOG_S:
                logged = waited_s - waited_s % LOCK_WAIT_LOG_S
                logger.warning("lock_wait", extra={"waited_s": logged})
        logger.info("lock_acquired", extra={"waited_s": int(clock.monotonic() - started)})
        await _boot(
            app,
            settings,
            engine,
            booted,
            clock=clock,
            run_migrations=run_migrations,
            on_lock_lost=on_lock_lost,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if not isinstance(error, BootFailure):
            logger.error("boot_failed", extra={"reason": type(error).__name__})
        on_boot_failed()


@asynccontextmanager
async def start_runtime(
    app: FastAPI,
    settings: Settings,
    *,
    clock: AppClock,
    run_migrations: bool,
    on_lock_lost: Callable[[], None] = exit_process,
    on_boot_failed: Callable[[], None] = exit_boot_failed,
) -> AsyncIterator[None]:
    """Boot the runtime onto `app.state`, yield while serving, then shut it down.

    With the lock, boot happens here and a failure raises out of the lifespan, as it
    always did. Without it (PD1), `app.state.standby` is set and the boot runs in a
    task once the lock frees, so uvicorn binds and `/healthz` answers meanwhile.
    """
    engine = create_engine(settings)
    app.state.engine = engine
    # Export and analytics reads (Phase 7 SD11): no pool, so nothing to open here.
    heavy_engine = create_heavy_read_engine(settings)
    app.state.heavy_engine = heavy_engine
    app.state.ready = False
    app.state.standby = False
    booted = _Booted()
    waiting: asyncio.Task[None] | None = None
    try:
        booted.lock = await acquire(engine)
        if booted.lock is not None:
            await _boot(
                app,
                settings,
                engine,
                booted,
                clock=clock,
                run_migrations=run_migrations,
                on_lock_lost=on_lock_lost,
            )
        else:
            app.state.standby = True
            logger.warning("lock_wait", extra={"waited_s": 0})
            waiting = asyncio.get_running_loop().create_task(
                _wait_then_boot(
                    app,
                    settings,
                    engine,
                    booted,
                    clock=clock,
                    run_migrations=run_migrations,
                    on_lock_lost=on_lock_lost,
                    on_boot_failed=on_boot_failed,
                )
            )
        yield
    finally:
        app.state.ready = False
        app.state.draining = True
        if waiting is not None:
            waiting.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiting
        if booted.ticker is not None:
            await booted.ticker.stop()
        for task in booted.tasks[1:]:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if booted.hub is not None:
            await booted.hub.close_all(CLOSE_SERVICE_RESTART)
        if booted.lock is not None:
            await release(booted.lock)
        await heavy_engine.dispose()
        await engine.dispose()
        logger.info("runtime_stopped")
