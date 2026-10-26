"""Refunding a wallet payment (B-06 SD9; AC21-AC23; plan PD9).

`POST /api/payments/{entry_id}/refund` is `require_role("bar", "kassa", "admin")`,
then refused while draining (Phase 6 PD19). It carries an `Idempotency-Key` as a
kassa write does: the same key and payment again is a 200 replay of the stored
refund, another payment under it is 422 `idempotency_key_reused`.

A refund returns the money only: one `refund` entry of the payment's whole amount,
with the payment's run. The order, its lines, the revenue and the engine are never
touched (SD9, SD21). A bar key may refund only the payments it booked itself, for
10 minutes on the app clock; kassa and admin any, at any age.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from app.api.deps import Principal, clock_of, db_engine, refuse_while_draining, require_role
from app.api.kassa import BookedEntry, booked_entry
from app.api.orders import IDEMPOTENCY_KEY_PATTERN
from app.runtime import wallets as actions

router = APIRouter(prefix="/payments", tags=["payments"])

Refunder = Annotated[Principal, Depends(require_role("bar", "kassa", "admin"))]


@router.post(
    "/{entry_id}/refund",
    status_code=201,
    responses={200: {"model": BookedEntry, "description": "A replay of the stored refund"}},
)
async def refund(
    entry_id: int,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_KEY_PATTERN)
    ],
    principal: Refunder,
    _: Annotated[None, Depends(refuse_while_draining)],
) -> BookedEntry:
    booked = await actions.refund(
        db_engine(request),
        entry_id=entry_id,
        idempotency_key=idempotency_key,
        actor=actions.Actor(key_id=principal.key_id, label=principal.label),
        role=principal.role,
        now_ms=clock_of(request).wall_ms(),
    )
    return booked_entry(booked, response)
