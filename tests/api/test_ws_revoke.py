"""Revoking a key closes its open WebSockets (Phase 6 T16: AC37; SD30, PD12).

The revoke commits, then `hub.close_key` closes every connection of that key
with 4401 -- Phase 3's close code for a session that ended -- without the fake
clock moving at all, so well within SD30's 1 s. Other keys' sockets stay open.

One `TestClient` serves all three identities: a socket reads the session cookie
only at its handshake, so the jar can be switched once it is open.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import security
from tests.api.conftest import MintKey
from tests.api.test_keys import sign_in, switch
from tests.support.clock import FakeClock


def _open(client: TestClient) -> Any:
    ws = client.websocket_connect("wss://testserver/ws")
    return ws


def _handshake(ws: Any) -> None:
    assert json.loads(ws.receive_text())["type"] == "hello"
    ws.send_text(json.dumps({"type": "hello", "boot_id": "elsewhere", "last_seq": 0}))
    assert json.loads(ws.receive_text())["type"] == "snapshot"


def test_a_revoked_keys_socket_closes_4401_and_others_stay_open(
    live_client: TestClient, mint_key: MintKey, clock: FakeClock
) -> None:
    admin = sign_in(live_client, mint_key("admin"))
    revoked_raw = mint_key("display", "Oud scherm")
    parsed = security.parse_key(revoked_raw)
    assert parsed is not None
    at = clock.wall_ms()

    with ExitStack() as stack:
        sign_in(live_client, revoked_raw)
        gone = stack.enter_context(_open(live_client))
        _handshake(gone)
        sign_in(live_client, mint_key("display", "Nieuw scherm"))
        stays = stack.enter_context(_open(live_client))
        _handshake(stays)

        assert switch(live_client, admin).delete(f"/api/keys/{parsed.key_id}").status_code == 204

        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                gone.receive_text()
        assert closed.value.code == 4401
        assert clock.wall_ms() == at  # no time had to pass
        labels = [c["label"] for c in live_client.get("/api/admin/connections").json()]
        assert labels == ["Nieuw scherm"]
        stays.send_text(json.dumps({"type": "ping"}))
        while json.loads(stays.receive_text())["type"] != "pong":
            pass
