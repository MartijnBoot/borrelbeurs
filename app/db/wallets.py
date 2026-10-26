"""The wallet repository (B-05 SD3, SD9, SD13-SD15, SD23; plan PD4-PD11, PD17-PD19).

Every function takes an `AsyncConnection` and never begins or commits: the caller
(`app/runtime/wallets.py`) owns the one transaction each action is. Every wallet
read and write goes through here.

- **Live wallets only.** A getter returns a wallet that is not deleted, or `None`.
  A deleted row is blank (`wallet_deleted_check`), so nothing finds it by name or
  code anyway.
- **The balance is `SUM(amount_cents)`** of a wallet's entries; no column holds it.
- **Locks.** A money action calls `lock_wallet` (`SELECT … FOR UPDATE`) before it
  reads the balance it guards, so two actions on one wallet serialise. A move
  locks both wallets in `wallet_id` order (`lock_wallets`), as
  `app/db/keys.py:lock_unrevoked_admins` orders its locks.
- **Codes collide rarely, and are retried.** A new QR token or short code that hits
  its unique index is drawn again in a savepoint, up to five times (PD5).
- **Times come from the app clock** (`now_ms`), as `run.ended_at` does (PD8).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, DateTime, Interval, Row, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.errors import AppError
from app.db.models import Drink, OrderLine, Run, Wallet, WalletEntry, WalletSettings
from app.db.products import name_key
from app.db.runs import current_run
from app.runtime import wallet_codes

EntryKind = Literal["topup", "reversal", "move_out", "move_in", "closing", "payment", "refund"]

CODE_ATTEMPTS: Final = 5
DEFAULT_UNFUNDED_DAYS: Final = 30
DEFAULT_INACTIVE_MONTHS: Final = 12

_NAME_INDEX: Final = "wallet_name_key"
_CODE_INDEXES: Final = ("wallet_qr_token", "wallet_short_code")


class WalletNotFound(AppError):
    """No live wallet has this id, token or code (SD14)."""

    status_code = 404
    code = "wallet_not_found"


class NoWallet(AppError):
    """The request carries no cookie of a live wallet (SD19)."""

    status_code = 401
    code = "no_wallet"


class NameTaken(AppError):
    """A live wallet has this name, trimmed and case-folded; carries `suggestions` (SD3)."""

    status_code = 409
    code = "name_taken"


class AlreadyReversed(AppError):
    status_code = 409
    code = "already_reversed"


class InsufficientBalance(AppError):
    status_code = 409
    code = "insufficient_balance"


class WalletDeleted(AppError):
    """The wallet an entry belongs to is deleted, so it can no longer change (SD12)."""

    status_code = 409
    code = "wallet_deleted"


class NothingToMove(AppError):
    status_code = 409
    code = "nothing_to_move"


class IdempotencyKeyReused(AppError):
    """The key was used for a different request (PD9), as an order's is."""

    status_code = 422
    code = "idempotency_key_reused"


@dataclass(frozen=True)
class WalletRow:
    wallet_id: int
    name: str
    qr_token: str
    short_code: str
    created_at: datetime


@dataclass(frozen=True)
class EntryRow:
    entry_id: int
    wallet_id: int
    kind: EntryKind
    amount_cents: int
    run_id: int | None
    reverses_entry_id: int | None
    counterpart_entry_id: int | None
    actor_key_id: int | None
    actor_label: str | None
    idempotency_key: str | None
    created_at: datetime
    order_id: int | None
    refunds_entry_id: int | None


@dataclass(frozen=True)
class WalletSettingsRow:
    """No row is the defaults: sign-up closed, 30 days, 12 months (SD6, SD15)."""

    signup_code: str | None = None
    unfunded_days: int = DEFAULT_UNFUNDED_DAYS
    inactive_months: int = DEFAULT_INACTIVE_MONTHS


def at(ms: int) -> datetime:
    """An app-clock instant as the `timestamptz` the wallet tables store (PD8)."""
    return datetime.fromtimestamp(ms / 1000, UTC)


