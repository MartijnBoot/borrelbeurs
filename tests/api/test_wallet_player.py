"""The player's own routes and the wallet guard (B-05 T6: SD8, SD15, SD19; AC11-AC13, AC29)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.db.wallets import WalletSettingsRow
from app.runtime.wallet_codes import cookie_hash
from tests.api.conftest import Login

CODE = "Borrel2026"


def _db(settings: Settings, url: str, body: Callable[[AsyncConnection], Any]) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _sql(settings: Settings, url: str, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async def body(conn: AsyncConnection) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in await conn.execute(text(sql), params)]

    return list(_db(settings, url, body))


@pytest.fixture
def player(api_env: str, settings: Settings, client: TestClient) -> dict[str, Any]:
    """A signed-up wallet "Jan"; `client` holds its cookie."""
    _db(settings, api_env, lambda conn: wallets.put_settings(conn, WalletSettingsRow(CODE)))
    response = client.post("/api/wallet", json={"name": "Jan", "code": CODE})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    body["cookie"] = client.cookies["bb_wallet"]
    ((wallet_id,),) = _sql(settings, api_env, "SELECT wallet_id FROM wallet")
    body["wallet_id"] = wallet_id
    return body


def _top_up(settings: Settings, url: str, wallet_id: int, amount: int) -> None:
    _db(
        settings,
        url,
        lambda conn: wallets.insert_entry(
            conn, wallet_id=wallet_id, kind="topup", amount_cents=amount, now_ms=0
        ),
    )


def _attributes(cookie: str) -> set[str]:
    return {part.strip().lower() for part in cookie.split(";")}


def test_get_shows_the_wallet_and_renews_the_cookie(
    player: dict[str, Any], client: TestClient, advance: Callable[[int], None]
) -> None:
    """AC11: every visit, the same value with another 400 days."""
    advance(30 * 24 * 3600 * 1000)

    response = client.get("/api/wallet")

    assert response.status_code == 200
    assert response.json() == {k: player[k] for k in response.json()}
    (cookie,) = response.headers.get_list("set-cookie")
    assert cookie.startswith(f"bb_wallet={player['cookie']};")
    assert {"httponly", "samesite=strict", "path=/", "max-age=34560000", "secure"} <= _attributes(
        cookie
    )


@pytest.mark.parametrize("credential", ["qr_token", "short_code"])
def test_the_qr_token_or_short_code_opens_nothing(
    player: dict[str, Any], client: TestClient, credential: str
) -> None:
    """AC12: neither is a credential for the player's page."""
    client.cookies.clear()
    client.cookies.set("bb_wallet", player[credential])

    assert client.get("/api/wallet").status_code == 401
    assert client.delete("/api/wallet").status_code == 401


def test_only_the_cookies_hash_is_stored(
    player: dict[str, Any], settings: Settings, api_env: str
) -> None:
    """AC12."""
    ((stored,),) = _sql(settings, api_env, "SELECT cookie_hash FROM wallet")

    assert stored == cookie_hash(player["cookie"])
    assert stored != player["cookie"]


def test_a_deleted_wallets_cookie_is_401_and_cleared(
    player: dict[str, Any], client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC13: deleted elsewhere (here by the repository, as an admin delete is)."""
    _db(
        settings,
        api_env,
        lambda conn: wallets.delete_wallet(conn, player["wallet_id"], now_ms=0),
    )

    response = client.get("/api/wallet")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "no_wallet"
    (cookie,) = response.headers.get_list("set-cookie")
    assert cookie.startswith("bb_wallet=")
    assert "max-age=0" in _attributes(cookie)


def test_the_player_deletes_their_wallet(
    player: dict[str, Any], client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC29: a closing entry of the balance, the row blanked, the cookie cleared, the
    name free again."""
    _top_up(settings, api_env, player["wallet_id"], 3500)

    response = client.delete("/api/wallet")

    assert response.status_code == 204
    (cookie,) = response.headers.get_list("set-cookie")
    assert "max-age=0" in _attributes(cookie)
    assert _sql(
        settings, api_env, "SELECT kind, amount_cents FROM wallet_entry ORDER BY entry_id"
    ) == [("topup", 3500), ("closing", -3500)]
    assert _sql(
        settings,
        api_env,
        "SELECT name, qr_token, short_code, cookie_hash, deleted_at IS NOT NULL FROM wallet",
    ) == [(None, None, None, None, True)]

    client.cookies.clear()
    again = client.post("/api/wallet", json={"name": "jan", "code": CODE})
    assert again.status_code == 201
    assert again.json()["name"] == "jan"


def test_self_delete_while_draining_is_503_and_writes_nothing(
    player: dict[str, Any], client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC44."""
    _top_up(settings, api_env, player["wallet_id"], 1000)
    client.app.state.draining = True  # type: ignore[attr-defined]
    try:
        response = client.delete("/api/wallet")
    finally:
        client.app.state.draining = False  # type: ignore[attr-defined]

    assert (response.status_code, response.json()["error"]["code"]) == (503, "shutting_down")
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet_entry") == [(1,)]
    assert client.get("/api/wallet").json()["balance_cents"] == 1000


def test_one_phone_can_be_crew_and_player(
    player: dict[str, Any], client: TestClient, login: Login
) -> None:
    """SD19: `bb_wallet` and `bb_session` live side by side."""
    login("bar")

    assert client.get("/api/auth/me").json()["role"] == "bar"
    assert client.get("/api/wallet").json()["name"] == "Jan"
