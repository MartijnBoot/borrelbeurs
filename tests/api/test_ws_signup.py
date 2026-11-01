"""The sign-up state over `WS /ws` (B-10 T3: SD3, SD4; AC4, AC5; PD2, PD4).

`signup` follows `theme`: a broadcast with `version` null on every settings save,
with or without a live run, to every role; and a unicast at the current `seq`
after every handshake and every `resync_request` snapshot.

`BB_PUBLIC_URL` is set or deleted here explicitly, never inherited: the app reads
`get_settings()` from the process environment (`tests/api/conftest.py`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.api.conftest import Login

URL = "http://192.168.8.10"
ROLES = ("display", "bar", "kassa", "admin")


@pytest.fixture
def public_url(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str | None]:
    """`BB_PUBLIC_URL` for the app this test boots; `URL` unless parametrised."""
    value: str | None = getattr(request, "param", URL)
    if value is None:
        monkeypatch.delenv("BB_PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("BB_PUBLIC_URL", value)
    get_settings.cache_clear()
    yield value
    get_settings.cache_clear()


def _connect(client: TestClient) -> Any:
    # wss: the session cookie is Secure (SD8), as in tests/api/test_ws.py.
    return client.websocket_connect("wss://testserver/ws")


def _frame(ws: Any) -> dict[str, Any]:
    frame: dict[str, Any] = json.loads(ws.receive_text())
    return frame


def _hello(ws: Any, boot_id: str = "x", last_seq: int = 0) -> None:
    ws.send_text(json.dumps({"type": "hello", "boot_id": boot_id, "last_seq": last_seq}))


def _handshake(ws: Any, boot_id: str = "x", last_seq: int = 0) -> list[dict[str, Any]]:
    """`hello`, the client's `hello`, then every frame up to the `signup` catch-up."""
    frames = [_frame(ws)]
    _hello(ws, boot_id, last_seq)
    # hello, snapshot, theme, signup at most: a missing `signup` fails here, never hangs.
    while frames[-1]["type"] != "signup":
        assert len(frames) < 4, [f["type"] for f in frames]
        frames.append(_frame(ws))
    return frames


def _settings(**changes: Any) -> dict[str, Any]:
    return {
        "signup_code": "BORREL",
        "unfunded_days": 30,
        "inactive_months": 12,
        "show_signup_on_screen": True,
        **changes,
    }


def _pong_next(ws: Any) -> None:
    """Nothing else is queued: the next frame answers a ping."""
    ws.send_text(json.dumps({"type": "ping"}))
    assert _frame(ws)["type"] == "pong"


@pytest.mark.parametrize("live", [False, True], ids=["no-run", "live-run"])
def test_a_save_broadcasts_one_signup_to_every_role(
    public_url: str | None, request: pytest.FixtureRequest, live: bool
) -> None:
    """AC4, SD4: one frame per socket, the stored values, `version` null, any role."""
    # The app boots after `live_run` exists, so `login` (which needs `client`) comes after.
    client: TestClient = request.getfixturevalue("live_client" if live else "client")
    login: Login = request.getfixturevalue("login")
    hub = client.app.state.hub  # type: ignore[attr-defined]
    with ExitStack() as stack:
        sockets = []
        for role in ROLES:
            login(role)
            ws = stack.enter_context(_connect(client))
            _handshake(ws)
            sockets.append(ws)
        before = hub.seq

        response = client.put("/api/admin/wallet-settings", json=_settings())
        frames = [_frame(ws) for ws in sockets]
        for ws in sockets:
            _pong_next(ws)

    assert response.status_code == 200
    assert {f["type"] for f in frames} == {"signup"}
    assert {f["seq"] for f in frames} == {before + 1}
    assert all(f["version"] is None for f in frames)
    assert {f["run_id"] for f in frames} == {client.app.state.holder.run_id}  # type: ignore[attr-defined]
    assert all(
        f["data"] == {"show_on_screen": True, "signup_code": "BORREL", "public_url": URL}
        for f in frames
    )


def test_a_save_of_the_periods_only_still_broadcasts(public_url: str | None, login: Login) -> None:
    """PD4: every successful save sends the whole state, changed or not."""
    admin = login("admin")
    admin.put("/api/admin/wallet-settings", json=_settings())
    with _connect(admin) as ws:
        _handshake(ws)
        admin.put("/api/admin/wallet-settings", json=_settings(unfunded_days=7))
        frame = _frame(ws)

    assert frame["type"] == "signup"
    assert frame["data"]["signup_code"] == "BORREL"


