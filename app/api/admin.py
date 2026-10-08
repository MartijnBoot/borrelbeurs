"""`POST /api/admin/shutdown` (Phase 3 SD10; AC6d; plan PD17); `GET /api/admin/connections`.

An admin session, never a shared secret token (SD10 removed v1's). The
route marks the process draining -- new orders get 503 `shutting_down` -- answers
202, and only then asks the server to stop. Stopping is uvicorn's own graceful
path, which runs the lifespan's exit: the same `start_runtime` shutdown SIGTERM
reaches (`app/runtime/boot.py`): not ready, the ticker finishes its slot, every
socket closed with 1012, the lock released. Nothing is finalised or written.

Under `python -m app.main` the server sets `request_shutdown` (PD17); under
`uvicorn app.main:app` there is none, and SIGINT -- which uvicorn handles the
same way on every OS -- is raised instead.

`GET /api/admin/connections` (Phase 6 AC41) lists every open WebSocket the hub
knows the key of: `{role, label, connected_at_ms, last_seen_ms}`.
"""

from __future__ import annotations

import signal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel

from app.api.deps import Principal, require_role
from app.realtime.hub import Hub

router = APIRouter(prefix="/admin", tags=["admin"])


class ShutdownAccepted(BaseModel):
    status: str = "shutting_down"


def _stop(request: Request) -> None:
    request_shutdown = request.app.state.request_shutdown
    if request_shutdown is not None:
        request_shutdown()
    else:
        signal.raise_signal(signal.SIGINT)


@router.post("/shutdown", status_code=202)
async def shutdown(
    request: Request,
    background: BackgroundTasks,
    _: Annotated[Principal, Depends(require_role("admin"))],
) -> ShutdownAccepted:
    request.app.state.draining = True
    background.add_task(_stop, request)
    return ShutdownAccepted()


class ConnectionInfo(BaseModel):
    role: str
    label: str
    connected_at_ms: int
    last_seen_ms: int


@router.get("/connections")
async def connections(
    request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> list[ConnectionInfo]:
    hub: Hub = request.app.state.hub
    return [
        ConnectionInfo(
            role=peer.role,
            label=peer.label,
            connected_at_ms=peer.connected_at_ms,
            last_seen_ms=last_seen_ms,
        )
        for peer, last_seen_ms in hub.peers()
    ]
