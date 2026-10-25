"""The order route (Phase 3 T24: SD17, SD20, SD21; AC9, AC11, AC13 and AC14a over HTTP).

B-06 T4: an order may be paid from a scanned wallet (SD13-SD16).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.db.wallets import WalletRow
from app.runtime.wallet_codes import cookie_hash
from tests.api.conftest import Login

T = TypeVar("T")


def _live(client: TestClient) -> dict[int, int]:
    """Every drink's live `price_cents`, as the snapshot shows them."""
    state = client.get("/api/state").json()
    return {int(d): p["price_cents"] for d, p in state["prices"].items()}


def _version(client: TestClient) -> int:
    version: int = client.app.state.holder.state.version  # type: ignore[attr-defined]
    return version


def _order(
    client: TestClient, key: str | None, lines: list[dict[str, int]], quote: int | None = None
) -> Any:
    headers = {} if key is None else {"Idempotency-Key": key}
    body = {"quote_version": _version(client) if quote is None else quote, "lines": lines}
    return client.post("/api/orders", json=body, headers=headers)


def _rows(settings: Settings, url: str) -> list[tuple[Any, ...]]:
    async def scenario() -> list[tuple[Any, ...]]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text('SELECT order_id, actor_key_id FROM "order" ORDER BY order_id')
                )
                return [tuple(r) for r in rows]
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


@pytest.fixture
def bar(live_client: TestClient, login: Login) -> TestClient:
    return login("bar", "Bar 1")


def test_an_order_is_201_with_the_receipt_and_a_replay_is_200_byte_identical(
    bar: TestClient, settings: Settings, api_env: str
) -> None:
    """AC9 over HTTP: the same bytes, one order row, the actor stored."""
    live = _live(bar)
    drink = next(iter(live))
    lines = [{"drink_id": drink, "qty": 2, "unit_price_cents": live[drink]}]

    first = _order(bar, "k-http-0001", lines)
    again = bar.post(
        "/api/orders",
        json={"quote_version": first.json()["quote_version"], "lines": lines},
        headers={"Idempotency-Key": "k-http-0001"},
    )

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.content == first.content
    assert first.headers["content-type"] == "application/json"
    receipt = first.json()
    assert receipt["total_cents"] == 2 * live[drink]
    assert receipt["lines"] == [
        {
            "drink_id": drink,
            "qty": 2,
            "unit_price_cents": live[drink],
            "line_total_cents": 2 * live[drink],
        }
    ]
    rows = _rows(settings, api_env)
    assert len(rows) == 1
    assert rows[0][1] is not None  # actor_key_id from the session


@pytest.mark.parametrize(
    "key",
    [None, "short", "has space!", "x" * 129, "dotted.key.value"],
    ids=["missing", "seven-chars", "bad-character", "129-chars", "dot"],
)
def test_a_missing_or_malformed_idempotency_key_is_422(
    bar: TestClient, key: str | None, settings: Settings, api_env: str
) -> None:
    live = _live(bar)
    drink = next(iter(live))

    response = _order(bar, key, [{"drink_id": drink, "qty": 1, "unit_price_cents": live[drink]}])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert _rows(settings, api_env) == []


@pytest.mark.parametrize(
    "lines",
    [
        [{"drink_id": 0, "qty": 0, "unit_price_cents": 260}],
        [{"drink_id": 0, "qty": 100, "unit_price_cents": 260}],
        [
            {"drink_id": 0, "qty": 1, "unit_price_cents": 260},
            {"drink_id": 0, "qty": 2, "unit_price_cents": 260},
        ],
        [],
        [{"drink_id": 0, "qty": 1, "unit_price_cents": 2.6}],
    ],
    ids=["qty-0", "qty-100", "duplicate-drink", "no-lines", "float-price"],
)
def test_bad_lines_are_422(
    bar: TestClient, lines: list[dict[str, Any]], settings: Settings, api_env: str
) -> None:
    live = _live(bar)
    drink = next(iter(live))
    for line in lines:
        line["drink_id"] = drink

    response = _order(bar, "k-http-0002", lines)

    assert response.status_code == 422
    assert _rows(settings, api_env) == []


def test_qty_99_is_accepted(bar: TestClient) -> None:
    live = _live(bar)
    drink = next(iter(live))

    assert (
        _order(
            bar, "k-http-0003", [{"drink_id": drink, "qty": 99, "unit_price_cents": live[drink]}]
        ).status_code
        == 201
    )


