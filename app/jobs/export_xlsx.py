"""The xlsx export (Phase 7 SD6, SD8, SD15): a snapshot in, a workbook's bytes out.

`build_workbook` is pure: no clock (the generated-at stamp, which is also the
file's creation date, is passed in), no database, no file -- `xlsxwriter` writes
into a `BytesIO` in its `in_memory` mode. Three sheets, v1-shaped and extended:

- `Sales`: one row per order line, SD8's column order. `ts_iso` is UTC (SD15).
  `drink`, `p_min` and `p_max` are the drink's values at export time.
- `Per drink`: per product, removed drinks included; named after its newest
  drink in the run.
- `Summary`: label and value rows, as v1's.

Euros are `Decimal(cents) / 100` written with the `0.00` format; every total is
summed in integer cents first, never from the written numbers. Data text goes
through `write_string`, so a drink named `=1+1` stays text, not a formula.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

import xlsxwriter

from app.db.exports import ExportSnapshot

SALES_HEADERS: Final = (
    "ts_iso",
    "ts_ms",
    "drink",
    "qty",
    "unit_price",
    "total_price",
    "p_cont",
    "p_min",
    "p_max",
    "order_id",
    "drink_id",
    "bar_price",
    "version",
)
PER_DRINK_HEADERS: Final = ("drink", "qty", "revenue", "bar_price_total", "avg_price")


def euros(cents: int) -> Decimal:
    return Decimal(cents) / 100


def utc(ms: int) -> datetime:
    """`ms` since the epoch as an aware UTC datetime, exactly (no float division)."""
    return datetime.fromtimestamp(ms // 1000, tz=UTC) + timedelta(milliseconds=ms % 1000)


def iso_utc(ms: int) -> str:
    return utc(ms).isoformat(timespec="milliseconds")


@dataclass
class _ProductTotal:
    name: str
    qty: int = 0
    revenue_cents: int = 0
    bar_price_cents: int = 0


def _per_product(snapshot: ExportSnapshot) -> list[_ProductTotal]:
    """Per product in the order its first drink was added; the newest drink names it."""
    totals: dict[str, _ProductTotal] = {}
    key_of: dict[int, str] = {}
    for drink in sorted(snapshot.drinks, key=lambda d: d.drink_id):
        key_of[drink.drink_id] = drink.product_key
        totals.setdefault(drink.product_key, _ProductTotal(drink.name)).name = drink.name
    for line in snapshot.lines:
        total = totals[key_of[line.drink_id]]
        total.qty += line.qty
        total.revenue_cents += line.line_total_cents
        total.bar_price_cents += line.qty * line.bar_price_cents
    return list(totals.values())


def build_workbook(snapshot: ExportSnapshot, *, generated_at_ms: int) -> bytes:
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True})
    book.set_properties({"title": snapshot.name, "created": utc(generated_at_ms)})
    money = book.add_format({"num_format": "0.00"})
    bold = book.add_format({"bold": True})
    drinks = {drink.drink_id: drink for drink in snapshot.drinks}

    sales = book.add_worksheet("Sales")
    sales.write_row(0, 0, SALES_HEADERS, bold)
    sales.set_column(0, 0, 26)
    sales.set_column(2, 2, 20)
    for row, line in enumerate(snapshot.lines, start=1):
        drink = drinks[line.drink_id]
        sales.write_string(row, 0, iso_utc(line.ts_ms))
        sales.write_number(row, 1, line.ts_ms)
        sales.write_string(row, 2, drink.name)
        sales.write_number(row, 3, line.qty)
        sales.write_number(row, 4, euros(line.unit_price_cents), money)
        sales.write_number(row, 5, euros(line.line_total_cents), money)
        sales.write_number(row, 6, line.p_cont)
        sales.write_number(row, 7, euros(drink.p_min_cents), money)
        sales.write_number(row, 8, euros(drink.p_max_cents), money)
        sales.write_number(row, 9, line.order_id)
        sales.write_number(row, 10, line.drink_id)
        sales.write_number(row, 11, euros(line.bar_price_cents), money)
        sales.write_number(row, 12, line.version)

    per_drink = book.add_worksheet("Per drink")
    per_drink.write_row(0, 0, PER_DRINK_HEADERS, bold)
    per_drink.set_column(0, 0, 20)
    products = _per_product(snapshot)
    for row, product in enumerate(products, start=1):
        per_drink.write_string(row, 0, product.name)
        per_drink.write_number(row, 1, product.qty)
        per_drink.write_number(row, 2, euros(product.revenue_cents), money)
        per_drink.write_number(row, 3, euros(product.bar_price_cents), money)
        if product.qty:
            average = (Decimal(product.revenue_cents) / product.qty).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
            per_drink.write_number(row, 4, average / 100, money)

    summary = book.add_worksheet("Summary")
    summary.set_column(0, 0, 18)
    summary.set_column(1, 1, 30)
    revenue_cents = sum(line.line_total_cents for line in snapshot.lines)
    rows: list[tuple[str, str | int | Decimal | None]] = [
        ("run", snapshot.name),
        ("started", None if snapshot.t0_ms is None else iso_utc(snapshot.t0_ms)),
        (
            "ended",
            None
            if snapshot.ended_at is None
            else snapshot.ended_at.astimezone(UTC).isoformat(timespec="milliseconds"),
        ),
        ("total_revenue", euros(revenue_cents)),
        ("total_qty", sum(line.qty for line in snapshot.lines)),
        ("bar_price_total", euros(sum(p.bar_price_cents for p in products))),
        ("line_count", len(snapshot.lines)),
        ("generated_at", iso_utc(generated_at_ms)),
    ]
    for row, (label, value) in enumerate(rows):
        summary.write_string(row, 0, label, bold)
        if isinstance(value, str):
            summary.write_string(row, 1, value)
        elif isinstance(value, Decimal):
            summary.write_number(row, 1, value, money)
        elif value is not None:
            summary.write_number(row, 1, value)

    book.close()
    return buffer.getvalue()
