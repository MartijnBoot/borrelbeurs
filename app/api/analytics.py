"""`/api/analytics`: the run list and a run's detail (Phase 7 SD10, SD12; PD11, PD12).

Admin only (SD7), read-only, and read on the heavy engine (SD11, AC31): its
own connections and the longer timeout, never the order path's pool. Money is
integer cents named per PD11 -- `revenue_cents`, `bar_price_total_cents`,
`avg_price_cents` -- and no `p0_*` field exists (AC13).

- `GET /api/analytics/runs`: every run, newest first, with its totals.
- `GET /api/analytics/runs/{run_id}`: the same row plus `per_product`, one row
  per product that sold (removed drinks included); 404 `run_not_found`.
- `GET /api/analytics/compare?a=&b=`: both runs per product, joined on the
  product (PD14); a side the product is absent from is `null`.
- `GET /api/analytics/price-curve?product_id=&a=&b=&bucket_s=`: the product's
  price per bucket in each run, minutes since the run's start (PD13); `[]` for
  a run without the product.

Both two-run routes answer 404 `run_not_found` with `side` naming the unknown
run.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import Principal, heavy_engine, require_role
from app.api.earnings import BucketSeconds
from app.db.analytics import RunTotals, compare, price_curve, run_detail, run_list
from app.db.runs import RunNotFound, RunStatus

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


class CompareSide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int
    revenue_cents: int
    bar_price_total_cents: int


class CompareRowData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str
    product_id: int | None
    name: str
    a: CompareSide | None
    b: CompareSide | None


class PricePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: int
    price_cents: int | None


class PriceCurveData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: list[PricePoint]
    b: list[PricePoint]


@router.get("/compare")
async def get_compare(
    a: int, b: int, request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> list[CompareRowData]:
    async with heavy_engine(request).connect() as conn:
        rows = await compare(conn, a, b)
    return [CompareRowData.model_validate(dataclasses.asdict(row)) for row in rows]


@router.get("/price-curve")
async def get_price_curve(
    product_id: int,
    a: int,
    b: int,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    bucket_s: BucketSeconds = 60,
) -> PriceCurveData:
    curves: dict[str, list[PricePoint]] = {}
    async with heavy_engine(request).connect() as conn:
        for side, run_id in (("a", a), ("b", b)):
            try:
                points = await price_curve(conn, run_id, product_id, bucket_ms=bucket_s * 1000)
            except RunNotFound:
                raise RunNotFound(f"no run {run_id} ({side})", extra={"side": side}) from None
            curves[side] = [PricePoint(minute=p.minute, price_cents=p.price_cents) for p in points]
    return PriceCurveData(**curves)
