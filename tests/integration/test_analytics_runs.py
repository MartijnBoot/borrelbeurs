"""The analytics run list and run detail (Phase 7 T13: AC26, AC27, AC30; SD10, SD13; PD11, PD12).

Runs are seeded straight into the tables -- a first tick for `t0`, orders at
chosen prices and bar prices, `ended_at` on the app clock -- and every total is
checked against SQL over `order_line`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TypeVar

import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db import models
from app.db.analytics import ProductTotals, RunTotals, run_detail, run_list
from app.db.runs import RunNotFound, add_drink, create_draft_run
from app.db.session import create_engine
from exchange import Params

T0 = 1_759_312_800_000
HOUR = 3_600_000

T = TypeVar("T")


def _with_engine(settings: Settings, url: str, body: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _run(conn: AsyncConnection, name: str, *, t0_ms: int | None) -> int:
    run_id = await create_draft_run(conn, name=name, params=Params(step_quant=0.1), run_seed=5)
    if t0_ms is not None:
        await conn.execute(
            insert(models.PriceTick),
            [
                {"run_id": run_id, "version": v, "source": "tick", "prices": {}, "wall_ts_ms": ts}
                for v, ts in ((0, t0_ms), (1, t0_ms + 1_000))
            ],
        )
    return run_id


async def _drink(
    conn: AsyncConnection, run_id: int, name: str, slot: int, *, bar_price_cents: int
) -> int:
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
            bar_price_cents=bar_price_cents,
        )
    )


Line = tuple[int, int, int, int | None]  # (drink_id, qty, unit_price_cents, bar_price_cents)


async def _order(conn: AsyncConnection, run_id: int, version: int, lines: Sequence[Line]) -> None:
    order_id = (
        await conn.execute(
            insert(models.Order).returning(models.Order.order_id),
            {
                "run_id": run_id,
                "idempotency_key": f"k-analytics-{run_id}-{version}",
                "version": version,
                "wall_ts_ms": T0 + version * 1_000,
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
                "bar_price_cents": bar,
            }
            for drink_id, qty, price, bar in lines
        ],
    )


async def _end(conn: AsyncConnection, run_id: int, ended_at_ms: int) -> None:
    await conn.execute(
        update(models.Run)
        .where(models.Run.run_id == run_id)
        .values(status="ended", ended_at=datetime.fromtimestamp(ended_at_ms / 1000, UTC))
    )


async def _remove(conn: AsyncConnection, drink_id: int) -> None:
    await conn.execute(
        text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": drink_id}
    )


async def _sql_totals(engine: AsyncEngine, run_id: int) -> tuple[int, int, int]:
    """`(qty, sum(line_total_cents), sum of qty * bar price with SD13's fallback)` from SQL."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT coalesce(sum(l.qty), 0), coalesce(sum(l.line_total_cents), 0),"
                    " coalesce(sum(l.qty * coalesce(l.bar_price_cents, d.bar_price_cents)), 0)"
                    ' FROM order_line l JOIN "order" o USING (order_id)'
                    " JOIN drink d ON d.drink_id = l.drink_id WHERE o.run_id = :r"
                ),
                {"r": run_id},
            )
        ).one()
    return int(row[0]), int(row[1]), int(row[2])


async def _two_runs(engine: AsyncEngine) -> tuple[int, int]:
    """An ended run whose Wijn sold, then was removed; and a draft with a drink and no orders."""
    async with engine.begin() as conn:
        ended = await _run(conn, "Vrijmibo", t0_ms=T0)
        bier = await _drink(conn, ended, "Bier", 0, bar_price_cents=250)
        wijn = await _drink(conn, ended, "Wijn", 1, bar_price_cents=300)
        await _order(conn, ended, 1, [(bier, 2, 240, 250), (wijn, 1, 310, 300)])
        await _remove(conn, wijn)
        await _order(conn, ended, 2, [(bier, 1, 260, 275)])  # the bar price changed (AC12)
        await _end(conn, ended, T0 + HOUR)
        draft = await _run(conn, "Volgende", t0_ms=None)
        await _drink(conn, draft, "Bier", 0, bar_price_cents=250)
    return ended, draft


