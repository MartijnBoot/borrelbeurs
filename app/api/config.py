"""A run's config over HTTP (Phase 6 SD5, SD6, SD8; PD4, PD6, PD7).

`GET /api/runs/{run_id}/config` is the config document (`app/runtime/config.py`).
`PATCH /api/runs/{run_id}/config {name?, candle_interval_s?, params?}` merges
only the keys present into a draft and returns `{revision}`: the new one, or the
current one when nothing changed. A violation of SD8 is 422 naming the field.

404 `run_not_found`; 409 `run_ended`; a live run's PATCH is 409 `run_not_draft`
until live writes exist (T11). Admin only. The PATCH refuses while draining (SD24).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import Principal, db_engine, refuse_while_draining, require_role
from app.runtime.config import (
    ConfigData,
    ConfigPatch,
    RevisionData,
    read_config,
    write_draft_config,
)

router = APIRouter(prefix="/runs", tags=["config"])


@router.get("/{run_id}/config")
async def get_config(
    run_id: int, request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> ConfigData:
    return await read_config(db_engine(request), run_id)


@router.patch("/{run_id}/config")
async def patch_config(
    run_id: int,
    body: ConfigPatch,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RevisionData:
    revision = await write_draft_config(db_engine(request), run_id, body, author=principal.label)
    return RevisionData(revision=revision)
