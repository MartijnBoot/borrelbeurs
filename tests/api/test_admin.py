"""Admin shutdown (Phase 3 T27: SD10; AC6d; PD17)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.advisory_lock import acquire, release
from app.db.session import create_engine
from app.main import create_app
from tests.api.conftest import BASE_URL, MintKey
from tests.support.clock import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[2]


class RecordingSocket:
    def __init__(self) -> None:
        self.closed: int | None = None

    async def send_text(self, frame: str) -> None:
        pass

    async def close(self, code: int) -> None:
        self.closed = code


def _login(client: TestClient, mint_key: MintKey, role: str) -> None:
    assert client.post("/api/auth/login", json={"key": mint_key(role)}).status_code == 200


def test_an_admin_shutdown_answers_202_drains_and_asks_once(
    live_run: int, api_env: str, mint_key: MintKey, clock: FakeClock
) -> None:
    calls: list[str] = []
    app = create_app(
        clock=clock, run_migrations=False, request_shutdown=lambda: calls.append("stop")
    )
    with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
        _login(client, mint_key, "admin")
        holder = app.state.holder
        drink = holder.drink_ids[0]

        response = client.post("/api/admin/shutdown")
        order = client.post(
            "/api/orders",
            json={
                "quote_version": holder.state.version,
                "lines": [{"drink_id": drink, "qty": 1, "unit_price_cents": 260}],
            },
            headers={"Idempotency-Key": "k-after-shutdown"},
        )

        assert response.status_code == 202
        assert response.json() == {"status": "shutting_down"}
        assert calls == ["stop"]
        assert order.status_code == 503
        assert order.json()["error"]["code"] == "shutting_down"


@pytest.mark.parametrize("role", ["bar", "display"])
def test_only_admin_may_shut_down(live_client: TestClient, mint_key: MintKey, role: str) -> None:
    _login(live_client, mint_key, role)

    response = live_client.post("/api/admin/shutdown")

    assert response.status_code == 403
    assert live_client.app.state.draining is False  # type: ignore[attr-defined]


def test_the_lifespan_exit_is_the_graceful_path(
    live_run: int, api_env: str, settings: Settings, clock: FakeClock
) -> None:
    """SD10: not ready first, the ticker's slot committed, sockets closed 1012, the lock freed."""
    app = create_app(clock=clock, run_migrations=False)
    socket = RecordingSocket()

    async def scenario() -> tuple[bool, bool, int | None, int, bool]:
        async with app.router.lifespan_context(app):
            app.state.hub.connect(socket)
            ready_while_serving = app.state.ready
            # The ticker and the lock watchdog must be asleep on the clock before it moves.
            for _ in range(400):
                if clock.sleepers >= 2:
                    break
                await asyncio.sleep(0.005)
            clock.advance(1_000)
            for _ in range(1_000):
                await asyncio.sleep(0.005)
                if app.state.holder.state.version >= 1 and not app.state.ticker.busy:
                    break
        await asyncio.sleep(0)
        version = app.state.holder.state.version
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            again = await acquire(engine)
            free = again is not None
            if again is not None:
                await release(again)
        finally:
            await engine.dispose()
        return ready_while_serving, app.state.ready, socket.closed, version, free

    ready_while_serving, ready_after, closed, version, lock_free = asyncio.run(scenario())
    assert ready_while_serving is True
    assert ready_after is False
    assert closed == 1012
    assert version >= 1  # the slot that ran committed
    assert lock_free
    assert app.state.draining is True


def test_admin_token_does_not_exist() -> None:
    """AC6d: no shared admin secret -- not in app/, not in Settings, not in .env.example."""
    pattern = re.compile(r"ADMIN_TOKEN", re.IGNORECASE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "app").rglob("*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert not any(pattern.search(name) for name in Settings.model_fields)
    assert not pattern.search((REPO_ROOT / ".env.example").read_text(encoding="utf-8"))


def test_the_admin_token_detector_finds_it() -> None:
    sample = "ADMIN" + "_TOKEN=abc"
    assert re.search(r"ADMIN_TOKEN", sample, re.IGNORECASE)
