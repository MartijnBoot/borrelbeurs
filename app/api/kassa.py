"""The kassa's routes (B-05 SD7, SD10-SD14, SD22; plan PD9, PD17).

Every route is `require_role("kassa", "admin")` (SD7); a write is refused while
draining after that (Phase 6 PD19). A money write carries an `Idempotency-Key`
as an order does (`app/api/orders.py`): the same key and body again is a 200
replay of the stored entry, another body under it is 422 `idempotency_key_reused`.
An unknown or deleted wallet is 404 `wallet_not_found`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StringConstraints,
    field_validator,
)

from app.api.deps import Principal, clock_of, db_engine, refuse_while_draining, require_role
from app.api.orders import IDEMPOTENCY_KEY_PATTERN
from app.api.wallet_query import WalletQuery
from app.runtime import wallets as actions
from app.runtime.wallet_codes import display_short_code

router = APIRouter(prefix="/kassa", tags=["kassa"])

Kassa = Annotated[Principal, Depends(require_role("kassa", "admin"))]
Draining = Annotated[None, Depends(refuse_while_draining)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_KEY_PATTERN)]

# SD10: €10 to €100 in €5 steps.
TOPUP_AMOUNTS: Final = frozenset(range(1_000, 10_001, 500))


class RecentTopup(BaseModel):
    at: datetime
    amount_cents: int


class KassaWalletData(BaseModel):
    wallet_id: int
    name: str
    balance_cents: int
    created_at: datetime
    last_topup_at: datetime | None
    recent_topup: RecentTopup | None


class TopupData(BaseModel):
    entry_id: int
    amount_cents: int
    created_at: datetime
    actor_label: str | None
    reversed: bool


class TopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: StrictInt

    @field_validator("amount_cents")
    @classmethod
    def _a_step(cls, value: int) -> int:
        if value not in TOPUP_AMOUNTS:
            raise ValueError("a top-up is 1000 to 10000 cents in steps of 500")
        return value


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_wallet_id: StrictInt


class FoundWallet(BaseModel):
    """A wallet the move search lists (SD11, PD17)."""

    wallet_id: int
    name: str
    created_at: datetime
    balance_cents: int
    last_topup_at: datetime | None


class NewCode(BaseModel):
    qr_token: str
    short_code: str


class BookedEntry(BaseModel):
    entry_id: int
    wallet_id: int
    amount_cents: int
    created_at: datetime


def _actor(principal: Principal) -> actions.Actor:
    return actions.Actor(key_id=principal.key_id, label=principal.label)


def _booked(booked: actions.Booked, response: Response) -> BookedEntry:
    if booked.replay:
        response.status_code = 200
    entry = booked.entry
    return BookedEntry(
        entry_id=entry.entry_id,
        wallet_id=entry.wallet_id,
        amount_cents=entry.amount_cents,
        created_at=entry.created_at,
    )


@router.post("/lookup")
async def lookup(body: WalletQuery, request: Request, _: Kassa) -> KassaWalletData:
    found = await actions.lookup(
        db_engine(request),
        qr_token=body.qr_token,
        short_code=body.short_code,
        now_ms=clock_of(request).wall_ms(),
    )
    wallet = found.player.wallet
    recent = found.recent_topup
    return KassaWalletData(
        wallet_id=wallet.wallet_id,
        name=wallet.name,
        balance_cents=found.player.balance_cents,
        created_at=wallet.created_at,
        last_topup_at=found.last_topup_at,
        recent_topup=None
        if recent is None
        else RecentTopup(at=recent.created_at, amount_cents=recent.amount_cents),
    )


@router.get("/wallets/{wallet_id}/topups")
async def list_topups(wallet_id: int, request: Request, _: Kassa) -> list[TopupData]:
    return [
        TopupData(
            entry_id=entry.entry_id,
            amount_cents=entry.amount_cents,
            created_at=entry.created_at,
            actor_label=entry.actor_label,
            reversed=reversed_,
        )
        for entry, reversed_ in await actions.topups(db_engine(request), wallet_id)
    ]


@router.post(
    "/wallets/{wallet_id}/topups",
    status_code=201,
    responses={200: {"model": BookedEntry, "description": "A replay of the stored top-up"}},
)
async def top_up(
    wallet_id: int,
    body: TopupRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
    principal: Kassa,
    _: Draining,
) -> BookedEntry:
    booked = await actions.top_up(
        db_engine(request),
        wallet_id=wallet_id,
        amount_cents=body.amount_cents,
        idempotency_key=idempotency_key,
        actor=_actor(principal),
        now_ms=clock_of(request).wall_ms(),
    )
    return _booked(booked, response)


@router.post(
    "/topups/{entry_id}/reversal",
    status_code=201,
    responses={200: {"model": BookedEntry, "description": "A replay of the stored reversal"}},
)
async def reverse(
    entry_id: int,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
    principal: Kassa,
    _: Draining,
) -> BookedEntry:
    booked = await actions.reverse(
        db_engine(request),
        entry_id=entry_id,
        idempotency_key=idempotency_key,
        actor=_actor(principal),
        now_ms=clock_of(request).wall_ms(),
    )
    return _booked(booked, response)


@router.get("/wallets")
async def search(
    name: Annotated[
        str, Query(), StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
    ],
    request: Request,
    _: Kassa,
) -> list[FoundWallet]:
    return [
        FoundWallet(
            wallet_id=row.wallet.wallet_id,
            name=row.wallet.name,
            created_at=row.wallet.created_at,
            balance_cents=row.balance_cents,
            last_topup_at=row.last_topup_at,
        )
        for row in await actions.search(db_engine(request), name)
    ]


@router.post(
    "/wallets/{wallet_id}/move",
    status_code=201,
    responses={200: {"model": BookedEntry, "description": "A replay of the stored move"}},
)
async def move(
    wallet_id: int,
    body: MoveRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
    principal: Kassa,
    _: Draining,
) -> BookedEntry:
    """The `move_in` entry the move booked on `wallet_id` (SD11)."""
    booked = await actions.move(
        db_engine(request),
        wallet_id=wallet_id,
        from_wallet_id=body.from_wallet_id,
        idempotency_key=idempotency_key,
        actor=_actor(principal),
        now_ms=clock_of(request).wall_ms(),
    )
    return _booked(booked, response)


@router.post("/wallets/{wallet_id}/new-code")
async def new_code(wallet_id: int, request: Request, _: Kassa, __: Draining) -> NewCode:
    wallet = await actions.new_code(db_engine(request), wallet_id)
    return NewCode(qr_token=wallet.qr_token, short_code=display_short_code(wallet.short_code))
