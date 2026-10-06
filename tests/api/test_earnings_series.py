"""`GET /api/earnings/series` (Phase 5 T1: AC20, SD16, SD19).

The bucketing itself is pinned in `tests/integration/test_earnings_series.py`;
here the route: who may call it, the 409, and the response shape.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import T0, Login


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
