"""Kassa: lookup and top-up (B-05 T7: SD9, SD10, SD13; AC14-AC19, AC37, AC44)."""

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
from app.db.wallets import WalletRow
from app.runtime.wallet_codes import display_short_code
from tests.api.conftest import Login


def _db(settings: Settings, url: str, body: Callable[[AsyncConnection], Any]) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _sql(settings: Settings, url: str, sql: str) -> list[tuple[Any, ...]]:
    async def body(conn: AsyncConnection) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in await conn.execute(text(sql))]

    return list(_db(settings, url, body))


def _wallet(settings: Settings, url: str, name: str = "Jan") -> WalletRow:
    wallet: WalletRow = _db(
        settings,
        url,
        lambda conn: wallets.create_wallet(conn, name=name, cookie_hash=f"h-{name}", now_ms=0),
    )
    return wallet


@pytest.fixture
def kassa(login: Login) -> TestClient:
    return login("kassa", "Kassa 1")


def _top_up(client: TestClient, wallet_id: int, amount: int, key: str = "k-topup-0001") -> Any:
    return client.post(
        f"/api/kassa/wallets/{wallet_id}/topups",
        json={"amount_cents": amount},
        headers={"Idempotency-Key": key},
    )


def _lookup(client: TestClient, **body: str) -> Any:
    return client.post("/api/kassa/lookup", json=body)


def test_lookup_by_qr_token(kassa: TestClient, settings: Settings, api_env: str) -> None:
    """AC14."""
    wallet = _wallet(settings, api_env)

    response = _lookup(kassa, qr_token=wallet.qr_token)

    assert response.status_code == 200
    body = response.json()
    assert (body["wallet_id"], body["name"], body["balance_cents"]) == (wallet.wallet_id, "Jan", 0)
    assert body["last_topup_at"] is None
    assert body["recent_topup"] is None


def _spellings(code: str) -> list[str]:
    shown = display_short_code(code)
    return [
        shown,
        shown.lower(),
        code,
        f"  {shown[:4]} {shown[5:]}  ".lower(),
        shown.replace("0", "O").replace("1", "I"),
        shown.replace("1", "l"),
    ]


def test_lookup_by_every_short_code_spelling(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC14: case, hyphen, spaces, `O` for `0`, `I`/`L` for `1`."""
    wallet = _wallet(settings, api_env)

    for typed in _spellings(wallet.short_code):
        response = _lookup(kassa, short_code=typed)
        assert response.status_code == 200, typed
        assert response.json()["wallet_id"] == wallet.wallet_id


def test_unknown_codes_and_a_deleted_wallets_old_code_are_404(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC14."""
    wallet = _wallet(settings, api_env)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=0))

    for body in (
        {"qr_token": "no-such-token"},
        {"short_code": "ZZZZ-ZZZZ"},
        {"short_code": "not a code"},
        {"qr_token": wallet.qr_token},
        {"short_code": wallet.short_code},
    ):
        response = _lookup(kassa, **body)
        assert response.status_code == 404, body
        assert response.json()["error"]["code"] == "wallet_not_found"


@pytest.mark.parametrize("body", [{}, {"qr_token": "a", "short_code": "b"}, {"name": "Jan"}])
def test_lookup_takes_exactly_one_code(kassa: TestClient, body: dict[str, str]) -> None:
    assert kassa.post("/api/kassa/lookup", json=body).status_code == 422


