"""`GET /api/state`: the polling fallback (Phase 3 SD26, SD16; AC15).

The same snapshot `/ws` sends, built from holder memory by
`app/realtime/publish.py`. It never calls the engine or reads the database, so
polling it changes nothing (AC15, D-06). With no live run it is 409
`no_live_run` (SD16).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import ALL_ROLES, Principal, require_role
from app.realtime.messages import Snapshot
from app.realtime.publish import snapshot
from app.runtime.holder import NoLiveRunError

router = APIRouter(tags=["state"])


@router.get("/state")
async def get_state(
    request: Request, _: Annotated[Principal, Depends(require_role(*ALL_ROLES))]
) -> Snapshot:
    data = snapshot(request.app.state.holder, tick_interval_ms=request.app.state.tick_interval_ms)
    if data is None:
        raise NoLiveRunError("there is no live run")
    return data
