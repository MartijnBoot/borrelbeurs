"""The migrated schema, inspected: money is integer cents, revenue lives in one place.

AC9 and AC11 are claims about the *schema*, so these tests read
`information_schema.columns` from the migrated scratch database rather than the
models. The constraint tests write by direct SQL, as in `test_migrations.py`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable

import pytest
from sqlalchemy import pool, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

PHASE_2_TABLES = frozenset(
    {
        "run",
        "run_config_revision",
        "drink",
        "engine_state",
        "price_tick",
        "order",
        "order_line",
        "news",
    }
)

INTEGER_TYPES = frozenset({"integer", "bigint"})
FLOAT_TYPES = frozenset({"real", "double precision", "numeric", "money"})

# Float columns that are not money: demand coefficients, and the continuous
# price an order line records as a diagnostic beside the cents it charged.
NON_MONEY_FLOATS = frozenset(
    {
        ("drink", "a"),
        ("drink", "d"),
        ("drink", "s0"),
        ("drink", "c"),
        ("order_line", "p_cont"),
    }
)

REVENUE_PATTERN = re.compile(r"revenue|total|earn", re.IGNORECASE)
THE_REVENUE_COLUMN = ("order_line", "line_total_cents")

Column = tuple[str, str, str]  # table, column, data type


async def _columns(url: str) -> list[Column]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
                )
            )
            return [(str(t), str(c), str(d)) for t, c, d in result]
    finally:
        await engine.dispose()


def money_violations(columns: Iterable[Column]) -> list[str]:
    """Every `*_cents` column that is not an integer, and every float that is not allowlisted."""
    faults = []
    for table, column, data_type in columns:
        if column.endswith("_cents") and data_type not in INTEGER_TYPES:
            faults.append(f"{table}.{column} is {data_type}, not integer cents")
        if data_type in FLOAT_TYPES and (table, column) not in NON_MONEY_FLOATS:
            faults.append(f"{table}.{column} is {data_type}; a euro amount must be integer cents")
    return faults


def test_the_eight_phase_2_tables_are_the_ones_inspected(database_url: str) -> None:
    """Anti-vacuity: the inspection below reaches every table of SD4."""
    assert {table for table, _, _ in asyncio.run(_columns(database_url))} == PHASE_2_TABLES


def test_every_money_column_is_integer_cents(database_url: str) -> None:
    """AC9 (D-09)."""
    columns = asyncio.run(_columns(database_url))

    assert money_violations(columns) == []
    assert {(t, c) for t, c, _ in columns} >= NON_MONEY_FLOATS, "allowlist names a lost column"


@pytest.mark.parametrize(
    ("injected", "fault"),
    [
        (("order", "price", "numeric"), "order.price is numeric"),
        (("drink", "bar_price_cents", "double precision"), "not integer cents"),
        (("run", "fee", "money"), "run.fee is money"),
        (("order_line", "unit_price_cents", "numeric"), "not integer cents"),
    ],
)
def test_the_money_detector_flags_an_injected_column(injected: Column, fault: str) -> None:
    """The detector is not vacuous: a future `price NUMERIC` would fail AC9."""
    faults = money_violations([("drink", "a", "double precision"), injected])

    assert any(fault in f for f in faults), faults


def test_revenue_is_stored_only_as_order_line_totals(database_url: str) -> None:
    """AC11 (D-10): no other table or column stores revenue."""
    columns = asyncio.run(_columns(database_url))
    revenue_like = {(t, c) for t, c, _ in columns if REVENUE_PATTERN.search(c)}

    assert revenue_like == {THE_REVENUE_COLUMN}


def _in_transaction(url: str, body: Callable[[AsyncConnection], Awaitable[None]]) -> None:
    async def scenario() -> None:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as connection:
                await body(connection)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _run_and_drink(connection: AsyncConnection) -> tuple[int, int]:
    run_id: int = (
        await connection.execute(
            text("INSERT INTO run (run_seed, params) VALUES (1, '{}') RETURNING run_id")
        )
    ).scalar_one()
    drink_id: int = (
        await connection.execute(
            text(
                "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents, p0_cents, "
                "p_max_cents, a, d, s0, c, bar_price_cents) VALUES (:run_id, 0, 'Bier', 'bier', "
                "150, 260, 500, 0, 0, 0, 0, 260) RETURNING drink_id"
            ),
            {"run_id": run_id},
        )
    ).scalar_one()
    return int(run_id), int(drink_id)


async def _order(connection: AsyncConnection, run_id: int, key: str) -> int:
    result = await connection.execute(
        text(
            'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms) '
            "VALUES (:run_id, :key, 1, 0) RETURNING order_id"
        ),
        {"run_id": run_id, "key": key},
    )
    return int(result.scalar_one())


async def _line(
    connection: AsyncConnection, order_id: int, drink_id: int, *, qty: int, unit: int, total: int
) -> None:
    await connection.execute(
        text(
            "INSERT INTO order_line (order_id, drink_id, qty, unit_price_cents, "
            "line_total_cents, p_cont) VALUES (:order_id, :drink_id, :qty, :unit, :total, 2.6)"
        ),
        {"order_id": order_id, "drink_id": drink_id, "qty": qty, "unit": unit, "total": total},
    )


def test_a_capitalised_news_level_is_rejected_by_the_database(database_url: str) -> None:
    """AC16 (database half), SD13."""

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, 1, 'Info', 'x')"),
            {"r": run_id},
        )

    with pytest.raises(IntegrityError, match="news_level_check"):
        _in_transaction(database_url, write)


def test_the_four_lowercase_news_levels_are_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        for level in ("info", "success", "warning", "danger"):
            await connection.execute(
                text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, 1, :l, 'x')"),
                {"r": run_id, "l": level},
            )

    _in_transaction(database_url, write)


def test_an_unknown_tick_source_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text(
                "INSERT INTO price_tick (run_id, version, source, prices, wall_ts_ms) "
                "VALUES (:r, 0, 'bogus', '{}', 0)"
            ),
            {"r": run_id},
        )

    with pytest.raises(IntegrityError, match="price_tick_source_check"):
        _in_transaction(database_url, write)


def test_the_known_tick_sources_are_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        for version, source in enumerate(("tick", "order", "jump", "idle", "reset", "gap")):
            await connection.execute(
                text(
                    "INSERT INTO price_tick (run_id, version, source, prices, wall_ts_ms) "
                    "VALUES (:r, :v, :s, '{}', 0)"
                ),
                {"r": run_id, "v": version, "s": source},
            )

    _in_transaction(database_url, write)


def test_a_duplicate_idempotency_key_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await _order(connection, run_id, "k-1")
        await _order(connection, run_id, "k-1")

    with pytest.raises(IntegrityError, match="idempotency_key"):
        _in_transaction(database_url, write)


def test_a_line_total_must_equal_qty_times_unit_price(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=2, unit=260, total=500)

    with pytest.raises(IntegrityError, match="order_line_total_check"):
        _in_transaction(database_url, write)


def test_a_consistent_line_is_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=2, unit=260, total=520)

    _in_transaction(database_url, write)


@pytest.mark.parametrize(("qty", "unit"), [(0, 260), (-1, 260), (1, -10)])
def test_a_line_needs_a_positive_qty_and_a_non_negative_price(
    database_url: str, qty: int, unit: int
) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=qty, unit=unit, total=qty * unit)

    with pytest.raises(IntegrityError, match=r"order_line_(qty|unit_price_cents)_check"):
        _in_transaction(database_url, write)


def test_one_drink_appears_once_per_order(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=1, unit=260, total=260)
        await _line(connection, order_id, drink_id, qty=1, unit=260, total=260)

    with pytest.raises(IntegrityError, match="order_line_order_id_drink_id_key"):
        _in_transaction(database_url, write)