def test_a_refused_save_while_draining_broadcasts_nothing(
    public_url: str | None, login: Login
) -> None:
    admin = login("admin")
    hub = admin.app.state.hub  # type: ignore[attr-defined]
    with _connect(admin) as ws:
        _handshake(ws)
        before = hub.seq
        admin.app.state.draining = True  # type: ignore[attr-defined]
        try:
            response = admin.put("/api/admin/wallet-settings", json=_settings())
        finally:
            admin.app.state.draining = False  # type: ignore[attr-defined]
        _pong_next(ws)

    assert response.status_code == 503
    assert hub.seq == before


@pytest.mark.parametrize("live", [False, True], ids=["no-run", "live-run"])
def test_the_handshake_ends_with_a_signup_catch_up(
    public_url: str | None, request: pytest.FixtureRequest, live: bool
) -> None:
    """AC5 (connect, snapshot): after the theme, `signup` at the current seq, seq unmoved."""
    # The app boots after `live_run` exists, so `login` (which needs `client`) comes after.
    client: TestClient = request.getfixturevalue("live_client" if live else "client")
    login: Login = request.getfixturevalue("login")
    hub = client.app.state.hub  # type: ignore[attr-defined]
    admin = login("admin")
    admin.put("/api/admin/wallet-settings", json=_settings())
    login("display")
    seq = hub.seq
    with _connect(client) as ws:
        frames = _handshake(ws)

    expected = ["hello", "snapshot", "theme", "signup"] if live else ["hello", "theme", "signup"]
    assert [f["type"] for f in frames] == expected
    catch_up = frames[-1]
    assert catch_up["seq"] == seq == hub.seq
    assert catch_up["version"] is None
    assert catch_up["data"] == {"show_on_screen": True, "signup_code": "BORREL", "public_url": URL}


def test_a_replay_ends_with_the_current_signup(
    public_url: str | None, live_client: TestClient, login: Login
) -> None:
    """AC5 (replay): a missed `signup` is replayed, then the catch-up holds the latest."""
    admin = login("admin")
    hub = live_client.app.state.hub  # type: ignore[attr-defined]
    with _connect(admin) as ws:
        frames = _handshake(ws)
    boot_id, last_seq = frames[0]["data"]["boot_id"], frames[-1]["seq"]

    admin.put("/api/admin/wallet-settings", json=_settings(signup_code="EERST"))
    admin.put("/api/admin/wallet-settings", json=_settings(signup_code="DAARNA"))

    with _connect(admin) as ws:
        frames = [_frame(ws)]  # hello
        _hello(ws, boot_id, last_seq)
        frames += [_frame(ws) for _ in range(hub.seq - last_seq + 2)]  # replay, theme, signup

    assert [f["type"] for f in frames] == ["hello", "signup", "signup", "theme", "signup"]
    assert [f["data"]["signup_code"] for f in frames[1:3]] == ["EERST", "DAARNA"]
    assert frames[-1]["data"]["signup_code"] == "DAARNA"
    assert frames[-1]["seq"] == hub.seq == last_seq + 2


def test_a_resync_request_ends_with_the_signup(
    public_url: str | None, live_client: TestClient, login: Login
) -> None:
    """AC5 (resync): snapshot, theme, then `signup`, all at the current seq."""
    client = login("display")
    hub = client.app.state.hub  # type: ignore[attr-defined]
    with _connect(client) as ws:
        _handshake(ws)
        ws.send_text(json.dumps({"type": "resync_request"}))
        replies = [_frame(ws), _frame(ws), _frame(ws)]

    assert [r["type"] for r in replies] == ["snapshot", "theme", "signup"]
    assert {r["seq"] for r in replies} == {hub.seq}
    assert replies[2]["version"] is None


@pytest.mark.parametrize("public_url", [None], indirect=True)
def test_with_no_public_url_the_signup_carries_null(public_url: str | None, login: Login) -> None:
    """SD1: unset is valid; the screen then uses the address it is open at."""
    with _connect(login("display")) as ws:
        catch_up = _handshake(ws)[-1]

    assert catch_up["data"] == {"show_on_screen": False, "signup_code": None, "public_url": None}
