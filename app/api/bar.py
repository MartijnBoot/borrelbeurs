"""The bar's wallet routes (B-06 SD9, SD13; plan PD9).

Every route is `require_role("bar", "admin")`. A bar key may look a scanned wallet
up and sees only its name and balance (SD13): never a wallet id, a short code or a
token. It may list the wallet payments it booked itself in the last 10 minutes on
the app clock (SD9), each with its lines, amount, wallet name and whether it was
refunded; refunding one is `app/api/payments.py`'s.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import Principal, clock_of, db_engine, require_role
from app.api.wallet_query import WalletQuery
from app.db.wallets import PaymentRow
from app.runtime import wallets as actions

router = APIRouter(prefix="/bar", tags=["bar"])

Bar = Annotated[Principal, Depends(require_role("bar", "admin"))]


class BarWallet(BaseModel):
    name: str
    balance_cents: int


class PaymentLine(BaseModel):
    name: str
    qty: int


class PaymentData(BaseModel):
    """A payment in a list (PD9): `amount_cents` is the amount paid, positive, as a
    top-up's is; `lines` is `null` once the order is gone with its run (AC24)."""

    entry_id: int
    amount_cents: int
    created_at: datetime
    lines: list[PaymentLine] | None
    refunded: bool


class BarPayment(PaymentData):
    """`name` is the wallet's, `null` once it is deleted (B-05 SD15)."""

    name: str | None


def payment_data(row: PaymentRow) -> PaymentData:
    """`row` as a list shows it; the kassa's list extends it."""
    return PaymentData(
        entry_id=row.entry.entry_id,
        amount_cents=-row.entry.amount_cents,
        created_at=row.entry.created_at,
        lines=None
        if row.lines is None
        else [PaymentLine(name=name, qty=qty) for name, qty in row.lines],
        refunded=row.refunded,
    )


@router.post("/wallet-lookup")
async def wallet_lookup(body: WalletQuery, request: Request, _: Bar) -> BarWallet:
    found = await actions.bar_lookup(
        db_engine(request),
        qr_token=body.qr_token,
        short_code=body.short_code,
        now_ms=clock_of(request).wall_ms(),
    )
    return BarWallet(name=found.wallet.name, balance_cents=found.balance_cents)


@router.get("/payments")
async def recent_payments(request: Request, principal: Bar) -> list[BarPayment]:
    rows = await actions.recent_payments(
        db_engine(request), actor_key_id=principal.key_id, now_ms=clock_of(request).wall_ms()
    )
    return [BarPayment(**dict(payment_data(row)), name=row.wallet_name) for row in rows]
