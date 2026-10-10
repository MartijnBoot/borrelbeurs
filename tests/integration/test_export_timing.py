"""An export does not stall the market (Phase 7 T11: AC21; SD6, R5, R16).

The app runs in-process on the **real clock** (`RealClock`), so its ticker
ticks every second for real, and orders go through `TestClient` from this
thread at 20 per second. First a baseline without an export, then the same load
while the worker builds a 20 000-line run's export, woken through
`app.state.export_wakeup` (T11 has no export route yet). The window measured is
the export's own `started_at` .. `finished_at`, which the database stamps on the
same machine clock as the ticks' `wall_ts_ms`.

The thresholds are the plan's and are not loosened here (T11's autonomy note):
the largest gap between `tick` stamps is at most 1.5 x the interval, and the p95
order latency at most 2 x the baseline's.

A tick's `wall_ts_ms` is its grid slot's stamp, not the moment it ran, so a
late tick still reads one interval after the last. The same 1.5 x bound is
therefore also held over `created_at`, the database's start of each tick's
transaction: the time the slot really ran.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.api.security import format_key, hash_secret, mint_secret
from app.core.config import Settings, get_settings
from app.db import models
from app.db.keys import create_key, set_secret_hash
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.main import create_app
from app.runtime.clock import RealClock
from exchange import Params

BASE_URL = "https://testserver"
RATE_HZ = 20
BASELINE_S = 4.0
LOAD_S = 7.0
LINES = 20_000
LINES_PER_ORDER = 4


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


async def _drink(conn: AsyncConnection, run_id: int, name: str, slot: int) -> int:
    return int(
        await add_drink(
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
    )


async def _seed(engine: AsyncEngine) -> tuple[int, int, str]:
    """`(live run, ended run of LINES lines, a bar key)`."""
    now = time.time_ns() // 1_000_000
    async with engine.begin() as conn:
        ended = await create_draft_run(
            conn, name="Vorige", params=Params(step_quant=0.1), run_seed=3
        )
        drinks = [await _drink(conn, ended, name, slot) for slot, name in enumerate("ABCD")]
        order_ids = (
            await conn.execute(
                insert(models.Order).returning(models.Order.order_id),
                [
                    {
                        "run_id": ended,
                        "idempotency_key": f"k-timing-{i}",
                        "version": i,
                        "wall_ts_ms": now - 3_600_000 + i * 100,
                    }
                    for i in range(LINES // LINES_PER_ORDER)
                ],
            )
        ).scalars()
        await conn.execute(
            insert(models.OrderLine),
            [
                {
                    "order_id": order_id,
                    "drink_id": drink_id,
                    "qty": 1,
                    "unit_price_cents": 250,
                    "line_total_cents": 250,
                    "p_cont": 2.5,
                    "bar_price_cents": 260,
                }
                for order_id in order_ids
                for drink_id in drinks
            ],
        )
        await conn.execute(
            update(models.Run).where(models.Run.run_id == ended).values(status="ended")
        )
        live = await create_draft_run(
            conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
        )
        for slot, name in enumerate(("Bier", "Wijn", "Fris")):
            await _drink(conn, live, name, slot)
        key_id = await create_key(conn, label="timing", role="bar", secret_hash="pending")
        secret = mint_secret()
        await set_secret_hash(conn, key_id, hash_secret(secret))
    await go_live(engine, live, now_ms=now)
    return live, ended, format_key(key_id, secret)


async def _queue_export(engine: AsyncEngine, run_id: int) -> int:
    async with engine.begin() as conn:
        return int(
            (
                await conn.execute(
                    insert(models.Export)
                    .values(run_id=run_id, kind="manual", status="queued", requested_by="t")
                    .returning(models.Export.export_id)
                )
            ).scalar_one()
        )


async def _measure(
    engine: AsyncEngine, export_id: int, live: int
) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    async with engine.connect() as conn:
        export = (
            (
                await conn.execute(
                    text(
                        "SELECT status, line_count, error,"
                        " (extract(epoch FROM started_at) * 1000)::bigint AS started_ms,"
                        " (extract(epoch FROM finished_at) * 1000)::bigint AS finished_ms"
                        " FROM export WHERE export_id = :e"
                    ),
                    {"e": export_id},
                )
            )
            .mappings()
            .one()
        )
        ticks = await conn.execute(
            text(
                "SELECT wall_ts_ms, (extract(epoch FROM created_at) * 1000)::bigint"
                " FROM price_tick WHERE run_id = :r AND source = 'tick' ORDER BY version"
            ),
            {"r": live},
        )
        return dict(export), [(int(row[0]), int(row[1])) for row in ticks]


def _load(client: TestClient, seconds: float, prefix: str) -> list[tuple[float, float, int]]:
    """Orders at RATE_HZ for `seconds`: `(sent wall s, latency s, status)` per POST."""
    samples: list[tuple[float, float, int]] = []
    start = time.monotonic()
    i = 0
    while (due := start + i / RATE_HZ) < start + seconds:
        if (wait := due - time.monotonic()) > 0:
            time.sleep(wait)
        state = client.get("/api/state").json()
        drink, price = next(iter(state["prices"].items()))
        body = {
            "quote_version": state["version"],
            "lines": [{"drink_id": int(drink), "qty": 1, "unit_price_cents": price["price_cents"]}],
        }
        sent, began = time.time(), time.perf_counter()
        response = client.post(
            "/api/orders", json=body, headers={"Idempotency-Key": f"k-{prefix}-{i:05d}"}
        )
        samples.append((sent, time.perf_counter() - began, response.status_code))
        i += 1
    return samples


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def test_an_export_keeps_the_tick_cadence_and_order_latency(on: str, settings: Settings) -> None:
    """AC21."""
    scoped = settings.model_copy(update={"database_url": on})

    def run(coro: Any) -> Any:
        async def scenario() -> Any:
            engine = create_engine(scoped)
            try:
                return await coro(engine)
            finally:
                await engine.dispose()

        return asyncio.run(scenario())

    live, ended, key = run(_seed)
    app = create_app(clock=RealClock(), run_migrations=False)
    with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
        assert client.post("/api/auth/login", json={"key": key}).status_code == 200
        interval_ms = app.state.tick_interval_ms
        baseline = _load(client, BASELINE_S, "base")
        export_id = run(lambda engine: _queue_export(engine, ended))
        client.portal.call(app.state.export_wakeup.set)  # type: ignore[union-attr]
        during = _load(client, LOAD_S, "export")
    export, ticks = run(lambda engine: _measure(engine, export_id, live))

    assert export["status"] == "done", export
    assert export["line_count"] == LINES
    started, finished = export["started_ms"], export["finished_ms"]
    assert finished / 1000 < during[-1][0], "the load ended before the export did"
    covering = [
        tick for tick in ticks if started - 2 * interval_ms <= tick[1] <= finished + 2 * interval_ms
    ]
    gaps = [b[0] - a[0] for a, b in itertools.pairwise(covering)]
    ran = [b[1] - a[1] for a, b in itertools.pairwise(covering)]
    in_window = [lat for sent, lat, _ in during if started / 1000 <= sent <= finished / 1000]
    base_p95, export_p95 = _p95([lat for _, lat, _ in baseline]), _p95(in_window)
    report = (
        f"build {finished - started} ms, max tick gap {max(gaps)} ms stamped,"
        f" {max(ran)} ms ran (interval {interval_ms}),"
        f" p95 {export_p95 * 1000:.1f} ms over {len(in_window)} orders"
        f" vs baseline {base_p95 * 1000:.1f} ms over {len(baseline)}"
    )
    print(report)
    assert len(gaps) >= 2, report
    assert max(gaps) <= 1.5 * interval_ms, report
    assert max(ran) <= 1.5 * interval_ms, report
    assert len(in_window) >= 10, report
    assert export_p95 <= 2 * base_p95, report
    accepted = [status for *_, status in baseline + during if status == 201]
    assert len(accepted) >= 0.9 * len(baseline + during), "orders were refused under load"
