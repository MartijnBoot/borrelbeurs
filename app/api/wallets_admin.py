"""Admin's wallet routes (B-05 SD6, SD15, SD16; plan PD2, PD12, PD18).

`GET /api/admin/wallets` is the Wallets section in one read: the outstanding
balance, the top-ups per borrel net of reversals (newest first, then the entries
without a run when they do not sum to zero), and every live wallet by
case-folded name. `DELETE /api/admin/wallets/{wallet_id}` deletes one as a player
does (SD15), 204, or 404 `wallet_not_found`. `GET`/`PUT /api/admin/wallet-settings`
read and replace the sign-up code and the two retention periods (PD12).

Admin only. The writes refuse while draining (Phase 6 PD19).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from app.api.deps import Principal, clock_of, db_engine, refuse_while_draining, require_role
from app.db.wallets import WalletSettingsRow
from app.runtime import wallets as actions

router = APIRouter(prefix="/admin", tags=["wallets"])

Admin = Annotated[Principal, Depends(require_role("admin"))]
Draining = Annotated[None, Depends(refuse_while_draining)]

SIGNUP_CODE_MAX = 40


class BorrelTopups(BaseModel):
    """`run_id` and `name` are null on the row of entries without a run (PD2)."""

    run_id: int | None
    name: str | None
    net_topup_cents: int


class ListedWalletData(BaseModel):
    wallet_id: int
    name: str
    balance_cents: int
    last_activity_at: datetime


class WalletsOverview(BaseModel):
    outstanding_cents: int
    per_borrel: list[BorrelTopups]
    wallets: list[ListedWalletData]


class WalletSettingsData(BaseModel):
    """`signup_code` null is sign-up closed (SD6). A code is trimmed, and blank means null."""

    model_config = ConfigDict(extra="forbid")

    signup_code: StrictStr | None
    unfunded_days: Annotated[StrictInt, Field(ge=1, le=365)]
    inactive_months: Annotated[StrictInt, Field(ge=1, le=60)]

    @field_validator("signup_code")
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if len(value.strip()) > SIGNUP_CODE_MAX:
            raise ValueError(f"a sign-up code is at most {SIGNUP_CODE_MAX} characters")
        return value.strip()


def _settings(row: WalletSettingsRow) -> WalletSettingsData:
    return WalletSettingsData(
        signup_code=row.signup_code,
        unfunded_days=row.unfunded_days,
        inactive_months=row.inactive_months,
    )


@router.get("/wallets")
async def wallets_overview(request: Request, _: Admin) -> WalletsOverview:
    found = await actions.overview(db_engine(request))
    return WalletsOverview(
        outstanding_cents=found.outstanding_cents,
        per_borrel=[
            BorrelTopups(run_id=row.run_id, name=row.name, net_topup_cents=row.net_topup_cents)
            for row in found.per_run
        ],
        wallets=[
            ListedWalletData(
                wallet_id=row.wallet.wallet_id,
                name=row.wallet.name,
                balance_cents=row.balance_cents,
                last_activity_at=row.last_activity_at,
            )
            for row in found.wallets
        ],
    )


@router.delete("/wallets/{wallet_id}", status_code=204)
async def delete_wallet(
    wallet_id: int, request: Request, principal: Admin, _: Draining
) -> Response:
    await actions.delete(
        db_engine(request),
        wallet_id,
        actor=actions.Actor(key_id=principal.key_id, label=principal.label),
        now_ms=clock_of(request).wall_ms(),
    )
    return Response(status_code=204)


@router.get("/wallet-settings")
async def get_wallet_settings(request: Request, _: Admin) -> WalletSettingsData:
    return _settings(await actions.settings(db_engine(request)))


@router.put("/wallet-settings")
async def put_wallet_settings(
    body: WalletSettingsData, request: Request, _: Admin, __: Draining
) -> WalletSettingsData:
    stored = await actions.put_settings(
        db_engine(request),
        WalletSettingsRow(body.signup_code, body.unfunded_days, body.inactive_months),
    )
    return _settings(stored)
