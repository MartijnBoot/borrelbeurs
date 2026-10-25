"""The automatic wallet clean-up (B-05 SD15, SD23; plan PD11, PD19).

`sweep` deletes, in one transaction, every live wallet the retention rules name
(`app.db.wallets.expired`), as a player's delete does: a closing entry for any
balance left (with no run, /review R3), then the row blanked. Candidates are
locked `SKIP LOCKED` and checked again once locked, so a wallet a kassa action
holds is left for the next sweep, never waited on, and a top-up committed
meanwhile keeps its wallet.

`run_cleanup` sweeps every `CLEANUP_INTERVAL_MS` on the app clock, skipping a
sweep while the process drains. Boot runs the first one (`app.runtime.boot`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import wallets
from app.runtime.clock import Clock

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_MS: Final = 24 * 3600 * 1000


async def sweep(engine: AsyncEngine, *, now_ms: int) -> int:
    """Delete every expired wallet not locked elsewhere; returns how many."""
    async with engine.begin() as conn:
        settings = await wallets.get_settings(conn)
        candidates = await wallets.expired(conn, now_ms=now_ms, settings=settings)
        locked = await wallets.lock_unlocked(conn, candidates)
        still = await wallets.expired(conn, now_ms=now_ms, settings=settings, among=locked)
        for wallet_id in still:
            await wallets.delete_wallet(conn, wallet_id, now_ms=now_ms, with_run=False)
        return len(still)


async def run_cleanup(*, engine: AsyncEngine, clock: Clock, draining: Callable[[], bool]) -> None:
    """Sweep once every 24 h on `clock`, forever, until cancelled.

    A failed sweep is logged and the next day tries again, as `run_worker` does.
    """
    due = clock.monotonic() + CLEANUP_INTERVAL_MS / 1000
    while True:
        await clock.sleep_until(due)
        # From now, not from `due`: after a suspended laptop, one sweep, not one per day missed.
        due = clock.monotonic() + CLEANUP_INTERVAL_MS / 1000
        if draining():
            continue
        try:
            count = await sweep(engine, now_ms=clock.wall_ms())
        except Exception:
            logger.exception("wallet_cleanup_failed")
        else:
            logger.info("wallet_cleanup", extra={"count": count})
