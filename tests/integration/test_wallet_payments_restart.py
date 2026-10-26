"""Wallet payments survive a restart as committed (B-06 T18: SD14; AC34).

A first app books paid and unpaid orders and refunds one payment, then stops
(the lifespan exits). A fresh `create_app` on the same database finds every
order with its payment or none, exactly as committed; a paid order resent under
its key replays byte for byte and writes nothing; a new paid order books. Every
balance equals the SQL sum of its entries.

This test changes no source: one failing means the code does not do what SD14 says.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.security import format_key, hash_secret, mint_secret
from app.core.config import Settings, get_settings
from app.db import wallets
from app.db.keys import Role, create_key, set_secret_hash
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.main import create_app
from exchange import Params
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
BASE_URL = "https://testserver"


def _run(settings: Settings, url: str, body: Any) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """The app's settings on the scratch database, as `tests/api/conftest.py` does."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


async def _key(engine: AsyncEngine, role: Role, label: str) -> str:
    async with engine.begin() as conn:
        key_id = await create_key(conn, label=label, role=role, secret_hash="pending")
        secret = mint_secret()
        await set_secret_hash(conn, key_id, hash_secret(secret))
    return format_key(key_id, secret)


async def _seed(engine: AsyncEngine) -> tuple[dict[str, str], int, str]:
    """A live run of two drinks, a bar and a kassa key, and one wallet: its id and token."""
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
        )
        for slot, name in enumerate(("Bier", "Wijn")):
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
        jan = await wallets.create_wallet(conn, name="Jan", cookie_hash="h-jan", now_ms=T0)
    await go_live(engine, run_id, now_ms=T0)
    keys = {
        "bar": await _key(engine, "bar", "Bar 1"),
        "kassa": await _key(engine, "kassa", "Kassa 1"),
    }
    return keys, jan.wallet_id, jan.qr_token


def _app() -> TestClient:
    return TestClient(
        create_app(clock=FakeClock(T0), run_migrations=False),
        base_url=BASE_URL,
        headers={"origin": BASE_URL},
    )


def _login(client: TestClient, key: str) -> None:
    assert client.post("/api/auth/login", json={"key": key}).status_code == 200


def _body(client: TestClient, token: str | None) -> dict[str, Any]:
    """An order of one of each drink at the live prices, paid by `token` or by none."""
    state = client.get("/api/state").json()
    body: dict[str, Any] = {
        "quote_version": state["version"],
        "lines": [
            {"drink_id": int(drink), "qty": 1, "unit_price_cents": price["price_cents"]}
            for drink, price in sorted(state["prices"].items(), key=lambda item: int(item[0]))
        ],
    }
    if token is not None:
        body["wallet"] = {"qr_token": token}
    return body


def _order(client: TestClient, key: str, body: dict[str, Any], status: int = 201) -> Any:
    response = client.post("/api/orders", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == status, response.text
    return response


async def _committed(engine: AsyncEngine) -> dict[str, list[tuple[Any, ...]]]:
    async with engine.connect() as conn:
        return {
            table: [tuple(row) for row in await conn.execute(text(sql))]
            for table, sql in {
                "order": 'SELECT * FROM "order" ORDER BY order_id',
                "order_line": "SELECT * FROM order_line ORDER BY order_id, drink_id",
                "wallet": "SELECT * FROM wallet ORDER BY wallet_id",
                "wallet_entry": "SELECT * FROM wallet_entry ORDER BY entry_id",
            }.items()
        }


async def _payments(engine: AsyncEngine) -> dict[str, list[int]]:
    """Each order's key and the amounts of the payments naming it."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                'SELECT o.idempotency_key, e.amount_cents FROM "order" o'
                " LEFT JOIN wallet_entry e ON e.order_id = o.order_id AND e.kind = 'payment'"
                " ORDER BY o.order_id"
            )
        )
        found: dict[str, list[int]] = {}
        for row in rows:
            key, amount = row[0], row[1]
            found.setdefault(str(key), [])
            if amount is not None:
                found[str(key)].append(int(amount))
        return found


async def _balances(engine: AsyncEngine) -> list[tuple[int, int]]:
    """Each wallet's balance as the app reads it, and its entries' SQL sum."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT w.wallet_id, coalesce(sum(e.amount_cents), 0) FROM wallet w"
                " LEFT JOIN wallet_entry e USING (wallet_id) GROUP BY w.wallet_id"
            )
        )
        return [(await wallets.balance(conn, int(row[0])), int(row[1])) for row in rows.all()]


def test_paid_and_unpaid_orders_survive_a_restart_with_their_payments(
    settings: Settings, on: str
) -> None:
    """AC34."""
    keys, wallet_id, token = _run(settings, on, _seed)

    with _app() as first:
        _login(first, keys["kassa"])
        topped = first.post(
            f"/api/kassa/wallets/{wallet_id}/topups",
            json={"amount_cents": 5000},
            headers={"Idempotency-Key": "k-pr-topup-1"},
        )
        assert topped.status_code == 201, topped.text
        _login(first, keys["bar"])
        one = _order(first, "k-pr-order-1", _body(first, token)).json()
        two = _order(first, "k-pr-order-2", _body(first, None)).json()
        three_body = _body(first, token)
        three = _order(first, "k-pr-order-3", three_body)
        _login(first, keys["kassa"])
        listed = first.get(f"/api/kassa/wallets/{wallet_id}/payments").json()
        refunded_entry = next(
            p["entry_id"] for p in listed if p["amount_cents"] == one["total_cents"]
        )
        refunded = first.post(
            f"/api/payments/{refunded_entry}/refund", headers={"Idempotency-Key": "k-pr-refund-1"}
        )
        assert refunded.status_code == 201, refunded.text
    stopped = _run(settings, on, _committed)

    with _app() as second:
        assert _run(settings, on, _committed) == stopped
        _login(second, keys["bar"])
        replay = _order(second, "k-pr-order-3", three_body, status=200)
        assert replay.content == three.content
        assert _run(settings, on, _committed) == stopped
        four = _order(second, "k-pr-order-4", _body(second, token)).json()

    payments = _run(settings, on, _payments)
    assert payments == {
        "k-pr-order-1": [-one["total_cents"]],
        "k-pr-order-2": [],
        "k-pr-order-3": [-three.json()["total_cents"]],
        "k-pr-order-4": [-four["total_cents"]],
    }
    assert two["wallet"] is None
    assert four["wallet"]["balance_after_cents"] == (
        5000 - three.json()["total_cents"] - four["total_cents"]
    )
    balances = _run(settings, on, _balances)
    assert balances == [(four["wallet"]["balance_after_cents"],) * 2]
