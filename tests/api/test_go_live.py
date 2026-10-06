"""Go-live over HTTP (Phase 6 T9: SD1, SD3; AC25, AC26, AC27; PD11).

The app boots with no live run; a WebSocket client is connected; a draft is
created through the API, given a drink, and made live. The open socket gets the
run's snapshot without reconnecting, then ticks at the run's own interval.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.runs import add_drink
from app.db.session import create_engine
from tests.api.conftest import Login

Advance = Callable[[int], None]


def _sql(settings: Settings, url: str, statement: str, **params: Any) -> list[tuple[Any, ...]]:
    async def scenario() -> list[tuple[Any, ...]]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(statement), params)
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _add_drink(settings: Settings, url: str, run_id: int) -> None:
    async def scenario() -> None:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                await add_drink(
                    conn,
                    run_id,
                    name="Bier",
                    slot=0,
                    p_min_cents=150,
                    p0_cents=260,
                    p_max_cents=500,
                    a=1.0,
                    d=0.1,
                    s0=1.0,
                    c=0.1,
                    bar_price_cents=260,
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _until(ws: Any, kind: str, limit: int = 20) -> dict[str, Any]:
    for _ in range(limit):
        frame: dict[str, Any] = json.loads(ws.receive_text())
        if frame["type"] == kind:
            return frame
    raise AssertionError(f"no {kind} within {limit} frames")


def test_an_open_socket_gets_the_new_runs_snapshot_then_its_ticks(
    login: Login, settings: Settings, api_env: str, advance: Advance
) -> None:
    """AC25, AC27."""
    admin = login("admin", label="Bestuur")
    run_id = admin.post("/api/runs", json={"name": "Vrijmibo"}).json()["run_id"]
    _add_drink(settings, api_env, run_id)
    _sql(settings, api_env, "UPDATE run SET tick_interval_ms = 500 WHERE run_id = :r", r=run_id)

    with admin.websocket_connect("wss://testserver/ws") as ws:
        hello = _until(ws, "hello")
        assert hello["data"]["run_id"] is None
        ws.send_text(
            json.dumps({"type": "hello", "boot_id": hello["data"]["boot_id"], "last_seq": 0})
        )
        _until(ws, "theme")

        response = admin.post(f"/api/runs/{run_id}/go-live")

        assert response.status_code == 200, response.text
        assert response.json() == {"run_id": run_id, "name": "Vrijmibo", "status": "live"}
        snap = _until(ws, "snapshot")
        assert (snap["run_id"], snap["data"]["run"]["tick_interval_ms"]) == (run_id, 500)
        _until(ws, "theme")

        advance(500)
        tick = _until(ws, "tick")
        assert tick["version"] == snap["version"] + 1


@pytest.mark.parametrize("case", ["no_drink", "not_draft", "live_exists", "not_found"])
def test_each_refusal_is_409_or_404_and_changes_nothing(
    case: str,
    login: Login,
    settings: Settings,
    api_env: str,
) -> None:
    """AC26: `engine_state` stays empty and the run stays a draft."""
    admin = login("admin")
    run_id = admin.post("/api/runs", json={"name": "Concept"}).json()["run_id"]
    if case == "not_draft":
        _sql(settings, api_env, "UPDATE run SET status = 'ended' WHERE run_id = :r", r=run_id)
    if case == "live_exists":
        _add_drink(settings, api_env, run_id)
        _sql(
            settings,
            api_env,
            "INSERT INTO run (status, name, params, run_seed) VALUES ('live', 'Ander', '{}', 1)",
        )
    target = 999_999 if case == "not_found" else run_id

    response = admin.post(f"/api/runs/{target}/go-live")

    expected = {
        "no_drink": (409, "run_not_ready"),
        "not_draft": (409, "run_not_draft"),
        "live_exists": (409, "live_run_exists"),
        "not_found": (404, "run_not_found"),
    }[case]
    assert (response.status_code, response.json()["error"]["code"]) == expected
    assert _sql(settings, api_env, "SELECT count(*) FROM engine_state") == [(0,)]
    expected_status = "ended" if case == "not_draft" else "draft"
    assert _sql(settings, api_env, "SELECT status FROM run WHERE run_id = :r", r=run_id) == [
        (expected_status,)
    ]
    assert admin.app.state.holder.is_empty  # type: ignore[attr-defined]


def test_with_a_live_run_in_memory_go_live_is_409(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    _sql(
        settings,
        api_env,
        "INSERT INTO run (status, name, params, run_seed) VALUES ('draft', 'Twee', '{}', 1)",
    )
    (draft,) = _sql(settings, api_env, "SELECT run_id FROM run WHERE status = 'draft'")

    response = login("admin").post(f"/api/runs/{draft[0]}/go-live")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "live_run_exists"


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(login: Login, role: str) -> None:
    assert login(role).post("/api/runs/1/go-live").status_code == 403
