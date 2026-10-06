"""The cumulative revenue series (Phase 5 T1: AC20, SD16, PD12).

Orders are inserted straight into `"order"` and `order_line` at chosen
`wall_ts_ms`: the series reads nothing else, so no engine state is needed to
pin its bucketing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db import models
from app.db.orders import earnings_series
from app.db.runs import add_drink, create_draft_run
from app.db.session import create_engine
from exchange import Params

MINUTE = 60_000
T0 = 1_700_000_040_000  # 40 s into a minute, so a bucket end is not the order's own time
BUCKET_0 = (T0 // MINUTE) * MINUTE + MINUTE


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _run(engine: AsyncEngine, seed: int) -> tuple[int, int]:
    """A draft run with one drink: `(run_id, drink_id)`. The series does not care if it is live."""
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Borrel", params=Params(step_quant=0.1), run_seed=seed
        )
        drink_id = await add_drink(
            conn,
            run_id,
            name="Bier",
            slot=0,
            p_min_cents=150,
            p0_cents=260,
            p_max_cents=500,
            a=1.0,
            d=0.1,
            s0=1.0,
            c=0.1,
            bar_price_cents=260,
        )
    return run_id, int(drink_id)


async def _orders(
    engine: AsyncEngine, run_id: int, drink_id: int, orders: Sequence[tuple[int, int, int]]
) -> None:
    """Insert `(wall_ts_ms, qty, unit_price_cents)` orders, one line each."""
    async with engine.begin() as conn:
        order_ids = (
            await conn.execute(
                insert(models.Order).returning(models.Order.order_id),
                [
                    {
                        "run_id": run_id,
                        "idempotency_key": f"k-{run_id}-{i}",
                        "version": i,
                        "wall_ts_ms": ts,
                    }
                    for i, (ts, _, _) in enumerate(orders)
                ],
            )
        ).scalars()
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
                }
                for order_id, (_, qty, price) in zip(order_ids, orders, strict=True)
            ],
        )


async def _series(engine: AsyncEngine, run_id: int) -> list[tuple[int, int]]:
    async with engine.connect() as conn:
        return await earnings_series(conn, run_id)


async def _total(engine: AsyncEngine, run_id: int) -> int:
    async with engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT sum(l.line_total_cents) FROM order_line l"
                        ' JOIN "order" o USING (order_id) WHERE o.run_id = :r'
                    ),
                    {"r": run_id},
                )
            ).scalar_one()
        )


def test_buckets_are_cumulative_and_end_on_the_minute(
    settings: Settings, database_url: str
) -> None:
    """Three minutes, two orders in the first: three points at bucket ends, running totals."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, drink_id = await _run(engine, 1)
            await _orders(
                engine,
                run_id,
                drink_id,
                [
                    (T0, 1, 250),
                    (T0 + 10_000, 2, 260),  # same bucket as T0
                    (T0 + MINUTE, 1, 300),
                    (T0 + 2 * MINUTE + 5_000, 3, 200),
                ],
            )
            series = await _series(engine, run_id)
            assert series == [
                (BUCKET_0, 250 + 520),
                (BUCKET_0 + MINUTE, 250 + 520 + 300),
                (BUCKET_0 + 2 * MINUTE, 250 + 520 + 300 + 600),
            ]
            assert series[-1][1] == await _total(engine, run_id)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_an_order_on_a_minute_boundary_belongs_to_the_next_bucket(
    settings: Settings, database_url: str
) -> None:
    """Bucket end = floor(ts / 60 s) * 60 s + 60 s: an order at exactly :00 starts a bucket."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, drink_id = await _run(engine, 1)
            boundary = BUCKET_0
            await _orders(engine, run_id, drink_id, [(boundary, 1, 250)])
            assert await _series(engine, run_id) == [(boundary + MINUTE, 250)]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_two_thousand_orders_in_one_minute_are_one_point(
    settings: Settings, database_url: str
) -> None:
    """AC20: the size is bounded by run length / 60 s, not by order count."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, drink_id = await _run(engine, 1)
            await _orders(
                engine, run_id, drink_id, [(T0 + i * 10, 1, 200 + i % 7) for i in range(2_000)]
            )
            series = await _series(engine, run_id)
            assert len(series) == 1
            assert series == [(BUCKET_0, await _total(engine, run_id))]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_another_runs_orders_are_excluded(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, drink_id = await _run(engine, 1)
            other_id, other_drink = await _run(engine, 2)
            await _orders(engine, run_id, drink_id, [(T0, 1, 250)])
            await _orders(engine, other_id, other_drink, [(T0, 5, 400), (T0 + MINUTE, 1, 400)])
            assert await _series(engine, run_id) == [(BUCKET_0, 250)]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_no_orders_is_an_empty_series(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, _ = await _run(engine, 1)
            assert await _series(engine, run_id) == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())
