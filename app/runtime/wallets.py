"""The wallet actions, each one transaction (B-05 SD23; plan Approach, PD8-PD11).

Sign-up, top-up, reversal, move, new code and delete each run as one
`engine.begin()`. None touches `MarketHolder` or runs inside the market's state
lock: the live run an entry records is read inside the action's own transaction
(`app.db.wallets.live_run_id`, PD10). Times are the app clock's, passed in as
`now_ms` (PD8).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import AppError
from app.db import wallets
from app.db.products import name_key
from app.db.wallets import EntryRow, IdempotencyKeyReused, NoWallet, WalletNotFound, WalletRow
from app.runtime.wallet_codes import cookie_hash, new_cookie_value, normalise_short_code


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


async def player_wallet(engine: AsyncEngine, wallet: WalletRow) -> PlayerWallet:
    async with engine.connect() as conn:
        return await _player(conn, wallet)


class BalanceNegative(AppError):
    """A player cannot delete a wallet in debt; only admin can write a debt off (B-06 SD8)."""

    status_code = 409
    code = "balance_negative"


async def delete_own_wallet(engine: AsyncEngine, wallet_id: int, *, now_ms: int) -> None:
    """The player deletes their wallet (SD15). Gone meanwhile is `no_wallet`, as any
    player route answers a deleted wallet's cookie (AC13). A balance below zero is
    `BalanceNegative`, nothing written (B-06 SD8, AC26): the wallet is locked first,
    so a payment committing meanwhile is seen."""
    try:
        async with engine.begin() as conn:
            if await wallets.lock_wallet(conn, wallet_id) is None:
                raise WalletNotFound(f"no wallet {wallet_id}")
            if await wallets.balance(conn, wallet_id) < 0:
                raise BalanceNegative("this wallet is in debt; top it up at the kassa first")
            await wallets.delete_wallet(conn, wallet_id, now_ms=now_ms)
    except WalletNotFound:
        raise NoWallet("there is no wallet on this phone") from None


# --- the kassa (SD10, SD22) -------------------------------------------------------

RECENT_TOPUP_MS: Final = 2 * 60 * 1000
_KEY_INDEX: Final = "wallet_entry_idempotency_key_key"


@dataclass(frozen=True)
class Actor:
    """The crew key acting, recorded on the entries it writes (SD9)."""

    key_id: int
    label: str


@dataclass(frozen=True)
class KassaWallet:
    """A found wallet as the kassa sees it (SD22). `recent_topup` is a top-up booked in the
    last 2 minutes on the app clock, by any key (SD10), else `None`."""

    player: PlayerWallet
    last_topup_at: datetime | None
    recent_topup: EntryRow | None


@dataclass(frozen=True)
class Booked:
    """An entry a write booked, or found already booked under its key (`replay`, PD9)."""

    entry: EntryRow
    replay: bool


async def lookup(
    engine: AsyncEngine, *, qr_token: str | None, short_code: str | None, now_ms: int
) -> KassaWallet:
    """The live wallet behind a QR token or a typed short code (AC14), or `WalletNotFound`."""
    async with engine.connect() as conn:
        wallet = None
        if qr_token is not None:
            wallet = await wallets.get_by_qr_token(conn, qr_token)
        elif short_code is not None and (code := normalise_short_code(short_code)) is not None:
            wallet = await wallets.get_by_short_code(conn, code)
        if wallet is None:
            raise WalletNotFound("no wallet has this code")
        last = await wallets.last_topup(conn, wallet.wallet_id)
        recent = last is not None and last.created_at >= wallets.at(now_ms - RECENT_TOPUP_MS)
        return KassaWallet(
            await _player(conn, wallet),
            None if last is None else last.created_at,
            last if recent else None,
        )


async def topups(engine: AsyncEngine, wallet_id: int) -> list[tuple[EntryRow, bool]]:
    async with engine.connect() as conn:
        await wallets.get(conn, wallet_id)
        return await wallets.topups(conn, wallet_id)


async def _book_once(
    engine: AsyncEngine,
    key: str,
    same: Callable[[AsyncConnection, EntryRow], Awaitable[bool]],
    book: Callable[[AsyncConnection], Awaitable[EntryRow]],
) -> Booked:
    """Run `book` in one transaction unless `key` already booked an entry (PD9).

    A stored entry that `same` accepts is the replay; any other is
    `IdempotencyKeyReused`. Two first sends at once meet at the unique index: the
    loser reads the winner's entry and judges it the same way.
    """

    async def replay(conn: AsyncConnection, stored: EntryRow) -> Booked:
        if not await same(conn, stored):
            raise IdempotencyKeyReused("this Idempotency-Key was already used for another request")
        return Booked(stored, replay=True)

    try:
        async with engine.begin() as conn:
            stored = await wallets.find_entry_by_key(conn, key)
            if stored is not None:
                return await replay(conn, stored)
            return Booked(await book(conn), replay=False)
    except IntegrityError as error:
        if _KEY_INDEX not in str(error.orig):
            raise
        async with engine.connect() as conn:
            winner = await wallets.find_entry_by_key(conn, key)
            if winner is None:
                raise
            return await replay(conn, winner)


async def top_up(
    engine: AsyncEngine,
    *,
    wallet_id: int,
    amount_cents: int,
    idempotency_key: str,
    actor: Actor,
    now_ms: int,
) -> Booked:
    """One `topup` entry with the key, its label and the live run (SD9, SD13; AC15).

    It never refuses a second top-up: the 2-minute warning is the page's (SD10).
    """

    async def same(_: AsyncConnection, stored: EntryRow) -> bool:
        return (stored.kind, stored.wallet_id, stored.amount_cents) == (
            "topup",
            wallet_id,
            amount_cents,
        )

    async def book(conn: AsyncConnection) -> EntryRow:
        if await wallets.lock_wallet(conn, wallet_id) is None:
            raise WalletNotFound(f"no wallet {wallet_id}")
        return await wallets.insert_entry(
            conn,
            wallet_id=wallet_id,
            kind="topup",
            amount_cents=amount_cents,
            now_ms=now_ms,
            run_id=await wallets.live_run_id(conn),
            actor_key_id=actor.key_id,
            actor_label=actor.label,
            idempotency_key=idempotency_key,
        )

    return await _book_once(engine, idempotency_key, same, book)


class TopupNotFound(AppError):
    """No top-up has this id. Any other entry kind answers the same, so no route tells
    which other entries exist (SD12, AC24)."""

    status_code = 404
    code = "topup_not_found"


async def reverse(
    engine: AsyncEngine, *, entry_id: int, idempotency_key: str, actor: Actor, now_ms: int
) -> Booked:
    """One `reversal` of minus the top-up's amount, naming it, with the original's run
    (SD12; AC21, AC22). Once per top-up, never below zero, never on a deleted wallet.

    The wallet is locked before the reversal and the balance are read, so two
    reversals at once serialise and the second sees the first (AC23).
    """

    async def same(_: AsyncConnection, stored: EntryRow) -> bool:
        return stored.kind == "reversal" and stored.reverses_entry_id == entry_id

    async def book(conn: AsyncConnection) -> EntryRow:
        original = await wallets.get_entry(conn, entry_id)
        if original is None or original.kind != "topup":
            raise TopupNotFound(f"no top-up {entry_id}")
        if await wallets.lock_wallet(conn, original.wallet_id) is None:
            raise wallets.WalletDeleted("this wallet is deleted")
        if await wallets.reversal_of(conn, entry_id) is not None:
            raise wallets.AlreadyReversed("this top-up is already reversed")
        if await wallets.balance(conn, original.wallet_id) < original.amount_cents:
            raise wallets.InsufficientBalance("the balance is too low to reverse this top-up")
        return await wallets.insert_entry(
            conn,
            wallet_id=original.wallet_id,
            kind="reversal",
            amount_cents=-original.amount_cents,
            now_ms=now_ms,
            run_id=original.run_id,
            reverses_entry_id=entry_id,
            actor_key_id=actor.key_id,
            actor_label=actor.label,
            idempotency_key=idempotency_key,
        )

    return await _book_once(engine, idempotency_key, same, book)


async def search(engine: AsyncEngine, text: str) -> list[wallets.SearchRow]:
    """Every live wallet whose name contains `text` (case-folded), and the wallet a typed
    short code names, first (SD11, PD17)."""
    async with engine.connect() as conn:
        return await wallets.search(
            conn, fragment_key=name_key(text), short_code=normalise_short_code(text)
        )


async def move(
    engine: AsyncEngine,
    *,
    wallet_id: int,
    from_wallet_id: int,
    idempotency_key: str,
    actor: Actor,
    now_ms: int,
) -> Booked:
    """Move the whole balance and the name of `from_wallet_id` onto `wallet_id`, in one
    transaction (SD11; AC26, AC27). A debt moves too (B-06 SD8, AC28): only a zero
    balance or the same wallet is `nothing_to_move`.

    Both wallets are locked in id order. The order inside is fixed (plan T8): the
    out and in entries, then the old wallet deleted, freeing its name, then the new
    wallet takes it, since the name's unique index allows one holder at a time.
    The `move_in` carries the key.
    """

    async def same(conn: AsyncConnection, stored: EntryRow) -> bool:
        if stored.kind != "move_in" or stored.wallet_id != wallet_id:
            return False
        assert stored.counterpart_entry_id is not None
        counterpart = await wallets.get_entry(conn, stored.counterpart_entry_id)
        return counterpart is not None and counterpart.wallet_id == from_wallet_id

    async def book(conn: AsyncConnection) -> EntryRow:
        if wallet_id == from_wallet_id:
            raise wallets.NothingToMove("a wallet cannot take its own balance")
        target, source = await wallets.lock_wallets(conn, wallet_id, from_wallet_id)
        if target is None or source is None:
            raise WalletNotFound("one of the two wallets is deleted")
        amount = await wallets.balance(conn, from_wallet_id)
        if amount == 0:
            raise wallets.NothingToMove(f"{source.name} has no balance to move")
        run_id = await wallets.live_run_id(conn)
        out = await wallets.insert_entry(
            conn,
            wallet_id=from_wallet_id,
            kind="move_out",
            amount_cents=-amount,
            now_ms=now_ms,
            run_id=run_id,
            actor_key_id=actor.key_id,
            actor_label=actor.label,
        )
        moved_in = await wallets.insert_entry(
            conn,
            wallet_id=wallet_id,
            kind="move_in",
            amount_cents=amount,
            now_ms=now_ms,
            run_id=run_id,
            counterpart_entry_id=out.entry_id,
            actor_key_id=actor.key_id,
            actor_label=actor.label,
            idempotency_key=idempotency_key,
        )
        await wallets.delete_wallet(
            conn, from_wallet_id, now_ms=now_ms, actor_key_id=actor.key_id, actor_label=actor.label
        )
        await wallets.rename(conn, wallet_id, source.name)
        return moved_in

    return await _book_once(engine, idempotency_key, same, book)


async def new_code(engine: AsyncEngine, wallet_id: int) -> WalletRow:
    """A new QR token and short code; the old ones stop working at once (SD14, AC28)."""
    async with engine.begin() as conn:
        return await wallets.replace_codes(conn, wallet_id)


# --- admin (SD15, SD16) -------------------------------------------------------------


@dataclass(frozen=True)
class Overview:
    """Admin's Wallets section, one `REPEATABLE READ` snapshot so the totals and the list
    agree, as `app.db.analytics.run_detail` reads."""

    outstanding_cents: int
    per_run: list[wallets.RunTopups]
    wallets: list[wallets.ListedWallet]


async def overview(engine: AsyncEngine) -> Overview:
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
        async with conn.begin():
            return Overview(
                await wallets.outstanding_cents(conn),
                await wallets.topups_per_run(conn),
                await wallets.list_wallets(conn),
            )


async def delete(engine: AsyncEngine, wallet_id: int, *, actor: Actor, now_ms: int) -> None:
    """Admin deletes a wallet, as a player does (SD15, AC30); the closing entry names the key."""
    async with engine.begin() as conn:
        await wallets.delete_wallet(
            conn, wallet_id, now_ms=now_ms, actor_key_id=actor.key_id, actor_label=actor.label
        )


async def settings(engine: AsyncEngine) -> wallets.WalletSettingsRow:
    async with engine.connect() as conn:
        return await wallets.get_settings(conn)


async def put_settings(
    engine: AsyncEngine, value: wallets.WalletSettingsRow
) -> wallets.WalletSettingsRow:
    async with engine.begin() as conn:
        return await wallets.put_settings(conn, value)
