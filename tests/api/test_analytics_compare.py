"""`GET /api/analytics/compare` and `/price-curve` (Phase 7 T14: AC28-AC30; SD12; PD13, PD14).

The joining and bucketing are pinned in `tests/integration/test_analytics_compare.py`;
here the routes: the response shape, the 404 naming its side, `bucket_s`'s
422, and the heavy engine. Bar and display get 403 in the authorization matrix.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import Login


class _CountingEngine:
    """Stands in for `app.state.heavy_engine`, counting the connections taken from it."""

    def __init__(self, engine: Any) -> None:
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


def _first_product(settings: Settings, url: str, run_id: int) -> tuple[int, int]:
    """The run's slot-0 drink and its product."""

    async def scenario() -> tuple[int, int]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT drink_id, product_id FROM drink WHERE run_id = :r AND slot = 0"
                        ),
                        {"r": run_id},
                    )
                ).one()
            return int(row[0]), int(row[1])
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _order(client: TestClient, drink_id: int) -> int:
    state = client.get("/api/state").json()
    price = state["prices"][str(drink_id)]["price_cents"]
    response = client.post(
        "/api/orders",
        json={
            "quote_version": state["version"],
            "lines": [{"drink_id": drink_id, "qty": 2, "unit_price_cents": price}],
        },
        headers={"Idempotency-Key": "k-compare-0001"},
    )
    assert response.status_code == 201, response.text
    total: int = response.json()["total_cents"]
    return total


def test_comparing_a_run_with_itself_on_the_heavy_engine(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC28's shape: one row per product, both sides filled."""
    admin = login("admin")
    drink_id, product_id = _first_product(settings, api_env, live_run)
    total = _order(admin, drink_id)
    spy = _spy_heavy(live_client)

    response = admin.get("/api/analytics/compare", params={"a": live_run, "b": live_run})

    assert response.status_code == 200, response.text
    side = {"qty": 2, "revenue_cents": total, "bar_price_total_cents": 520}
    assert response.json() == [
        {
            "product_key": f"product:{product_id}",
            "product_id": product_id,
            "name": "Bier",
            "a": side,
            "b": side,
        }
    ]
    assert spy.connects == 1


def test_the_price_curve_on_the_heavy_engine(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """PD13's shape: `{a, b}` of `{minute, price_cents}`, the live run's first tick at minute 0."""
    _, product_id = _first_product(settings, api_env, live_run)
    admin = login("admin")
    spy = _spy_heavy(live_client)

    response = admin.get(
        "/api/analytics/price-curve",
        params={"product_id": product_id, "a": live_run, "b": live_run, "bucket_s": 300},
    )

    assert response.status_code == 200, response.text
    curve = response.json()
    assert curve["a"] == curve["b"]
    assert curve["a"][0]["minute"] == 0
    assert isinstance(curve["a"][0]["price_cents"], int)
    assert spy.connects == 1


def test_a_product_absent_from_both_runs_is_two_empty_curves(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    """AC30."""
    response = login("admin").get(
        "/api/analytics/price-curve",
        params={"product_id": 999_999, "a": live_run, "b": live_run},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"a": [], "b": []}


def test_an_unknown_run_is_404_naming_its_side(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    admin = login("admin")

    compared = admin.get("/api/analytics/compare", params={"a": live_run, "b": 999_999})
    curve = admin.get(
        "/api/analytics/price-curve", params={"product_id": 1, "a": 999_999, "b": live_run}
    )

    assert compared.status_code == curve.status_code == 404
    assert (compared.json()["error"]["code"], compared.json()["error"]["side"]) == (
        "run_not_found",
        "b",
    )
    assert (curve.json()["error"]["code"], curve.json()["error"]["side"]) == ("run_not_found", "a")


def test_a_bucket_size_outside_the_three_is_422(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    response = login("admin").get(
        "/api/analytics/price-curve",
        params={"product_id": 1, "a": live_run, "b": live_run, "bucket_s": 120},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
