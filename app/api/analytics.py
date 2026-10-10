"""`/api/analytics`: the run list and a run's detail (Phase 7 SD10, SD12; PD11, PD12).

Admin only (SD7), read-only, and read on the heavy engine (SD11, AC31): its
own connections and the longer timeout, never the order path's pool. Money is
integer cents named per PD11 -- `revenue_cents`, `bar_price_total_cents`,
`avg_price_cents` -- and no `p0_*` field exists (AC13).

- `GET /api/analytics/runs`: every run, newest first, with its totals.
- `GET /api/analytics/runs/{run_id}`: the same row plus `per_product`, one row
  per product that sold (removed drinks included); 404 `run_not_found`.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import Principal, heavy_engine, require_role
from app.db.analytics import RunTotals, run_detail, run_list
from app.db.runs import RunStatus

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int
    name: str
    status: RunStatus
    t0_ms: int | None
    ended_at_ms: int | None
    duration_ms: int | None
    qty: int
    revenue_cents: int
    bar_price_total_cents: int


class AnalyticsProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str
    product_id: int | None
    name: str
    qty: int
    revenue_cents: int
    bar_price_total_cents: int
    avg_price_cents: int


class AnalyticsRunDetail(AnalyticsRun):
    per_product: list[AnalyticsProduct]


def _run(totals: RunTotals) -> AnalyticsRun:
    return AnalyticsRun.model_validate(dataclasses.asdict(totals))


@router.get("/runs")
async def get_runs(
    request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> list[AnalyticsRun]:
    async with heavy_engine(request).connect() as conn:
        runs = await run_list(conn)
    return [_run(run) for run in runs]


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: int, request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> AnalyticsRunDetail:
    async with heavy_engine(request).connect() as conn:
        detail = await run_detail(conn, run_id)
    return AnalyticsRunDetail(
        **_run(detail.run).model_dump(),
        per_product=[
            AnalyticsProduct.model_validate(dataclasses.asdict(p)) for p in detail.per_product
        ],
    )
