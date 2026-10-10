"""`GET /api/analytics/runs` and `/runs/{run_id}` (Phase 7 T13: AC26, AC27, AC30, AC31; SD12).

The totals themselves are pinned in `tests/integration/test_analytics_runs.py`;
here the routes: the response shape, the 404, and that both read on the heavy
engine (AC31). Bar and display get 403 in the authorization matrix.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

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


def _order(client: TestClient, key: str) -> int:
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


def test_the_run_list_on_the_heavy_engine(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    """AC26, AC31: the live run with its sale; no duration while live (PD12)."""
    admin = login("admin")
    total = _order(admin, "k-analytics-0001")
    spy = _spy_heavy(live_client)

    response = admin.get("/api/analytics/runs")

    assert response.status_code == 200, response.text
    (run,) = response.json()
    assert run["run_id"] == live_run
    assert (run["name"], run["status"], run["duration_ms"], run["ended_at_ms"]) == (
        "Borrel",
        "live",
        None,
        None,
    )
    assert isinstance(run["t0_ms"], int)
    assert (run["qty"], run["revenue_cents"]) == (2, total)
    assert run["bar_price_total_cents"] == 2 * 260
    assert spy.connects == 1


def test_the_run_detail_on_the_heavy_engine(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    """AC27, AC31: the run's totals and one row per product that sold."""
    admin = login("admin")
    total = _order(admin, "k-analytics-0002")
    spy = _spy_heavy(live_client)

    response = admin.get(f"/api/analytics/runs/{live_run}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert (detail["run_id"], detail["revenue_cents"], detail["qty"]) == (live_run, total, 2)
    (row,) = detail["per_product"]
    assert row["product_key"] == f"product:{row['product_id']}"
    assert (row["qty"], row["revenue_cents"], row["bar_price_total_cents"]) == (2, total, 520)
    assert row["avg_price_cents"] == total // 2
    assert spy.connects == 1


def test_with_no_runs_the_list_is_empty(client: TestClient, login: Login) -> None:
    """AC30: an empty state, not an error."""
    response = login("admin").get("/api/analytics/runs")

    assert response.status_code == 200
    assert response.json() == []


def test_an_unknown_run_is_404(live_client: TestClient, login: Login) -> None:
    response = login("admin").get("/api/analytics/runs/999999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"
