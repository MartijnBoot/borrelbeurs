"""Heavy reads under volume (Phase 7 T15: AC31; SD11).

One ended run is bulk-seeded with `INSERT ... SELECT generate_series`: 30 000
orders of two lines each (60 000 lines) and 18 000 ticks, one a second for five
hours, with a `gap` tick in it. Then every heavy read runs against it:

- directly, `read_snapshot` + `build_workbook` -- the export's two halves;
- through the real routes (`create_app`, `TestClient`): the run list, the run
  detail, compare, the price curve, the run's earnings series, and an export
  requested and built by the worker's process.

A `before_cursor_execute` listener on `app.state.engine` -- the live path's --
counts every statement that touches `order_line` or `price_tick` during the
route calls: the routes must pick the heavy engine, so it counts zero.

The heavy timeout is left at its default (60 s). T15's autonomy note: a call
over 10 s, or a seed over a minute, is a stop -- the bounds below assert both,
and the timings are printed (`-s`) for the phase exit. The 10 s bound holds
for the reads and for `read_snapshot` + `build_workbook`, the export's work.
The export **through the worker** is not one call: it adds the build process's
start, storing the file and the polling, and on a loaded gate it measured
10.87 s with the build itself at 6.3 s. So it is held to the heavy timeout
instead (the user's choice, 2026-10-10).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.api.security import format_key, hash_secret, mint_secret
from app.core.config import Settings, get_settings
from app.db.exports import read_snapshot
from app.db.keys import create_key, set_secret_hash
from app.db.runs import add_drink, create_draft_run
from app.db.session import create_engine, create_heavy_read_engine
from app.jobs.export_xlsx import build_workbook
from app.main import create_app
from exchange import Params
from tests.support.clock import FakeClock

BASE_URL = "https://testserver"
T0 = 1_759_312_800_000
ORDERS: Final = 30_000
TICKS: Final = 18_000  # one a second for five hours
DRINKS: Final = ("Bier", "Wijn", "Fris", "Cola", "Tonic", "Radler")
CALL_LIMIT_S: Final = 10.0
# The export through the worker: the heavy-read timeout's default.
ROUND_TRIP_LIMIT_S: Final = 60.0
SEED_LIMIT_S: Final = 60.0


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


async def _seed(conn: AsyncConnection) -> tuple[int, int, str]:
    """`(run_id, a product_id, an admin key)`: the volume, in a handful of statements."""
    run_id = await create_draft_run(conn, name="Groot", params=Params(step_quant=0.1), run_seed=9)
    drink_ids = [
        int(
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
        for slot, name in enumerate(DRINKS)
    ]
    # `{drink_id: {"p_cont", "p_q"}}`, SD10's shape; the ids are ints, so inlining is safe.
    prices = ", ".join(f"'{d}', jsonb_build_object('p_cont', p, 'p_q', p)" for d in drink_ids)
    await conn.execute(
        text(
            "INSERT INTO price_tick (run_id, version, source, prices, wall_ts_ms)"
            " SELECT :r, g, CASE WHEN g = 7200 THEN 'gap' ELSE 'tick' END,"
            f" jsonb_build_object({prices}), CAST(:t0 AS bigint) + g * 1000"
            " FROM generate_series(0, :n - 1) g, LATERAL (SELECT 2.0 + (g % 200) / 100.0 AS p) x"
        ),
        {"r": run_id, "t0": T0, "n": TICKS},
    )
    await conn.execute(
        text(
            'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms)'
            " SELECT :r, 'k-heavy-' || g, g, CAST(:t0 AS bigint) + g * 600"
            " FROM generate_series(1, :n) g"
        ),
        {"r": run_id, "t0": T0, "n": ORDERS},
    )
    await conn.execute(
        text(
            "INSERT INTO order_line (order_id, drink_id, qty, unit_price_cents,"
            " line_total_cents, p_cont, bar_price_cents)"
            " SELECT o.order_id, (CAST(:d AS bigint[]))[1 + (o.order_id + k) % 6],"
            " q, u, q * u, u / 100.0, 250"
            ' FROM "order" o, generate_series(0, 1) k,'
            " LATERAL (SELECT 1 + (o.order_id % 3) AS q, 200 + (o.order_id % 50) AS u) v"
            " WHERE o.run_id = :r"
        ),
        {"r": run_id, "d": drink_ids},
    )
    await conn.execute(
        text(
            "UPDATE run SET status = 'ended', ended_at = to_timestamp(:end / 1000.0)"
            " WHERE run_id = :r"
        ),
        {"r": run_id, "end": T0 + TICKS * 1000},
    )
    product: int = (
        await conn.execute(
            text("SELECT product_id FROM drink WHERE drink_id = :d"), {"d": drink_ids[0]}
        )
    ).scalar_one()
    key_id = await create_key(conn, label="heavy", role="admin", secret_hash="pending")
    secret = mint_secret()
    await set_secret_hash(conn, key_id, hash_secret(secret))
    return run_id, int(product), format_key(key_id, secret)


def _timed(timings: dict[str, float], name: str, call: Any) -> Any:
    began = time.perf_counter()
    result = call()
    timings[name] = time.perf_counter() - began
    return result


def test_every_heavy_read_is_fast_enough_and_off_the_live_engine(
    on: str, settings: Settings
) -> None:
    """AC31."""
    scoped = settings.model_copy(update={"database_url": on})
    assert scoped.heavy_read_timeout_seconds == 60.0  # the default, not raised for the test
    timings: dict[str, float] = {}

    async def seed_and_build() -> tuple[int, int, str, int, int]:
        engine, heavy = create_engine(scoped), create_heavy_read_engine(scoped)
        try:
            began = time.perf_counter()
            async with engine.begin() as conn:
                run_id, product, key = await _seed(conn)
            timings["seed"] = time.perf_counter() - began
            async with heavy.connect() as conn:
                began = time.perf_counter()
                snapshot = await read_snapshot(conn, run_id)
                timings["read_snapshot"] = time.perf_counter() - began
            began = time.perf_counter()
            data = await asyncio.to_thread(build_workbook, snapshot, generated_at_ms=T0)
            timings["build_workbook"] = time.perf_counter() - began
            return run_id, product, key, snapshot.line_count, len(data)
        finally:
            await engine.dispose()
            await heavy.dispose()

    run_id, product, key, line_count, size = asyncio.run(seed_and_build())
    assert line_count == 2 * ORDERS

    live_statements: list[str] = []
    seen: list[str] = []
    app = create_app(clock=FakeClock(T0 + 10 * 3_600_000), run_migrations=False)
    with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
        assert client.post("/api/auth/login", json={"key": key}).status_code == 200
        live: AsyncEngine = app.state.engine

        def count(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
            seen.append(statement)
            lowered = statement.lower()
            if "order_line" in lowered or "price_tick" in lowered:
                live_statements.append(statement)

        event.listen(live.sync_engine, "before_cursor_execute", count)
        try:
            calls = {
                "run_list": "/api/analytics/runs",
                "run_detail": f"/api/analytics/runs/{run_id}",
                "compare": f"/api/analytics/compare?a={run_id}&b={run_id}",
                "price_curve": (
                    f"/api/analytics/price-curve?product_id={product}&a={run_id}&b={run_id}"
                    "&bucket_s=60"
                ),
                "earnings_series": f"/api/earnings/series?run_id={run_id}&bucket_s=60",
            }
            responses = {
                name: _timed(timings, name, lambda path=path: client.get(path))
                for name, path in calls.items()
            }
            export_id = client.post(f"/api/runs/{run_id}/exports").json()["export_id"]
            began = time.perf_counter()
            while (status := client.get(f"/api/exports/{export_id}").json())["status"] not in {
                "done",
                "failed",
            }:
                assert time.perf_counter() - began < ROUND_TRIP_LIMIT_S, status
                time.sleep(0.1)
            timings["export_via_worker"] = time.perf_counter() - began
        finally:
            event.remove(live.sync_engine, "before_cursor_execute", count)

    report = ", ".join(f"{name} {seconds:.2f} s" for name, seconds in timings.items())
    print(f"\nT15 timings: {report}; workbook {size} bytes, {line_count} lines")

    assert all(r.status_code == 200 for r in responses.values()), {
        name: r.text[:200] for name, r in responses.items() if r.status_code != 200
    }
    detail = responses["run_detail"].json()
    assert detail["qty"] == sum(p["qty"] for p in detail["per_product"])
    assert len(responses["price_curve"].json()["a"]) <= TICKS // 60
    assert None in [p["price_cents"] for p in responses["price_curve"].json()["a"]]  # the gap
    assert (status["status"], status["line_count"]) == ("done", 2 * ORDERS), status
    assert any("auth_key" in s for s in seen)  # the listener does fire: the session lookups
    assert live_statements == [], live_statements
    assert timings["seed"] < SEED_LIMIT_S, report
    assert timings["read_snapshot"] + timings["build_workbook"] < CALL_LIMIT_S, report
    assert timings["export_via_worker"] < ROUND_TRIP_LIMIT_S, report
    bounded_above = {"seed", "read_snapshot", "build_workbook", "export_via_worker"}
    slow = {
        name: s for name, s in timings.items() if name not in bounded_above and s > CALL_LIMIT_S
    }
    assert not slow, report
