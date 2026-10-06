"""`POST /api/orders` (Phase 3 SD17, SD20, SD21; AC9, AC11, AC13, AC14a).

The request shape is validated here -- the `Idempotency-Key` header (required,
8-128 of `[A-Za-z0-9_-]`), `quote_version >= 0`, 1..N lines with `qty` 1-99
and each `drink_id` once -- and everything that needs the live market is
`place_order`'s, under the holder's lock (T18). A process that is shutting
down refuses new orders with 503 `shutting_down` (SD10; `refuse_while_draining`).

The body is the receipt's bytes exactly: 201 the first time, 200 on a replay,
byte-identical (plan PD7).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.api.deps import Principal, clock_of, refuse_while_draining, require_role
from app.runtime.grace import QuotedLine
from app.runtime.orders import OrderRequest, Receipt, place_order

router = APIRouter(prefix="/orders", tags=["orders"])

IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_-]{8,128}$"


class OrderLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drink_id: int
    qty: Annotated[int, Field(ge=1, le=99)]
    unit_price_cents: Annotated[int, Field(ge=0)]


def _one_line_per_drink(lines: list[OrderLine]) -> list[OrderLine]:
    if len({line.drink_id for line in lines}) != len(lines):
        raise ValueError("each drink_id may appear in at most one line")
    return lines


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_version: Annotated[int, Field(ge=0)]
    lines: Annotated[list[OrderLine], Field(min_length=1), AfterValidator(_one_line_per_drink)]


@router.post(
    "",
    status_code=201,
    response_model=Receipt,
    responses={200: {"model": Receipt, "description": "A replay of the stored receipt"}},
)
async def post_order(
    body: OrderBody,
    request: Request,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_KEY_PATTERN)
    ],
    principal: Annotated[Principal, Depends(require_role("bar", "admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> Response:
    placed = await place_order(
        request.app.state.holder,
        OrderRequest(
            idempotency_key=idempotency_key,
            quote_version=body.quote_version,
            lines=tuple(
                QuotedLine(drink_id=ln.drink_id, qty=ln.qty, unit_price_cents=ln.unit_price_cents)
                for ln in body.lines
            ),
        ),
        actor_key_id=principal.key_id,
        clock=clock_of(request),
    )
    return Response(
        content=placed.body,
        status_code=200 if placed.replay else 201,
        media_type="application/json",
    )