_WALLET = (Wallet.wallet_id, Wallet.name, Wallet.qr_token, Wallet.short_code, Wallet.created_at)
_ENTRY = (
    WalletEntry.entry_id,
    WalletEntry.wallet_id,
    WalletEntry.kind,
    WalletEntry.amount_cents,
    WalletEntry.run_id,
    WalletEntry.reverses_entry_id,
    WalletEntry.counterpart_entry_id,
    WalletEntry.actor_key_id,
    WalletEntry.actor_label,
    WalletEntry.idempotency_key,
    WalletEntry.created_at,
    WalletEntry.order_id,
    WalletEntry.refunds_entry_id,
)


def _wallet(row: Any) -> WalletRow:  # a `Row` of `_WALLET`, with or without `deleted_at`
    return WalletRow(int(row.wallet_id), row.name, row.qr_token, row.short_code, row.created_at)


def _entry(row: Any) -> EntryRow:  # a `Row` of `_ENTRY`
    return EntryRow(
        int(row.entry_id),
        int(row.wallet_id),
        row.kind,
        int(row.amount_cents),
        row.run_id,
        row.reverses_entry_id,
        row.counterpart_entry_id,
        row.actor_key_id,
        row.actor_label,
        row.idempotency_key,
        row.created_at,
        row.order_id,
        row.refunds_entry_id,
    )


# --- creating and finding -------------------------------------------------------


