"""Wallet sign-up and the name check, public (B-05 T5: SD3, SD6, SD19; AC3-AC8, AC11, AC19)."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

import app.db.wallets
from app.core.config import Settings, get_settings
from app.db import wallets
from app.db.session import create_engine
from app.db.wallets import WalletSettingsRow
from app.main import create_app
from tests.api.conftest import BASE_URL
from tests.support.clock import FakeClock

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


def _count(settings: Settings, url: str, table: str = "wallet") -> int:
    async def body(conn: AsyncConnection) -> int:
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())

    return int(_db(settings, url, body))


@pytest.fixture
def signup_code(api_env: str, settings: Settings) -> str:
    """The deployment's sign-up code, set through the repository before the app boots."""
    _db(settings, api_env, lambda conn: wallets.put_settings(conn, WalletSettingsRow(CODE)))
    return CODE


def _sign_up(client: TestClient, name: str = "Jan", code: str = CODE) -> Any:
    return client.post("/api/wallet", json={"name": name, "code": code})


def test_a_free_name_makes_an_empty_wallet_and_sets_its_cookie(
    signup_code: str, client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC3, AC11, AC19 (no live run)."""
    response = _sign_up(client, " Jan ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["name"], body["balance_cents"]) == ("Jan", 0)
    assert len(body["short_code"]) == 9 and body["short_code"][4] == "-"
    assert body["qr_token"]
    (cookie,) = response.headers.get_list("set-cookie")
    assert cookie.startswith("bb_wallet=")
    attributes = {part.strip().lower() for part in cookie.split(";")}
    assert {"httponly", "samesite=strict", "path=/", "max-age=34560000", "secure"} <= attributes
    assert _count(settings, api_env) == 1


@pytest.mark.parametrize("secure", [True, False])
def test_the_wallet_cookie_is_secure_exactly_when_the_crew_cookie_is(
    signup_code: str, api_env: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch, secure: bool
) -> None:
    """AC11, SD19: `cookie_kwargs`, so plain HTTP at the venue."""
    monkeypatch.setenv("SESSION_COOKIE_SECURE", str(secure).lower())
    get_settings.cache_clear()
    app = create_app(clock=clock, run_migrations=False)
    with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
        (cookie,) = _sign_up(client).headers.get_list("set-cookie")

    assert ("secure" in {part.strip().lower() for part in cookie.split(";")}) is secure


@pytest.mark.parametrize("typed", ["jan", "Jan ", "  JAN"])
def test_a_taken_name_is_409_with_suggestions_and_the_check_agrees(
    signup_code: str, client: TestClient, settings: Settings, api_env: str, typed: str
) -> None:
    """AC4: compared trimmed and case-folded; nothing created; the check says the same."""
    assert _sign_up(client, "Jan").status_code == 201
    client.cookies.clear()
    assert _sign_up(client, "Jan 2").status_code == 201
    client.cookies.clear()

    refused = _sign_up(client, typed)
    checked = client.post("/api/wallet/name-check", json={"name": typed, "code": CODE})

    expected = [f"{typed.strip()} {n}" for n in (3, 4, 5)]
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "name_taken"
    assert refused.json()["error"]["suggestions"] == expected
    assert "set-cookie" not in refused.headers
    assert checked.json() == {"available": False, "suggestions": expected}
    assert _count(settings, api_env) == 2


def test_a_free_name_checks_available(signup_code: str, client: TestClient) -> None:
    response = client.post("/api/wallet/name-check", json={"name": "Anna", "code": CODE})

    assert response.json() == {"available": True, "suggestions": []}


def test_two_sign_ups_of_one_free_name_at_once_make_one_wallet(
    signup_code: str,
    client: TestClient,
    settings: Settings,
    api_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5: the first insert holds its transaction open; the second waits on the unique
    index and, once the first commits, gets `name_taken`."""
    create = app.db.wallets.create_wallet

    async def slow_create(conn: AsyncConnection, **kwargs: Any) -> Any:
        row = await create(conn, **kwargs)
        await conn.execute(text("SELECT pg_sleep(0.3)"))
        return row

    monkeypatch.setattr(app.db.wallets, "create_wallet", slow_create)
    statuses: list[int] = []

    def one() -> None:
        # No shared cookie jar: each thread is its own phone.
        response = client.post(
            "/api/wallet", json={"name": "Jan", "code": CODE}, headers={"cookie": ""}
        )
        statuses.append(response.status_code)

    threads = [threading.Thread(target=one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [201, 409]
    assert _count(settings, api_env) == 1


@pytest.mark.parametrize(
    ("code", "status", "error"),
    [("Fout", 403, "signup_code_invalid"), ("", 403, "signup_code_invalid")],
)
def test_a_wrong_code_is_403_and_creates_nothing(
    signup_code: str,
    client: TestClient,
    settings: Settings,
    api_env: str,
    code: str,
    status: int,
    error: str,
) -> None:
    """AC6."""
    for path in ("/api/wallet", "/api/wallet/name-check"):
        response = client.post(path, json={"name": "Jan", "code": code})
        assert (response.status_code, response.json()["error"]["code"]) == (status, error)

    assert _count(settings, api_env) == 0


def test_with_no_code_set_sign_up_is_closed(
    client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC6, SD6: no wallet settings row at all."""
    response = _sign_up(client, code="anything")

    assert (response.status_code, response.json()["error"]["code"]) == (409, "signup_closed")
    assert _count(settings, api_env) == 0


@pytest.mark.parametrize("name", ["", "   ", "x" * 41], ids=["empty", "blank", "41-chars"])
def test_a_name_empty_after_trimming_or_over_forty_is_422(
    signup_code: str, client: TestClient, settings: Settings, api_env: str, name: str
) -> None:
    """AC6."""
    response = _sign_up(client, name)

    assert response.status_code == 422
    assert _count(settings, api_env) == 0


def test_the_code_is_compared_trimmed_and_ignoring_case(
    api_env: str, settings: Settings, client: TestClient
) -> None:
    """SD6."""
    _db(settings, api_env, lambda conn: wallets.put_settings(conn, WalletSettingsRow(" ABC ")))

    assert _sign_up(client, code="abc").status_code == 201


def test_the_sixth_sign_up_or_check_in_a_minute_is_429(
    signup_code: str, client: TestClient, advance: Callable[[int], None]
) -> None:
    """AC7: one limiter for both, five per minute by default; the window slides."""
    answers = [
        client.post("/api/wallet/name-check", json={"name": "Jan", "code": CODE}).status_code,
        _sign_up(client, "Jan").status_code,
        client.post("/api/wallet/name-check", json={"name": "Piet", "code": CODE}).status_code,
        _sign_up(client, "x", code="Fout").status_code,
        client.post("/api/wallet/name-check", json={"name": "", "code": CODE}).status_code,
    ]
    sixth = client.post("/api/wallet/name-check", json={"name": "Anna", "code": CODE})

    assert answers == [200, 201, 200, 200, 422]  # the fourth: this phone already has a wallet
    assert sixth.status_code == 429
    assert sixth.json()["error"]["code"] == "rate_limited"
    assert int(sixth.headers["retry-after"]) >= 1

    advance(60_000)
    assert (
        client.post("/api/wallet/name-check", json={"name": "Anna", "code": CODE}).status_code
        == 200
    )


def test_a_phone_with_a_wallet_gets_it_back(
    signup_code: str, client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC8: 200, the same wallet, nothing created, whatever name it sends."""
    first = _sign_up(client, "Jan").json()

    again = _sign_up(client, "Iemand anders")

    assert again.status_code == 200
    assert again.json() == first
    assert "set-cookie" not in again.headers
    assert _count(settings, api_env) == 1


def test_sign_up_works_with_a_live_run_too(signup_code: str, live_client: TestClient) -> None:
    """AC19, SD13: wallets are independent of runs."""
    assert _sign_up(live_client).status_code == 201


def test_sign_up_while_draining_is_503_and_creates_nothing(
    signup_code: str, client: TestClient, settings: Settings, api_env: str
) -> None:
    """AC44."""
    client.app.state.draining = True  # type: ignore[attr-defined]
    try:
        response = _sign_up(client)
    finally:
        client.app.state.draining = False  # type: ignore[attr-defined]

    assert (response.status_code, response.json()["error"]["code"]) == (503, "shutting_down")
    assert _count(settings, api_env) == 0


def test_sign_up_needs_no_crew_session(signup_code: str, client: TestClient) -> None:
    """SD6, SD8: public; no `bb_session` anywhere."""
    client.cookies.clear()

    response = _sign_up(client)

    assert response.status_code == 201
    assert "bb_session" not in response.headers.get("set-cookie", "")
