"""Compare two runs, and a product's price curve in each (Phase 7 T14: AC11, AC28-AC30; PD13, PD14).

Runs are seeded straight into the tables: drinks through `add_drink` (so they
get their products, Phase 7 T3), orders and ticks at chosen times and prices.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db import models
from app.db.analytics import (
    CompareRow,
    CurvePoint,
    ProductTotals,
    SideTotals,
    compare,
    match_products,
    price_curve,
)
from app.db.runs import RunNotFound, add_drink, create_draft_run
from app.db.session import create_engine
from exchange import Params

T0 = 1_759_312_800_000
MINUTE = 60_000

T = TypeVar("T")


def _with_engine(settings: Settings, url: str, body: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _run(conn: AsyncConnection, name: str) -> int:
    return await create_draft_run(conn, name=name, params=Params(step_quant=0.1), run_seed=5)


async def _drink(conn: AsyncConnection, run_id: int, name: str, slot: int) -> int:
    return int(
        await add_drink(
            conn,
            run_id,
            name=name,
            slot=slot,
            p_min_cents=120,
            p0_cents=250,
            p_max_cents=480,
            a=1.0,
            d=0.1,
            s0=1.0,
            c=0.1,
            bar_price_cents=250,
        )
    )


async def _order(
    conn: AsyncConnection, run_id: int, version: int, lines: Sequence[tuple[int, int, int]]
) -> None:
    order_id = (
        await conn.execute(
            insert(models.Order).returning(models.Order.order_id),
            {
                "run_id": run_id,
                "idempotency_key": f"k-compare-{run_id}-{version}",
                "version": version,
                "wall_ts_ms": T0 + version,
            },
        )
    ).scalar_one()
    await conn.execute(
        insert(models.OrderLine),
        [
            {
                "order_id": order_id,
                "drink_id": drink_id,
                "qty": qty,
                "unit_price_cents": price,
                "line_total_cents": qty * price,
                "p_cont": price / 100,
                "bar_price_cents": 250,
            }
            for drink_id, qty, price in lines
        ],
    )


async def _ticks(
    conn: AsyncConnection, run_id: int, ticks: Sequence[tuple[int, str, dict[int, float]]]
) -> None:
    """`(wall_ts_ms, source, {drink_id: p_q})` ticks at versions 0, 1, 2, ..."""
    await conn.execute(
        insert(models.PriceTick),
        [
            {
                "run_id": run_id,
                "version": version,
                "source": source,
                "prices": {str(d): {"p_cont": p, "p_q": p} for d, p in prices.items()},
                "wall_ts_ms": ts,
            }
            for version, (ts, source, prices) in enumerate(ticks)
        ],
    )


async def _product(conn: AsyncConnection, drink_id: int) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT product_id FROM drink WHERE drink_id = :d"), {"d": drink_id}
            )
        ).scalar_one()
    )


def test_a_product_renamed_in_b_joins_its_row_in_a(settings: Settings, database_url: str) -> None:
    """AC11, PD14: Bier in A and Pils in B are one product, one row, named after B's drink."""

    async def body(engine: AsyncEngine) -> tuple[list[CompareRow], int, int]:
        async with engine.begin() as conn:
            a = await _run(conn, "A")
            bier_a = await _drink(conn, a, "Bier", 0)
            await _order(conn, a, 1, [(bier_a, 2, 250)])
            await conn.execute(text("UPDATE run SET status = 'ended' WHERE run_id = :r"), {"r": a})
            b = await _run(conn, "B")
            bier_b = await _drink(conn, b, "Bier", 0)  # resolves to A's product (T3)
            await conn.execute(
                text("UPDATE drink SET name = 'Pils', name_key = 'pils' WHERE drink_id = :d"),
                {"d": bier_b},
            )
            await _order(conn, b, 1, [(bier_b, 3, 300)])
            product = await _product(conn, bier_a)
            assert await _product(conn, bier_b) == product
        async with engine.connect() as conn:
            return await compare(conn, a, b), product, b

    rows, product, _ = _with_engine(settings, database_url, body)

    assert rows == [
        CompareRow(
            f"product:{product}",
            product,
            "Pils",
            SideTotals(2, 500, 500),
            SideTotals(3, 900, 750),
        )
    ]


def _totals(key: str, name: str, qty: int) -> ProductTotals:
    return ProductTotals(key, None, name, qty, qty * 250, qty * 250, 250)


@pytest.mark.parametrize(
    ("key", "joins"),
    [
        pytest.param(lambda p: p.product_key, True, id="product-key"),
        pytest.param(lambda p: p.name, False, id="name-mutant"),
    ],
)
def test_the_join_key_is_the_product_and_a_name_join_would_split_the_row(
    key: Callable[[ProductTotals], str], joins: bool
) -> None:
    """AC11's mutation check: keyed by name, a rename breaks the row in two."""
    a = [_totals("product:7", "Bier", 2)]
    b = [_totals("product:7", "Pils", 3)]

    rows = match_products(a, b, key=key)

    assert (len(rows) == 1) is joins
    assert all((row.a is not None and row.b is not None) is joins for row in rows)


