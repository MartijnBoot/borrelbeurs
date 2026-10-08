"""Boot and shutdown of the runtime (Phase 3 SD11, SD15, SD16; ADR 0011).

Startup, in this order, and nothing is served until the end:

1. the engine;
2. **the advisory lock** on its own connection (`app/db/advisory_lock.py`), or
   `BootFailure` -- before anything is migrated, so a second instance never
   touches the schema (AC18);
3. **migrate** to head, in a worker thread (plan PD3: `db/migrations/env.py`
   calls `asyncio.run`, which cannot nest in this loop). A failure fails boot.
   The Alembic config is built without a file name, so `env.py` does not call
   `fileConfig` and reset the application's logging;
4. **the theme** (Phase 4 PD5): the stored row, or Blauw at revision 0, with
   or without a live run;
5. **rehydrate** the live run (with the gap rule), or an empty holder (SD16);
6. the hub and the publisher (the holder's sink);
7. the ticker and the lock watchdog;
8. ready.

Shutdown (SD10): not ready, draining, the ticker finishes its slot, every
socket is closed with 1012, the lock is released, the engine disposed. Nothing
is written on the way out.
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
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.advisory_lock import acquire, release, watchdog
from app.db.models import Run
from app.db.session import create_engine
from app.db.theme import get_theme
from app.realtime.hub import Hub
from app.realtime.publish import Publisher, active_drink_ids, seeded_book
from app.runtime.clock import Clock
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


class BootFailure(RuntimeError):
    """The runtime cannot start; the process must exit non-zero without serving."""


def exit_process() -> None:
    """Production's reaction to a lost lock or a diverged state: no graceful path that
    might write; the next boot rehydrates from what was committed."""
    os._exit(LOCK_LOST_EXIT)


def upgrade_to_head() -> None:
    """`alembic upgrade head`, blocking; run it in a worker thread."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")


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


@asynccontextmanager
async def start_runtime(
    app: FastAPI,
    settings: Settings,
    *,
    clock: Clock,
    run_migrations: bool,
    on_lock_lost: Callable[[], None] = exit_process,
) -> AsyncIterator[None]:
    """Boot the runtime onto `app.state`, yield while serving, then shut it down."""
    engine = create_engine(settings)
    app.state.engine = engine
    lock = None
    tasks: list[asyncio.Task[None]] = []
    ticker: Ticker | None = None
    hub: Hub | None = None
    try:
        lock = await acquire(engine)
        if lock is None:
            logger.error("boot_failed", extra={"reason": "advisory lock held by another instance"})
            raise BootFailure("advisory lock held by another instance")

        if run_migrations:
            try:
                await asyncio.to_thread(upgrade_to_head)
            except Exception as error:
                logger.error("boot_failed", extra={"reason": "migration failed"})
                raise BootFailure(f"migration failed: {type(error).__name__}") from error

        app.state.theme = await _stored_theme(engine)

        sink = _LateSink()
        # Room for a statement to hit the engine's own timeout and report it first.
        step_timeout_s = 2 * settings.database_timeout_seconds
        run = await rehydrate(engine, now_ms=clock.wall_ms())
        if isinstance(run, RehydratedRun):
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

        hub = Hub(clock=clock, replay_window_ms=replay_window_ms)
        publisher = Publisher(
            hub, seeded_book(holder), active=active_drink_ids(holder), ring=lambda: holder.ring
        )
        sink.target = publisher
        ticker = Ticker(holder, clock=clock, interval_ms=tick_interval_ms)

        app.state.holder = holder
        app.state.hub = hub
        app.state.publisher = publisher
        app.state.ticker = ticker
        app.state.tick_interval_ms = tick_interval_ms
        app.state.draining = False
        # /healthz measures from here until the ticker's first iteration (SD15).
        app.state.runtime_started_monotonic = clock.monotonic()

        tasks.append(ticker.start())
        tasks.append(
            asyncio.get_running_loop().create_task(
                watchdog(
                    lock,
                    clock=clock,
                    interval_ms=tick_interval_ms,
                    on_lost=on_lock_lost,
                    timeout_s=step_timeout_s,
                )
            )
        )
        app.state.ready = True
        logger.info(
            "runtime_started",
            extra={"run_id": holder.run_id, "tick_interval_ms": tick_interval_ms},
        )
        yield
    finally:
        app.state.ready = False
        app.state.draining = True
        if ticker is not None:
            await ticker.stop()
        for task in tasks[1:]:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if hub is not None:
            await hub.close_all(CLOSE_SERVICE_RESTART)
        if lock is not None:
            await release(lock)
        await engine.dispose()
        logger.info("runtime_stopped")
