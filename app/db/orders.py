"""The atomic order write and the earnings query.

`write_order` is the one write path for an order (D-10, D-12). In one
transaction it moves `engine_state` from `expected_version` to `state` with the
same compare-and-set as `save_transition`, inserts the `"order"`, its lines and
the version's `price_tick` (`source = 'order'`). Any failure rolls all of it
back, so an order is never stored without the state and tick it produced.

The caller prices the lines: this module computes `line_total_cents` and
nothing else -- no prices, no grace (ADR 0008). A duplicate `idempotency_key`
surfaces as the database's `IntegrityError`; `app/runtime/orders.py` replays it.

Phase 3 (SD20) adds the acting key and the receipt. The receipt needs the
`order_id`, so it is written by an UPDATE of the order row once the id is known,
still inside the same transaction: an order is never stored without its receipt.

B-06 (SD14, SD15, PD5) adds the wallet payment to the same transaction. Before any
write, the scanned wallet's row is locked `FOR UPDATE` by its credential (with a
2 s `lock_timeout`, so a wallet held elsewhere is a 503 the bar retries, not a
market lock held until the step timeout) and its balance checked against the
run's limit. A refusal raises before anything is written. Then the `payment`
entry is one more `INSERT`, naming the order: an order is never stored without
its payment, nor a payment without its order (AC34).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, func, insert, select, text, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import models, wallets
from app.db.engine_state import compare_and_set, insert_tick
from app.runtime.wallet_codes import normalise_short_code
from exchange import EngineState, MarketSpec


@dataclass(frozen=True)
class OrderLineInput:
    drink_id: int
    qty: int
    unit_price_cents: int
    p_cont: float


@dataclass(frozen=True)
class PaymentInput:
    """A wallet paying for the order (B-06 SD13, PD5): exactly one credential as scanned,
    the live run's "Rood staan tot", and the acting key's label for the entry."""

    qr_token: str | None
    short_code: str | None
    credit_limit_cents: int
    actor_label: str | None


@dataclass(frozen=True)
class WalletPaid:
    """The wallet that paid, and its balance after the payment (SD16)."""

    wallet_id: int
    name: str
    balance_after_cents: int


@dataclass(frozen=True)
class OrderWritten:
    order_id: int
    version: int
    paid: WalletPaid | None = None


@dataclass(frozen=True)
class StoredOrder:
    order_id: int
    run_id: int
    version: int
    actor_key_id: int | None
    response: Mapping[str, Any] | None


async def write_order(
    engine: AsyncEngine,
    *,
    run_id: int,
    idempotency_key: str,
    expected_version: int,
    state: EngineState,
    spec: MarketSpec,
    drink_ids: Sequence[int],
    lines: Sequence[OrderLineInput],
    wall_ts_ms: int,
    actor_key_id: int | None = None,
    response: Callable[[int, WalletPaid | None], Mapping[str, Any]] | None = None,
    payment: PaymentInput | None = None,
) -> OrderWritten:
    """Store the order, its lines, `state` and its tick in one transaction, or nothing.

    With `payment`, the wallet pays the lines' total in that same transaction, or
    `WalletNotFound` / `InsufficientBalance` is raised before any write (SD15).
    `response` gets the order's id and the wallet that paid.
    """
    unknown = sorted({line.drink_id for line in lines} - set(drink_ids))
    if unknown:
        raise ValueError(
            f"order lines name drink(s) {', '.join(map(str, unknown))}, "
            f"which run {run_id} does not have"
        )
    if not lines:
        raise ValueError("an order needs at least one line")

    total_cents = sum(line.qty * line.unit_price_cents for line in lines)
    async with engine.begin() as conn:
        paid = None if payment is None else await _check_payment(conn, payment, total_cents)
        await compare_and_set(
            conn,
            run_id=run_id,
            expected_version=expected_version,
            state=state,
            drink_ids=drink_ids,
            wall_ts_ms=wall_ts_ms,
        )
        order_id = int(
            (
                await conn.execute(
                    insert(models.Order)
                    .values(
                        run_id=run_id,
                        idempotency_key=idempotency_key,
                        version=state.version,
                        wall_ts_ms=wall_ts_ms,
                        actor_key_id=actor_key_id,
                    )
                    .returning(models.Order.order_id)
                )
            ).scalar_one()
        )
        await conn.execute(
            insert(models.OrderLine).values(
                [
                    {
                        "order_id": order_id,
                        "drink_id": line.drink_id,
                        "qty": line.qty,
                        "unit_price_cents": line.unit_price_cents,
                        "line_total_cents": line.qty * line.unit_price_cents,
                        "p_cont": line.p_cont,
                        # The bar price in force at this sale, read in this transaction
                        # (Phase 7 SD5, PD6, D-20): a later bar-price edit moves no line.
                        "bar_price_cents": select(models.Drink.bar_price_cents)
                        .where(models.Drink.drink_id == line.drink_id)
                        .scalar_subquery(),
                    }
                    for line in lines
                ]
            )
        )
        if paid is not None:
            assert payment is not None
            await wallets.insert_entry(
                conn,
                wallet_id=paid.wallet_id,
                kind="payment",
                amount_cents=-total_cents,
                now_ms=wall_ts_ms,
                run_id=run_id,
                actor_key_id=actor_key_id,
                actor_label=payment.actor_label,
                order_id=order_id,
            )
        if response is not None:
            await conn.execute(
                update(models.Order)
                .where(models.Order.order_id == order_id)
                .values(response=dict(response(order_id, paid)))
            )
        await insert_tick(
            conn,
            run_id=run_id,
            state=state,
            spec=spec,
            drink_ids=drink_ids,
            source="order",
            wall_ts_ms=wall_ts_ms,
        )
    return OrderWritten(order_id=order_id, version=state.version, paid=paid)


async def _check_payment(
    conn: AsyncConnection, payment: PaymentInput, total_cents: int
) -> WalletPaid:
    """Lock the scanned wallet and check `total_cents` against balance + limit (SD15)."""
    await conn.execute(text("SET LOCAL lock_timeout = '2s'"))
    wallet = None
    if payment.qr_token is not None:
        wallet = await wallets.lock_wallet_by_qr_token(conn, payment.qr_token)
    elif payment.short_code is not None:
        code = normalise_short_code(payment.short_code)
        if code is not None:
            wallet = await wallets.lock_wallet_by_short_code(conn, code)
    if wallet is None:
        raise wallets.WalletNotFound("no wallet has this code")
    balance = await wallets.balance(conn, wallet.wallet_id)
    if total_cents > balance + payment.credit_limit_cents:
        raise wallets.InsufficientBalance(
            "the balance is too low for this order",
            extra={"balance_cents": balance, "credit_limit_cents": payment.credit_limit_cents},
        )
    return WalletPaid(wallet.wallet_id, wallet.name, balance - total_cents)


async def find_order_by_key(conn: AsyncConnection, idempotency_key: str) -> StoredOrder | None:
    """The order stored under `idempotency_key`, with its receipt, or `None`."""
    order = models.Order
    row = (
        await conn.execute(
            select(
                order.order_id, order.run_id, order.version, order.actor_key_id, order.response
            ).where(order.idempotency_key == idempotency_key)
        )
    ).one_or_none()
    if row is None:
        return None
    return StoredOrder(
        order_id=int(row.order_id),
        run_id=int(row.run_id),
        version=int(row.version),
        actor_key_id=None if row.actor_key_id is None else int(row.actor_key_id),
        response=row.response,
    )


async def earnings_by_drink(conn: AsyncConnection, run_id: int) -> list[tuple[int, int, int]]:
    """`(drink_id, qty, revenue_cents)` per drink sold in the run (SD12's boot query)."""
    line = models.OrderLine
    result = await conn.execute(
        select(line.drink_id, func.sum(line.qty), func.sum(line.line_total_cents))
        .join(models.Order, models.Order.order_id == line.order_id)
        .where(models.Order.run_id == run_id)
        .group_by(line.drink_id)
        .order_by(line.drink_id)
    )
    return [(int(drink_id), int(qty), int(revenue)) for drink_id, qty, revenue in result]


async def earnings_series(
    conn: AsyncConnection, run_id: int, *, bucket_ms: int = 60_000
) -> list[tuple[int, int]]:
    """`(bucket_end_ms, cumulative_revenue_cents)` for the run, ascending (Phase 5 SD16, PD12).

    A bucket ends at `floor(wall_ts_ms / bucket_ms) * bucket_ms + bucket_ms`. Only
    buckets holding an order are returned, so the size is bounded by run length /
    `bucket_ms` whatever the order count (AC20); no orders is `[]`. The bucket is
    named once in a subquery: a bound `bucket_ms` written twice, in the select and
    the `GROUP BY`, would be two parameters Postgres cannot match.
    """
    line = models.OrderLine
    order = models.Order
    lines = (
        select(
            ((order.wall_ts_ms // bucket_ms) * bucket_ms + bucket_ms).label("t_ms"),
            line.line_total_cents,
        )
        .join(order, order.order_id == line.order_id)
        .where(order.run_id == run_id)
        .subquery()
    )
    # Typing only (no SQL): the subquery's columns and the window are untyped to mypy.
    bucket = type_coerce(lines.c.t_ms, BigInteger)
    running = type_coerce(
        func.sum(func.sum(lines.c.line_total_cents)).over(order_by=lines.c.t_ms), BigInteger
    )
    result = await conn.execute(
        select(bucket, running).group_by(lines.c.t_ms).order_by(lines.c.t_ms)
    )
    return [(int(t_ms), int(cumulative)) for t_ms, cumulative in result]
