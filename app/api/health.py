"""Liveness and readiness (ADR 0001:24).

The two answer different questions and must not be collapsed into one endpoint:

- `/healthz` — *is this process alive?* It does no work and touches nothing, so
  a restart-on-failure policy only ever fires on a process that is genuinely
  wedged. It answers before the lifespan has run, on purpose.
- `/readyz` — *should traffic be sent here?* 503 until boot has completed.

Readiness is a single flag on `app.state` today because the only precondition
in Phase 0 is "the lifespan finished". Phase 3's ticker and the database pool
become further preconditions; they belong in this predicate, not in a second
endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.errors import AppError

router = APIRouter(tags=["health"])


class NotReady(AppError):
    """Boot has not completed, so this instance must not be sent traffic."""

    status_code = 503
    code = "not_ready"


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness. Constant, cheap, and never dependent on a downstream."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    """Readiness. 200 only once the lifespan has completed."""
    if not request.app.state.ready:
        raise NotReady("the application has not finished starting")
    return {"status": "ready"}
