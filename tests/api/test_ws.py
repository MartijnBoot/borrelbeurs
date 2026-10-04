"""`WS /ws` (Phase 3 T26: SD27, SD30, SD31, SD16; AC3, AC16, AC18c, AC21, AC24, AC25)."""

from __future__ import annotations

import concurrent.futures
import json
import time
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import security
from app.cli.keys import main as keys_main
from tests.api.conftest import BASE_URL, Login, MintKey

Advance = Callable[[int], None]


def _engine_state(client: TestClient) -> Any:
    holder = client.app.state.holder  # type: ignore[attr-defined]
    return None if holder.state is None else (holder.state.version, holder.state.rng_counter)


@pytest.fixture
def mutations(live_client: TestClient) -> Iterator[list[str]]:
    """A spy on `holder.mutate` for the ws handler's calls; the ticker is stopped first so
    every recorded call would be the handler's."""
    app = live_client.app
    ticker = app.state.ticker  # type: ignore[attr-defined]
    assert live_client.portal is not None
    live_client.portal.call(ticker.stop)
    holder = app.state.holder  # type: ignore[attr-defined]
    calls: list[str] = []
    real = holder.mutate

    async def spy(op: str, step: Any) -> Any:
        calls.append(op)
        return await real(op, step)

    holder.mutate = spy
    yield calls
    holder.mutate = real


def _seq_reached(hub: Any, target: int) -> bool:
    return bool(hub.seq >= target)


