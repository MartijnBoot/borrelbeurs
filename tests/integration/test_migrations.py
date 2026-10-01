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
            "INSERT INTO run (status, run_seed, params) VALUES (:status, 1, '{}') RETURNING run_id"
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
