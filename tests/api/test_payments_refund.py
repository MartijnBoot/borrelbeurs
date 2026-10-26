"""Refunds, and the kassa's payments list (B-06 T7: SD9, SD10; AC21-AC23, AC33; PD9).

A refund is one `refund` entry of the payment's whole amount, naming it, with the
payment's run and the acting key; the order, its lines, the revenue and the engine
stay as they were. The bar refunds only its own payments, for 10 minutes; kassa and
admin any, at any age. The kassa lists a wallet's payments at any age.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.db.wallets import WalletRow
from app.runtime.wallet_codes import cookie_hash
from tests.api.conftest import Login

T = TypeVar("T")


def _db(settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    async def scenario() -> T:
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

    return _db(settings, url, body)


def _wallet(settings: Settings, url: str, name: str = "Jan", amount: int = 5000) -> WalletRow:
    async def body(conn: AsyncConnection) -> WalletRow:
        wallet = await wallets.create_wallet(
            conn, name=name, cookie_hash=cookie_hash(f"cookie-{name}"), now_ms=0
        )
        await wallets.insert_entry(
            conn, wallet_id=wallet.wallet_id, kind="topup", amount_cents=amount, now_ms=0
        )
        return wallet

    return _db(settings, url, body)


def _balance(settings: Settings, url: str, wallet_id: int) -> int:
    return _db(settings, url, lambda conn: wallets.balance(conn, wallet_id))


def _pay(client: TestClient, key: str, wallet: WalletRow, qty: int = 2) -> tuple[int, int]:
    """A wallet order of `qty` Bier; the payment's entry id and the total."""
    state = client.get("/api/state").json()
    bier = next(d["drink_id"] for d in state["drinks"] if d["name"] == "Bier")
    price = state["prices"][str(bier)]["price_cents"]
    response = client.post(
        "/api/orders",
        json={
            "quote_version": client.app.state.holder.state.version,  # type: ignore[attr-defined]
            "lines": [{"drink_id": bier, "qty": qty, "unit_price_cents": price}],
            "wallet": {"qr_token": wallet.qr_token},
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    ((entry_id,),) = _sql(
        settings,
        settings.database_url,
        "SELECT entry_id FROM wallet_entry WHERE order_id = :o",
        o=response.json()["order_id"],
    )
    return int(entry_id), int(response.json()["total_cents"])


def _refund(client: TestClient, entry_id: int, key: str = "k-refund-0001") -> Any:
    return client.post(f"/api/payments/{entry_id}/refund", headers={"Idempotency-Key": key})


def _error(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def _untouched(settings: Settings, url: str) -> tuple[Any, ...]:
    """What a refund must not move: orders, lines, revenue, the engine's version."""
    ((row),) = _sql(
        settings,
        url,
        'SELECT (SELECT count(*) FROM "order"), (SELECT count(*) FROM order_line),'
        " (SELECT coalesce(sum(line_total_cents), 0) FROM order_line),"
        " (SELECT version FROM engine_state)",
    )
    return tuple(row)


def _entries(settings: Settings, url: str) -> int:
    ((count,),) = _sql(settings, url, "SELECT count(*) FROM wallet_entry")
    return int(count)


def test_a_bar_refund_of_its_own_payment_returns_the_money_only(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC21: one refund of +total naming the payment, with its run, the key and label;
    the balance rises by the total; orders, lines, revenue and the engine unchanged."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    payment, total = _pay(bar, "k-pay-refund-01", jan)
    before = _untouched(settings, api_env)
    balance = _balance(settings, api_env, jan.wallet_id)

    response = _refund(bar, payment)

    assert response.status_code == 201, response.text
    assert response.json()["amount_cents"] == total
    ((key_id,),) = _sql(settings, api_env, "SELECT key_id FROM auth_key WHERE label = 'Bar 1'")
    assert _sql(
        settings,
        api_env,
        "SELECT amount_cents, refunds_entry_id, run_id, actor_key_id, actor_label"
        " FROM wallet_entry WHERE kind = 'refund'",
    ) == [(total, payment, live_run, key_id, "Bar 1")]
    assert _balance(settings, api_env, jan.wallet_id) == balance + total
    assert _untouched(settings, api_env) == before
    assert bar.get("/api/state").json()["version"] == before[3]


def test_a_refund_carries_the_payments_run_after_that_run_is_closed(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """SD9: a borrel's payment total is net of its refunds, whenever they are booked."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    payment, _ = _pay(bar, "k-pay-closed-01", jan)
    admin = login("admin", "Bestuur")
    assert admin.post(f"/api/runs/{live_run}/close", json={"confirm_name": "Borrel"}).is_success

    response = _refund(admin, payment)

    assert response.status_code == 201, response.text
    assert _sql(settings, api_env, "SELECT run_id FROM wallet_entry WHERE kind = 'refund'") == [
        (live_run,)
    ]


def test_a_second_refund_is_already_refunded(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC22."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    payment, _ = _pay(bar, "k-pay-twice-001", jan)
    assert _refund(bar, payment).status_code == 201
    before = _entries(settings, api_env)

    assert _error(_refund(bar, payment, key="k-refund-0002")) == (409, "already_refunded")
    assert _entries(settings, api_env) == before


def test_a_refund_on_a_deleted_wallet_is_wallet_deleted(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC22."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    payment, _ = _pay(bar, "k-pay-deleted-1", jan)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, jan.wallet_id, now_ms=0))
    before = _entries(settings, api_env)

    assert _error(_refund(bar, payment)) == (409, "wallet_deleted")
    assert _entries(settings, api_env) == before


def test_a_bar_key_may_not_refund_another_keys_payment(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC22, SD9."""
    jan = _wallet(settings, api_env)
    payment, _ = _pay(login("bar", "Bar 1"), "k-pay-other-001", jan)
    other = login("bar", "Bar 2")
    before = _entries(settings, api_env)

    assert _error(_refund(other, payment)) == (403, "refund_not_allowed")
    assert _entries(settings, api_env) == before


def test_a_bar_key_may_not_refund_after_ten_minutes(
    live_client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    advance: Callable[[int], None],
) -> None:
    """AC22, SD9: the window is the app clock's."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    payment, _ = _pay(bar, "k-pay-late-0001", jan)
    advance(600_001)
    before = _entries(settings, api_env)

    assert _error(_refund(bar, payment)) == (403, "refund_not_allowed")
    assert _entries(settings, api_env) == before


@pytest.mark.parametrize("kind", ["topup", "unknown"])
def test_anything_but_a_payment_is_payment_not_found(
    live_client: TestClient, login: Login, settings: Settings, api_env: str, kind: str
) -> None:
    """PD9: 404 before 403, so no one learns which other entries exist."""
    jan = _wallet(settings, api_env)
    entry_id = 999_999
    if kind == "topup":
        ((entry_id,),) = _sql(
            settings,
            api_env,
            "SELECT entry_id FROM wallet_entry WHERE wallet_id = :w",
            w=jan.wallet_id,
        )
    bar = login("bar", "Bar 1")
    before = _entries(settings, api_env)

    assert _error(_refund(bar, entry_id)) == (404, "payment_not_found")
    assert _entries(settings, api_env) == before


@pytest.mark.parametrize("role", ["kassa", "admin"])
def test_kassa_and_admin_refund_an_old_bar_payment(
    live_client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    advance: Callable[[int], None],
    role: str,
) -> None:
    """AC23: at any age, whoever booked it."""
    jan = _wallet(settings, api_env)
    payment, total = _pay(login("bar", "Bar 1"), "k-pay-old-0001", jan)
    advance(3_600_000)
    crew = login(role, f"Crew {role}")

    response = _refund(crew, payment)

    assert response.status_code == 201, response.text
    assert _sql(
        settings,
        api_env,
        "SELECT amount_cents, actor_label FROM wallet_entry WHERE kind = 'refund'",
    ) == [(total, f"Crew {role}")]


def test_a_refund_replays_with_its_key_and_refuses_it_for_another_payment(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC23, PD9."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    first, _ = _pay(bar, "k-pay-replay-01", jan, qty=1)
    second, _ = _pay(bar, "k-pay-replay-02", jan, qty=1)
    booked = _refund(bar, first)
    before = _entries(settings, api_env)

    replay = _refund(bar, first)
    reused = _refund(bar, second)

    assert (booked.status_code, replay.status_code) == (201, 200)
    assert replay.json() == booked.json()
    assert _error(reused) == (422, "idempotency_key_reused")
    assert _entries(settings, api_env) == before


def test_the_kassa_lists_a_wallets_payments_at_any_age_newest_first(
    live_client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    advance: Callable[[int], None],
) -> None:
    """AC23: lines, the amount, who booked it, and whether it was refunded."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    first, first_total = _pay(bar, "k-pay-list-0001", jan, qty=2)
    advance(1_000)
    second, second_total = _pay(bar, "k-pay-list-0002", jan, qty=1)
    assert _refund(bar, first).status_code == 201
    advance(3_600_000)
    kassa = login("kassa", "Kassa 1")

    response = kassa.get(f"/api/kassa/wallets/{jan.wallet_id}/payments")

    assert response.status_code == 200, response.text
    listed = response.json()
    assert [
        (p["entry_id"], p["amount_cents"], p["refunded"], p["actor_label"]) for p in listed
    ] == [(second, second_total, False, "Bar 1"), (first, first_total, True, "Bar 1")]
    assert listed[1]["lines"] == [{"name": "Bier", "qty": 2}]
    assert set(listed[0]) == {
        "entry_id",
        "amount_cents",
        "created_at",
        "lines",
        "refunded",
        "actor_label",
    }


def test_the_kassa_list_of_an_unknown_wallet_is_404(live_client: TestClient, login: Login) -> None:
    kassa = login("kassa", "Kassa 1")

    assert _error(kassa.get("/api/kassa/wallets/999999/payments")) == (404, "wallet_not_found")


def test_a_refund_while_draining_is_503_and_writes_nothing(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC33."""
    jan = _wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    payment, _ = _pay(bar, "k-pay-drain-001", jan)
    before = _entries(settings, api_env)
    live_client.app.state.draining = True  # type: ignore[attr-defined]
    try:
        response = _refund(bar, payment)
    finally:
        live_client.app.state.draining = False  # type: ignore[attr-defined]

    assert _error(response) == (503, "shutting_down")
    assert _entries(settings, api_env) == before