def test_a_price_outside_grace_is_409_with_version_and_prices(bar: TestClient) -> None:
    """AC11: the 409 body carries `error.code`, the current `version` and every line's price."""
    live = _live(bar)
    drink = next(iter(live))

    response = _order(
        bar, "k-http-0004", [{"drink_id": drink, "qty": 1, "unit_price_cents": live[drink] + 20}]
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "price_changed"
    assert error["version"] == _version(bar)
    assert error["prices"] == [{"drink_id": drink, "price_cents": live[drink]}]


def test_an_inactive_drink_or_a_future_quote_is_422(
    bar: TestClient, settings: Settings, api_env: str
) -> None:
    """AC14a over HTTP."""
    live = _live(bar)
    drink = next(iter(live))

    unknown = _order(bar, "k-http-0005", [{"drink_id": 999_999, "qty": 1, "unit_price_cents": 260}])
    future = _order(
        bar,
        "k-http-0006",
        [{"drink_id": drink, "qty": 1, "unit_price_cents": live[drink]}],
        quote=_version(bar) + 1,
    )

    assert (unknown.status_code, future.status_code) == (422, 422)
    assert _rows(settings, api_env) == []


def test_a_database_failure_is_503_and_a_retry_with_the_key_succeeds_once(
    bar: TestClient, settings: Settings, api_env: str
) -> None:
    """AC13 over HTTP, and SD21's "a retry with the same key is then safe"."""
    live = _live(bar)
    drink = next(iter(live))
    lines = [{"drink_id": drink, "qty": 1, "unit_price_cents": live[drink]}]
    engine = bar.app.state.engine  # type: ignore[attr-defined]
    armed = {"on": True}

    def fail(*args: Any) -> None:
        if armed["on"] and args[2].startswith('INSERT INTO "order"'):
            armed["on"] = False
            raise OSError("injected")

    event.listen(engine.sync_engine, "before_cursor_execute", fail)
    try:
        failed = _order(bar, "k-http-0007", lines)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail)
    retried = bar.post(
        "/api/orders",
        json={"quote_version": _version(bar), "lines": lines},
        headers={"Idempotency-Key": "k-http-0007"},
    )

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "persistence_unavailable"
    assert retried.status_code == 201
    assert len(_rows(settings, api_env)) == 1


def test_a_draining_process_refuses_orders_with_503(bar: TestClient) -> None:
    live = _live(bar)
    drink = next(iter(live))
    bar.app.state.draining = True  # type: ignore[attr-defined]
    try:
        response = _order(
            bar, "k-http-0008", [{"drink_id": drink, "qty": 1, "unit_price_cents": live[drink]}]
        )
    finally:
        bar.app.state.draining = False  # type: ignore[attr-defined]

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "shutting_down"


def test_display_may_not_order(live_client: TestClient, login: Login) -> None:
    client = login("display")

    assert (
        _order(
            client, "k-http-0009", [{"drink_id": 1, "qty": 1, "unit_price_cents": 260}]
        ).status_code
        == 403
    )


