"""Products: resolved on add, kept on rename (Phase 7 T3: AC10, SD1, PD7)."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db.runs import add_drink, all_drinks, create_draft_run, remove_drink, update_drink
from app.db.session import create_engine
from exchange import Params


def _scenario(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[None]]
) -> None:
    """`body(conn)` in one committed transaction on the scratch database."""

    async def run() -> None:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                await body(conn)
        finally:
            await engine.dispose()

    asyncio.run(run())


async def _run(conn: AsyncConnection) -> int:
    return await create_draft_run(conn, name="Borrel", params=Params(), run_seed=1)


async def _add(conn: AsyncConnection, run_id: int, name: str, slot: int) -> int:
    return await add_drink(
        conn,
        run_id,
        name=name,
        slot=slot,
        p_min_cents=150,
        p0_cents=260,
        p_max_cents=500,
        a=1.0,
        d=0.1,
        s0=1.0,
        c=0.1,
        bar_price_cents=260,
    )


async def _product(conn: AsyncConnection, drink_id: int) -> int | None:
    result = await conn.execute(
        text("SELECT product_id FROM drink WHERE drink_id = :d"), {"d": drink_id}
    )
    value: int | None = result.scalar_one()
    return None if value is None else int(value)


def test_the_same_name_in_three_runs_is_one_product(settings: Settings, database_url: str) -> None:
    """SD1: two runs adding "Bier", and " bier " in a third, share a product."""
    products: list[int | None] = []

    async def body(conn: AsyncConnection) -> None:
        for name in ("Bier", "Bier", " bier "):
            run_id = await _run(conn)
            products.append(await _product(conn, await _add(conn, run_id, name, 0)))

    _scenario(settings, database_url, body)
    assert products[0] is not None
    assert products == [products[0]] * 3


def test_different_names_are_different_products(settings: Settings, database_url: str) -> None:
    products: list[int | None] = []

    async def body(conn: AsyncConnection) -> None:
        run_id = await _run(conn)
        products.append(await _product(conn, await _add(conn, run_id, "Bier", 0)))
        products.append(await _product(conn, await _add(conn, run_id, "Wijn", 1)))

    _scenario(settings, database_url, body)
    assert None not in products
    assert products[0] != products[1]


def test_a_rename_keeps_the_product(settings: Settings, database_url: str) -> None:
    """SD1: renaming "Bier" to "Pils" keeps the product, so history stays joined."""
    seen: list[int | None] = []

    async def body(conn: AsyncConnection) -> None:
        run_id = await _run(conn)
        drink_id = await _add(conn, run_id, "Bier", 0)
        seen.append(await _product(conn, drink_id))
        [row] = await all_drinks(conn, run_id)
        await update_drink(conn, run_id, dataclasses.replace(row, name="Pils"))
        seen.append(await _product(conn, drink_id))
        # A new "Bier" beside the renamed one cannot share its product.
        seen.append(await _product(conn, await _add(conn, run_id, "Bier", 1)))

    _scenario(settings, database_url, body)
    before, after, new_bier = seen
    assert before is not None
    assert after == before
    assert new_bier is not None and new_bier != before


def test_a_removed_drink_re_added_lands_on_its_product(
    settings: Settings, database_url: str
) -> None:
    """SD1: remove then re-add "Wijn" in a live run: a new drink, the same product."""
    seen: list[tuple[int, int | None]] = []

    async def body(conn: AsyncConnection) -> None:
        run_id = await _run(conn)
        await _add(conn, run_id, "Bier", 0)
        wijn = await _add(conn, run_id, "Wijn", 1)
        await conn.execute(text("UPDATE run SET status = 'live' WHERE run_id = :r"), {"r": run_id})
        seen.append((wijn, await _product(conn, wijn)))
        await remove_drink(conn, wijn)
        again = await _add(conn, run_id, "Wijn", 2)
        seen.append((again, await _product(conn, again)))

    _scenario(settings, database_url, body)
    (first, product), (second, again) = seen
    assert second != first
    assert product is not None
    assert again == product
