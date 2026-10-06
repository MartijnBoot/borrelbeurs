"""Market manipulation over HTTP (Phase 3 SD1, SD23; AC26, AC27).

`POST /api/market/jumps {drink_id, target_price_cents, duration_ms}`: `duration_ms`
1 000-1 800 000, an active drink of the live run, and a target within that
drink's `[p_min_cents, p_max_cents]`, else 422.

`POST /api/market/events {kind, duration_ms}`: crash, bubble or correction;
`duration_ms` 1 000-600 000, default 30 000.

Both are bar and admin (SD1: bar keeps v1's manipulation rights).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Principal, clock_of, refuse_while_draining, require_role
from app.core.errors import AppError
from app.realtime.messages import MarketEventInfo
from app.runtime.holder import MarketHolder, NoLiveRunError
from app.runtime.manipulation import DEFAULT_EVENT_MS, schedule, start_event
from app.runtime.market_events import EventKind

router = APIRouter(prefix="/market", tags=["market"])


class InvalidManipulation(AppError):
    status_code = 422
    code = "invalid_request"


class JumpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drink_id: int
    target_price_cents: int
    duration_ms: Annotated[int, Field(ge=1_000, le=1_800_000)]


class JumpResult(BaseModel):
    version: int


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EventKind
    duration_ms: Annotated[int, Field(ge=1_000, le=600_000)] = DEFAULT_EVENT_MS


def _holder(request: Request) -> MarketHolder:
    holder: MarketHolder = request.app.state.holder
    return holder


@router.post("/jumps", status_code=201)
async def post_jump(
    body: JumpRequest,
    request: Request,
    _: Annotated[Principal, Depends(require_role("bar", "admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> JumpResult:
    holder = _holder(request)
    if holder.is_empty or holder.spec is None:
        raise NoLiveRunError("there is no live run")
    if body.drink_id not in holder.drink_ids:
        raise InvalidManipulation(f"drink {body.drink_id} is not an active drink of the live run")
    i = holder.drink_ids.index(body.drink_id)
    p_min = round(float(holder.spec.p_min[i]) * 100)
    p_max = round(float(holder.spec.p_max[i]) * 100)
    if not p_min <= body.target_price_cents <= p_max:
        raise InvalidManipulation(
            f"target {body.target_price_cents} is outside [{p_min}, {p_max}] for this drink"
        )
    version = await schedule(
        holder, body.drink_id, body.target_price_cents, body.duration_ms, clock=clock_of(request)
    )
    return JumpResult(version=version)


@router.post("/events", status_code=201)
async def post_event(
    body: EventRequest,
    request: Request,
    _: Annotated[Principal, Depends(require_role("bar", "admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> MarketEventInfo:
    event = await start_event(
        _holder(request), body.kind, body.duration_ms, clock=clock_of(request)
    )
    return MarketEventInfo(
        event_id=event.event_id,
        kind=event.kind,
        drink_ids=event.drink_ids,
        t_start_ms=event.t_start_ms,
        t_end_ms=event.t_end_ms,
    )
