"""The migrations: they round-trip (AC23), and the schema enforces what Python cannot.

AC23 runs on a database of its own (`empty_database`), never on the session's
scratch database, because `downgrade base` would pull the schema out from under
every other test. The gate runs this file in its integration step, which is
AC23's "the gate shall run this".

The constraint tests write by direct SQL on purpose. The repositories that will
normally guard these rules come later (T5, T8); what is proven here is that the
database refuses on its own, whoever is writing.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, pool, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.models import Base

RunAlembic = Callable[..., subprocess.CompletedProcess[str]]

APPLICATION_TABLES = frozenset(Base.metadata.tables)


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
            return {str(row[0]) for row in result}
    finally:
        await engine.dispose()


def test_upgrade_downgrade_upgrade_round_trips(empty_database: str, alembic: RunAlembic) -> None:
    """AC23: each step exits 0 and leaves exactly the tables it should."""
    for args, expected in (
        (("upgrade", "head"), APPLICATION_TABLES | {"alembic_version"}),
        (("downgrade", "base"), {"alembic_version"}),
        (("upgrade", "head"), APPLICATION_TABLES | {"alembic_version"}),
    ):
        step = alembic(empty_database, *args)
        assert step.returncode == 0, f"alembic {' '.join(args)} failed:\n{step.stderr}"
        assert asyncio.run(_tables(empty_database)) == expected, f"after {' '.join(args)}"


def test_the_models_match_the_migrated_schema(database_url: str) -> None:
    """`app/db/models.py` is column-for-column what the migrations create."""

    def diff(connection: Connection) -> list[object]:
        return list(compare_metadata(MigrationContext.configure(connection), Base.metadata))

    async def scenario() -> list[object]:
        engine = create_async_engine(database_url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(diff)
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == []


async def _insert_run(connection: AsyncConnection, status: str = "draft") -> int:
    result = await connection.execute(
        text(
            "INSERT INTO run (name, status, run_seed, params) VALUES ('B', :status, 1, '{}') "
            "RETURNING run_id"
        ),
        {"status": status},
    )
    return int(result.scalar_one())


async def _insert_drink(
    connection: AsyncConnection, run_id: int, *, slot: int, name: str, removed: bool = False
) -> None:
    await connection.execute(
        text(
            "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents, p0_cents, "
            "p_max_cents, a, d, s0, c, bar_price_cents, removed_at) VALUES (:run_id, :slot, "
            ":name, :name_key, 150, 260, 500, 0, 0, 0, 0, 260, "
            "CASE WHEN :removed THEN now() END)"
        ),
        {
            "run_id": run_id,
            "slot": slot,
            "name": name,
            "name_key": name.strip().casefold(),
            "removed": removed,
        },
    )


def _in_transaction(url: str, body: Callable[[AsyncConnection], Awaitable[None]]) -> None:
    """Run `body(connection)` in one committed transaction on a fresh engine."""

    async def scenario() -> None:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as connection:
                await body(connection)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_second_live_run_is_rejected_by_the_database(database_url: str) -> None:
    """AC22 (database half), SD6: the partial unique index on `status = 'live'`."""

    async def setup(connection: AsyncConnection) -> None:
        await _insert_run(connection, "live")
        await _insert_run(connection, "draft")
        await _insert_run(connection, "ended")
        await _insert_run(connection, "ended")

    _in_transaction(database_url, setup)

    async def second_live(connection: AsyncConnection) -> None:
        await connection.execute(text("UPDATE run SET status = 'live' WHERE status = 'draft'"))

    with pytest.raises(IntegrityError, match="run_one_live"):
        _in_transaction(database_url, second_live)


def test_an_unknown_run_status_is_rejected(database_url: str) -> None:
    async def bogus(connection: AsyncConnection) -> None:
        await _insert_run(connection, "paused")

    with pytest.raises(IntegrityError, match="run_status_check"):
        _in_transaction(database_url, bogus)


def test_two_non_removed_drinks_may_not_share_a_name_key(database_url: str) -> None:
    """SD14 at the SQL level: `Bier` and ` bier ` share the key `bier`."""

    async def clash(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        await _insert_drink(connection, run_id, slot=0, name="Bier")
        await _insert_drink(connection, run_id, slot=1, name=" bier ")

    with pytest.raises(IntegrityError, match="drink_name_live"):
        _in_transaction(database_url, clash)


def test_a_removed_drinks_name_key_may_be_reused(database_url: str) -> None:
    """SD14: the index covers non-removed drinks only; other runs are independent."""

    async def reuse(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        await _insert_drink(connection, run_id, slot=0, name="Bier", removed=True)
        await _insert_drink(connection, run_id, slot=1, name="Bier")
        other = await _insert_run(connection)
        await _insert_drink(connection, other, slot=0, name="Bier")

    _in_transaction(database_url, reuse)


def test_drink_bounds_must_be_ordered(database_url: str) -> None:
    async def inverted(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        await connection.execute(
            text(
                "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents, p0_cents, "
                "p_max_cents, a, d, s0, c, bar_price_cents) VALUES (:run_id, 0, 'Bier', 'bier', "
                "260, 150, 500, 0, 0, 0, 0, 260)"
            ),
            {"run_id": run_id},
        )

    with pytest.raises(IntegrityError, match="drink_prices_check"):
        _in_transaction(database_url, inverted)


def test_two_drinks_may_not_share_a_slot(database_url: str) -> None:
    async def clash(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        await _insert_drink(connection, run_id, slot=0, name="Bier")
        await _insert_drink(connection, run_id, slot=0, name="Wijn")

    with pytest.raises(IntegrityError, match="drink_run_id_slot_key"):
        _in_transaction(database_url, clash)


def test_0009_names_existing_runs_after_their_id(empty_database: str, alembic: RunAlembic) -> None:
    """Phase 6 PD3: a run from before 0009 is backfilled as `Borrel <run_id>`."""
    assert alembic(empty_database, "upgrade", "0008").returncode == 0

    async def old_run(connection: AsyncConnection) -> None:
        await connection.execute(
            text("INSERT INTO run (status, run_seed, params) VALUES ('draft', 1, '{}')")
        )

    _in_transaction(empty_database, old_run)
    step = alembic(empty_database, "upgrade", "head")
    assert step.returncode == 0, step.stderr

    names: list[tuple[int, str]] = []

    async def read(connection: AsyncConnection) -> None:
        result = await connection.execute(text("SELECT run_id, name FROM run"))
        names.extend((int(row[0]), str(row[1])) for row in result)

    _in_transaction(empty_database, read)
    [(run_id, name)] = names
    assert name == f"Borrel {run_id}"


async def _insert_old_drink(
    connection: AsyncConnection,
    run_id: int,
    *,
    slot: int,
    name: str,
    bar_price_cents: int,
    added_at: datetime,
    removed: bool = False,
) -> int:
    """A drink as a 0009 database holds it: no `product_id`."""
    result = await connection.execute(
        text(
            "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents, p0_cents, "
            "p_max_cents, a, d, s0, c, bar_price_cents, added_at, removed_at) VALUES (:run_id, "
            ":slot, :name, :name_key, 150, 260, 500, 0, 0, 0, 0, :bar, :added_at, "
            "CASE WHEN :removed THEN now() END) RETURNING drink_id"
        ),
        {
            "run_id": run_id,
            "slot": slot,
            "name": name,
            "name_key": name.strip().casefold(),
            "bar": bar_price_cents,
            "added_at": added_at,
            "removed": removed,
        },
    )
    return int(result.scalar_one())


async def _insert_old_order(
    connection: AsyncConnection, run_id: int, key: str, lines: list[tuple[int, int]]
) -> None:
    """An order with `(drink_id, qty)` lines at 260 cents each, as 0009 writes it."""
    order_id: int = (
        await connection.execute(
            text(
                'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms) '
                "VALUES (:run_id, :key, 1, 0) RETURNING order_id"
            ),
            {"run_id": run_id, "key": key},
        )
    ).scalar_one()
    for drink_id, qty in lines:
        await connection.execute(
            text(
                "INSERT INTO order_line (order_id, drink_id, qty, unit_price_cents, "
                "line_total_cents, p_cont) VALUES (:order_id, :drink_id, :qty, 260, :total, 2.6)"
            ),
            {"order_id": order_id, "drink_id": drink_id, "qty": qty, "total": qty * 260},
        )


def test_0010_backfills_products_and_line_bar_prices(
    empty_database: str, alembic: RunAlembic
) -> None:
    """Phase 7 T1 (AC10, AC12): one product per `name_key`, every line's bar price."""
    assert alembic(empty_database, "upgrade", "0009").returncode == 0

    async def seed(connection: AsyncConnection) -> None:
        a = await _insert_run(connection, "ended")
        b = await _insert_run(connection, "ended")
        bier_a = await _insert_old_drink(
            connection,
            a,
            slot=0,
            name="Bier",
            bar_price_cents=250,
            added_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        wijn_old = await _insert_old_drink(
            connection,
            a,
            slot=1,
            name="Wijn",
            bar_price_cents=300,
            added_at=datetime(2026, 1, 1, tzinfo=UTC),
            removed=True,
        )
        wijn_new = await _insert_old_drink(
            connection,
            a,
            slot=2,
            name="wijn",
            bar_price_cents=320,
            added_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        bier_b = await _insert_old_drink(
            connection,
            b,
            slot=0,
            name=" bier ",
            bar_price_cents=270,
            added_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        await _insert_old_order(connection, a, "a1", [(bier_a, 2), (wijn_old, 1)])
        await _insert_old_order(connection, a, "a2", [(wijn_new, 3)])
        await _insert_old_order(connection, b, "b1", [(bier_b, 1)])

    _in_transaction(empty_database, seed)
    step = alembic(empty_database, "upgrade", "head")
    assert step.returncode == 0, step.stderr

    drinks: dict[str, int | None] = {}
    products: dict[int, str] = {}
    lines: list[tuple[int | None, int]] = []

    async def read(connection: AsyncConnection) -> None:
        for row in await connection.execute(text("SELECT name, product_id FROM drink")):
            drinks[str(row[0])] = row[1]
        for row in await connection.execute(text("SELECT product_id, name FROM product")):
            products[int(row[0])] = str(row[1])
        result = await connection.execute(
            text(
                "SELECT order_line.bar_price_cents, drink.bar_price_cents FROM order_line "
                "JOIN drink USING (drink_id)"
            )
        )
        lines.extend((row[0], int(row[1])) for row in result)

    _in_transaction(empty_database, read)
    assert None not in drinks.values()
    assert drinks["Bier"] == drinks[" bier "]
    assert drinks["Wijn"] == drinks["wijn"]
    assert drinks["Bier"] != drinks["Wijn"]
    # Named after the key's earliest drink.
    assert sorted(products.values()) == ["Bier", "Wijn"]
    assert len(lines) == 4
    assert all(line == drink for line, drink in lines)


async def _insert_product(connection: AsyncConnection, name: str) -> int:
    result = await connection.execute(
        text("INSERT INTO product (name_key, name) VALUES (:key, :name) RETURNING product_id"),
        {"key": name.strip().casefold(), "name": name},
    )
    return int(result.scalar_one())


async def _set_product(connection: AsyncConnection, run_id: int, slot: int, product: int) -> None:
    await connection.execute(
        text("UPDATE drink SET product_id = :p WHERE run_id = :run_id AND slot = :slot"),
        {"p": product, "run_id": run_id, "slot": slot},
    )


def test_two_active_drinks_of_a_run_may_not_share_a_product(database_url: str) -> None:
    """Phase 7 SD1: the partial unique index `drink_product_live`."""

    async def clash(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        product = await _insert_product(connection, "Bier")
        await _insert_drink(connection, run_id, slot=0, name="Bier")
        await _insert_drink(connection, run_id, slot=1, name="Pils")
        await _set_product(connection, run_id, 0, product)
        await _set_product(connection, run_id, 1, product)

    with pytest.raises(IntegrityError, match="drink_product_live"):
        _in_transaction(database_url, clash)


def test_a_removed_drinks_product_may_be_reused(database_url: str) -> None:
    """Phase 7 SD1: re-adding a removed drink lands on the same product."""

    async def reuse(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        product = await _insert_product(connection, "Wijn")
        await _insert_drink(connection, run_id, slot=0, name="Wijn", removed=True)
        await _insert_drink(connection, run_id, slot=1, name="Wijn")
        await _set_product(connection, run_id, 0, product)
        await _set_product(connection, run_id, 1, product)

    _in_transaction(database_url, reuse)


@pytest.mark.parametrize(
    ("status", "data", "size", "constraint"),
    [
        ("done", None, None, "export_done_check"),
        ("done", b"xlsx", 3, "export_bytes_check"),
        ("paused", None, None, "export_status_check"),
    ],
)
def test_an_inconsistent_export_is_rejected(
    database_url: str, status: str, data: bytes | None, size: int | None, constraint: str
) -> None:
    """Phase 7 SD6: a done export holds its file, and its byte count is the file's."""

    async def write(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection, "ended")
        await connection.execute(
            text(
                "INSERT INTO export (run_id, kind, status, requested_by, data, bytes) "
                "VALUES (:run_id, 'final', :status, 'admin', :data, :size)"
            ),
            {"run_id": run_id, "status": status, "data": data, "size": size},
        )

    with pytest.raises(IntegrityError, match=constraint):
        _in_transaction(database_url, write)


def test_a_bar_price_on_a_line_may_not_be_negative(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id = await _insert_run(connection)
        await _insert_drink(connection, run_id, slot=0, name="Bier")
        drink_id = (await connection.execute(text("SELECT max(drink_id) FROM drink"))).scalar()
        order_id: int = (
            await connection.execute(
                text(
                    'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms) '
                    "VALUES (:run_id, 'neg', 1, 0) RETURNING order_id"
                ),
                {"run_id": run_id},
            )
        ).scalar_one()
        await connection.execute(
            text(
                "INSERT INTO order_line (order_id, drink_id, qty, unit_price_cents, "
                "line_total_cents, p_cont, bar_price_cents) "
                "VALUES (:order_id, :drink_id, 1, 260, 260, 2.6, -1)"
            ),
            {"order_id": order_id, "drink_id": drink_id},
        )

    with pytest.raises(IntegrityError, match="order_line_bar_price_cents_check"):
        _in_transaction(database_url, write)