def test_with_no_live_run_an_order_is_409(login: Login) -> None:
    client = login("bar")

    response = client.post(
        "/api/orders",
        json={"quote_version": 0, "lines": [{"drink_id": 1, "qty": 1, "unit_price_cents": 260}]},
        headers={"Idempotency-Key": "k-http-0010"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_live_run"


# --- B-06 T4: paying from a wallet (SD13-SD16; AC5-AC8, AC12, AC14-AC16, PD2, PD5) ---


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


def _new_wallet(settings: Settings, url: str, name: str = "Jan") -> WalletRow:
    return _db(
        settings,
        url,
        lambda conn: wallets.create_wallet(
            conn, name=name, cookie_hash=cookie_hash(f"cookie-{name}"), now_ms=0
        ),
    )


def _balance(settings: Settings, url: str, wallet_id: int) -> int:
    return _db(settings, url, lambda conn: wallets.balance(conn, wallet_id))


def _adjust(settings: Settings, url: str, wallet_id: int, to: int) -> None:
    """Bring the balance to exactly `to` with one earlier payment (no order) or top-up."""
    diff = to - _balance(settings, url, wallet_id)
    if diff:
        _db(
            settings,
            url,
            lambda conn: wallets.insert_entry(
                conn,
                wallet_id=wallet_id,
                kind="topup" if diff > 0 else "payment",
                amount_cents=diff,
                now_ms=0,
            ),
        )


def _patch_run(login: Login, run_id: int, body: dict[str, Any]) -> None:
    admin = login("admin", "Bestuur")
    response = admin.patch(f"/api/runs/{run_id}/config", json=body)
    assert response.status_code == 200, response.text


def _funded(login: Login, wallet: WalletRow, amount: int = 1500) -> None:
    kassa = login("kassa", "Kassa 1")
    response = kassa.post(
        f"/api/kassa/wallets/{wallet.wallet_id}/topups",
        json={"amount_cents": amount},
        headers={"Idempotency-Key": f"k-fund-{wallet.wallet_id:06d}"},
    )
    assert response.status_code == 201, response.text


def _pay(
    client: TestClient,
    key: str,
    lines: list[dict[str, int]],
    wallet: dict[str, str] | None,
    quote: int | None = None,
) -> Any:
    body: dict[str, Any] = {
        "quote_version": _version(client) if quote is None else quote,
        "lines": lines,
    }
    if wallet is not None:
        body["wallet"] = wallet
    return client.post("/api/orders", json=body, headers={"Idempotency-Key": key})


_COUNTS = (
    'SELECT (SELECT count(*) FROM "order"), '
    "(SELECT count(*) FROM wallet_entry WHERE kind = 'payment' AND order_id IS NOT NULL)"
)


def _counts(settings: Settings, url: str) -> tuple[int, int]:
    ((orders, entries),) = _sql(settings, url, _COUNTS)
    return int(orders), int(entries)


def _market(client: TestClient) -> tuple[int, dict[int, int]]:
    return _version(client), _live(client)


def test_a_wallet_order_writes_one_payment_and_the_receipt_names_the_wallet(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC6, SD16: 201; `wallet` on the receipt; one payment of -total naming the order, the
    live run and the bar key and label, with no key of its own; the balance falls by it."""
    jan = _new_wallet(settings, api_env)
    _funded(login, jan)
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier, wijn = list(live)[:2]
    lines = [
        {"drink_id": bier, "qty": 2, "unit_price_cents": live[bier]},
        {"drink_id": wijn, "qty": 1, "unit_price_cents": live[wijn]},
    ]

    response = _pay(bar, "k-pay-000001", lines, {"short_code": jan.short_code.lower()})

    assert response.status_code == 201, response.text
    receipt = response.json()
    total = 2 * live[bier] + live[wijn]
    assert receipt["total_cents"] == total
    assert receipt["wallet"] == {"name": "Jan", "balance_after_cents": 1500 - total}
    ((key_id,),) = _sql(settings, api_env, "SELECT key_id FROM auth_key WHERE label = 'Bar 1'")
    assert _sql(
        settings,
        api_env,
        "SELECT wallet_id, amount_cents, order_id, run_id, actor_key_id, actor_label,"
        " idempotency_key FROM wallet_entry WHERE kind = 'payment'",
    ) == [(jan.wallet_id, -total, receipt["order_id"], live_run, key_id, "Bar 1", None)]
    assert _balance(settings, api_env, jan.wallet_id) == 1500 - total


def test_a_wallet_order_by_qr_token_pays_too(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    jan = _new_wallet(settings, api_env)
    _funded(login, jan)
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))

    response = _pay(
        bar,
        "k-pay-000002",
        [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}],
        {"qr_token": jan.qr_token},
    )

    assert response.status_code == 201, response.text
    assert _balance(settings, api_env, jan.wallet_id) == 1500 - live[bier]


def test_the_limit_admits_exactly_minus_l_and_refuses_one_cent_more(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC7, AC8, SD15: at limit 250 an order to exactly -250 is booked; at -251 it is 409
    with the balance and the limit, and no order, no entry, no price moved."""
    _patch_run(login, live_run, {"credit_limit_cents": 250})
    jan = _new_wallet(settings, api_env)
    _funded(login, jan)
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))
    lines = [{"drink_id": bier, "qty": 4, "unit_price_cents": live[bier]}]
    total = 4 * live[bier]

    _adjust(settings, api_env, jan.wallet_id, total - 251)
    before, counts = _market(bar), _counts(settings, api_env)
    refused = _pay(bar, "k-pay-000003", lines, {"short_code": jan.short_code})

    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert (error["code"], error["balance_cents"], error["credit_limit_cents"]) == (
        "insufficient_balance",
        total - 251,
        250,
    )
    assert _market(bar) == before
    assert _counts(settings, api_env) == counts

    _adjust(settings, api_env, jan.wallet_id, total - 250)
    booked = _pay(bar, "k-pay-000004", lines, {"short_code": jan.short_code}, quote=before[0])

    assert booked.status_code == 201, booked.text
    assert booked.json()["wallet"]["balance_after_cents"] == -250
    assert _balance(settings, api_env, jan.wallet_id) == -250


def test_with_the_switch_on_an_order_without_a_wallet_is_409_wallet_required(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC14: nothing written, no price moved."""
    _patch_run(login, live_run, {"wallet_required": True})
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))
    before, counts = _market(bar), _counts(settings, api_env)

    response = _pay(
        bar, "k-pay-000005", [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}], None
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "wallet_required"
    assert _market(bar) == before
    assert _counts(settings, api_env) == counts


def test_with_the_switch_off_an_order_books_with_or_without_a_wallet(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC15: without a wallet `wallet: null` and no entry; with one, the wallet pays."""
    jan = _new_wallet(settings, api_env)
    _funded(login, jan)
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))
    line = [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}]

    unpaid = _pay(bar, "k-pay-000006", line, None)
    paid = _pay(
        bar, "k-pay-000007", line, {"qr_token": jan.qr_token}, quote=unpaid.json()["version"]
    )

    assert (unpaid.status_code, paid.status_code) == (201, 201), paid.text
    assert unpaid.json()["wallet"] is None
    assert '"wallet":null' in unpaid.text
    assert paid.json()["wallet"]["name"] == "Jan"
    assert _sql(settings, api_env, "SELECT order_id FROM wallet_entry WHERE kind = 'payment'") == [
        (paid.json()["order_id"],)
    ]


