"""The authorization matrix (Phase 3 T28: SD1, SD4; AC1, AC6d 403 half).

SD1's table is written out **here**, as data, independent of the app's code. Every
(route, actor) pair is exercised: anonymous and a revoked key get 401, a role not
in the row gets 403, a permitted role gets neither. A completeness check compares
the table to the routes the app actually serves, so a new route without a row
fails here. If the matrix ever disagrees with SD1, the code is wrong, not the table.
"""

from __future__ import annotations

from typing import Final

import pytest
from fastapi.testclient import TestClient

from app.api import security
from app.cli.keys import main as keys_main
from tests.api.conftest import MintKey
from tests.meta.test_route_authorization import PUBLIC_ROUTES, flatten

# B-05 SD7 (plan PD1 reading A): a kassa session keeps its own routes and the market
# feed; every other route below is 403 for it (AC36).
ALL: Final = frozenset({"display", "bar", "admin", "kassa"})
MARKET: Final = frozenset({"display", "bar", "admin"})
WRITERS: Final = frozenset({"bar", "admin"})
ADMIN: Final = frozenset({"admin"})
# B-05 SD7.
KASSA: Final = frozenset({"kassa", "admin"})

# SD1, verbatim. (method, path) -> roles allowed.
SD1: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("POST", "/api/auth/logout"): ALL,
    ("GET", "/api/auth/me"): ALL,
    ("GET", "/api/state"): ALL,
    ("GET", "/api/news"): MARKET,
    ("WS", "/ws"): ALL,
    ("POST", "/api/orders"): WRITERS,
    ("POST", "/api/news"): WRITERS,
    ("DELETE", "/api/news/{news_id}"): WRITERS,
    ("POST", "/api/market/jumps"): WRITERS,
    ("POST", "/api/market/events"): WRITERS,
    ("POST", "/api/admin/shutdown"): ADMIN,
    # Phase 4 SD5.
    ("PUT", "/api/theme"): ADMIN,
    # Phase 5 SD19.
    ("GET", "/api/earnings/series"): WRITERS,
    # Phase 6 SD2, SD4 (PD2).
    ("POST", "/api/runs"): ADMIN,
    ("GET", "/api/runs/current"): ADMIN,
    ("POST", "/api/runs/{run_id}/go-live"): ADMIN,
    # Phase 6 SD5.
    ("GET", "/api/runs/{run_id}/config"): ADMIN,
    ("PATCH", "/api/runs/{run_id}/config"): ADMIN,
    ("POST", "/api/runs/{run_id}/drinks"): ADMIN,
    ("PATCH", "/api/runs/{run_id}/drinks/{drink_id}"): ADMIN,
    ("DELETE", "/api/runs/{run_id}/drinks/{drink_id}"): ADMIN,
    ("POST", "/api/runs/{run_id}/anchor-s0"): ADMIN,
    # Phase 6 SD30, AC41.
    ("GET", "/api/keys"): ADMIN,
    ("POST", "/api/keys"): ADMIN,
    ("DELETE", "/api/keys/{key_id}"): ADMIN,
    ("GET", "/api/admin/connections"): ADMIN,
    # Phase 6 SD29.
    ("POST", "/api/theme/images/{slot}"): ADMIN,
    ("DELETE", "/api/theme/images/{slot}"): ADMIN,
    # Phase 7 SD2.
    ("POST", "/api/runs/{run_id}/close"): ADMIN,
    # Phase 7 SD3.
    ("DELETE", "/api/runs/{run_id}"): ADMIN,
    # Phase 7 SD12.
    ("GET", "/api/analytics/runs"): ADMIN,
    ("GET", "/api/analytics/runs/{run_id}"): ADMIN,
    ("GET", "/api/analytics/compare"): ADMIN,
    ("GET", "/api/analytics/price-curve"): ADMIN,
    ("POST", "/api/runs/{run_id}/exports"): ADMIN,
    ("GET", "/api/runs/{run_id}/exports"): ADMIN,
    ("GET", "/api/exports/{export_id}"): ADMIN,
    ("GET", "/api/exports/{export_id}/file"): ADMIN,
    # B-04 SD14.
    ("GET", "/api/profiles"): ADMIN,
    ("POST", "/api/profiles"): ADMIN,
    ("DELETE", "/api/profiles/{profile_id}"): ADMIN,
    ("POST", "/api/runs/{run_id}/profile"): ADMIN,
    # B-05 SD7, SD10, SD22.
    ("POST", "/api/kassa/lookup"): KASSA,
    ("GET", "/api/kassa/wallets/{wallet_id}/topups"): KASSA,
    ("POST", "/api/kassa/wallets/{wallet_id}/topups"): KASSA,
    # B-05 SD11, SD12, SD14.
    ("POST", "/api/kassa/topups/{entry_id}/reversal"): KASSA,
    ("GET", "/api/kassa/wallets"): KASSA,
    ("POST", "/api/kassa/wallets/{wallet_id}/move"): KASSA,
    ("POST", "/api/kassa/wallets/{wallet_id}/new-code"): KASSA,
    # B-05 SD6, SD15, SD16.
    ("GET", "/api/admin/wallets"): ADMIN,
    ("DELETE", "/api/admin/wallets/{wallet_id}"): ADMIN,
    ("GET", "/api/admin/wallet-settings"): ADMIN,
    ("PUT", "/api/admin/wallet-settings"): ADMIN,
    # B-06 SD9, SD13 (PD9).
    ("POST", "/api/bar/wallet-lookup"): WRITERS,
    ("GET", "/api/bar/payments"): WRITERS,
}

