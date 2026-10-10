"""`GET /api/earnings/series` (Phase 5 T1: AC20, SD16, SD19; Phase 7 T9: AC16, SD9, PD15).

The bucketing itself is pinned in `tests/integration/test_earnings_series.py`;
here the route: who may call it, the 409, the response shape, and Phase 7's
`run_id` and `bucket_s`. The bar's 403 for another run is in the matrix file.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db import models
from app.db.runs import add_drink, create_draft_run
from app.db.session import create_engine
from exchange import Params
from tests.api.conftest import T0, Login

MINUTE = 60_000


def _order(client: TestClient, key: str) -> int:
    """Place a one-line order at the live price; its total."""
    state = client.get("/api/state").json()
    drink, price = next(iter(state["prices"].items()))
    response = client.post(
        "/api/orders",
        json={
            "quote_version": state["version"],
            "lines": [{"drink_id": int(drink), "qty": 2, "unit_price_cents": price["price_cents"]}],
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    total: int = response.json()["total_cents"]
    return total


def test_bar_gets_the_cumulative_series(live_client: TestClient, login: Login) -> None:
    bar = login("bar")
    first = _order(bar, "k-series-0001")
    second = _order(bar, "k-series-0002")

    response = bar.get("/api/earnings/series")

    assert response.status_code == 200
    bucket_end = (T0 // 60_000) * 60_000 + 60_000
    assert response.json() == [{"t_ms": bucket_end, "cum_revenue_cents": first + second}]


def test_admin_may_read_the_series(live_client: TestClient, login: Login) -> None:
    response = login("admin").get("/api/earnings/series")

    assert response.status_code == 200
    assert response.json() == []


def test_display_may_not_read_the_series(live_client: TestClient, login: Login) -> None:
    response = login("display").get("/api/earnings/series")

    assert response.status_code == 403


def test_the_series_needs_a_session(live_client: TestClient) -> None:
    assert live_client.get("/api/earnings/series").status_code == 401


def test_with_no_live_run_the_series_is_409(login: Login) -> None:
    response = login("bar").get("/api/earnings/series")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_live_run"


def seed_run(settings: Settings, url: str, *, status: str, orders: list[tuple[int, int]]) -> int:
    """A run of one drink in `status`, holding `(wall_ts_ms, line_total_cents)` orders."""

    async def scenario() -> int:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(
                    conn, name="Vorige", params=Params(step_quant=0.1), run_seed=3
                )
                drink_id = await add_drink(
                    conn,
                    run_id,
                    name="Bier",
                    slot=0,
                    p_min_cents=100,
                    p0_cents=200,
                    p_max_cents=500,
                    a=1.0,
                    d=0.1,
                    s0=1.0,
                    c=0.1,
                    bar_price_cents=200,
                )
                await _insert_orders(conn, run_id, int(drink_id), orders)
                await conn.execute(
                    update(models.Run).where(models.Run.run_id == run_id).values(status=status)
                )
            return run_id
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _insert_orders(
    conn: AsyncConnection, run_id: int, drink_id: int, orders: list[tuple[int, int]]
) -> None:
    for i, (ts, total) in enumerate(orders):
        order_id = (
            await conn.execute(
                insert(models.Order).returning(models.Order.order_id),
                {
                    "run_id": run_id,
                    "idempotency_key": f"k-seed-{run_id}-{i:04d}",
                    "version": i,
                    "wall_ts_ms": ts,
                },
            )
        ).scalar_one()
        await conn.execute(
            insert(models.OrderLine),
            {
                "order_id": order_id,
                "drink_id": drink_id,
                "qty": 1,
                "unit_price_cents": total,
                "line_total_cents": total,
                "p_cont": total / 100,
            },
        )


class _CountingEngine:
    """Stands in for `app.state.heavy_engine`, counting the connections taken from it."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.connects = 0

    def connect(self) -> Any:
        self.connects += 1
        return self.engine.connect()


def _spy_heavy(client: TestClient) -> _CountingEngine:
    state = client.app.state  # type: ignore[attr-defined]
    spy = _CountingEngine(state.heavy_engine)
    state.heavy_engine = spy
    return spy


def test_admin_reads_an_ended_run_on_the_heavy_engine_at_a_bucket_size(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """SD9, PD15: another run's series, 5-minute buckets, read on the heavy engine."""
    start = (T0 // (5 * MINUTE)) * (5 * MINUTE)
    ended = seed_run(
        settings,
        api_env,
        status="ended",
        orders=[(start, 200), (start + MINUTE, 300), (start + 5 * MINUTE, 400)],
    )
    admin = login("admin")
    spy = _spy_heavy(live_client)

    response = admin.get("/api/earnings/series", params={"run_id": ended, "bucket_s": 300})

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"t_ms": start + 5 * MINUTE, "cum_revenue_cents": 500},
        {"t_ms": start + 10 * MINUTE, "cum_revenue_cents": 900},
    ]
    assert spy.connects == 1


def test_the_live_run_by_id_reads_on_the_main_engine(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    """PD15: naming the live run is the no-parameter call; the bar may make it."""
    bar = login("bar")
    total = _order(bar, "k-series-0003")
    spy = _spy_heavy(live_client)

    response = bar.get("/api/earnings/series", params={"run_id": live_run, "bucket_s": 900})

    assert response.status_code == 200, response.text
    assert [point["cum_revenue_cents"] for point in response.json()] == [total]
    assert response.json()[0]["t_ms"] % (15 * MINUTE) == 0
    assert spy.connects == 0


def test_a_draft_run_is_an_empty_series(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC16: a run with no orders is `[]`, not an error."""
    draft = seed_run(settings, api_env, status="draft", orders=[])

    response = login("admin").get("/api/earnings/series", params={"run_id": draft})

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_another_run_needs_no_live_run(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """With no live run, an explicit `run_id` still answers; only the default is 409."""
    ended = seed_run(settings, api_env, status="ended", orders=[(T0, 250)])

    response = login("admin").get("/api/earnings/series", params={"run_id": ended})

    assert response.status_code == 200, response.text
    assert [point["cum_revenue_cents"] for point in response.json()] == [250]


def test_an_unknown_run_is_404(live_client: TestClient, login: Login) -> None:
    """AC16."""
    response = login("admin").get("/api/earnings/series", params={"run_id": 999_999})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


def test_a_bucket_size_outside_the_three_is_422(live_client: TestClient, login: Login) -> None:
    """AC16: `bucket_s` is one of 60, 300, 900."""
    admin = login("admin")

    for bad in ("120", "0", "minute"):
        response = admin.get("/api/earnings/series", params={"bucket_s": bad})
        assert response.status_code == 422, (bad, response.text)
        assert response.json()["error"]["code"] == "invalid_request"
