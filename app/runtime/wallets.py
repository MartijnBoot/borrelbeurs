"""The wallet actions, each one transaction (B-05 SD23; plan Approach, PD8-PD11).

Sign-up, top-up, reversal, move, new code and delete each run as one
`engine.begin()`. None touches `MarketHolder` or runs inside the market's state
lock: the live run an entry records is read inside the action's own transaction
(`app.db.wallets.live_run_id`, PD10). Times are the app clock's, passed in as
`now_ms` (PD8).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import AppError
from app.db import wallets
from app.db.products import name_key
from app.db.wallets import WalletRow
from app.runtime.wallet_codes import cookie_hash, new_cookie_value


class SignupClosed(AppError):
    """No sign-up code is set, so sign-up is closed (SD6)."""

    status_code = 409
    code = "signup_closed"


class SignupCodeInvalid(AppError):
    status_code = 403
    code = "signup_code_invalid"


@dataclass(frozen=True)
class PlayerWallet:
    """A wallet as its player sees it (SD21)."""

    wallet: WalletRow
    balance_cents: int


@dataclass(frozen=True)
class SignUp:
    """`cookie_value` is the new wallet's credential, or `None` when the request's own
    cookie already held a wallet and that one is returned (SD6, AC8)."""

    player: PlayerWallet
    cookie_value: str | None


async def _check_code(conn: AsyncConnection, code: str) -> None:
    """The deployment's sign-up code, compared trimmed and case-insensitively (SD6, PD12)."""
    expected = (await wallets.get_settings(conn)).signup_code
    if expected is None:
        raise SignupClosed("sign-up is closed")
    if code.strip().casefold() != expected.strip().casefold():
        raise SignupCodeInvalid("that sign-up code is not valid")


async def name_check(engine: AsyncEngine, *, name: str, code: str) -> list[str] | None:
    """`None` when `name` is free; else up to three free suggestions (SD3, AC4)."""
    async with engine.connect() as conn:
        await _check_code(conn, code)
        key = name_key(name)
        if key not in await wallets.taken_name_keys(conn, key):
            return None
        return await wallets.name_suggestions(conn, name)


async def _player(conn: AsyncConnection, wallet: WalletRow) -> PlayerWallet:
    return PlayerWallet(wallet, await wallets.balance(conn, wallet.wallet_id))


async def sign_up(
    engine: AsyncEngine, *, name: str, code: str, cookie_value: str | None, now_ms: int
) -> SignUp:
    """The wallet the request's cookie holds, else a new one named `name` (SD3, SD6).

    The cookie is looked at before the code (plan T5's order), so a phone with a
    wallet gets it back even after the code changed. A taken name is
    `NameTaken` with suggestions, nothing written.
    """
    async with engine.begin() as conn:
        if cookie_value:
            existing = await wallets.get_by_cookie_hash(conn, cookie_hash(cookie_value))
            if existing is not None:
                return SignUp(await _player(conn, existing), None)
        await _check_code(conn, code)
        value = new_cookie_value()
        wallet = await wallets.create_wallet(
            conn, name=name, cookie_hash=cookie_hash(value), now_ms=now_ms
        )
        return SignUp(PlayerWallet(wallet, 0), value)
