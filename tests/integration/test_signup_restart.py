"""The screen's sign-up state survives a restart as stored (B-10 T3: SD3; AC8).

A first app saves a code with the switch on; it stops. A fresh `create_app` on the
same database, with a different `BB_PUBLIC_URL`, answers a new socket's catch-up
with the stored code and switch and its own address -- never a copy from before.

Pattern: `test_wallets_restart.py`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.security import issue_key
from app.core.config import Settings, get_settings
from app.db.session import create_engine
from app.main import create_app
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
BASE_URL = "https://testserver"


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """The app's settings on the scratch database, as `tests/api/conftest.py` does."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("BB_PUBLIC_URL", "http://192.168.8.10")
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _admin_key(settings: Settings, url: str) -> str:
    async def scenario() -> str:
        engine: AsyncEngine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return (await issue_key(conn, role="admin", label="Admin")).key
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _app() -> TestClient:
    return TestClient(
        create_app(clock=FakeClock(T0), run_migrations=False),
        base_url=BASE_URL,
        headers={"origin": BASE_URL},
    )


def _catch_up(client: TestClient) -> dict[str, Any]:
    """A new socket's `signup` catch-up, after the `theme` one."""
    with client.websocket_connect("wss://testserver/ws") as ws:
        ws.receive_text()  # hello
        ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        # No live run: the theme catch-up, then the signup one.
        frames = [json.loads(ws.receive_text()) for _ in range(2)]
    assert [f["type"] for f in frames] == ["theme", "signup"]
    data: dict[str, Any] = frames[1]["data"]
    return data


def test_a_reconnect_after_a_restart_gets_the_stored_state(
    settings: Settings, on: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC8."""
    key = _admin_key(settings, on)
    body = {
        "signup_code": "BORREL",
        "unfunded_days": 30,
        "inactive_months": 12,
        "show_signup_on_screen": True,
    }

    with _app() as first:
        assert first.post("/api/auth/login", json={"key": key}).status_code == 200
        assert _catch_up(first)["show_on_screen"] is False
        assert first.put("/api/admin/wallet-settings", json=body).status_code == 200

    monkeypatch.setenv("BB_PUBLIC_URL", "https://borrelbeurs.example")
    get_settings.cache_clear()
    with _app() as second:
        assert second.post("/api/auth/login", json={"key": key}).status_code == 200
        state = _catch_up(second)

    assert state == {
        "show_on_screen": True,
        "signup_code": "BORREL",
        "public_url": "https://borrelbeurs.example",
    }
