"""The order route (Phase 3 T24: SD17, SD20, SD21; AC9, AC11, AC13 and AC14a over HTTP)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import Login


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