def test_the_run_list_totals_each_run_in_one_query(settings: Settings, database_url: str) -> None:
    """AC26, PD12: revenue, bar-price revenue, quantity; duration from the first tick."""

    async def body(engine: AsyncEngine) -> tuple[list[RunTotals], tuple[int, int, int], int, int]:
        ended, draft = await _two_runs(engine)
        async with engine.connect() as conn:
            listed = await run_list(conn)
        return listed, await _sql_totals(engine, ended), ended, draft

    listed, (qty, revenue, bar), ended, draft = _with_engine(settings, database_url, body)

    assert listed == [
        RunTotals(draft, "Volgende", "draft", None, None, None, 0, 0, 0),
        RunTotals(ended, "Vrijmibo", "ended", T0, T0 + HOUR, HOUR, qty, revenue, bar),
    ]
    assert (qty, revenue, bar) == (4, 480 + 310 + 260, 2 * 250 + 300 + 275)


def test_the_run_detail_includes_a_removed_drink_that_sold(
    settings: Settings, database_url: str
) -> None:
    """AC27: per product, removed drinks included; the totals equal SQL."""

    async def body(engine: AsyncEngine) -> tuple[RunTotals, list[ProductTotals], int, int]:
        ended, _ = await _two_runs(engine)
        async with engine.connect() as conn:
            detail = await run_detail(conn, ended)
        revenue = (await _sql_totals(engine, ended))[1]
        return detail.run, list(detail.per_product), revenue, ended

    run, per_product, revenue, ended = _with_engine(settings, database_url, body)

    assert [(p.name, p.qty, p.revenue_cents, p.bar_price_total_cents) for p in per_product] == [
        ("Bier", 3, 480 + 260, 2 * 250 + 275),
        ("Wijn", 1, 310, 300),
    ]
    assert [p.avg_price_cents for p in per_product] == [247, 310]  # round(740 / 3)
    assert all(p.product_id is not None for p in per_product)
    assert [p.product_key for p in per_product] == [f"product:{p.product_id}" for p in per_product]
    assert sum(p.revenue_cents for p in per_product) == run.revenue_cents == revenue
    assert (run.run_id, run.duration_ms) == (ended, HOUR)


def test_a_run_without_orders_is_zero_totals_and_no_rows(
    settings: Settings, database_url: str
) -> None:
    """AC30: a draft with a drink and no orders is an empty state, not an error."""

    async def body(engine: AsyncEngine) -> tuple[RunTotals, list[ProductTotals]]:
        _, draft = await _two_runs(engine)
        async with engine.connect() as conn:
            detail = await run_detail(conn, draft)
        return detail.run, list(detail.per_product)

    run, per_product = _with_engine(settings, database_url, body)

    assert (run.qty, run.revenue_cents, run.bar_price_total_cents) == (0, 0, 0)
    assert (run.t0_ms, run.ended_at_ms, run.duration_ms) == (None, None, None)
    assert per_product == []


def test_a_live_run_has_no_duration_yet(settings: Settings, database_url: str) -> None:
    """PD12: only an ended run has a duration; the UI shows "loopt"."""

    async def body(engine: AsyncEngine) -> RunTotals:
        async with engine.begin() as conn:
            live = await _run(conn, "Nu", t0_ms=T0)
            await conn.execute(
                update(models.Run).where(models.Run.run_id == live).values(status="live")
            )
        async with engine.connect() as conn:
            return (await run_detail(conn, live)).run

    run = _with_engine(settings, database_url, body)

    assert (run.status, run.t0_ms, run.ended_at_ms, run.duration_ms) == ("live", T0, None, None)


def test_rows_from_a_rolled_back_image_are_counted(settings: Settings, database_url: str) -> None:
    """SD13: a NULL-product drink groups by its name_key; a NULL bar price is the drink's."""

    async def body(engine: AsyncEngine) -> tuple[RunTotals, list[ProductTotals]]:
        async with engine.begin() as conn:
            run_id = await _run(conn, "Oud", t0_ms=T0)
            bier = await _drink(conn, run_id, "Bier", 0, bar_price_cents=275)
            await conn.execute(
                update(models.Drink).where(models.Drink.drink_id == bier).values(product_id=None)
            )
            await _order(conn, run_id, 1, [(bier, 2, 250, None)])
        async with engine.connect() as conn:
            detail = await run_detail(conn, run_id)
            (listed,) = [r for r in await run_list(conn) if r.run_id == run_id]
        assert listed == detail.run
        return detail.run, list(detail.per_product)

    run, per_product = _with_engine(settings, database_url, body)

    assert per_product == [ProductTotals("name:bier", None, "Bier", 2, 500, 550, 250)]
    assert (run.qty, run.revenue_cents, run.bar_price_total_cents) == (2, 500, 550)


def test_an_unknown_run_is_run_not_found(settings: Settings, database_url: str) -> None:
    async def body(engine: AsyncEngine) -> None:
        async with engine.connect() as conn:
            with pytest.raises(RunNotFound):
                await run_detail(conn, 999_999)

    _with_engine(settings, database_url, body)
