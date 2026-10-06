"""Runs: create a draft, find the current run (Phase 6 SD2, SD4; PD2, PD6).

`POST /api/runs {name}` creates a draft through `create_run`: params copied from
the most recently created run (else `Params()`), a random seed, the column
defaults, and revision 1 authored by the session's key label. It refuses with
409 `live_run_exists`, or 409 `draft_exists` carrying the draft's `run_id`, so
the UI can open that draft.

`GET /api/runs/current` is what `/settings` and home edit: the live run, else
the draft, else 404 `no_current_run` (PD2).

`POST /api/runs/{run_id}/go-live` makes a draft live in this process
(`app/runtime/golive.py`, SD3): 404 `run_not_found`, 409 `run_not_draft`,
`run_not_ready` (no drink) or `live_run_exists`, each writing nothing.

Admin only. The writes refuse while draining (SD24).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.api.deps import Principal, db_engine, refuse_while_draining, require_role
from app.core.errors import AppError
from app.db.runs import RunStatus, create_run, current_run
from app.runtime.golive import go_live_in_process

router = APIRouter(prefix="/runs", tags=["runs"])


class NoCurrentRun(AppError):
    status_code = 404
    code = "no_current_run"


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RunSummaryData(BaseModel):
    run_id: int
    name: str
    status: RunStatus


@router.post("", status_code=201)
async def post_run(
    body: CreateRunRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RunSummaryData:
    run_id = await create_run(db_engine(request), name=body.name, author=principal.label)
    return RunSummaryData(run_id=run_id, name=body.name, status="draft")


@router.get("/current")
async def get_current_run(
    request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> RunSummaryData:
    async with db_engine(request).connect() as conn:
        run = await current_run(conn)
    if run is None:
        raise NoCurrentRun("there is no live or draft run")
    return RunSummaryData(run_id=run.run_id, name=run.name, status=run.status)


@router.post("/{run_id}/go-live")
async def post_go_live(
    run_id: int,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RunSummaryData:
    await go_live_in_process(request.app.state, run_id, author=principal.label)
    async with db_engine(request).connect() as conn:
        run = await current_run(conn)
    assert run is not None and run.run_id == run_id
    return RunSummaryData(run_id=run.run_id, name=run.name, status=run.status)
