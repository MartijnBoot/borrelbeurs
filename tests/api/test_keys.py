"""Access keys over HTTP (Phase 6 T16: SD30; AC36, AC37 (HTTP half), AC38).

`GET /api/keys` lists keys without a secret or hash; `POST /api/keys` shows
`bb_<key_id>_<secret>` once and stores only its argon2id hash; `DELETE
/api/keys/{key_id}` revokes, refusing the last unrevoked admin key.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import security
from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import Login


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
    """AC36."""
    admin = login("admin")

    response = admin.post("/api/keys", json={"role": "bar", "label": " Tap 1 "})

    assert response.status_code == 201, response.text
    created = response.json()
    raw = created["key"]
    parsed = security.parse_key(raw)
    assert parsed is not None and parsed.key_id == created["key_id"]
    stored = _sql(
        settings, api_env, "SELECT secret_hash FROM auth_key WHERE key_id = :k", k=parsed.key_id
    )
    assert stored.startswith("$argon2id$")
    assert parsed.secret not in stored
    listed = admin.get("/api/keys").json()
    row = next(k for k in listed if k["key_id"] == parsed.key_id)
    assert row["label"] == "Tap 1" and row["role"] == "bar" and row["revoked"] is False
    assert set(row) == {"key_id", "label", "role", "created_at", "last_used_at", "revoked"}
    assert parsed.secret not in admin.get("/api/keys").text


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


def test_a_revoked_sessions_next_request_is_401(client: TestClient, mint_key: Any) -> None:
    """AC37, HTTP half."""
    admin = sign_in(client, mint_key("admin"))
    raw = mint_key("bar")
    bar = sign_in(client, raw)
    parsed = security.parse_key(raw)
    assert parsed is not None

    response = switch(client, admin).delete(f"/api/keys/{parsed.key_id}")

    assert response.status_code == 204, response.text
    assert switch(client, bar).get("/api/auth/me").status_code == 401
    listed = {k["key_id"]: k["revoked"] for k in switch(client, admin).get("/api/keys").json()}
    assert listed[parsed.key_id] is True


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