# B-05 SD8: the player's own routes. A player is not a role: these carry
# `require_wallet`, and every crew session without a wallet cookie is 401 there.
WALLET_ROUTES: Final = frozenset({("GET", "/api/wallet"), ("DELETE", "/api/wallet")})

ACTORS: Final = ("anonymous", "revoked", "display", "bar", "admin", "kassa")


def _served_routes(client: TestClient) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in flatten(client.app.routes):  # type: ignore[attr-defined]
        methods = getattr(route, "methods", None)
        if methods:
            keys.update((m, route.path) for m in set(methods) - {"HEAD"})
        elif type(getattr(route, "original_route", route)).__name__.endswith("WebSocketRoute"):
            keys.add(("WS", route.path))
    return keys


def test_the_table_covers_every_served_route(client: TestClient) -> None:
    """A route added without a row here -- or a row whose route is gone -- fails."""
    public = {key for key in PUBLIC_ROUTES if key[0] != "MOUNT"}
    served = _served_routes(client) - public - WALLET_ROUTES

    assert served == set(SD1)
    assert _served_routes(client) >= WALLET_ROUTES


@pytest.mark.parametrize("actor", ["anonymous", "display", "bar", "kassa", "admin"])
@pytest.mark.parametrize(("method", "path"), sorted(WALLET_ROUTES))
def test_a_player_route_needs_the_wallet_cookie_not_a_session(
    client: TestClient, mint_key: MintKey, method: str, path: str, actor: str
) -> None:
    """B-05 AC38: a crew session without a wallet cookie is 401 `no_wallet`."""
    _act(client, mint_key, actor)

    response = client.request(method, path)

    assert response.status_code == 401, (method, path, actor)
    assert response.json()["error"]["code"] == "no_wallet"


def _act(client: TestClient, mint_key: MintKey, actor: str) -> None:
    client.cookies.clear()
    if actor == "anonymous":
        return
    raw = mint_key("bar" if actor == "revoked" else actor)
    assert client.post("/api/auth/login", json={"key": raw}).status_code == 200
    if actor == "revoked":
        parsed = security.parse_key(raw)
        assert parsed is not None
        assert keys_main(["revoke", str(parsed.key_id)]) == 0


def _status(client: TestClient, method: str, path: str) -> int:
    url = (
        path.replace("{news_id}", "999999")
        .replace("{run_id}", "999999")
        .replace("{drink_id}", "999999")
        .replace("{key_id}", "999999")
        .replace("{export_id}", "999999")
        .replace("{profile_id}", "999999")
        .replace("{wallet_id}", "999999")
        .replace("{entry_id}", "999999")
        .replace("{slot}", "bg")
    )
    if method == "WS":
        from starlette.websockets import WebSocketDisconnect

        try:
            # wss: the session cookie is Secure (SD8), as in tests/api/test_ws.py.
            with client.websocket_connect(f"wss://testserver{url}") as ws:
                ws.receive_text()
            return 101
        except WebSocketDisconnect as closed:
            return 401 if closed.code == 1008 else 101
    body: dict[str, object] | None = {} if method in {"POST", "DELETE", "PATCH"} else None
    if method == "PUT":
        body = {"preset": "blauw"}  # valid, so a permitted role is not refused for its body
    response = client.request(method, url, json=body, headers={"Idempotency-Key": "k-matrix-0001"})
    return int(response.status_code)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize(("method", "path"), sorted(SD1))
def test_every_route_and_actor(
    live_client: TestClient, mint_key: MintKey, method: str, path: str, actor: str
) -> None:
    """AC1: 401 for anonymous and revoked, 403 for a role not in the row, else neither."""
    if (method, path) == ("POST", "/api/admin/shutdown") and actor == "admin":
        live_client.app.state.request_shutdown = lambda: None  # type: ignore[attr-defined]
    _act(live_client, mint_key, actor)

    status = _status(live_client, method, path)

    if actor in {"anonymous", "revoked"}:
        assert status == 401, (method, path, actor, status)
    elif actor not in SD1[(method, path)]:
        expected = 401 if method == "WS" else 403  # a refused handshake has one close code, 1008
        assert status == expected, (method, path, actor, status)
    else:
        assert status not in {401, 403}, (method, path, actor, status)


@pytest.mark.parametrize(("run_id", "expected"), [("other", 403), ("live", 200)])
def test_the_bar_reads_only_the_live_runs_series(
    live_client: TestClient, live_run: int, mint_key: MintKey, run_id: str, expected: int
) -> None:
    """Phase 7 SD9, AC16: inside the route's row, any other run is admin-only.

    The other run is unknown here, so the bar learns nothing from 403 vs 404.
    """
    _act(live_client, mint_key, "bar")
    target = live_run if run_id == "live" else 999_999

    response = live_client.get("/api/earnings/series", params={"run_id": target})

    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["error"]["code"] == "forbidden"
