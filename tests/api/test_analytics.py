"""`GET /api/analytics/runs` and `/runs/{run_id}` (Phase 7 T13: AC26, AC27, AC30, AC31; SD12).

The totals themselves are pinned in `tests/integration/test_analytics_runs.py`;
here the routes: the response shape, the 404, and that both read on the heavy
engine (AC31). Bar and display get 403 in the authorization matrix.

B-06 T18 (AC36): paying an order from a wallet, and refunding it, changes no
analytics response.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.runtime.wallet_codes import cookie_hash
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


def _order(client: TestClient, key: str, wallet: dict[str, str] | None = None) -> int:
    state = client.get("/api/state").json()
    drink, price = next(iter(state["prices"].items()))
    body: dict[str, Any] = {
        "quote_version": state["version"],
        "lines": [{"drink_id": int(drink), "qty": 2, "unit_price_cents": price["price_cents"]}],
    }
    if wallet is not None:
        body["wallet"] = wallet
    response = client.post("/api/orders", json=body, headers={"Idempotency-Key": key})
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
    assert row["removed"] is False
    assert spy.connects == 1


def test_payments_and_refunds_change_no_analytics_response(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """B-06 AC36: the run list and the run detail are byte-identical before and after
    the run's orders are paid from a wallet and refunded."""

    async def make_wallet() -> str:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            async with engine.begin() as conn:
                jan = await wallets.create_wallet(
                    conn, name="Jan", cookie_hash=cookie_hash("cookie-jan"), now_ms=0
                )
                await wallets.insert_entry(
                    conn, wallet_id=jan.wallet_id, kind="topup", amount_cents=10_000, now_ms=0
                )
                return jan.qr_token
        finally:
            await engine.dispose()

    admin = login("admin")
    token = asyncio.run(make_wallet())
    _order(admin, "k-analytics-paid-1", {"qr_token": token})
    _order(admin, "k-analytics-paid-2", {"qr_token": token})
    _order(admin, "k-analytics-unpaid")

    def responses() -> tuple[bytes, bytes]:
        listed = admin.get("/api/analytics/runs")
        detail = admin.get(f"/api/analytics/runs/{live_run}")
        assert (listed.status_code, detail.status_code) == (200, 200)
        return listed.content, detail.content

    before = responses()

    async def payments() -> list[int]:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT entry_id FROM wallet_entry WHERE kind = 'payment'")
                )
                return [int(row[0]) for row in rows]
        finally:
            await engine.dispose()

    paid = asyncio.run(payments())
    assert len(paid) == 2, "anti-vacuity"
    for n, entry_id in enumerate(paid):
        refunded = admin.post(
            f"/api/payments/{entry_id}/refund", headers={"Idempotency-Key": f"k-analytics-ref-{n}"}
        )
        assert refunded.status_code == 201, refunded.text

    assert responses() == before


def test_with_no_runs_the_list_is_empty(client: TestClient, login: Login) -> None:
    """AC30: an empty state, not an error."""
    response = login("admin").get("/api/analytics/runs")

    assert response.status_code == 200
    assert response.json() == []


def test_an_unknown_run_is_404(live_client: TestClient, login: Login) -> None:
    response = login("admin").get("/api/analytics/runs/999999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"
