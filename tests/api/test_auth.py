"""Login, logout and /me over HTTP (Phase 3 T17: SD1, SD2, SD6-SD9; AC5, AC6, AC6a, AC6b, AC6e).

B-08 (AC2, AC4, AC5, AC7): a key is read forgivingly, and any well-formed one
costs exactly one hash, counted through `security.key_hash`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.api import security
from app.cli.keys import main as keys_main
from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import BASE_URL, IssueKey, Login, MintKey
from tests.support.clock import FakeClock


class CountingHasher:
    def __init__(self) -> None:
        self.calls = 0
        self._real = security.key_hash

    def __call__(self, symbols: str) -> str:
        self.calls += 1
        return self._real(symbols)


@pytest.fixture
def hasher(monkeypatch: pytest.MonkeyPatch) -> Iterator[CountingHasher]:
    counting = CountingHasher()
    monkeypatch.setattr(security, "key_hash", counting)
    yield counting


def _unknown_key() -> str:
    return security.display_key(security.new_key_symbols())


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
        ("admin", ["/", "/koers", "/bar", "/manipulation", "/settings", "/analytics", "/kassa"]),
        # B-05 SD7, AC36.
        ("kassa", ["/kassa"]),
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


def test_the_eleventh_login_is_429_with_retry_after_and_costs_no_hash(
    client: TestClient, hasher: CountingHasher
) -> None:
    """AC5, B-08 AC7: ten attempts (malformed ones count too), then 429 before any hashing."""
    for _ in range(9):
        assert client.post("/api/auth/login", json={"key": "nonsense"}).status_code == 401
    assert client.post("/api/auth/login", json={"key": _unknown_key()}).status_code == 401
    assert hasher.calls == 1

    response = client.post("/api/auth/login", json={"key": _unknown_key()})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) == 60
    assert hasher.calls == 1


def test_the_login_window_rolls_on_the_injected_clock(
    client: TestClient, advance: Callable[[int], None]
) -> None:
    for _ in range(10):
        client.post("/api/auth/login", json={"key": "nonsense"})
    assert client.post("/api/auth/login", json={"key": "nonsense"}).status_code == 429

    advance(60_000)

    assert client.post("/api/auth/login", json={"key": "nonsense"}).status_code == 401


def test_exactly_one_hash_per_well_formed_login_and_none_for_malformed(
    client: TestClient, issued_key: IssueKey, hasher: CountingHasher
) -> None:
    """B-08 AC4, AC5: unknown, revoked and valid each cost one hash; malformed costs none."""
    valid = issued_key("bar")
    revoked = issued_key("bar")
    assert keys_main(["revoke", str(revoked.key_id)]) == 0
    symbols = security.normalise_key(valid.key)
    assert symbols is not None
    cases = {
        "malformed": ("bb_not_a_key!", 0, 401),
        "long-key": ("bb_1_" + "x" * 43, 0, 401),
        "8-symbols": (symbols[:8], 0, 401),
        "10-symbols": (symbols + "0", 0, 401),
        "unknown": (_unknown_key(), 1, 401),
        "revoked": (revoked.key, 1, 401),
        "valid": (valid.key, 1, 200),
    }
    bodies: dict[str, bytes] = {}
    for name, (raw, hashes, status) in cases.items():
        client.cookies.clear()
        before = hasher.calls
        response = client.post("/api/auth/login", json={"key": raw})
        assert response.status_code == status, name
        assert hasher.calls - before == hashes, name
        bodies[name] = response.content

    assert bodies["unknown"] == bodies["revoked"]


def test_every_forgiving_spelling_of_a_key_logs_in(
    client: TestClient, mint_key: MintKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-08 AC2: case, spaces, dashes, whitespace and O/I/L for 0/1/1 all read as the key."""
    monkeypatch.setattr(security, "new_key_symbols", lambda: "K7M4QX901")
    key = mint_key("bar")
    assert key == "K7M-4QX-901"

    for spelling in (
        "k7m-4qx-901",
        "K7M 4QX 901",
        "K7M4QX901",
        " K7M-4QX-901\n",
        "K 7 M-4Q X901",
        "K7M-4QX-9OL",
        "k7m4qx9oi",
    ):
        client.cookies.clear()
        response = client.post("/api/auth/login", json={"key": spelling})
        assert response.status_code == 200, spelling


def test_a_rejected_login_never_echoes_the_key(client: TestClient) -> None:
    raw = _unknown_key()

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
    client: TestClient, issued_key: IssueKey
) -> None:
    """AC6e: the row is loaded per request, so revoke takes effect before expiry."""
    issued = issued_key("admin")
    assert client.post("/api/auth/login", json={"key": issued.key}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert keys_main(["revoke", str(issued.key_id)]) == 0

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


@pytest.mark.parametrize(("app_env", "secure"), [("production", "true"), ("venue", "false")])
def test_docs_are_absent_in_production_and_at_the_venue(
    api_env: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch, app_env: str, secure: str
) -> None:
    """SD3; AC25: the venue boots with a plain-http cookie and still hides the docs."""
    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", secure)
    get_settings.cache_clear()
    with TestClient(create_app(clock=clock, run_migrations=False), base_url=BASE_URL) as client:
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert client.get(path).status_code == 404, path
        assert client.app.openapi()["info"]["title"] == "BorrelBeurs"  # type: ignore[attr-defined]
