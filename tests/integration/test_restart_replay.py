"""Same-key replay across a real restart (Phase 5 T17: the server half of AC26; SD13).

The production entrypoint, `python -m app.main`, as a subprocess on the scratch
database, over stdlib `urllib` (`tests/integration/realapp/harness.py`). An order
is acknowledged with key K, the app is killed and restarted on the same
database, and the same key and body are posted again: the answer is a 200 whose
body is byte-identical to the first receipt, and the database holds one order.
The bar's retries after a restart (SD13) rest on exactly this.

Responses are read here as raw bytes -- the harness `Client` parses JSON, which
would hide a byte-level difference.

B-06 T5 (AC34, SD16): a wallet order replays the same way after a restart, its
`wallet.balance_after_cents` included, and the ledger still holds one payment.
"""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import wallets
from tests.integration.realapp.harness import Client, mint_key, seed_live_run, start_app

KEY = "k-restart-replay-0001"
PAID_KEY = "k-restart-paid-0001"


class RawClient:
    """A logged-in browser stand-in whose order answers stay bytes."""

    def __init__(self, base: str, key: str) -> None:
        self.base = base
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        status, _ = self.post("/api/auth/login", {"key": key})
        assert status == 200

    def post(
        self, path: str, body: Any, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Origin": self.base, "Content-Type": "application/json", **(headers or {})},
        )
        try:
            with self._opener.open(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def order(self, key: str, body: dict[str, Any]) -> tuple[int, bytes]:
        return self.post("/api/orders", body, headers={"Idempotency-Key": key})


def _count(url: str, key: str) -> int:
    async def query() -> int:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text('SELECT count(*) FROM "order" WHERE idempotency_key = :key'),
                    {"key": key},
                )
                return int(result.scalar_one())
        finally:
            await engine.dispose()

    return asyncio.run(query())


def _acknowledged(
    client: RawClient,
    state: dict[str, Any],
    key: str = KEY,
    wallet: dict[str, str] | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Order one of drink one under `key`; on a 409, again with the version and price it returns.

    A 409 commits nothing and stores no key, so the same key is retried with the
    new quote; the body that is finally acknowledged is the one to replay.
    """
    drink = int(next(iter(state["prices"])))
    price = state["prices"][str(drink)]["price_cents"]
    quote = 0
    for _ in range(5):
        body: dict[str, Any] = {
            "quote_version": quote,
            "lines": [{"drink_id": drink, "qty": 1, "unit_price_cents": price}],
        }
        if wallet is not None:
            body["wallet"] = wallet
        status, raw = client.order(key, body)
        if status == 201:
            return body, raw
        assert status == 409, (status, raw)
        error = json.loads(raw)["error"]
        quote = error["version"]
        price = next(p["price_cents"] for p in error["prices"] if p["drink_id"] == drink)
    raise AssertionError("no order was acknowledged in five attempts")


def test_a_same_key_retry_after_a_restart_replays_the_receipt_byte_for_byte(
    database_url: str, tmp_path: Path
) -> None:
    seed_live_run(database_url)
    key = mint_key(database_url, "bar")
    stderr = tmp_path / "app.stderr"

    app = start_app(database_url, stderr)
    try:
        state = Client(app.base)
        state.login(key)
        body, first = _acknowledged(RawClient(app.base, key), state.state())
    finally:
        app.kill()

    app = start_app(database_url, stderr)
    try:
        client = RawClient(app.base, key)
        status, replay = client.order(KEY, body)
        assert status == 200, replay
        assert replay == first

        viewer = Client(app.base)
        viewer.login(key)
        earnings = viewer.state()["earnings"]
        assert sum(e["qty"] for e in earnings.values()) == 1
        assert _count(database_url, KEY) == 1

        reused = {**body, "lines": [{**body["lines"][0], "qty": 2}]}
        status, raw = client.order(KEY, reused)
        assert status == 422, raw
        assert json.loads(raw)["error"]["code"] == "idempotency_key_reused"
    finally:
        app.kill()


def _now_ms() -> int:
    """The app sweeps unfunded wallets at boot on the wall clock: a wallet dated 1970 is gone."""
    return int(time.time() * 1000)


def _wallet(url: str) -> wallets.WalletRow:
    async def create() -> wallets.WalletRow:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as conn:
                return await wallets.create_wallet(
                    conn, name="Jan", cookie_hash="h-jan", now_ms=_now_ms()
                )
        finally:
            await engine.dispose()

    return asyncio.run(create())


def _payments(url: str) -> list[tuple[Any, ...]]:
    async def query() -> list[tuple[Any, ...]]:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT wallet_id, amount_cents FROM wallet_entry WHERE kind = 'payment'")
                )
                return [tuple(row) for row in result]
        finally:
            await engine.dispose()

    return asyncio.run(query())


def test_a_paid_order_replays_byte_for_byte_after_a_restart_with_one_payment(
    database_url: str, tmp_path: Path
) -> None:
    """AC34, SD16: the switch on by PATCH, a wallet funded at the kassa, a paid order, a
    kill and a restart: the replay is 200 with identical bytes and one payment entry."""
    run_id = seed_live_run(database_url)
    jan = _wallet(database_url)
    bar_key = mint_key(database_url, "bar")
    stderr = tmp_path / "app.stderr"

    app = start_app(database_url, stderr)
    try:
        admin = Client(app.base)
        admin.login(mint_key(database_url, "admin"))
        status, body = admin.request(
            "PATCH", f"/api/runs/{run_id}/config", {"wallet_required": True}
        )
        assert status == 200, body
        kassa = Client(app.base)
        kassa.login(mint_key(database_url, "kassa"))
        status, body = kassa.request(
            "POST",
            f"/api/kassa/wallets/{jan.wallet_id}/topups",
            {"amount_cents": 2000},
            headers={"Idempotency-Key": "k-restart-fund-01"},
        )
        assert status == 201, body
        state = Client(app.base)
        state.login(bar_key)
        paid, first = _acknowledged(
            RawClient(app.base, bar_key), state.state(), PAID_KEY, {"qr_token": jan.qr_token}
        )
    finally:
        app.kill()
    assert json.loads(first)["wallet"]["name"] == "Jan"

    app = start_app(database_url, stderr)
    try:
        status, replay = RawClient(app.base, bar_key).order(PAID_KEY, paid)
        assert status == 200, replay
        assert replay == first
        price = paid["lines"][0]["unit_price_cents"]
        assert _payments(database_url) == [(jan.wallet_id, -price)]
    finally:
        app.kill()
