"""Connected clients (Phase 6 T16: AC41, server half).

`GET /api/admin/connections` lists every open WebSocket as `{role, label,
connected_at_ms, last_seen_ms}`, from the hub's own record of who connected.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import Login, MintKey
from tests.api.test_keys import sign_in, switch
from tests.support.clock import FakeClock


def test_connections_lists_a_connected_display(
    live_client: TestClient, login: Login, mint_key: MintKey, clock: FakeClock
) -> None:
    admin = sign_in(live_client, mint_key("admin"))
    assert live_client.get("/api/admin/connections").json() == []
    sign_in(live_client, mint_key("display", "Beamer"))

    with live_client.websocket_connect("wss://testserver/ws") as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
        ws.send_text(json.dumps({"type": "hello", "boot_id": "elsewhere", "last_seq": 0}))
        assert json.loads(ws.receive_text())["type"] == "snapshot"
        ws.send_text(json.dumps({"type": "ping"}))
        while json.loads(ws.receive_text())["type"] != "pong":
            pass

        listed = switch(live_client, admin).get("/api/admin/connections").json()

    assert listed == [
        {
            "role": "display",
            "label": "Beamer",
            "connected_at_ms": clock.wall_ms(),
            "last_seen_ms": clock.wall_ms(),
        }
    ]


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(live_client: TestClient, login: Login, role: str) -> None:
    assert login(role).get("/api/admin/connections").status_code == 403