def _literal(text: str) -> str:
    """`text` for a `LIKE … ESCAPE '\\'` pattern, its `%` and `_` taken literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def taken_name_keys(conn: AsyncConnection, prefix_key: str) -> set[str]:
    """The keys of live wallets whose key starts with `prefix_key` (PD7's one query)."""
    result = await conn.execute(
        select(Wallet.name_key).where(Wallet.name_key.like(f"{_literal(prefix_key)}%", escape="\\"))
    )
    return {str(key) for key in result.scalars()}


async def name_suggestions(conn: AsyncConnection, name: str) -> list[str]:
    """Up to three free names built from `name` as typed (SD3)."""
    base = name.strip()
    # Every candidate up to "<base> 9999" starts with this, however its base is cut.
    prefix = base[: wallet_codes.NAME_MAX - len(" 9999")].rstrip()
    return wallet_codes.suggestions(base, await taken_name_keys(conn, name_key(prefix)))


async def _with_fresh_codes(
    conn: AsyncConnection, statement_for: Callable[[str, str], Any], *, name: str | None = None
) -> Row[Any]:
    """Run the statement `statement_for(qr_token, short_code)` makes, drawing new codes on a
    collision (PD5). A taken name is `NameTaken` with its suggestions."""
    for attempt in range(CODE_ATTEMPTS):
        statement = statement_for(wallet_codes.new_qr_token(), wallet_codes.new_short_code())
        try:
            # A savepoint, so a violation leaves the caller's transaction usable.
            async with conn.begin_nested():
                return (await conn.execute(statement)).one()
        except IntegrityError as error:
            reason = str(error.orig)
            if name is not None and _NAME_INDEX in reason:
                raise NameTaken(
                    "a wallet with this name exists (names compare trimmed, ignoring case)",
                    extra={"suggestions": list(await name_suggestions(conn, name))},
                ) from error
            if not any(index in reason for index in _CODE_INDEXES) or attempt == CODE_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


async def create_wallet(
    conn: AsyncConnection, *, name: str, cookie_hash: str, now_ms: int
) -> WalletRow:
    """A new wallet named `name` (trimmed), or `NameTaken` with nothing written (SD3)."""
    name = name.strip()

    def statement(token: str, code: str) -> Any:
        return (
            insert(Wallet)
            .values(
                name=name,
                name_key=name_key(name),
                qr_token=token,
                short_code=code,
                cookie_hash=cookie_hash,
                created_at=at(now_ms),
            )
            .returning(*_WALLET)
        )

    return _wallet(await _with_fresh_codes(conn, statement, name=name))


async def replace_codes(conn: AsyncConnection, wallet_id: int) -> WalletRow:
    """New QR token and short code for a live wallet; the old ones stop working (SD14).

    An unknown or deleted wallet is `WalletNotFound`, nothing written.
    """
    if await lock_wallet(conn, wallet_id) is None:
        raise WalletNotFound(f"no wallet {wallet_id}")

    def statement(token: str, code: str) -> Any:
        return (
            update(Wallet)
            .where(Wallet.wallet_id == wallet_id)
            .values(qr_token=token, short_code=code)
            .returning(*_WALLET)
        )

    return _wallet(await _with_fresh_codes(conn, statement))


async def _one_live(conn: AsyncConnection, *where: Any) -> WalletRow | None:
    row = (
        await conn.execute(select(*_WALLET).where(Wallet.deleted_at.is_(None), *where))
    ).one_or_none()
    return None if row is None else _wallet(row)


async def get(conn: AsyncConnection, wallet_id: int) -> WalletRow:
    wallet = await _one_live(conn, Wallet.wallet_id == wallet_id)
    if wallet is None:
        raise WalletNotFound(f"no wallet {wallet_id}")
    return wallet


async def get_by_cookie_hash(conn: AsyncConnection, cookie_hash: str) -> WalletRow | None:
    return await _one_live(conn, Wallet.cookie_hash == cookie_hash)


async def get_by_qr_token(conn: AsyncConnection, qr_token: str) -> WalletRow | None:
    return await _one_live(conn, Wallet.qr_token == qr_token)


async def get_by_short_code(conn: AsyncConnection, short_code: str) -> WalletRow | None:
    """`short_code` in its stored form (`wallet_codes.normalise_short_code`)."""
    return await _one_live(conn, Wallet.short_code == short_code)


async def rename(conn: AsyncConnection, wallet_id: int, name: str) -> None:
    """Give a live wallet `name`; only a move does this, after freeing it (SD11)."""
    await conn.execute(
        update(Wallet)
        .where(Wallet.wallet_id == wallet_id)
        .values(name=name, name_key=name_key(name))
    )


# --- money ----------------------------------------------------------------------


async def lock_wallet(conn: AsyncConnection, wallet_id: int) -> WalletRow | None:
    """Lock the wallet's row `FOR UPDATE`: the live wallet, or `None` once deleted.

    No row at all is `WalletNotFound`.
    """
    row = (
        await conn.execute(
            select(*_WALLET, Wallet.deleted_at)
            .where(Wallet.wallet_id == wallet_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise WalletNotFound(f"no wallet {wallet_id}")
    return None if row.deleted_at is not None else _wallet(row)


async def _lock_live(conn: AsyncConnection, where: ColumnElement[bool]) -> WalletRow | None:
    row = (
        await conn.execute(
            select(*_WALLET).where(Wallet.deleted_at.is_(None), where).with_for_update()
        )
    ).one_or_none()
    return None if row is None else _wallet(row)


async def lock_wallet_by_qr_token(conn: AsyncConnection, qr_token: str) -> WalletRow | None:
    """Lock the live wallet holding `qr_token` `FOR UPDATE`, or `None` (B-06 PD5).

    The credential is the `WHERE`, so under READ COMMITTED a "Nieuwe code" or a
    delete that commits while this waits leaves no row: the order is 404, never
    charged to a wallet that was re-coded since the scan (AC12).
    """
    return await _lock_live(conn, Wallet.qr_token == qr_token)


async def lock_wallet_by_short_code(conn: AsyncConnection, short_code: str) -> WalletRow | None:
    """As `lock_wallet_by_qr_token`, for `short_code` in its stored form."""
    return await _lock_live(conn, Wallet.short_code == short_code)


async def lock_wallets(
    conn: AsyncConnection, first: int, second: int
) -> tuple[WalletRow | None, WalletRow | None]:
    """`lock_wallet` on both, the lower `wallet_id` first, so two moves cannot deadlock."""
    locked = {
        wallet_id: await lock_wallet(conn, wallet_id) for wallet_id in sorted({first, second})
    }
    return locked[first], locked[second]


async def balance(conn: AsyncConnection, wallet_id: int) -> int:
    result = await conn.execute(
        select(func.coalesce(func.sum(WalletEntry.amount_cents), 0)).where(
            WalletEntry.wallet_id == wallet_id
        )
    )
    return int(result.scalar_one())


async def live_run_id(conn: AsyncConnection) -> int | None:
    """The run live now, or `None` (SD13, PD10), read inside the caller's transaction."""
    run = await current_run(conn)
    return run.run_id if run is not None and run.status == "live" else None


async def insert_entry(
    conn: AsyncConnection,
    *,
    wallet_id: int,
    kind: EntryKind,
    amount_cents: int,
    now_ms: int,
    run_id: int | None = None,
    reverses_entry_id: int | None = None,
    counterpart_entry_id: int | None = None,
    actor_key_id: int | None = None,
    actor_label: str | None = None,
    idempotency_key: str | None = None,
    order_id: int | None = None,
    refunds_entry_id: int | None = None,
) -> EntryRow:
    row = (
        await conn.execute(
            insert(WalletEntry)
            .values(
                wallet_id=wallet_id,
                kind=kind,
                amount_cents=amount_cents,
                run_id=run_id,
                reverses_entry_id=reverses_entry_id,
                counterpart_entry_id=counterpart_entry_id,
                actor_key_id=actor_key_id,
                actor_label=actor_label,
                idempotency_key=idempotency_key,
                order_id=order_id,
                refunds_entry_id=refunds_entry_id,
                created_at=at(now_ms),
            )
            .returning(*_ENTRY)
        )
    ).one()
    return _entry(row)


async def get_entry(conn: AsyncConnection, entry_id: int) -> EntryRow | None:
    row = (
        await conn.execute(select(*_ENTRY).where(WalletEntry.entry_id == entry_id))
    ).one_or_none()
    return None if row is None else _entry(row)


async def find_entry_by_key(conn: AsyncConnection, idempotency_key: str) -> EntryRow | None:
    row = (
        await conn.execute(select(*_ENTRY).where(WalletEntry.idempotency_key == idempotency_key))
    ).one_or_none()
    return None if row is None else _entry(row)


async def refund_of(conn: AsyncConnection, entry_id: int) -> EntryRow | None:
    """The `refund` naming payment `entry_id`, or `None` (B-06 SD9)."""
    row = (
        await conn.execute(select(*_ENTRY).where(WalletEntry.refunds_entry_id == entry_id))
    ).one_or_none()
    return None if row is None else _entry(row)


async def reversal_of(conn: AsyncConnection, entry_id: int) -> EntryRow | None:
    row = (
        await conn.execute(select(*_ENTRY).where(WalletEntry.reverses_entry_id == entry_id))
    ).one_or_none()
    return None if row is None else _entry(row)


# --- deleting -------------------------------------------------------------------


async def delete_wallet(
    conn: AsyncConnection,
    wallet_id: int,
    *,
    now_ms: int,
    actor_key_id: int | None = None,
    actor_label: str | None = None,
    with_run: bool = True,
) -> None:
    """Delete a live wallet (SD15): a `closing` entry for any balance left, then blank it.

    A balance below zero is written off by a positive closing entry (B-06 SD8), so
    admin's delete and the clean-up never refuse a wallet in debt.

    The closing entry carries the live run, as any entry does (PD10), unless
    `with_run` is false: the clean-up's carries none, so its one long transaction
    holds no lock on the run's row that a config write would wait for (/review
    R3). A closing entry counts towards no borrel's total either way. The entries
    and the anonymous row stay, so a borrel's top-up totals never change (AC32).
    An unknown or already deleted wallet is `WalletNotFound`, nothing written.
    """
    if await lock_wallet(conn, wallet_id) is None:
        raise WalletNotFound(f"no wallet {wallet_id}")
    left = await balance(conn, wallet_id)
    if left != 0:
        await insert_entry(
            conn,
            wallet_id=wallet_id,
            kind="closing",
            amount_cents=-left,
            now_ms=now_ms,
            run_id=await live_run_id(conn) if with_run else None,
            actor_key_id=actor_key_id,
            actor_label=actor_label,
        )
    await conn.execute(
        update(Wallet)
        .where(Wallet.wallet_id == wallet_id)
        .values(
            name=None,
            name_key=None,
            qr_token=None,
            short_code=None,
            cookie_hash=None,
            deleted_at=at(now_ms),
        )
    )


# --- the clean-up (SD15, PD11, PD19) ---------------------------------------------


async def expired(
    conn: AsyncConnection,
    *,
    now_ms: int,
    settings: WalletSettingsRow,
    among: list[int] | None = None,
) -> list[int]:
    """The live wallets the retention rules delete, in `wallet_id` order (PD19):

    - no entry at all, and created more than `unfunded_days` days ago;
    - the newest entry, or the creation without one, more than `inactive_months`
      calendar months ago.

    Only entries are activity: a visit to the player page is not (SD15).
    """
    now = literal(at(now_ms), DateTime(timezone=True))
    unfunded_before = now - func.make_interval(0, 0, 0, settings.unfunded_days, type_=Interval)
    inactive_before = now - func.make_interval(0, settings.inactive_months, type_=Interval)
    newest = func.max(WalletEntry.created_at)
    statement = (
        select(Wallet.wallet_id)
        .outerjoin(WalletEntry, WalletEntry.wallet_id == Wallet.wallet_id)
        .where(Wallet.deleted_at.is_(None))
        .group_by(Wallet.wallet_id)
        .having(
            or_(
                (func.count(WalletEntry.entry_id) == 0) & (Wallet.created_at < unfunded_before),
                func.coalesce(newest, Wallet.created_at) < inactive_before,
            )
        )
        .order_by(Wallet.wallet_id)
    )
    if among is not None:
        statement = statement.where(Wallet.wallet_id.in_(among))
    return [int(wallet_id) for wallet_id in (await conn.execute(statement)).scalars()]


async def lock_unlocked(conn: AsyncConnection, wallet_ids: list[int]) -> list[int]:
    """Lock those of `wallet_ids` no other transaction holds, skipping the rest (PD11), so
    a sweep never waits on a kassa action."""
    if not wallet_ids:
        return []
    result = await conn.execute(
        select(Wallet.wallet_id)
        .where(Wallet.wallet_id.in_(wallet_ids), Wallet.deleted_at.is_(None))
        .order_by(Wallet.wallet_id)
        .with_for_update(skip_locked=True)
    )
    return [int(wallet_id) for wallet_id in result.scalars()]


# --- settings -------------------------------------------------------------------


async def get_settings(conn: AsyncConnection) -> WalletSettingsRow:
    row = (
        await conn.execute(
            select(
                WalletSettings.signup_code,
                WalletSettings.unfunded_days,
                WalletSettings.inactive_months,
            )
        )
    ).one_or_none()
    if row is None:
        return WalletSettingsRow()
    return WalletSettingsRow(row.signup_code, int(row.unfunded_days), int(row.inactive_months))


async def put_settings(conn: AsyncConnection, settings: WalletSettingsRow) -> WalletSettingsRow:
    """Write the one settings row, inserting it the first time (as `app/db/theme.py`)."""
    values = {
        "signup_code": settings.signup_code,
        "unfunded_days": settings.unfunded_days,
        "inactive_months": settings.inactive_months,
    }
    statement = insert(WalletSettings).values(**values)
    await conn.execute(
        statement.on_conflict_do_update(index_elements=[WalletSettings.id], set_=values)
    )
    return settings


# --- the kassa's reads ------------------------------------------------------------


async def last_topup(conn: AsyncConnection, wallet_id: int) -> EntryRow | None:
    """The wallet's newest top-up, reversed or not (SD10's 2-minute check, SD11)."""
    row = (
        await conn.execute(
            select(*_ENTRY)
            .where(WalletEntry.wallet_id == wallet_id, WalletEntry.kind == "topup")
            .order_by(WalletEntry.created_at.desc(), WalletEntry.entry_id.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else _entry(row)


async def topups(conn: AsyncConnection, wallet_id: int) -> list[tuple[EntryRow, bool]]:
    """The wallet's top-ups, newest first, each with whether it was reversed (SD12, SD22)."""
    reversal = WalletEntry.__table__.alias("reversal")
    rows = await conn.execute(
        select(*_ENTRY, reversal.c.entry_id.is_not(None).label("reversed"))
        .outerjoin(reversal, reversal.c.reverses_entry_id == WalletEntry.entry_id)
        .where(WalletEntry.wallet_id == wallet_id, WalletEntry.kind == "topup")
        .order_by(WalletEntry.created_at.desc(), WalletEntry.entry_id.desc())
    )
    return [(_entry(row), bool(row.reversed)) for row in rows]


@dataclass(frozen=True)
class PaymentRow:
    """A `payment` entry as the bar and the kassa list it (B-06 SD9, SD10, PD9).

    `wallet_name` is `None` once the wallet is deleted (B-05 SD15); `lines` are the
    order's `(drink name, qty)` by `drink_id`, or `None` once the order is gone
    with its run (Phase 7 SD3, AC24).
    """

    entry: EntryRow
    refunded: bool
    wallet_name: str | None
    lines: list[tuple[str, int]] | None


async def payments(
    conn: AsyncConnection,
    *,
    wallet_id: int | None = None,
    actor_key_id: int | None = None,
    since: datetime | None = None,
) -> list[PaymentRow]:
    """`payment` entries, newest first, filtered by wallet, booking key and time."""
    refund = WalletEntry.__table__.alias("refund")
    statement = (
        select(
            *_ENTRY,
            refund.c.entry_id.is_not(None).label("refunded"),
            Wallet.name.label("wallet_name"),
        )
        .join(Wallet, Wallet.wallet_id == WalletEntry.wallet_id)
        .outerjoin(refund, refund.c.refunds_entry_id == WalletEntry.entry_id)
        .where(WalletEntry.kind == "payment")
        .order_by(WalletEntry.created_at.desc(), WalletEntry.entry_id.desc())
    )
    if wallet_id is not None:
        statement = statement.where(WalletEntry.wallet_id == wallet_id)
    if actor_key_id is not None:
        statement = statement.where(WalletEntry.actor_key_id == actor_key_id)
    if since is not None:
        statement = statement.where(WalletEntry.created_at >= since)
    rows = (await conn.execute(statement)).all()
    order_ids = [int(row.order_id) for row in rows if row.order_id is not None]
    lines: dict[int, list[tuple[str, int]]] = {}
    if order_ids:
        for line in await conn.execute(
            select(OrderLine.order_id, Drink.name, OrderLine.qty)
            .join(Drink, Drink.drink_id == OrderLine.drink_id)
            .where(OrderLine.order_id.in_(order_ids))
            .order_by(OrderLine.order_id, OrderLine.drink_id)
        ):
            lines.setdefault(int(line.order_id), []).append((line.name, int(line.qty)))
    return [
        PaymentRow(
            _entry(row),
            bool(row.refunded),
            row.wallet_name,
            None if row.order_id is None else lines.get(int(row.order_id), []),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class SearchRow:
    """A wallet as the move search lists it (SD11, PD17)."""

    wallet: WalletRow
    balance_cents: int
    last_topup_at: datetime | None


async def search(
    conn: AsyncConnection, *, fragment_key: str, short_code: str | None
) -> list[SearchRow]:
    """Live wallets whose `name_key` contains `fragment_key`, sorted as names are (PD18),
    with the wallet `short_code` names first."""
    matches: ColumnElement[bool] = Wallet.name_key.like(f"%{_literal(fragment_key)}%", escape="\\")
    if short_code is not None:
        matches = or_(matches, Wallet.short_code == short_code)
    rows = await conn.execute(
        select(
            *_WALLET,
            Wallet.name_key,
            func.coalesce(func.sum(WalletEntry.amount_cents), 0).label("balance"),
            func.max(WalletEntry.created_at)
            .filter(WalletEntry.kind == "topup")
            .label("last_topup_at"),
        )
        .outerjoin(WalletEntry, WalletEntry.wallet_id == Wallet.wallet_id)
        .where(Wallet.deleted_at.is_(None), matches)
        .group_by(Wallet.wallet_id)
    )
    ordered = sorted(
        rows,
        key=lambda row: (row.short_code != short_code, row.name_key, row.wallet_id),
    )
    return [SearchRow(_wallet(row), int(row.balance), row.last_topup_at) for row in ordered]


# --- admin's reads (SD16) ---------------------------------------------------------


@dataclass(frozen=True)
class ListedWallet:
    """A wallet in admin's list. Last activity is its newest entry, or its creation when it
    has none: the clean-up's rule (SD15, PD18)."""

    wallet: WalletRow
    balance_cents: int
    last_activity_at: datetime


@dataclass(frozen=True)
class RunTopups:
    """One borrel's top-ups net of their reversals (SD12, SD16), and its wallet payments
    net of their refunds as a positive amount (B-06 SD20, PD10). `run_id` `None` is the
    entries with no run: none was live, or the run was deleted (PD2)."""

    run_id: int | None
    name: str | None
    net_topup_cents: int
    net_payment_cents: int = 0


async def list_wallets(conn: AsyncConnection) -> list[ListedWallet]:
    """Every live wallet, by case-folded name (PD18)."""
    rows = await conn.execute(
        select(
            *_WALLET,
            Wallet.name_key,
            func.coalesce(func.sum(WalletEntry.amount_cents), 0).label("balance"),
            func.coalesce(func.max(WalletEntry.created_at), Wallet.created_at).label("active"),
        )
        .outerjoin(WalletEntry, WalletEntry.wallet_id == Wallet.wallet_id)
        .where(Wallet.deleted_at.is_(None))
        .group_by(Wallet.wallet_id)
    )
    ordered = sorted(rows, key=lambda row: (row.name_key, row.wallet_id))
    return [ListedWallet(_wallet(row), int(row.balance), row.active) for row in ordered]


async def balance_totals(conn: AsyncConnection) -> tuple[int, int]:
    """The sums of the live wallets' positive and negative balances (B-06 SD20, PD10):
    what the association still owes in drinks, and what players owe. Never netted."""
    balances = (
        select(func.sum(WalletEntry.amount_cents).label("balance"))
        .join(Wallet, Wallet.wallet_id == WalletEntry.wallet_id)
        .where(Wallet.deleted_at.is_(None))
        .group_by(WalletEntry.wallet_id)
        .subquery()
    )
    row = (
        await conn.execute(
            select(
                func.coalesce(func.sum(balances.c.balance).filter(balances.c.balance > 0), 0),
                func.coalesce(func.sum(balances.c.balance).filter(balances.c.balance < 0), 0),
            )
        )
    ).one()
    return int(row[0]), int(row[1])


async def topups_per_run(conn: AsyncConnection) -> list[RunTopups]:
    """Top-ups net of reversals and payments net of refunds per run, newest borrel first
    (PD18; B-06 PD10); the entries without a run last, only when either sum is not
    zero (PD2 reading A).

    A reversal carries its top-up's run (SD12) and a refund its payment's (B-06 SD9), so
    a run's sums are already net. A closing or move entry counts nowhere, so deleting a
    wallet changes no row (AC32).
    """
    topups = WalletEntry.kind.in_(("topup", "reversal"))
    payments = WalletEntry.kind.in_(("payment", "refund"))
    rows = (
        await conn.execute(
            select(
                WalletEntry.run_id,
                Run.name,
                Run.started_at,
                func.coalesce(func.sum(WalletEntry.amount_cents).filter(topups), 0).label("net"),
                func.coalesce(func.sum(WalletEntry.amount_cents).filter(payments), 0).label("paid"),
            )
            .outerjoin(Run, Run.run_id == WalletEntry.run_id)
            .where(or_(topups, payments))
            .group_by(WalletEntry.run_id, Run.name, Run.started_at)
        )
    ).all()
    runs = sorted(
        (row for row in rows if row.run_id is not None),
        key=lambda row: (row.started_at, row.run_id),
        reverse=True,
    )
    totals = [RunTopups(int(row.run_id), row.name, int(row.net), -int(row.paid)) for row in runs]
    unrun = [(int(row.net), -int(row.paid)) for row in rows if row.run_id is None]
    if unrun and any(unrun[0]):
        totals.append(RunTopups(None, None, *unrun[0]))
    return totals
