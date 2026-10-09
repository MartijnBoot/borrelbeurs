"""Deleting a run (Phase 7 T7: AC8; SD3; PD17; R7).

Two complete runs share a product; deleting one removes every row it owns, in
every table, and touches nothing of the other. A product no drink references
any more goes too.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.market_events import insert_event
from app.db.runs import (
    NameMismatch,
    RunLive,
    RunNotFound,
    add_drink,
    create_draft_run,
    delete_run,
    go_live,
)
from app.db.session import create_engine
from exchange import Params

T0 = 1_759_312_800_000
# Every table that holds a run's rows, keyed by run_id directly or through `order`.
PER_RUN = {
    "run": "SELECT row_to_json(t)::text FROM run t WHERE run_id = :r",
    "run_config_revision": "SELECT row_to_json(t)::text FROM run_config_revision t"
    " WHERE run_id = :r",
    "drink": "SELECT row_to_json(t)::text FROM drink t WHERE run_id = :r",
    "engine_state": "SELECT row_to_json(t)::text FROM engine_state t WHERE run_id = :r",
    "price_tick": "SELECT row_to_json(t)::text FROM price_tick t WHERE run_id = :r",
    "order": 'SELECT row_to_json(t)::text FROM "order" t WHERE run_id = :r',
    "order_line": "SELECT row_to_json(l)::text FROM order_line l"
    ' JOIN "order" o USING (order_id) WHERE o.run_id = :r',
    "news": "SELECT row_to_json(t)::text FROM news t WHERE run_id = :r",
    "market_event": "SELECT row_to_json(t)::text FROM market_event t WHERE run_id = :r",
    "export": "SELECT row_to_json(t)::text FROM export t WHERE run_id = :r",
}


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _complete_run(engine: AsyncEngine, name: str, drinks: tuple[str, ...]) -> int:
    """A run with drinks, revisions, state, ticks, orders, news, an event and an export; ended."""
    async with engine.begin() as conn:
        run_id = await create_draft_run(conn, name=name, params=Params(step_quant=0.1), run_seed=3)
        await conn.execute(
            text(
                "INSERT INTO run_config_revision (run_id, revision, config, author) "
                "VALUES (:r, 1, '{}', 'test')"
            ),
            {"r": run_id},
        )
        for slot, drink in enumerate(drinks):
            await add_drink(
                conn,
                run_id,
                name=drink,
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
    await go_live(engine, run_id, now_ms=T0)
    async with engine.begin() as conn:
        await _orders(conn, run_id, count=5)
        await conn.execute(
            text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, :t, 'info', 'x')"),
            {"r": run_id, "t": T0},
        )
        drink_ids: list[int] = list(
            (
                await conn.execute(
                    text("SELECT drink_id FROM drink WHERE run_id = :r"), {"r": run_id}
                )
            ).scalars()
        )
        await insert_event(
            conn, run_id=run_id, kind="crash", drink_ids=drink_ids, t_start_ms=T0, t_end_ms=T0 + 1
        )
        await conn.execute(
            text(
                "INSERT INTO export (run_id, kind, status, requested_by) "
                "VALUES (:r, 'final', 'queued', 'test')"
            ),
            {"r": run_id},
        )
        await conn.execute(
            text("UPDATE run SET status = 'ended', ended_at = now() WHERE run_id = :r"),
            {"r": run_id},
        )
    return run_id


async def _orders(conn: Any, run_id: int, *, count: int) -> None:
    """`count` orders of two lines each (one line for a one-drink run), in two statements."""
    await conn.execute(
        text(
            'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms) '
            "SELECT CAST(:r AS bigint), 'k-' || CAST(:r AS bigint) || '-' || g, g, "
            "CAST(:t AS bigint) + g FROM generate_series(1, :n) g"
        ),
        {"r": run_id, "n": count, "t": T0},
    )
    await conn.execute(
        text(
            "INSERT INTO order_line (order_id, drink_id, qty, unit_price_cents, "
            "line_total_cents, p_cont, bar_price_cents) "
            'SELECT o.order_id, d.drink_id, 1, 260, 260, 2.6, 260 FROM "order" o '
            "JOIN (SELECT drink_id FROM drink WHERE run_id = :r ORDER BY slot LIMIT 2) d "
            "ON true WHERE o.run_id = :r"
        ),
        {"r": run_id},
    )


async def _snapshot(engine: AsyncEngine, run_id: int) -> dict[str, list[str]]:
    async with engine.connect() as conn:
        return {
            table: sorted(str(row[0]) for row in await conn.execute(text(sql), {"r": run_id}))
            for table, sql in PER_RUN.items()
        }


async def _products(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        return sorted(str(n) for (n,) in await conn.execute(text("SELECT name FROM product")))


def test_deleting_a_run_removes_all_of_it_and_none_of_another(
    settings: Settings, database_url: str
) -> None:
    """AC8: every table's rows for the other run are byte-identical afterwards."""

    async def scenario() -> tuple[dict[str, list[str]], dict[str, list[str]], Any, list[str]]:
        engine = _engine(settings, database_url)
        try:
            keep = await _complete_run(engine, "Blijft", ("Bier", "Wijn"))
            gone = await _complete_run(engine, "Weg", ("Bier", "Jenever"))
            before = await _snapshot(engine, keep)
            assert [t for t, rows in before.items() if not rows] == [], "anti-vacuity"
            assert all((await _snapshot(engine, gone)).values())

            await delete_run(engine, gone, confirm_name="Weg")

            return (
                before,
                await _snapshot(engine, keep),
                await _snapshot(engine, gone),
                (await _products(engine)),
            )
        finally:
            await engine.dispose()

    before, after, deleted, products = asyncio.run(scenario())
    assert after == before
    assert all(rows == [] for rows in deleted.values()), deleted
    # PD17: the shared "Bier" stays; "Jenever", used only by the deleted run, is gone.
    assert products == ["Bier", "Wijn"]


