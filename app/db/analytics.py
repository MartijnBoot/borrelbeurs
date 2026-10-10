"""Read-only analytics over past and live runs (Phase 7 SD10, SD13; PD11, PD12).

Meant for a heavy-read connection (SD11). Money is integer cents throughout,
summed in SQL from `order_line`; nothing here is stored.

- `run_list`: every run, newest first, with its totals, in **one** grouped
  query (no query per run). `t0_ms` is the run's first `price_tick` by
  `version` (PD12), `None` for a draft; `duration_ms` is `ended_at_ms - t0_ms`
  for an ended run only.
- `run_detail`: one run's totals, and a row per product that sold -- removed
  drinks included -- named after the product's newest drink in the run.

SD13's fallbacks for rows a rolled-back image wrote: a line without a bar price
takes its drink's current one, and a drink without a product groups by its
`name_key` (`app/db/exports.py:product_key`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, ColumnElement, cast, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import models
from app.db.exports import product_key
from app.db.runs import RunNotFound


@dataclass(frozen=True)
class RunTotals:
    run_id: int
    name: str
    status: str
    t0_ms: int | None
    ended_at_ms: int | None
    duration_ms: int | None
    qty: int
    revenue_cents: int
    bar_price_total_cents: int


@dataclass(frozen=True)
class ProductTotals:
    product_key: str
    product_id: int | None
    name: str
    qty: int
    revenue_cents: int
    bar_price_total_cents: int
    avg_price_cents: int  # round(revenue / qty), half up


@dataclass(frozen=True)
class RunDetail:
    run: RunTotals
    per_product: tuple[ProductTotals, ...]


def _bar_price_total() -> ColumnElement[Any]:
    """`sum(qty * bar price)`, the line's own, else its drink's (SD5, SD13)."""
    line, drink = models.OrderLine, models.Drink
    return func.sum(line.qty * func.coalesce(line.bar_price_cents, drink.bar_price_cents))


@dataclass
class _Sum:
    product_id: int | None
    name: str
    qty: int = 0
    revenue_cents: int = 0
    bar_price_cents: int = 0


def _half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


async def _runs(conn: AsyncConnection, run_id: int | None = None) -> list[RunTotals]:
    run, order, line, drink, tick = (
        models.Run,
        models.Order,
        models.OrderLine,
        models.Drink,
        models.PriceTick,
    )
    sales = (
        select(
            order.run_id,
            func.sum(line.qty).label("qty"),
            func.sum(line.line_total_cents).label("revenue"),
            _bar_price_total().label("bar"),
        )
        .join(order, order.order_id == line.order_id)
        .join(drink, drink.drink_id == line.drink_id)
        .group_by(order.run_id)
    )
    if run_id is not None:
        sales = sales.where(order.run_id == run_id)
    totals = sales.subquery()
    t0 = (
        select(tick.wall_ts_ms)
        .where(tick.run_id == run.run_id)
        .order_by(tick.version)
        .limit(1)
        .correlate(run)
        .scalar_subquery()
    )
    statement = (
        select(
            run.run_id,
            run.name,
            run.status,
            t0.label("t0_ms"),
            cast(func.round(func.extract("epoch", run.ended_at) * 1000), BigInteger).label(
                "ended_at_ms"
            ),
            func.coalesce(totals.c.qty, 0).label("qty"),
            func.coalesce(totals.c.revenue, 0).label("revenue"),
            func.coalesce(totals.c.bar, 0).label("bar"),
        )
        .outerjoin(totals, totals.c.run_id == run.run_id)
        .order_by(run.run_id.desc())
    )
    if run_id is not None:
        statement = statement.where(run.run_id == run_id)
    result: list[RunTotals] = []
    for row in await conn.execute(statement):
        t0_ms = None if row.t0_ms is None else int(row.t0_ms)
        ended_at_ms = None if row.ended_at_ms is None else int(row.ended_at_ms)
        duration_ms = None
        if row.status == "ended" and t0_ms is not None and ended_at_ms is not None:
            duration_ms = ended_at_ms - t0_ms
        result.append(
            RunTotals(
                run_id=int(row.run_id),
                name=row.name,
                status=row.status,
                t0_ms=t0_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                qty=int(row.qty),
                revenue_cents=int(row.revenue),
                bar_price_total_cents=int(row.bar),
            )
        )
    return result


async def run_list(conn: AsyncConnection) -> list[RunTotals]:
    """Every run with its totals, newest first, in one query."""
    return await _runs(conn)


async def run_detail(conn: AsyncConnection, run_id: int) -> RunDetail:
    """The run's totals and its per-product rows, or `RunNotFound`."""
    runs = await _runs(conn, run_id)
    if not runs:
        raise RunNotFound(f"no run {run_id}")
    order, line, drink = models.Order, models.OrderLine, models.Drink
    drinks = (
        await conn.execute(
            select(drink.drink_id, drink.name, drink.name_key, drink.product_id)
            .where(drink.run_id == run_id)
            .order_by(drink.drink_id)
        )
    ).all()
    sold = {
        int(row.drink_id): (int(row.qty), int(row.revenue), int(row.bar))
        for row in await conn.execute(
            select(
                line.drink_id,
                func.sum(line.qty).label("qty"),
                func.sum(line.line_total_cents).label("revenue"),
                _bar_price_total().label("bar"),
            )
            .join(order, order.order_id == line.order_id)
            .join(drink, drink.drink_id == line.drink_id)
            .where(order.run_id == run_id)
            .group_by(line.drink_id)
        )
    }
    # Per product, in the order its first drink was added; the newest drink names it.
    products: dict[str, _Sum] = {}
    for row in drinks:
        key = product_key(row.product_id, row.name_key)
        total = products.setdefault(key, _Sum(row.product_id, row.name))
        total.name = row.name
        qty, revenue, bar = sold.get(int(row.drink_id), (0, 0, 0))
        total.qty += qty
        total.revenue_cents += revenue
        total.bar_price_cents += bar
    per_product = tuple(
        ProductTotals(
            key,
            t.product_id,
            t.name,
            t.qty,
            t.revenue_cents,
            t.bar_price_cents,
            _half_up(t.revenue_cents, t.qty),
        )
        for key, t in products.items()
        if t.qty
    )
    return RunDetail(run=runs[0], per_product=per_product)
