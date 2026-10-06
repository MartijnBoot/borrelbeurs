"""`GET /api/earnings/series`: the live run's cumulative revenue (Phase 5 SD16, AC20).

60 s buckets aggregated in SQL by `app/db/orders.py:earnings_series`, read
outside the holder's lock: `holder.run_id` is a plain read, and the query
touches only committed orders. Bar and admin (SD19). With no live run it is
409 `no_live_run`. Phase 7 extends it with a run parameter and bucket sizes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import Principal, db_engine, require_role
from app.db.orders import earnings_series
from app.runtime.holder import MarketHolder, NoLiveRunError

router = APIRouter(prefix="/earnings", tags=["earnings"])


class EarningsPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_ms: int
    cum_revenue_cents: int


@router.get("/series")
async def get_series(
    request: Request, _: Annotated[Principal, Depends(require_role("bar", "admin"))]
) -> list[EarningsPoint]:
    holder: MarketHolder = request.app.state.holder
    run_id = holder.run_id
    if run_id is None:
        raise NoLiveRunError("there is no live run")
    async with db_engine(request).connect() as conn:
        series = await earnings_series(conn, run_id)
    return [EarningsPoint(t_ms=t_ms, cum_revenue_cents=cum) for t_ms, cum in series]
