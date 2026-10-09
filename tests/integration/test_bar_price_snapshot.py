"""The bar price is stored per sale (Phase 7 T2: AC12, SD5, PD6; D-20's gate).

A line's `bar_price_cents` is the drink's bar price read inside the order's own
transaction. Changing the bar price later moves no earlier line, so
`sum(qty * bar_price_cents)` is what the sales would have earned at the bar price
in force when each sold.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.config import Settings
from app.runtime.drinks import DrinkPatch, edit_live_drink
from tests.integration.test_place_order import Market, _market

OLD_BAR = 260
NEW_BAR = 300


async def _lines(m: Market) -> list[tuple[int, int, int | None]]:
    """`(order_id, qty, bar_price_cents)` per line, in order."""
    async with m.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT order_id, qty, bar_price_cents FROM order_line "
                "ORDER BY order_id, order_line_id"
            )
        )
        return [(int(r[0]), int(r[1]), r[2]) for r in rows]


def test_a_bar_price_change_moves_no_earlier_line(settings: Settings, database_url: str) -> None:
    """AC12: earlier lines keep the old bar price, later ones carry the new one."""

    async def scenario() -> tuple[list[tuple[int, int, int | None]], int]:
        async with _market(settings, database_url) as m:
            bier, wijn, _ = m.drinks
            live = m.live()
            await m.place(m.request("bar-0000001", {bier: (2, live[bier]), wijn: (1, live[wijn])}))
            live = m.live()
            await m.place(m.request("bar-0000002", {bier: (3, live[bier])}))

            await edit_live_drink(
                m.holder,
                m.holder.run_id,  # type: ignore[arg-type]
                bier,
                DrinkPatch(bar_price_cents=NEW_BAR),
                author="test",
                clock=m.clock,
            )

            live = m.live()
            await m.place(m.request("bar-0000003", {bier: (4, live[bier]), wijn: (5, live[wijn])}))
            async with m.engine.connect() as conn:
                total: int = (
                    await conn.execute(text("SELECT sum(qty * bar_price_cents) FROM order_line"))
                ).scalar_one()
            return await _lines(m), int(total)

    lines, total = asyncio.run(scenario())

    first, second, third = sorted({order for order, _, _ in lines})
    assert [bar for order, _, bar in lines if order in (first, second)] == [OLD_BAR] * 3
    # Bier at the new price, Wijn untouched.
    assert [bar for order, _, bar in lines if order == third] == [NEW_BAR, OLD_BAR]
    expected = (2 + 3) * OLD_BAR + 1 * OLD_BAR + 4 * NEW_BAR + 5 * OLD_BAR
    assert total == expected


def test_no_line_the_app_writes_lacks_a_bar_price(settings: Settings, database_url: str) -> None:
    """SD13: NULL is only ever a rolled-back image's line, never this app's."""

    async def scenario() -> int:
        async with _market(settings, database_url) as m:
            bier, wijn, fris = m.drinks
            live = m.live()
            await m.place(
                m.request(
                    "bar-0000004",
                    {bier: (1, live[bier]), wijn: (2, live[wijn]), fris: (3, live[fris])},
                )
            )
            async with m.engine.connect() as conn:
                return int(
                    (
                        await conn.execute(
                            text("SELECT count(*) FROM order_line WHERE bar_price_cents IS NULL")
                        )
                    ).scalar_one()
                )

    assert asyncio.run(scenario()) == 0