def test_a_switch_turned_on_between_two_orders_refuses_the_second(
    live_run: int, live_client: TestClient, login: Login
) -> None:
    """AC16, SD1: the order is judged by the switch as it stands when it arrives."""
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))
    line = [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}]
    first = _pay(bar, "k-pay-000008", line, None)
    _patch_run(login, live_run, {"wallet_required": True})
    bar = login("bar", "Bar 1")

    second = _pay(bar, "k-pay-000009", line, None, quote=first.json()["version"])

    assert first.status_code == 201
    assert (second.status_code, second.json()["error"]["code"]) == (409, "wallet_required")


@pytest.mark.parametrize("case", ["new-code", "deleted", "malformed", "unknown-token"])
def test_a_wallet_that_no_longer_resolves_is_404_and_writes_nothing(
    live_client: TestClient, login: Login, settings: Settings, api_env: str, case: str
) -> None:
    """AC12, SD13: a re-code or delete since the scan, a malformed code, an unknown token."""
    jan = _new_wallet(settings, api_env)
    _funded(login, jan)
    scanned: dict[str, str] = {"short_code": jan.short_code}
    if case == "new-code":
        _db(settings, api_env, lambda conn: wallets.replace_codes(conn, jan.wallet_id))
    elif case == "deleted":
        _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, jan.wallet_id, now_ms=0))
    elif case == "malformed":
        scanned = {"short_code": "!!"}
    else:
        scanned = {"qr_token": "no-such-token"}
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))
    before, counts = _market(bar), _counts(settings, api_env)

    response = _pay(
        bar, "k-pay-000010", [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}], scanned
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "wallet_not_found"
    assert _market(bar) == before
    assert _counts(settings, api_env) == counts


def test_the_checks_come_in_sd15s_order(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """SD15: the price before the wallet; the switch before the wallet; the wallet before
    the balance. Nothing written and no price moved on any of them."""
    poor = _new_wallet(settings, api_env, "Arm")
    _patch_run(login, live_run, {"wallet_required": True})
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))
    good = [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}]
    stale = [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier] + 20}]
    before, counts = _market(bar), _counts(settings, api_env)

    price = _pay(bar, "k-order-001", stale, {"short_code": "!!"})
    switch = _pay(bar, "k-order-002", good, None)
    wallet = _pay(bar, "k-order-003", good, {"qr_token": "no-such-token"})
    balance = _pay(bar, "k-order-004", good, {"qr_token": poor.qr_token})

    assert [r.json()["error"]["code"] for r in (price, switch, wallet, balance)] == [
        "price_changed",
        "wallet_required",
        "wallet_not_found",
        "insufficient_balance",
    ]
    assert _market(bar) == before
    assert _counts(settings, api_env) == counts


def test_a_body_naming_both_a_token_and_a_code_is_422(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    jan = _new_wallet(settings, api_env)
    bar = login("bar", "Bar 1")
    live = _live(bar)
    bier = next(iter(live))

    response = _pay(
        bar,
        "k-pay-000011",
        [{"drink_id": bier, "qty": 1, "unit_price_cents": live[bier]}],
        {"qr_token": jan.qr_token, "short_code": jan.short_code},
    )

    assert response.status_code == 422
    assert _counts(settings, api_env) == (0, 0)
