"""Access keys over HTTP (Phase 6 T16: SD30; AC36, AC37 (HTTP half), AC38).

`GET /api/keys` lists keys without a secret or hash; `POST /api/keys` shows
the grouped 9-symbol key once and stores only its argon2id hash (B-08); `DELETE
/api/keys/{key_id}` revokes, refusing the last unrevoked admin key.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import security
from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import IssueKey, Login, MintKey

GROUPED = re.compile(r"[0-9A-HJKMNP-TV-Z]{3}(-[0-9A-HJKMNP-TV-Z]{3}){2}")


def _sql(settings: Settings, url: str, sql: str, **bind: Any) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), bind)
                return result.scalar_one() if result.returns_rows else None
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def sign_in(client: TestClient, raw: str) -> httpx.Cookies:
    """Log `client` in with `raw`; the session's cookie jar, to switch back to it later.

    One `TestClient` serves every identity: a second, never-entered one would run
    the app on another event loop than its database engine's.
    """
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"key": raw}).status_code == 200
    return httpx.Cookies(client.cookies)


def switch(client: TestClient, jar: httpx.Cookies) -> TestClient:
    client.cookies.clear()
    client.cookies.update(jar)
    return client


def test_create_shows_the_key_once_and_stores_only_its_hash(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC36; B-08 AC1, AC3: a grouped 9-symbol key, and the new row's own `key_id`."""
    admin = login("admin")

    response = admin.post("/api/keys", json={"role": "bar", "label": " Tap 1 "})

    assert response.status_code == 201, response.text
    created = response.json()
    raw = created["key"]
    assert GROUPED.fullmatch(raw), raw
    assert "bb_" not in raw and str(created["key_id"]) not in raw.split("-")
    symbols = security.normalise_key(raw)
    assert symbols is not None
    stored = _sql(
        settings,
        api_env,
        "SELECT secret_hash FROM auth_key WHERE key_id = :k",
        k=created["key_id"],
    )
    assert stored == security.key_hash(symbols)
    listed = admin.get("/api/keys").json()
    row = next(k for k in listed if k["key_id"] == created["key_id"])
    assert row["label"] == "Tap 1" and row["role"] == "bar" and row["revoked"] is False
    assert set(row) == {"key_id", "label", "role", "created_at", "last_used_at", "revoked"}


