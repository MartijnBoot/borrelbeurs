"""Wallets survive a restart as committed (B-05 T11: SD23; AC45).

A first app signs up two wallets, tops them up and reverses one top-up; it stops
(the lifespan exits) mid-sequence. A fresh `create_app` on the same database
moves a balance and reads everything back. Every wallet, entry and setting is as
last committed, and every balance equals the SQL sum of its entries.

This test changes no source: one failing means the code does not do what SD23 says.
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
from app.db.session import create_engine
from app.db.wallets import WalletSettingsRow
from app.main import create_app
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
BASE_URL = "https://testserver"
CODE = "Borrel2026"


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


def _app() -> TestClient:
    return TestClient(
        create_app(clock=FakeClock(T0), run_migrations=False),
        base_url=BASE_URL,
        headers={"origin": BASE_URL},
    )


def _sign_up(client: TestClient, name: str) -> str:
    """A wallet named `name`; its cookie value. The client keeps no wallet cookie."""
    response = client.post("/api/wallet", json={"name": name, "code": CODE})
    assert response.status_code == 201, response.text
    cookie = str(client.cookies["bb_wallet"])
    client.cookies.delete("bb_wallet")
    return cookie


def _lookup(client: TestClient, cookie: str) -> dict[str, Any]:
    client.cookies.set("bb_wallet", cookie)
    try:
        page = client.get("/api/wallet")
    finally:
        client.cookies.delete("bb_wallet")
    assert page.status_code == 200, page.text
    found = client.post("/api/kassa/lookup", json={"qr_token": page.json()["qr_token"]})
    assert found.status_code == 200, found.text
    body: dict[str, Any] = found.json()
    return body


def _post(client: TestClient, path: str, key: str, body: dict[str, Any] | None = None) -> Any:
    response = client.post(path, json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 201, response.text
    return response.json()


async def _committed(engine: AsyncEngine) -> dict[str, list[tuple[Any, ...]]]:
    async with engine.connect() as conn:
        return {
            table: [tuple(row) for row in await conn.execute(text(sql))]
            for table, sql in {
                "wallet": "SELECT * FROM wallet ORDER BY wallet_id",
                "wallet_entry": "SELECT * FROM wallet_entry ORDER BY entry_id",
                "wallet_settings": (
                    "SELECT signup_code, unfunded_days, inactive_months FROM wallet_settings"
                ),
            }.items()
        }


async def _sums(engine: AsyncEngine) -> dict[int, int]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT w.wallet_id, coalesce(sum(e.amount_cents), 0) FROM wallet w"
                " LEFT JOIN wallet_entry e USING (wallet_id) GROUP BY w.wallet_id"
            )
        )
        return {int(row[0]): int(row[1]) for row in rows}


def test_wallets_entries_and_settings_survive_a_restart(settings: Settings, on: str) -> None:
    """AC45."""

    async def seed(engine: AsyncEngine) -> str:
        async with engine.begin() as conn:
            await wallets.put_settings(conn, WalletSettingsRow(CODE, 45, 6))
        return await _key(engine, "kassa", "Kassa 1")

    key = _run(settings, on, seed)

    with _app() as first:
        jan, piet = _sign_up(first, "Jan"), _sign_up(first, "Piet")
        assert first.post("/api/auth/login", json={"key": key}).status_code == 200
        jan_id = _lookup(first, jan)["wallet_id"]
        piet_id = _lookup(first, piet)["wallet_id"]
        _post(first, f"/api/kassa/wallets/{jan_id}/topups", "k-r-0001", {"amount_cents": 2000})
        doubled = _post(
            first, f"/api/kassa/wallets/{jan_id}/topups", "k-r-0002", {"amount_cents": 1500}
        )
        _post(first, f"/api/kassa/topups/{doubled['entry_id']}/reversal", "k-r-0003")
        _post(first, f"/api/kassa/wallets/{piet_id}/topups", "k-r-0004", {"amount_cents": 1000})
    stopped = _run(settings, on, _committed)

    with _app() as second:
        assert _run(settings, on, _committed) == stopped
        assert second.post("/api/auth/login", json={"key": key}).status_code == 200
        assert _lookup(second, jan)["balance_cents"] == 2000
        assert _lookup(second, piet)["balance_cents"] == 1000
        _post(second, f"/api/kassa/wallets/{piet_id}/move", "k-r-0005", {"from_wallet_id": jan_id})
        moved = _lookup(second, piet)
        second.cookies.set("bb_wallet", jan)
        assert second.get("/api/wallet").status_code == 401
    after = _run(settings, on, _committed)

    with _app() as third:
        assert third.post("/api/auth/login", json={"key": key}).status_code == 200
        assert _lookup(third, piet) == moved
    assert _run(settings, on, _committed) == after
    assert (moved["name"], moved["balance_cents"]) == ("Jan", 3000)
    assert after["wallet_settings"] == stopped["wallet_settings"] == [(CODE, 45, 6)]
    sums = _run(settings, on, _sums)
    assert sums == {jan_id: 0, piet_id: 3000}
