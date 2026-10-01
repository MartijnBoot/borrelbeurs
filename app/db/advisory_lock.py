"""The single-writer lock (ADR 0003, Phase 3 SD11): a session-level Postgres advisory lock.

The app takes it at boot, before migrating, on a **dedicated connection held for
the process lifetime**; `app.cli.runs go-live` takes the same key and refuses if
the app holds it. A session-level lock lives exactly as long as its connection,
so a crashed process releases it without help, and a dropped connection means
the process can no longer prove it is the only writer: `watchdog` notices and
calls `on_lost` (plan PD5), which in production exits the process.

Only `pg_try_advisory_lock`: a writer that would wait for the lock is a second
writer in waiting, and boot must fail fast instead (AC18).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.runtime.clock import Clock

logger = logging.getLogger(__name__)

# "bbv3" in ASCII. One definition, imported by both holders of the lock (PD4).
ADVISORY_LOCK_KEY: Final = 0x6262_7633


async def acquire(engine: AsyncEngine) -> AsyncConnection | None:
    """The open connection now holding the lock, or `None` (connection closed) if it is held."""
    conn = await engine.connect()
    try:
        held: bool = (
            await conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
            )
        ).scalar_one()
        # End the implicit transaction; a session-level lock outlives it.
        await conn.commit()
    except BaseException:
        await conn.close()
        raise
    if not held:
        await conn.close()
        return None
    return conn


async def release(conn: AsyncConnection) -> None:
    """Unlock and close. On a connection already lost there is nothing left to unlock."""
    try:
        await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
        await conn.commit()
    except Exception:
        # Never hand a possibly-locked connection back to the pool.
        await conn.invalidate()
    finally:
        await conn.close()


async def watchdog(
    conn: AsyncConnection, *, clock: Clock, interval_ms: int, on_lost: Callable[[], None]
) -> None:
    """Probe the lock connection once per interval; on any failure log and call `on_lost`."""
    deadline = clock.monotonic()
    while True:
        deadline += interval_ms / 1000
        await clock.sleep_until(deadline)
        try:
            await conn.execute(text("SELECT 1"))
            await conn.commit()
        except Exception as error:
            logger.error("advisory_lock_lost", extra={"error": type(error).__name__})
            on_lost()
            return