def test_a_top_up_books_one_entry_with_the_key_and_the_live_run(
    live_run: int, kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC15: the balance rises by X; the entry has the key, its label and the live run."""
    wallet = _wallet(settings, api_env)

    response = _top_up(kassa, wallet.wallet_id, 1500)

    assert response.status_code == 201, response.text
    assert response.json()["amount_cents"] == 1500
    assert _lookup(kassa, qr_token=wallet.qr_token).json()["balance_cents"] == 1500
    ((kind, amount, run_id, actor_key_id, label),) = _sql(
        settings,
        api_env,
        "SELECT kind, amount_cents, run_id, actor_key_id, actor_label FROM wallet_entry",
    )
    ((kassa_key,),) = _sql(settings, api_env, "SELECT key_id FROM auth_key WHERE role = 'kassa'")
    assert (kind, amount, run_id, actor_key_id, label) == (
        "topup",
        1500,
        live_run,
        kassa_key,
        "Kassa 1",
    )


@pytest.mark.parametrize("amount", [500, 1250, 10_500, 0, -1000, 1000.0, "1500"])
def test_an_amount_off_the_steps_is_422_and_writes_nothing(
    kassa: TestClient, settings: Settings, api_env: str, amount: object
) -> None:
    """AC16."""
    wallet = _wallet(settings, api_env)

    response = kassa.post(
        f"/api/kassa/wallets/{wallet.wallet_id}/topups",
        json={"amount_cents": amount},
        headers={"Idempotency-Key": "k-topup-0001"},
    )

    assert response.status_code == 422
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet_entry") == [(0,)]


def test_every_step_from_ten_to_a_hundred_euros_is_accepted(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    wallet = _wallet(settings, api_env)

    statuses = {
        _top_up(kassa, wallet.wallet_id, amount, key=f"k-step-{amount:05d}").status_code
        for amount in range(1000, 10_001, 500)
    }

    assert statuses == {201}
    assert _lookup(kassa, qr_token=wallet.qr_token).json()["balance_cents"] == sum(
        range(1000, 10_001, 500)
    )


def test_a_second_lookup_within_two_minutes_shows_the_recent_top_up(
    kassa: TestClient, settings: Settings, api_env: str, advance: Callable[[int], None]
) -> None:
    """AC17, SD10: on the app clock, by any key; the window closes after 2 minutes."""
    wallet = _wallet(settings, api_env)
    booked = _top_up(kassa, wallet.wallet_id, 1000).json()

    advance(120_000)
    recent = _lookup(kassa, qr_token=wallet.qr_token).json()
    advance(1)
    later = _lookup(kassa, qr_token=wallet.qr_token).json()

    assert recent["recent_topup"] == {"at": booked["created_at"], "amount_cents": 1000}
    assert later["recent_topup"] is None
    assert later["last_topup_at"] == booked["created_at"]


def test_a_second_top_up_within_two_minutes_is_still_booked(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """SD10: "It never refuses"."""
    wallet = _wallet(settings, api_env)

    assert _top_up(kassa, wallet.wallet_id, 1000, key="k-first-0001").status_code == 201
    assert _top_up(kassa, wallet.wallet_id, 1000, key="k-again-0001").status_code == 201
    assert _lookup(kassa, qr_token=wallet.qr_token).json()["balance_cents"] == 2000


def test_a_replay_returns_the_stored_entry_and_a_changed_body_is_422(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC18."""
    wallet = _wallet(settings, api_env)
    first = _top_up(kassa, wallet.wallet_id, 1500)

    replay = _top_up(kassa, wallet.wallet_id, 1500)
    reused = _top_up(kassa, wallet.wallet_id, 2000)

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json() == first.json()
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet_entry") == [(1,)]


def test_a_key_reused_on_another_wallet_is_422(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    jan, piet = _wallet(settings, api_env, "Jan"), _wallet(settings, api_env, "Piet")
    _top_up(kassa, jan.wallet_id, 1500)

    reused = _top_up(kassa, piet.wallet_id, 1500)

    assert reused.json()["error"]["code"] == "idempotency_key_reused"


def test_without_a_live_run_the_entry_carries_no_run(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC19."""
    wallet = _wallet(settings, api_env)

    assert _top_up(kassa, wallet.wallet_id, 1000).status_code == 201
    assert _sql(settings, api_env, "SELECT run_id FROM wallet_entry") == [(None,)]


def test_an_admin_key_may_top_up(login: Login, settings: Settings, api_env: str) -> None:
    """AC37."""
    admin = login("admin", "Bestuur")
    wallet = _wallet(settings, api_env)

    assert _top_up(admin, wallet.wallet_id, 1000).status_code == 201
    assert _sql(settings, api_env, "SELECT actor_label FROM wallet_entry") == [("Bestuur",)]


def test_a_top_up_of_an_unknown_or_deleted_wallet_is_404(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    wallet = _wallet(settings, api_env)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=0))

    for wallet_id in (wallet.wallet_id, 999_999):
        response = _top_up(kassa, wallet_id, 1000, key=f"k-gone-{wallet_id:06d}")
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "wallet_not_found",
        )
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet_entry") == [(0,)]


def test_the_top_up_list_is_newest_first_with_its_reversed_flag(
    kassa: TestClient, settings: Settings, api_env: str, advance: Callable[[int], None]
) -> None:
    wallet = _wallet(settings, api_env)
    first = _top_up(kassa, wallet.wallet_id, 1000, key="k-list-0001").json()
    advance(1000)
    second = _top_up(kassa, wallet.wallet_id, 2000, key="k-list-0002").json()
    _db(
        settings,
        api_env,
        lambda conn: wallets.insert_entry(
            conn,
            wallet_id=wallet.wallet_id,
            kind="reversal",
            amount_cents=-1000,
            reverses_entry_id=first["entry_id"],
            now_ms=0,
        ),
    )

    listed = kassa.get(f"/api/kassa/wallets/{wallet.wallet_id}/topups").json()

    assert [(t["entry_id"], t["amount_cents"], t["reversed"]) for t in listed] == [
        (second["entry_id"], 2000, False),
        (first["entry_id"], 1000, True),
    ]
    assert listed[0]["actor_label"] == "Kassa 1"
    assert kassa.get("/api/kassa/wallets/999999/topups").status_code == 404


def test_a_top_up_while_draining_is_503(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC44."""
    wallet = _wallet(settings, api_env)
    kassa.app.state.draining = True  # type: ignore[attr-defined]
    try:
        response = _top_up(kassa, wallet.wallet_id, 1000)
    finally:
        kassa.app.state.draining = False  # type: ignore[attr-defined]

    assert response.status_code == 503
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet_entry") == [(0,)]
