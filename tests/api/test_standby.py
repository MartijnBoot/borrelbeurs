"""Standby, over HTTP and `/ws` (Phase 8 T6: SD4, SD5; AC12, AC29 server half).

The test holds the advisory lock on its own connection, then boots the real app: it
cannot take the lock, so it serves in standby instead of exiting. `/healthz` says so
with 200, `/readyz` is 503, every `/api` request is 503 `standby` -- before
authentication, so the code is the same for a stranger and a logged-in phone -- and
`/ws` is accepted and closed with 1013 ("try again later").

The handover itself (release the lock, the instance boots) is in
`tests/integration/test_boot.py`; two real processes in `test_handover.py` (T7).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.db.advisory_lock import acquire, release
from app.db.session import create_engine
from app.main import create_app
from tests.api.conftest import BASE_URL
from tests.support.clock import FakeClock

BUILD_SHA = "0123456789abcdef0123456789abcdef01234567"
CLOSE_TRY_AGAIN_LATER = 1013


@pytest.fixture
def standby_client(
    api_env: str, clock: FakeClock, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """The app booted while another holder has the lock."""
    monkeypatch.setenv("BUILD_SHA", BUILD_SHA)
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(settings.model_copy(update={"database_url": api_env}))
    loop = asyncio.new_event_loop()
    held: AsyncConnection | None = loop.run_until_complete(acquire(engine))
    assert held is not None
    try:
        app = create_app(clock=clock, run_migrations=False)
        with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
            yield client
    finally:
        loop.run_until_complete(release(held))
        loop.run_until_complete(engine.dispose())
        loop.close()


def test_healthz_reports_standby_and_readyz_is_not_ready(standby_client: TestClient) -> None:
    health = standby_client.get("/healthz")
    ready = standby_client.get("/readyz")

    assert (health.status_code, health.json()) == (
        200,
        {
            "status": "standby",
            "build_sha": BUILD_SHA,
            "last_tick_age_ms": None,
            "last_commit_age_ms": None,
        },
    )
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "not_ready"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/state"),
        ("POST", "/api/orders"),
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/nope"),
        ("GET", "/theme.css"),  # needs the theme a standby has not built: 503, not a 500
    ],
)
def test_every_api_request_and_the_theme_is_503_standby(
    standby_client: TestClient, method: str, path: str
) -> None:
    response = standby_client.request(method, path, json={})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "standby"
    assert error["message"]


def test_ws_is_accepted_and_closed_with_1013(standby_client: TestClient) -> None:
    """Before the session check: a phone reconnects later, it is not told it is logged out."""
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        standby_client.websocket_connect("wss://testserver/ws") as ws,
    ):
        ws.receive_text()

    assert excinfo.value.code == CLOSE_TRY_AGAIN_LATER


def test_once_booted_the_gate_is_open(client: TestClient) -> None:
    """Holding the lock itself, the app is never in standby."""
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/api/state").status_code != 503