def test_a_product_in_one_run_only_has_an_empty_other_side(
    settings: Settings, database_url: str
) -> None:
    """AC28, PD14: Wijn only in A is `b: None`; Fris only in B is `a: None`."""

    async def body(engine: AsyncEngine) -> list[CompareRow]:
        async with engine.begin() as conn:
            a = await _run(conn, "A")
            bier_a = await _drink(conn, a, "Bier", 0)
            wijn = await _drink(conn, a, "Wijn", 1)
            await _order(conn, a, 1, [(bier_a, 1, 250), (wijn, 1, 300)])
            b = await _run(conn, "B")
            bier_b = await _drink(conn, b, "Bier", 0)
            fris = await _drink(conn, b, "Fris", 1)
            await _order(conn, b, 1, [(bier_b, 2, 260), (fris, 4, 150)])
        async with engine.connect() as conn:
            return await compare(conn, a, b)

    rows = _with_engine(settings, database_url, body)

    assert [(r.name, r.a, r.b) for r in rows] == [
        ("Bier", SideTotals(1, 250, 250), SideTotals(2, 520, 500)),
        ("Wijn", SideTotals(1, 300, 250), None),
        ("Fris", None, SideTotals(4, 600, 1000)),
    ]


def test_an_unknown_run_names_its_side(settings: Settings, database_url: str) -> None:
    """The 404 says which of `a` and `b` is unknown."""

    async def body(engine: AsyncEngine) -> list[Any]:
        async with engine.begin() as conn:
            known = await _run(conn, "A")
        sides = []
        async with engine.connect() as conn:
            for a, b in ((999_999, known), (known, 999_999)):
                with pytest.raises(RunNotFound) as raised:
                    await compare(conn, a, b)
                sides.append(raised.value.extra["side"])
        return sides

    assert _with_engine(settings, database_url, body) == ["a", "b"]


def test_the_price_curve_breaks_on_a_gap_and_is_bounded(
    settings: Settings, database_url: str
) -> None:
    """AC29, PD13: minutes since t0, the last tick's price per bucket, null with a gap."""

    async def body(engine: AsyncEngine) -> tuple[list[CurvePoint], list[CurvePoint], int]:
        async with engine.begin() as conn:
            run_id = await _run(conn, "A")
            bier = await _drink(conn, run_id, "Bier", 0)
            other = await _drink(conn, run_id, "Wijn", 1)
            ticks: list[tuple[int, str, dict[int, float]]] = []
            for second in range(0, 6 * 60, 10):  # six minutes, a tick every 10 s
                source = "gap" if second == 3 * 60 + 20 else "tick"
                ticks.append((T0 + second * 1000, source, {bier: 2.0 + second / 100, other: 3.0}))
            await _ticks(conn, run_id, ticks)
            product = await _product(conn, bier)
        async with engine.connect() as conn:
            per_minute = await price_curve(conn, run_id, product, bucket_ms=MINUTE)
            per_five = await price_curve(conn, run_id, product, bucket_ms=5 * MINUTE)
        return per_minute, per_five, 6 * 60

    per_minute, per_five, duration_s = _with_engine(settings, database_url, body)

    assert [p.minute for p in per_minute] == [0, 1, 2, 3, 4, 5]
    assert len(per_minute) <= math.ceil(duration_s / 60)
    # A bucket's price is its last tick's: second 50 of each minute.
    assert [p.price_cents for p in per_minute] == [250, 310, 370, None, 490, 550]
    assert per_five == [CurvePoint(0, None), CurvePoint(5, 550)]
    assert len(per_five) <= math.ceil(duration_s / 300)


def test_the_curve_uses_the_products_newest_drink_and_skips_its_absence(
    settings: Settings, database_url: str
) -> None:
    """PD13: a re-added drink's curve is the newest drink's; ticks without it give no point."""

    async def body(engine: AsyncEngine) -> list[CurvePoint]:
        async with engine.begin() as conn:
            run_id = await _run(conn, "A")
            old = await _drink(conn, run_id, "Bier", 0)
            await conn.execute(
                text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": old}
            )
            new = await _drink(conn, run_id, "Bier", 1)
            assert await _product(conn, new) == await _product(conn, old)
            await _ticks(
                conn,
                run_id,
                [
                    (T0, "tick", {old: 9.0}),
                    (T0 + MINUTE, "tick", {old: 9.0}),
                    (T0 + 2 * MINUTE, "tick", {new: 2.5}),
                ],
            )
            product = await _product(conn, new)
        async with engine.connect() as conn:
            return await price_curve(conn, run_id, product, bucket_ms=MINUTE)

    assert _with_engine(settings, database_url, body) == [CurvePoint(2, 250)]


def test_runs_without_orders_or_ticks_are_empty(settings: Settings, database_url: str) -> None:
    """AC30: no rows, and no curve, rather than an error."""

    async def body(engine: AsyncEngine) -> tuple[list[CompareRow], list[CurvePoint]]:
        async with engine.begin() as conn:
            a = await _run(conn, "A")
            bier = await _drink(conn, a, "Bier", 0)
            b = await _run(conn, "B")
            product = await _product(conn, bier)
        async with engine.connect() as conn:
            return await compare(conn, a, b), await price_curve(conn, b, product, bucket_ms=MINUTE)

    rows, curve = _with_engine(settings, database_url, body)

    assert rows == []
    assert curve == []
