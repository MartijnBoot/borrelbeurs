"""Login, logout and /me over HTTP (Phase 3 T17: SD1, SD2, SD6-SD9; AC5, AC6, AC6a, AC6b, AC6e)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.api import security
from app.api.security import format_key, mint_secret
from app.cli.keys import main as keys_main
from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import BASE_URL, Login, MintKey
from tests.support.clock import FakeClock


class CountingVerifier:
    def __init__(self) -> None:
        self.calls = 0
        self._real = security.verify_secret

    def __call__(self, secret_hash: str, secret: str) -> bool:
        self.calls += 1
        return self._real(secret_hash, secret)


@pytest.fixture
def verifier(monkeypatch: pytest.MonkeyPatch) -> Iterator[CountingVerifier]:
    counting = CountingVerifier()
    monkeypatch.setattr(security, "verify_secret", counting)
    yield counting


def _key_id(raw: str) -> int:
    parsed = security.parse_key(raw)
    assert parsed is not None
    return parsed.key_id


def test_login_sets_a_secure_httponly_samesite_strict_cookie(
    client: TestClient, mint_key: MintKey
) -> None:
    """AC6a: the cookie attributes, read off the real Set-Cookie header."""
    response = client.post("/api/auth/login", json={"key": mint_key("bar", "Bar 1")})

    assert response.status_code == 200
    assert response.json() == {
        "role": "bar",
        "label": "Bar 1",
        "allowed_routes": ["/bar", "/manipulation"],
    }
    (cookie,) = response.headers.get_list("set-cookie")
    attributes = {part.strip().split("=")[0].lower() for part in cookie.split(";")}
    assert cookie.startswith("bb_session=")
    assert {"secure", "httponly", "samesite", "path", "max-age"} <= attributes
    assert "samesite=strict" in cookie.lower()
    assert "max-age=86400" in cookie.lower()


@pytest.mark.parametrize(
    ("role", "routes"),
    [
        ("display", ["/koers"]),
        ("bar", ["/bar", "/manipulation"]),
        ("admin", ["/", "/koers", "/bar", "/manipulation", "/settings"]),
    ],
)
def test_me_returns_sd2s_routes_per_role(login: Login, role: str, routes: list[str]) -> None:
    client = login(role, f"{role} key")

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"role": role, "label": f"{role} key", "allowed_routes": routes}


def test_me_without_a_session_is_401(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_logout_clears_the_cookie(login: Login) -> None:
    client = login("display")

    response = client.post("/api/auth/logout")

    assert response.status_code == 204
    assert (
        'bb_session=""' in response.headers["set-cookie"]
        or "max-age=0" in response.headers["set-cookie"].lower()
    )
    assert client.get("/api/auth/me").status_code == 401


def test_the_eleventh_login_is_429_with_retry_after_and_costs_no_verify(
    client: TestClient, verifier: CountingVerifier
) -> None:
    """AC5: ten attempts (malformed ones count too), then 429 before any parsing or hashing."""
    for _ in range(9):
        assert client.post("/api/auth/login", json={"key": "nonsense"}).status_code == 401
    assert (
        client.post("/api/auth/login", json={"key": format_key(9_999, mint_secret())}).status_code
        == 401
    )
    assert verifier.calls == 1

    response = client.post("/api/auth/login", json={"key": format_key(9_999, mint_secret())})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) == 60
    assert verifier.calls == 1


def test_the_login_window_rolls_on_the_injected_clock(
    client: TestClient, advance: Callable[[int], None]
) -> None:
    for _ in range(10):
        client.post("/api/auth/login", json={"key": "nonsense"})
    assert client.post("/api/auth/login", json={"key": "nonsense"}).status_code == 429

    advance(60_000)

    assert client.post("/api/auth/login", json={"key": "nonsense"}).status_code == 401


def test_exactly_one_verify_per_well_formed_login_and_none_for_malformed(
    client: TestClient, mint_key: MintKey, verifier: CountingVerifier
) -> None:
    """AC6: unknown, revoked, wrong secret and valid each cost one verify; malformed costs none."""
    valid = mint_key("bar")
    revoked = mint_key("bar")
    assert keys_main(["revoke", str(_key_id(revoked))]) == 0
    cases = {
        "malformed": ("bb_not_a_key!", 0, 401),
        "unknown": (format_key(9_999, mint_secret()), 1, 401),
        "revoked": (revoked, 1, 401),
        "wrong-secret": (format_key(_key_id(valid), mint_secret()), 1, 401),
        "valid": (valid, 1, 200),
    }
    for name, (raw, verifies, status) in cases.items():
        before = verifier.calls
        response = client.post("/api/auth/login", json={"key": raw})
        assert response.status_code == status, name
        assert verifier.calls - before == verifies, name


def test_a_rejected_login_never_echoes_the_key(client: TestClient) -> None:
    raw = format_key(1, mint_secret())

    for body in ({"key": raw}, {"key": raw, "extra": 1}, {"key": 5}):
        assert raw not in client.post("/api/auth/login", json=body).text


def test_login_updates_last_used_at(
    client: TestClient, mint_key: MintKey, settings: Settings, api_env: str
) -> None:
    raw = mint_key("bar")
    assert client.post("/api/auth/login", json={"key": raw}).status_code == 200

    async def last_used() -> object:
        from sqlalchemy import text

        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text("SELECT last_used_at FROM auth_key"))).scalar_one()
        finally:
            await engine.dispose()

    assert asyncio.run(last_used()) is not None


def test_revoking_a_key_ends_its_session_on_the_next_request(
    client: TestClient, mint_key: MintKey
) -> None:
    """AC6e: the row is loaded per request, so revoke takes effect before expiry."""
    raw = mint_key("admin")
    assert client.post("/api/auth/login", json={"key": raw}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert keys_main(["revoke", str(_key_id(raw))]) == 0

    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_a_session_expires_after_24_hours_on_the_injected_clock(
    login: Login, advance: Callable[[int], None]
) -> None:
    client = login("bar")
    advance(security.SESSION_MS - 1)
    assert client.get("/api/auth/me").status_code == 200

    advance(1)

    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "origin", [None, "", "https://evil.example", "https://testserver:8443", "testserver", "null"]
)
def test_an_unsafe_request_without_a_same_origin_origin_is_403(
    client: TestClient, mint_key: MintKey, origin: str | None
) -> None:
    """SD9: login and logout alike; the guard runs before the route."""
    headers = {"origin": origin} if origin is not None else {}
    client.headers.pop("origin", None)

    for path, body in (("/api/auth/login", {"key": mint_key("bar")}), ("/api/auth/logout", None)):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 403, (path, origin)
        assert response.json()["error"]["code"] == "origin_mismatch"


def test_a_safe_request_needs_no_origin(login: Login) -> None:
    client = login("display")
    client.headers.pop("origin", None)

    assert client.get("/api/auth/me").status_code == 200


def test_no_cors_middleware_is_installed(client: TestClient) -> None:
    """AC6b: one origin; nothing grants another site access."""
    classes = [middleware.cls for middleware in client.app.user_middleware]  # type: ignore[attr-defined]

    assert CORSMiddleware not in classes
    assert security.OriginGuard in classes
    response = client.options(
        "/api/auth/me",
        headers={"origin": "https://evil.example", "access-control-request-method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_a_validation_error_uses_the_one_error_envelope(client: TestClient) -> None:
    """PD9: FastAPI's 422 re-rendered as `invalid_request`."""
    response = client.post("/api/auth/login", json={})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["faults"][0]["loc"] == ["body", "key"]


def test_docs_are_served_outside_production(client: TestClient) -> None:
    """SD3: APP_ENV is not production in the test environment."""
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_docs_are_absent_in_production(
    api_env: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    with TestClient(create_app(clock=clock, run_migrations=False), base_url=BASE_URL) as client:
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert client.get(path).status_code == 404, path
        assert client.app.openapi()["info"]["title"] == "BorrelBeurs"  # type: ignore[attr-defined]
