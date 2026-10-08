"""The theme over `WS /ws` (Phase 4 T5: SD9; AC5, AC6, AC9; PD7)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient

from app.runtime.theme import PRESETS
from tests.api.conftest import Login
from tests.api.test_assets import _upload
from tests.unit.test_images import PNG


def _connect(client: TestClient) -> Any:
    # wss: the session cookie is Secure (SD8), as in tests/api/test_ws.py.
    return client.websocket_connect("wss://testserver/ws")


def _frame(ws: Any) -> dict[str, Any]:
    frame: dict[str, Any] = json.loads(ws.receive_text())
    return frame


def _hello(ws: Any, boot_id: str = "x", last_seq: int = 0) -> None:
    ws.send_text(json.dumps({"type": "hello", "boot_id": boot_id, "last_seq": last_seq}))


def test_hello_carries_blauw_on_an_empty_table(client: TestClient, login: Login) -> None:
    """AC9 (hello half), with no live run."""
    with _connect(login("display")) as ws:
        hello = _frame(ws)

    theme = hello["data"]["theme"]
    assert (theme["preset"], theme["revision"]) == ("blauw", 0)
    assert theme["tokens"] == dict(PRESETS["blauw"].tokens)
    assert theme["font_family"] == PRESETS["blauw"].font_family


def test_hello_carries_the_stored_theme(live_client: TestClient, login: Login) -> None:
    admin = login("admin")
    admin.put("/api/theme", json={"preset": "rood"})

    with _connect(admin) as ws:
        hello = _frame(ws)

    assert (hello["data"]["theme"]["preset"], hello["data"]["theme"]["revision"]) == ("rood", 1)


def test_the_handshake_ends_with_a_theme_catch_up(live_client: TestClient, login: Login) -> None:
    """PD7 (a): after the snapshot, a `theme` unicast at the current seq."""
    client = login("display")
    with _connect(client) as ws:
        hello = _frame(ws)
        _hello(ws)
        snapshot = _frame(ws)
        theme = _frame(ws)

    assert snapshot["type"] == "snapshot"
    assert theme["type"] == "theme"
    assert theme["seq"] == snapshot["seq"] == hello["seq"]
    assert theme["version"] is None
    assert theme["data"] == hello["data"]["theme"]


def test_with_no_live_run_a_client_receives_the_put(client: TestClient, login: Login) -> None:
    """AC5: no run, no snapshot -- the catch-up, then the admin's broadcast."""
    admin = login("admin")
    with _connect(admin) as ws:
        _frame(ws)  # hello
        _hello(ws)
        catch_up = _frame(ws)
        response = admin.put("/api/theme", json={"preset": "paars"})
        broadcast = _frame(ws)

    assert response.status_code == 200
    assert (catch_up["type"], catch_up["data"]["revision"]) == ("theme", 0)
    assert broadcast["type"] == "theme"
    assert (broadcast["data"]["preset"], broadcast["data"]["revision"]) == ("paars", 1)
    assert broadcast["seq"] == catch_up["seq"] + 1
    assert broadcast["run_id"] is None


def test_a_reconnect_replays_a_missed_theme(live_client: TestClient, login: Login) -> None:
    """AC6: disconnect, the admin switches, reconnect with the boot and seq held."""
    admin = login("admin")
    hub = live_client.app.state.hub  # type: ignore[attr-defined]
    with _connect(admin) as ws:
        boot_id = _frame(ws)["data"]["boot_id"]
        _hello(ws)
        _frame(ws)  # snapshot
        last_seq = _frame(ws)["seq"]  # the catch-up theme
    assert hub.seq == last_seq

    admin.put("/api/theme", json={"preset": "oudgeld"})

    with _connect(admin) as ws:
        _frame(ws)  # hello
        _hello(ws, boot_id, last_seq)
        frames = [_frame(ws) for _ in range(hub.seq - last_seq)]
        catch_up = _frame(ws)

    replayed = [f for f in frames if f["type"] == "theme"]
    assert [(f["data"]["preset"], f["data"]["revision"]) for f in replayed] == [("oudgeld", 1)]
    assert (catch_up["type"], catch_up["data"]["revision"]) == ("theme", 1)


def test_a_resync_request_is_answered_by_a_snapshot_then_the_theme(
    live_client: TestClient, login: Login
) -> None:
    """PD7 (b): a gap repaired by a snapshot also restores the theme."""
    client = login("display")
    with _connect(client) as ws:
        _frame(ws)  # hello
        _hello(ws)
        _frame(ws)  # snapshot
        _frame(ws)  # catch-up theme
        ws.send_text(json.dumps({"type": "resync_request"}))
        replies = [_frame(ws), _frame(ws)]

    assert [r["type"] for r in replies] == ["snapshot", "theme"]
    assert replies[1]["seq"] == replies[0]["seq"]


def test_two_racing_puts_converge_on_the_last_committed(client: TestClient, login: Login) -> None:
    """SD9: two broadcasts, revisions 1 and 2; the server ends on revision 2, which a
    client keeps whatever order the frames came in, because it applies only higher ones."""
    admin = login("admin")
    with _connect(admin) as ws:
        _frame(ws)  # hello
        _hello(ws)
        _frame(ws)  # catch-up
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda preset: admin.put("/api/theme", json={"preset": preset}),
                    ("rood", "groen"),
                )
            )
        broadcasts = [_frame(ws), _frame(ws)]

    assert [r.status_code for r in responses] == [200, 200]
    assert all(b["type"] == "theme" for b in broadcasts)
    assert sorted(b["data"]["revision"] for b in broadcasts) == [1, 2]
    assert client.app.state.theme.revision == 2  # type: ignore[attr-defined]


def test_hello_carries_the_theme_images(client: TestClient, login: Login) -> None:
    """Phase 6 T19 (PD9; AC35): each slot as "/assets/<id>", or null."""
    admin = login("admin")
    logo = _upload(admin, "logo", PNG).json()["asset_id"]

    with _connect(admin) as ws:
        hello = _frame(ws)

    assert hello["data"]["theme"]["images"] == {
        "bg": None,
        "header": None,
        "logo": f"/assets/{logo}",
        "promo": None,
    }
