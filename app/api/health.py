"""Liveness and readiness (ADR 0001:24; Phase 3 SD15).

The two answer different questions and must not be collapsed into one endpoint:

- `/healthz` -- *is this process alive?* Phase 3 makes that "is the ticker
  loop turning": 200 while it completed an iteration (committed, failed or
  idle) within three tick intervals, else 503, so a wedged ticker gets the
  process restarted. A database outage alone does not fail it; it shows as
  `last_commit_age_ms`, and fails `/readyz` instead, so the platform does not
  restart-loop a healthy process against a dead database. Before the runtime
  has booted there is no ticker to judge and the answer is 200, as in Phase 0.
- `/readyz` -- *should traffic be sent here?* 503 unless boot completed and a
  `SELECT 1` answers within a second.
"""

from __future__ import annotations

import asyncio
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.errors import AppError

router = APIRouter(tags=["health"])

STALE_INTERVALS: Final = 3
READY_PROBE_S: Final = 1.0


class NotReady(AppError):
    """Boot has not completed, or the database does not answer: send no traffic here."""

    status_code = 503
    code = "not_ready"


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    """Liveness: the ticker loop turned within three intervals."""
    state = request.app.state
    ticker = getattr(state, "ticker", None)
    if ticker is None:
        return JSONResponse({"status": "ok", "last_tick_age_ms": None, "last_commit_age_ms": None})
    clock = state.clock
    last = ticker.last_iteration_monotonic
    if last is None:
        last = state.runtime_started_monotonic
    tick_age_ms = round((clock.monotonic() - last) * 1000)
    committed = state.holder.last_commit_wall_ms
    commit_age_ms = None if committed is None else clock.wall_ms() - committed
    alive = tick_age_ms <= STALE_INTERVALS * state.tick_interval_ms
    return JSONResponse(
        {
            "status": "ok" if alive else "stale",
            "last_tick_age_ms": tick_age_ms,
            "last_commit_age_ms": commit_age_ms,
        },
        status_code=200 if alive else 503,
    )


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    """Readiness: booted, and the database answers within a second."""
    if not request.app.state.ready:
        raise NotReady("the application has not finished starting")
    try:
        await asyncio.wait_for(_select_one(request), timeout=READY_PROBE_S)
    except Exception:
        raise NotReady("the database does not answer") from None
    return {"status": "ready"}


async def _select_one(request: Request) -> None:
    async with request.app.state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