def _wait_for(condition: Callable[[], bool], timeout_s: float = 10.0) -> None:
    """Advancing the fake clock only wakes the ticker; its commit takes real time."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the ticker"
        time.sleep(0.01)


def _connect(client: TestClient, **headers: str) -> Any:
    # wss: the session cookie is `Secure` (SD8); TestClient would otherwise open ws:// and
    # leave it behind, exactly as a browser would.
    return client.websocket_connect("wss://testserver/ws", headers=headers)


@pytest.mark.parametrize("case", ["no-cookie", "revoked-key", "foreign-origin", "missing-origin"])
def test_a_bad_handshake_closes_1008_with_no_frame(
    live_client: TestClient, mint_key: MintKey, case: str
) -> None:
    """AC3."""
    client = live_client
    headers: dict[str, str] = {}
    if case != "no-cookie":
        raw = mint_key("display")
        assert client.post("/api/auth/login", json={"key": raw}).status_code == 200
        if case == "revoked-key":
            parsed = security.parse_key(raw)
            assert parsed is not None
            assert keys_main(["revoke", str(parsed.key_id)]) == 0
    if case == "foreign-origin":
        headers["origin"] = "https://evil.example"
    if case == "missing-origin":
        client.headers.pop("origin", None)

    with pytest.raises(WebSocketDisconnect) as excinfo, _connect(client, **headers) as ws:
        ws.receive_text()

    assert excinfo.value.code == 1008


def test_hello_then_snapshot_when_the_client_hello_is_foreign(
    live_client: TestClient, login: Login
) -> None:
    """AC21 (otherwise branch): a foreign `boot_id` gets one snapshot at the current seq."""
    client = login("display")
    with _connect(client) as ws:
        hello = json.loads(ws.receive_text())
        ws.send_text(json.dumps({"type": "hello", "boot_id": "not-this-boot", "last_seq": 0}))
        snap = json.loads(ws.receive_text())

    assert hello["type"] == "hello"
    assert hello["data"]["role"] == "display" and hello["data"]["run_id"] is not None
    assert snap["type"] == "snapshot"
    assert snap["seq"] == hello["seq"] == client.app.state.hub.seq  # type: ignore[attr-defined]


def test_a_current_hello_gets_exactly_the_missed_broadcasts_and_no_snapshot(
    live_client: TestClient, login: Login, advance: Advance
) -> None:
    """AC21: replay from the log, in order, then live frames."""
    client = login("bar")
    hub = client.app.state.hub  # type: ignore[attr-defined]
    with _connect(client) as first:
        hello = json.loads(first.receive_text())
        first.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        assert json.loads(first.receive_text())["type"] == "snapshot"
    seen = hub.seq
    for k in range(1, 4):  # three ticks broadcast while no one listens
        advance(1_000)
        _wait_for(partial(_seq_reached, hub, seen + k))
    assert hub.seq == seen + 3

    with _connect(client) as ws:
        json.loads(ws.receive_text())  # hello
        ws.send_text(
            json.dumps({"type": "hello", "boot_id": hello["data"]["boot_id"], "last_seq": seen})
        )
        frames = [json.loads(ws.receive_text()) for _ in range(3)]
        catch_up = json.loads(ws.receive_text())  # the theme (Phase 4 PD7)
        advance(1_000)
        live = json.loads(ws.receive_text())

    assert [f["type"] for f in frames] == ["tick", "tick", "tick"]
    assert (catch_up["type"], catch_up["seq"]) == ("theme", seen + 3)
    assert [f["seq"] for f in frames] == [seen + 1, seen + 2, seen + 3]
    assert (live["type"], live["seq"]) == ("tick", seen + 4)


def test_closing_a_session_never_leaks_a_foreign_cancellation(
    live_client: TestClient, login: Login
) -> None:
    """Regression: on exit TestClient cancels the handler's anyio scope right after the
    disconnect. If that lands while the handler's cleanup awaits its two tasks, the
    `CancelledError` escaping must be anyio's own, which the scope swallows; a child's,
    re-raised by `gather`, made `__exit__` raise `CancelledError` in about one exit in 40.
    A race, so it is run many times: 300 exits failed 4-9 times before the fix."""
    client = login("display")
    leaked = 0
    for _ in range(300):
        try:
            with _connect(client) as ws:
                ws.receive_text()  # hello
                ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
                ws.receive_text()  # snapshot
        except concurrent.futures.CancelledError:
            leaked += 1

    assert leaked == 0


def test_ping_gets_a_json_pong_and_every_frame_is_json(
    live_client: TestClient, login: Login
) -> None:
    """AC24: no bare "pong" string, ever."""
    client = login("display")
    with _connect(client) as ws:
        frames = [ws.receive_text()]
        ws.send_text(json.dumps({"type": "ping"}))
        frames.append(ws.receive_text())  # snapshot (the ping was not a hello)
        frames.append(ws.receive_text())  # theme (Phase 4 PD7)
        frames.append(ws.receive_text())  # pong

    decoded = [json.loads(f) for f in frames]
    assert [d["type"] for d in decoded] == ["hello", "snapshot", "theme", "pong"]
    assert decoded[3]["data"]["server_ts_ms"] == client.app.state.clock.wall_ms()  # type: ignore[attr-defined]


def test_resync_request_gets_a_snapshot_and_garbage_gets_an_error(
    live_client: TestClient, login: Login
) -> None:
    client = login("display")
    with _connect(client) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        ws.receive_text()  # snapshot
        ws.receive_text()  # theme (Phase 4 PD7)
        replies = []
        for raw in ('{"type": "resync_request"}', "state", "{", '{"type": "ping", "x": 1}'):
            ws.send_text(raw)
            replies.append(json.loads(ws.receive_text()))
        replies.append(json.loads(ws.receive_text()))  # the last error; the resync sent two

    assert [r["type"] for r in replies] == ["snapshot", "theme", "error", "error", "error"]
    assert replies[2]["data"] == {"code": "invalid_message"}


def test_a_binary_frame_gets_an_error_and_the_connection_stays_open(
    live_client: TestClient, login: Login
) -> None:
    """SD30: a binary frame is "anything else", in the hello window and after it."""
    client = login("display")
    with _connect(client) as ws:
        ws.receive_text()  # hello
        ws.send_bytes(b"\x00\x01")
        replies = [json.loads(ws.receive_text()) for _ in range(3)]  # snapshot, theme, error
        ws.send_bytes(b'{"type": "ping"}')
        replies.append(json.loads(ws.receive_text()))
        ws.send_text(json.dumps({"type": "ping"}))
        replies.append(json.loads(ws.receive_text()))

    assert [r["type"] for r in replies] == ["snapshot", "theme", "error", "error", "pong"]
    assert replies[2]["data"] == replies[3]["data"] == {"code": "invalid_message"}


def test_client_messages_never_touch_the_market_and_six_a_second_close_1008(
    live_client: TestClient, login: Login, mutations: list[str]
) -> None:
    """AC16 (D-36): no client message mutates; the sixth in a second is a policy violation."""
    client = login("admin")
    before = _engine_state(client)
    with pytest.raises(WebSocketDisconnect) as excinfo, _connect(client) as ws:
        ws.receive_text()
        for raw in (
            '{"type": "hello", "boot_id": "x", "last_seq": 0}',
            '{"type": "ping"}',
            '{"type": "resync_request"}',
            "state",
            '{"type": "order"}',
            '{"type": "ping"}',
        ):
            ws.send_text(raw)
        while True:
            ws.receive_text()

    assert excinfo.value.code == 1008
    assert mutations == []
    assert _engine_state(client) == before


def test_five_a_second_is_allowed(live_client: TestClient, login: Login, advance: Advance) -> None:
    client = login("display")
    with _connect(client) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        ws.receive_text()  # snapshot
        ws.receive_text()  # theme (Phase 4 PD7)
        for _ in range(4):
            ws.send_text('{"type": "ping"}')
        replies = [json.loads(ws.receive_text())["type"] for _ in range(4)]
        advance(1_000)
        ws.send_text('{"type": "ping"}')
        frames = [json.loads(ws.receive_text())["type"] for _ in range(2)]

    assert replies == ["pong"] * 4
    assert "pong" in frames


def test_the_session_expiring_closes_the_socket_4401(
    live_client: TestClient, login: Login, advance: Advance
) -> None:
    """AC25."""
    client = login("display")
    with pytest.raises(WebSocketDisconnect) as excinfo, _connect(client) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        ws.receive_text()
        advance(security.SESSION_MS)
        while True:
            ws.receive_text()

    assert excinfo.value.code == 4401


def test_with_no_live_run_hello_has_no_run_and_no_snapshot_follows(login: Login) -> None:
    """AC18c (ws half), SD16."""
    client = login("display")
    with _connect(client) as ws:
        hello = json.loads(ws.receive_text())
        ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        ws.send_text('{"type": "ping"}')
        catch_up = json.loads(ws.receive_text())
        reply = json.loads(ws.receive_text())

    assert hello["data"]["run_id"] is None and hello["run_id"] is None
    # No snapshot: the theme catch-up (Phase 4 PD7) is the only frame before the pong.
    assert catch_up["type"] == "theme"
    assert reply["type"] == "pong"


def test_the_handshake_needs_the_same_origin_even_with_a_valid_session(
    live_client: TestClient, login: Login
) -> None:
    client = login("admin")
    foreign_port = BASE_URL.replace("https", "http") + ":81"
    with pytest.raises(WebSocketDisconnect) as excinfo, _connect(client, origin=foreign_port) as ws:
        ws.receive_text()

    assert excinfo.value.code == 1008
