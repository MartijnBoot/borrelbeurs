"""`GET /api/earnings/series`: a run's cumulative revenue (Phase 5 SD16, AC20; Phase 7 SD9).

Bucketed in SQL by `app/db/orders.py:earnings_series` at `bucket_s` (60, 300
or 900; anything else is 422), so the size is bounded by run length over the
bucket, not by order count (D-31). Read outside the holder's lock:
`holder.run_id` is a plain read, and the query touches only committed orders.

Without `run_id`, or naming the live run, it is the live run's series on the
main engine, for bar and admin (SD19); with no live run that is 409
`no_live_run`. Any other `run_id` is admin-only (the bar gets 403, known run or
not) and is read on the heavy engine (PD15); an unknown one is 404
`run_not_found`, and a run without orders is `[]`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.api.deps import Forbidden, Principal, db_engine, heavy_engine, require_role
from app.db.orders import earnings_series
from app.db.runs import get_run
from app.runtime.holder import MarketHolder, NoLiveRunError

router = APIRouter(prefix="/earnings", tags=["earnings"])


def _digits_to_int(value: object) -> object:
    """A query string arrives as text, and a `Literal` of ints never coerces it."""
    return int(value) if isinstance(value, str) and value.isdecimal() else value


BucketSeconds = Annotated[Literal[60, 300, 900], BeforeValidator(_digits_to_int)]


class EarningsPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_ms: int
    cum_revenue_cents: int


@router.get("/series")
async def get_series(
    request: Request,
    principal: Annotated[Principal, Depends(require_role("bar", "admin"))],
    run_id: int | None = None,
    bucket_s: BucketSeconds = 60,
) -> list[EarningsPoint]:
    holder: MarketHolder = request.app.state.holder
    live_id = holder.run_id
    bucket_ms = bucket_s * 1000
    if run_id is None or run_id == live_id:
        if live_id is None:
            raise NoLiveRunError("there is no live run")
        async with db_engine(request).connect() as conn:
            series = await earnings_series(conn, live_id, bucket_ms=bucket_ms)
    else:
        if principal.role != "admin":
            raise Forbidden("only the admin may read another run's series")
        async with heavy_engine(request).connect() as conn:
            await get_run(conn, run_id)
            series = await earnings_series(conn, run_id, bucket_ms=bucket_ms)
    return [EarningsPoint(t_ms=t_ms, cum_revenue_cents=cum) for t_ms, cum in series]
