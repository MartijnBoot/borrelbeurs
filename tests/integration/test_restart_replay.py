"""Same-key replay across a real restart (Phase 5 T17: the server half of AC26; SD13).

The production entrypoint, `python -m app.main`, as a subprocess on the scratch
database, over stdlib `urllib` (`tests/integration/realapp/harness.py`). An order
is acknowledged with key K, the app is killed and restarted on the same
database, and the same key and body are posted again: the answer is a 200 whose
body is byte-identical to the first receipt, and the database holds one order.
The bar's retries after a restart (SD13) rest on exactly this.

Responses are read here as raw bytes -- the harness `Client` parses JSON, which
would hide a byte-level difference.
"""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.realapp.harness import Client, mint_key, seed_live_run, start_app

KEY = "k-restart-replay-0001"


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


def _acknowledged(client: RawClient, state: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Order one of drink one under KEY; on a 409, again with the version and price it returns.

    A 409 commits nothing and stores no key, so the same key is retried with the
    new quote; the body that is finally acknowledged is the one to replay.
    """
    drink = int(next(iter(state["prices"])))
    price = state["prices"][str(drink)]["price_cents"]
    quote = 0
    for _ in range(5):
        body = {
            "quote_version": quote,
            "lines": [{"drink_id": drink, "qty": 1, "unit_price_cents": price}],
        }
        status, raw = client.order(KEY, body)
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
