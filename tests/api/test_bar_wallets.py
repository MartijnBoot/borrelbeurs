"""The bar's wallet routes (B-06 T6: SD9, SD13; AC4, AC20, AC35 server half; PD9).

`POST /api/bar/wallet-lookup` shows a bar key a scanned wallet's name and balance and
nothing else. `GET /api/bar/payments` lists the wallet payments this key booked in
the last 10 minutes on the app clock, newest first, each with its lines, amount,
wallet name (`null` once deleted) and whether it was refunded.
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


def _wallet(settings: Settings, url: str, name: str, amount: int = 5000) -> WalletRow:
    async def body(conn: AsyncConnection) -> WalletRow:
        wallet = await wallets.create_wallet(
            conn, name=name, cookie_hash=cookie_hash(f"cookie-{name}"), now_ms=0
        )
        await wallets.insert_entry(
            conn, wallet_id=wallet.wallet_id, kind="topup", amount_cents=amount, now_ms=0
        )
        return wallet

    return _db(settings, url, body)


def _pay(client: TestClient, key: str, wallet: WalletRow, qtys: dict[str, int]) -> Any:
    """One wallet order of `qtys` by drink name, at the live prices."""
    state = client.get("/api/state").json()
    ids = {d["name"]: d["drink_id"] for d in state["drinks"]}
    lines = [
        {
            "drink_id": ids[name],
            "qty": qty,
            "unit_price_cents": state["prices"][str(ids[name])]["price_cents"],
        }
        for name, qty in qtys.items()
    ]
    response = client.post(
        "/api/orders",
        json={
            "quote_version": client.app.state.holder.state.version,  # type: ignore[attr-defined]
            "lines": lines,
            "wallet": {"qr_token": wallet.qr_token},
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_lookup_by_token_or_code_shows_only_the_name_and_balance(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC4, AC35, SD13: never a wallet id, a code or a token."""
    jan = _wallet(settings, api_env, "Jan", 750)
    bar = login("bar", "Bar 1")

    by_token = bar.post("/api/bar/wallet-lookup", json={"qr_token": jan.qr_token})
    by_code = bar.post("/api/bar/wallet-lookup", json={"short_code": jan.short_code.lower()})

    assert (by_token.status_code, by_code.status_code) == (200, 200)
    assert by_token.json() == by_code.json() == {"name": "Jan", "balance_cents": 750}


@pytest.mark.parametrize("case", ["unknown", "deleted", "malformed"])
def test_an_unknown_or_deleted_wallet_is_404(
    live_client: TestClient, login: Login, settings: Settings, api_env: str, case: str
) -> None:
    """AC4."""
    jan = _wallet(settings, api_env, "Jan")
    body: dict[str, str] = {"qr_token": "no-such-token"}
    if case == "deleted":
        _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, jan.wallet_id, now_ms=0))
        body = {"qr_token": jan.qr_token}
    if case == "malformed":
        body = {"short_code": "!!"}
    bar = login("bar", "Bar 1")

    response = bar.post("/api/bar/wallet-lookup", json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"


def test_each_bar_key_sees_only_its_own_payments_newest_first(
    live_client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    advance: Callable[[int], None],
) -> None:
    """AC20: lines (by drink id), amount, name, time and `refunded`."""
    jan = _wallet(settings, api_env, "Jan")
    piet = _wallet(settings, api_env, "Piet")
    one = login("bar", "Bar 1")
    first = _pay(one, "k-bar-one-001", jan, {"Wijn": 1, "Bier": 2})
    advance(1_000)
    second = _pay(one, "k-bar-one-002", piet, {"Fris": 1})
    mine = one.get("/api/bar/payments")
    two = login("bar", "Bar 2")
    other = _pay(two, "k-bar-two-001", jan, {"Bier": 1})

    theirs = two.get("/api/bar/payments")

    assert mine.status_code == 200, mine.text
    assert [p["entry_id"] for p in mine.json()] == sorted(
        [p["entry_id"] for p in mine.json()], reverse=True
    )
    listed = mine.json()
    assert [(p["name"], p["amount_cents"], p["refunded"]) for p in listed] == [
        ("Piet", second["total_cents"], False),
        ("Jan", first["total_cents"], False),
    ]
    assert listed[1]["lines"] == [{"name": "Bier", "qty": 2}, {"name": "Wijn", "qty": 1}]
    assert set(listed[0]) == {"entry_id", "amount_cents", "created_at", "lines", "refunded", "name"}
    assert [(p["name"], p["amount_cents"]) for p in theirs.json()] == [
        ("Jan", other["total_cents"])
    ]


def test_a_payment_older_than_ten_minutes_drops_out_of_the_list(
    live_client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    advance: Callable[[int], None],
) -> None:
    """AC20, SD9: the window is the server's, on the app clock."""
    jan = _wallet(settings, api_env, "Jan")
    bar = login("bar", "Bar 1")
    _pay(bar, "k-bar-old-001", jan, {"Bier": 1})
    advance(600_000)
    assert len(bar.get("/api/bar/payments").json()) == 1

    advance(1)

    assert bar.get("/api/bar/payments").json() == []


def test_a_payment_whose_wallet_was_deleted_shows_no_name(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    jan = _wallet(settings, api_env, "Jan")
    bar = login("bar", "Bar 1")
    _pay(bar, "k-bar-gone-001", jan, {"Bier": 1})
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, jan.wallet_id, now_ms=0))

    (listed,) = bar.get("/api/bar/payments").json()

    assert listed["name"] is None
    assert listed["lines"] == [{"name": "Bier", "qty": 1}]


def test_a_refunded_payment_is_marked(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    jan = _wallet(settings, api_env, "Jan")
    bar = login("bar", "Bar 1")
    _pay(bar, "k-bar-refund-1", jan, {"Bier": 1})

    async def refund(conn: AsyncConnection) -> None:
        (payment,) = (
            await conn.execute(
                text("SELECT entry_id, amount_cents FROM wallet_entry WHERE kind = 'payment'")
            )
        ).all()
        await wallets.insert_entry(
            conn,
            wallet_id=jan.wallet_id,
            kind="refund",
            amount_cents=-int(payment.amount_cents),
            now_ms=0,
            refunds_entry_id=int(payment.entry_id),
        )

    _db(settings, api_env, refund)

    assert [p["refunded"] for p in bar.get("/api/bar/payments").json()] == [True]


def test_an_admin_key_sees_its_own_payments(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    jan = _wallet(settings, api_env, "Jan")
    admin = login("admin", "Bestuur")
    paid = _pay(admin, "k-admin-pay-01", jan, {"Bier": 1})

    response = admin.get("/api/bar/payments")

    assert response.status_code == 200
    assert [p["amount_cents"] for p in response.json()] == [paid["total_cents"]]
