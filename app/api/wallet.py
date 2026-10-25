"""The player's wallet routes (B-05 SD3, SD6, SD19, SD21; plan PD12-PD14).

Sign-up and the name check are public (SD6: the owner approved them for the
public-route allowlist), behind the deployment's sign-up code and one per-IP
limiter shaped as the login one, counted before the code or the cookie is looked
at. The player's own routes carry `require_wallet` (SD8).

A player has no crew session: the wallet is the `bb_wallet` cookie, set
`HttpOnly`, `SameSite=Strict`, `Secure` exactly as the crew cookie is, with a
400-day max-age (SD19). Only the cookie value's SHA-256 is stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import security
from app.api.auth import RateLimited
from app.api.deps import (
    WALLET_COOKIE,
    clock_of,
    db_engine,
    refuse_while_draining,
    require_wallet,
    settings_of,
)
from app.db.wallets import WalletRow
from app.runtime import wallets as actions
from app.runtime.wallet_codes import display_short_code

router = APIRouter(prefix="/wallet", tags=["wallet"])

WALLET_COOKIE_MAX_AGE_S: Final = 400 * 24 * 3600

WalletName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: WalletName
    code: Annotated[str, Field(max_length=200)]


class NameCheck(BaseModel):
    available: bool
    suggestions: list[str]


class WalletData(BaseModel):
    """The player's own wallet (SD21): the short code in its display form (PD6)."""

    name: str
    balance_cents: int
    qr_token: str
    short_code: str
    created_at: datetime


def limit_signups(request: Request) -> None:
    """SD6: sign-up and the name check share one per-IP limiter, as login (SD7)."""
    limiter: security.LoginLimiter = request.app.state.signup_limiter
    retry_after = limiter.check(request.client.host if request.client else "unknown")
    if retry_after is not None:
        raise RateLimited(
            "too many sign-up attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )


def wallet_data(player: actions.PlayerWallet) -> WalletData:
    wallet = player.wallet
    return WalletData(
        name=wallet.name,
        balance_cents=player.balance_cents,
        qr_token=wallet.qr_token,
        short_code=display_short_code(wallet.short_code),
        created_at=wallet.created_at,
    )


def set_wallet_cookie(request: Request, response: Response, value: str) -> None:
    response.set_cookie(
        WALLET_COOKIE,
        value,
        max_age=WALLET_COOKIE_MAX_AGE_S,
        path="/",
        **security.cookie_kwargs(settings_of(request)),
    )


@router.post("/name-check")
async def name_check(
    body: SignupRequest,
    request: Request,
    _: Annotated[None, Depends(limit_signups)],
) -> NameCheck:
    suggestions = await actions.name_check(db_engine(request), name=body.name, code=body.code)
    return NameCheck(available=suggestions is None, suggestions=suggestions or [])


@router.post("", status_code=201)
async def sign_up(
    body: SignupRequest,
    request: Request,
    response: Response,
    _draining: Annotated[None, Depends(refuse_while_draining)],
    _limited: Annotated[None, Depends(limit_signups)],
) -> WalletData:
    """201 with a new wallet and its cookie, or 200 with the one the cookie holds (AC8)."""
    outcome = await actions.sign_up(
        db_engine(request),
        name=body.name,
        code=body.code,
        cookie_value=request.cookies.get(WALLET_COOKIE),
        now_ms=clock_of(request).wall_ms(),
    )
    if outcome.cookie_value is None:
        response.status_code = 200
    else:
        set_wallet_cookie(request, response, outcome.cookie_value)
    return wallet_data(outcome.player)


@router.get("")
async def my_wallet(
    request: Request, response: Response, wallet: Annotated[WalletRow, Depends(require_wallet)]
) -> WalletData:
    """The player's wallet; renews the cookie, same value, another 400 days (AC11)."""
    player = await actions.player_wallet(db_engine(request), wallet)
    set_wallet_cookie(request, response, request.cookies[WALLET_COOKIE])
    return wallet_data(player)


@router.delete("", status_code=204)
async def delete_my_wallet(
    request: Request,
    response: Response,
    wallet: Annotated[WalletRow, Depends(require_wallet)],
    _: Annotated[None, Depends(refuse_while_draining)],
) -> None:
    """SD15: a closing entry for any balance left, the row blanked, the cookie cleared."""
    # A wallet in debt is 409 `balance_negative`, raised before the cookie is touched
    # (B-06 SD8, AC26); left out of the docstring so the OpenAPI schema is unchanged.
    await actions.delete_own_wallet(
        db_engine(request), wallet.wallet_id, now_ms=clock_of(request).wall_ms()
    )
    response.delete_cookie(WALLET_COOKIE, path="/", **security.cookie_kwargs(settings_of(request)))
