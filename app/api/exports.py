"""Export routes (Phase 7 SD6, SD7, SD12; PD8, PD10). Admin only.

- `POST /api/runs/{run_id}/exports`: 202 with the export, `queued` -- or the
  run's own `queued` or `running` one (PD8) -- then wakes the worker; 409
  `export_busy` when one export runs and another waits; 404 `run_not_found`;
  503 while draining. Written on the main engine.
- `GET /api/runs/{run_id}/exports`: the run's exports, newest first.
- `GET /api/exports/{export_id}`: one export; 404 `export_not_found`.
- `GET /api/exports/{export_id}/file`: the workbook once `done`, else 409
  `export_not_ready`; with the xlsx content type, an attachment filename
  `borrel-<slug>-<yyyymmdd-hhmm>.xlsx` (PD10, the export's `created_at` in UTC)
  and `X-Content-Type-Options: nosniff`.

No route returns the bytes but the file route. The reads use the heavy engine
(SD11): a file is megabytes of `bytea`, never on the order path's pool.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.deps import Principal, db_engine, heavy_engine, refuse_while_draining, require_role
from app.db.exports import ExportRow, export_file, get_export, list_exports, request_export

router = APIRouter(tags=["exports"])

XLSX: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SLUG_MAX: Final = 40


class ExportData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: int
    run_id: int
    kind: Literal["manual", "final"]
    status: Literal["queued", "running", "done", "failed"]
    requested_by: str
    sha256: str | None
    bytes: int | None
    line_count: int | None
    total_cents: int | None
    error: str | None
    created_at_ms: int
    started_at_ms: int | None
    finished_at_ms: int | None


def _data(row: ExportRow) -> ExportData:
    return ExportData.model_validate(dataclasses.asdict(row))


def filename(run_name: str, run_id: int, created_at_ms: int) -> str:
    """PD10: `borrel-<slug>-<yyyymmdd-hhmm>.xlsx`, ASCII only, stamped in UTC."""
    folded = unicodedata.normalize("NFKD", run_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:SLUG_MAX].strip("-")
    stamp = datetime.fromtimestamp(created_at_ms // 1000, tz=UTC).strftime("%Y%m%d-%H%M")
    return f"borrel-{slug or f'run-{run_id}'}-{stamp}.xlsx"


@router.post("/runs/{run_id}/exports", status_code=202)
async def post_export(
    run_id: int,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> ExportData:
    async with db_engine(request).begin() as conn:
        row = await request_export(conn, run_id, requested_by=principal.label)
    wakeup: asyncio.Event = request.app.state.export_wakeup
    wakeup.set()
    return _data(row)


@router.get("/runs/{run_id}/exports")
async def get_run_exports(
    run_id: int, request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> list[ExportData]:
    async with heavy_engine(request).connect() as conn:
        rows = await list_exports(conn, run_id)
    return [_data(row) for row in rows]


@router.get("/exports/{export_id}")
async def get_one_export(
    export_id: int, request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> ExportData:
    async with heavy_engine(request).connect() as conn:
        row = await get_export(conn, export_id)
    return _data(row)


@router.get(
    "/exports/{export_id}/file",
    response_class=Response,
    responses={200: {"content": {XLSX: {}}, "description": "The workbook."}},
)
async def get_export_file(
    export_id: int, request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> Response:
    async with heavy_engine(request).connect() as conn:
        row, run_name, data = await export_file(conn, export_id)
    name = filename(run_name, row.run_id, row.created_at_ms)
    return Response(
        content=data,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