def test_a_draft_without_orders_deletes(settings: Settings, database_url: str) -> None:
    async def scenario() -> list[tuple[Any, ...]]:
        engine = _engine(settings, database_url)
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(conn, name="Concept", params=Params(), run_seed=1)
            await delete_run(engine, run_id, confirm_name="Concept")
            async with engine.connect() as conn:
                return list(await conn.execute(text("SELECT run_id FROM run")))
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == []


@pytest.mark.parametrize(
    ("case", "error"),
    [("live", RunLive), ("mismatch", NameMismatch), ("unknown", RunNotFound)],
)
def test_a_refused_delete_removes_nothing(
    settings: Settings, database_url: str, case: str, error: type[Exception]
) -> None:
    async def scenario() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        engine = _engine(settings, database_url)
        try:
            run_id = await _complete_run(engine, "Vrijmibo", ("Bier",))
            if case == "live":
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE run SET status = 'live' WHERE run_id = :r"), {"r": run_id}
                    )
            before = await _snapshot(engine, run_id)
            target = 999_999 if case == "unknown" else run_id
            name = "Vrijmibo 2" if case == "mismatch" else "Vrijmibo"
            with pytest.raises(error):
                await delete_run(engine, target, confirm_name=name)
            return before, await _snapshot(engine, run_id)
        finally:
            await engine.dispose()

    before, after = asyncio.run(scenario())
    assert after == before


def test_a_thirty_thousand_order_run_deletes_within_the_live_timeout(
    settings: Settings, database_url: str
) -> None:
    """R7: the delete runs on the 5 s engine; a 30 000-order run must fit inside it."""
    bounded = settings.model_copy(update={"database_timeout_seconds": 5.0})

    async def scenario() -> tuple[float, int]:
        seeder = _engine(
            settings.model_copy(update={"database_timeout_seconds": 120.0}), database_url
        )
        engine = _engine(bounded, database_url)
        try:
            run_id = await _complete_run(seeder, "Groot", ("Bier", "Wijn"))
            async with seeder.begin() as conn:
                await conn.execute(text('DELETE FROM "order" WHERE run_id = :r'), {"r": run_id})
                await _orders(conn, run_id, count=30_000)
            async with seeder.begin() as conn:
                await conn.execute(text("ANALYZE"))
            started = time.monotonic()
            await delete_run(engine, run_id, confirm_name="Groot")
            elapsed = time.monotonic() - started
            async with engine.connect() as conn:
                left = int(
                    (await conn.execute(text("SELECT count(*) FROM order_line"))).scalar_one()
                )
            return elapsed, left
        finally:
            await engine.dispose()
            await seeder.dispose()

    elapsed, left = asyncio.run(scenario())
    print(f"delete of a 30 000-order run: {elapsed:.2f} s")
    assert left == 0
    assert elapsed < 5.0