def test_the_key_is_nowhere_after_mint_and_login(
    client: TestClient,
    mint_key: MintKey,
    settings: Settings,
    api_env: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B-08 AC8: not in the row, the logs or the listing, whole or by group.

    The draw is pinned to letters only, so a group cannot turn up by chance in a
    timestamp or an id. The groups are not looked for in `secret_hash`: a
    3-character match in base64 is a coincidence, not a leak (plan R9).
    """
    caplog.set_level(logging.DEBUG)
    admin = sign_in(client, mint_key("admin"))
    monkeypatch.setattr(security, "new_key_symbols", lambda: "KXMWQPRZH")

    raw = client.post("/api/keys", json={"role": "bar", "label": "Tap 1"}).json()["key"]
    sign_in(client, raw)

    assert raw == "KXM-WQP-RZH"
    forms = (raw, "KXMWQPRZH")
    row = _row(settings, api_env, raw)
    for column, value in row.items():
        assert not any(form in str(value) for form in forms), f"auth_key.{column}"
    assert caplog.records, "nothing was logged: the check below would be vacuous"
    assert not any(form in caplog.text for form in forms)
    listing = switch(client, admin).get("/api/keys").text
    assert not any(part in listing for part in (*forms, "KXM", "WQP", "RZH"))


def _row(settings: Settings, url: str, raw: str) -> dict[str, Any]:
    symbols = security.normalise_key(raw)
    assert symbols is not None

    async def scenario() -> dict[str, Any]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT * FROM auth_key WHERE secret_hash = :h"),
                    {"h": security.key_hash(symbols)},
                )
                return dict(result.one()._mapping)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _count(settings: Settings, url: str) -> int:
    count: int = _sql(settings, url, "SELECT count(*) FROM auth_key")
    return count


def test_a_draw_that_collides_is_drawn_again(
    issued_key: IssueKey, settings: Settings, api_env: str
) -> None:
    """B-08 AC9: four taken draws, then a free one, is five draws and one new row."""
    taken = security.normalise_key(issued_key("bar").key)
    assert taken is not None
    draws = [taken, taken, taken, taken, "KXMWQPRZH"]
    drawn: list[str] = []

    def draw() -> str:
        drawn.append(draws[len(drawn)])
        return drawn[-1]

    async def scenario() -> security.IssuedKey:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            async with engine.begin() as conn:
                return await security.issue_key(conn, role="bar", label="Tap 2", draw=draw)
        finally:
            await engine.dispose()

    issued = asyncio.run(scenario())

    assert len(drawn) == 5
    assert issued.key == "KXM-WQP-RZH"
    assert _count(settings, api_env) == 2


def test_five_collisions_write_nothing(
    issued_key: IssueKey, settings: Settings, api_env: str
) -> None:
    """B-08 AC9: five taken draws raise `KeyDrawExhausted` and insert no row."""
    taken = security.normalise_key(issued_key("bar").key)
    assert taken is not None
    drawn: list[str] = []

    def draw() -> str:
        drawn.append(taken)
        return taken

    async def scenario() -> None:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            async with engine.begin() as conn:
                await security.issue_key(conn, role="bar", label="Tap 2", draw=draw)
        finally:
            await engine.dispose()

    with pytest.raises(security.KeyDrawExhausted):
        asyncio.run(scenario())

    assert len(drawn) == 5
    assert _count(settings, api_env) == 1


def test_a_create_that_keeps_colliding_is_500_and_writes_nothing(
    client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-08 AC9, API half: the generic 500, and no row."""
    admin = login("admin")
    taken = security.normalise_key(
        admin.post("/api/keys", json={"role": "bar", "label": "Tap 1"}).json()["key"]
    )
    assert taken is not None
    before = _count(settings, api_env)
    monkeypatch.setattr(security, "new_key_symbols", lambda: taken)

    response = admin.post("/api/keys", json={"role": "bar", "label": "Tap 2"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert _count(settings, api_env) == before


def test_the_created_key_logs_in(client: TestClient, login: Login) -> None:
    raw = (
        login("admin").post("/api/keys", json={"role": "display", "label": "Scherm"}).json()["key"]
    )
    client.cookies.clear()

    response = client.post("/api/auth/login", json={"key": raw})

    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "body",
    [
        {"role": "root", "label": "x"},
        {"role": "bar", "label": "  "},
        {"role": "bar", "label": "x" * 101},
        {"role": "bar"},
        {"role": "bar", "label": "x", "secret": "mine"},
    ],
)
def test_an_invalid_create_is_422(client: TestClient, login: Login, body: Any) -> None:
    assert login("admin").post("/api/keys", json=body).status_code == 422


def test_a_revoked_sessions_next_request_is_401(
    client: TestClient, mint_key: MintKey, issued_key: IssueKey
) -> None:
    """AC37, HTTP half."""
    admin = sign_in(client, mint_key("admin"))
    issued = issued_key("bar")
    bar = sign_in(client, issued.key)

    response = switch(client, admin).delete(f"/api/keys/{issued.key_id}")

    assert response.status_code == 204, response.text
    assert switch(client, bar).get("/api/auth/me").status_code == 401
    listed = {k["key_id"]: k["revoked"] for k in switch(client, admin).get("/api/keys").json()}
    assert listed[issued.key_id] is True


def test_revoking_the_last_unrevoked_admin_is_409(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC38."""
    admin = login("admin")
    (only,) = [k["key_id"] for k in admin.get("/api/keys").json() if k["role"] == "admin"]

    response = admin.delete(f"/api/keys/{only}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_admin_key"
    revoked = _sql(
        settings, api_env, "SELECT revoked_at IS NOT NULL FROM auth_key WHERE key_id = :k", k=only
    )
    assert revoked is False


def test_with_two_admins_one_may_be_revoked(client: TestClient, login: Login) -> None:
    admin = login("admin")
    second = admin.post("/api/keys", json={"role": "admin", "label": "Tweede"}).json()["key_id"]

    assert admin.delete(f"/api/keys/{second}").status_code == 204


def test_an_unknown_key_is_404(client: TestClient, login: Login) -> None:
    response = login("admin").delete("/api/keys/999999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "key_not_found"


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(client: TestClient, login: Login, role: str) -> None:
    session = login(role)

    assert session.get("/api/keys").status_code == 403
    assert session.post("/api/keys", json={"role": "bar", "label": "x"}).status_code == 403
    assert session.delete("/api/keys/1").status_code == 403
