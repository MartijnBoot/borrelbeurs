"""Closing a run over HTTP (Phase 7 T6: AC1-AC5, AC34, AC35; SD2, SD16; PD3, PD4).

`live_client` boots on the three-drink live run named "Borrel". The close takes
the typed name, ends the run on the app clock, ends its open market events,
queues the final export, empties the holder and tells every socket.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
from app.runtime.clock import Clock
from app.runtime.grace import QuotedLine
from app.runtime.holder import MarketHolder, NoLiveRunError
from app.runtime.orders import OrderRequest, PriceChangedError, place_order
from tests.api.conftest import Login

Advance = Callable[[int], None]


def _sql(settings: Settings, url: str, statement: str, **params: Any) -> list[tuple[Any, ...]]:
    async def scenario() -> list[tuple[Any, ...]]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(statement), params)
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _ended_at_ms(settings: Settings, url: str, run_id: int) -> int | None:
    [(value,)] = _sql(
        settings,
        url,
        "SELECT (extract(epoch FROM ended_at) * 1000)::bigint FROM run WHERE run_id = :r",
        r=run_id,
    )
    return None if value is None else int(value)


def _footprint(settings: Settings, url: str) -> list[tuple[Any, ...]]:
    """Everything a close writes: run status and end, open events, exports."""
    return _sql(
        settings,
        url,
        "SELECT (SELECT json_agg(json_build_array(run_id, status, ended_at) ORDER BY run_id)"
        " FROM run)::text,"
        " (SELECT count(*) FROM market_event WHERE ended_at IS NULL),"
        " (SELECT count(*) FROM export)",
    )


def _until(ws: Any, kind: str, limit: int = 30) -> dict[str, Any]:
    for _ in range(limit):
        frame: dict[str, Any] = json.loads(ws.receive_text())
        if frame["type"] == kind:
            return frame
    raise AssertionError(f"no {kind} within {limit} frames")


def test_a_close_ends_the_run_and_unloads_it(
    live_client: TestClient,
    live_run: int,
    login: Login,
    settings: Settings,
    api_env: str,
    advance: Advance,
) -> None:
    """AC1: ended on the app clock, events ended, one final export queued, no more ticks."""
    admin = login("admin", label="Bestuur")
    assert admin.post(
        "/api/market/events", json={"kind": "crash", "duration_ms": 60_000}
    ).is_success
    advance(2_500)
    now = live_client.app.state.clock.wall_ms()  # type: ignore[attr-defined]

    response = admin.post(f"/api/runs/{live_run}/close", json={"confirm_name": " Borrel "})

    assert response.status_code == 200, response.text
    assert response.json() == {"run_id": live_run, "name": "Borrel", "status": "ended"}
    assert _ended_at_ms(settings, api_env, live_run) == now
    assert _sql(settings, api_env, "SELECT count(*) FROM market_event WHERE ended_at IS NULL") == [
        (0,)
    ]
    assert _sql(settings, api_env, "SELECT run_id, kind, status, requested_by FROM export") == [
        (live_run, "final", "queued", "Bestuur")
    ]
    assert live_client.app.state.holder.is_empty  # type: ignore[attr-defined]
    ticks = _sql(settings, api_env, "SELECT count(*) FROM price_tick WHERE run_id = :r", r=live_run)
    advance(5_000)
    assert (
        _sql(settings, api_env, "SELECT count(*) FROM price_tick WHERE run_id = :r", r=live_run)
        == ticks
    )


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("unknown", 404, "run_not_found"),
        ("draft", 409, "run_not_live"),
        ("ended", 409, "run_not_live"),
        ("mismatch", 422, "name_mismatch"),
        ("case", 422, "name_mismatch"),
        ("draining", 503, "shutting_down"),
    ],
)
def test_each_refusal_changes_nothing(
    case: str,
    status: int,
    code: str,
    live_client: TestClient,
    live_run: int,
    login: Login,
    settings: Settings,
    api_env: str,
) -> None:
    """AC2: status, ended_at, event and export counts and the holder are as before."""
    admin = login("admin")
    assert admin.post(
        "/api/market/events", json={"kind": "bubble", "duration_ms": 60_000}
    ).is_success
    target, name = live_run, "Borrel"
    if case == "unknown":
        target = 999_999
    elif case in {"draft", "ended"}:
        [(target,)] = _sql(
            settings,
            api_env,
            "INSERT INTO run (status, name, params, run_seed) VALUES (:s, 'Borrel', '{}', 1)"
            " RETURNING run_id",
            s=case,
        )
    elif case == "mismatch":
        name = "Borrel 2"
    elif case == "case":
        name = "borrel"  # PD3: case-sensitive
    elif case == "draining":
        live_client.app.state.draining = True  # type: ignore[attr-defined]
    before = _footprint(settings, api_env)
    holder: MarketHolder = live_client.app.state.holder  # type: ignore[attr-defined]
    view = holder.view

    try:
        response = admin.post(f"/api/runs/{target}/close", json={"confirm_name": name})
    finally:
        live_client.app.state.draining = False  # type: ignore[attr-defined]

    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert _footprint(settings, api_env) == before
    assert holder.view is view


def test_a_connected_socket_is_told_the_run_closed(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    """AC3 (server half): `run_closed` with the run's name, and the market is empty."""
    admin = login("admin")
    with admin.websocket_connect("wss://testserver/ws") as ws:
        hello = _until(ws, "hello")
        assert hello["data"]["run_id"] == live_run
        ws.send_text(json.dumps({"type": "hello", "boot_id": "x", "last_seq": 0}))
        _until(ws, "snapshot")

        assert admin.post(f"/api/runs/{live_run}/close", json={"confirm_name": "Borrel"}).is_success

        closed = _until(ws, "run_closed")
        assert closed["data"]["run_id"] == live_run
        assert closed["data"]["name"] == "Borrel"
        assert closed["version"] is None
    assert admin.get("/api/state").status_code == 409


def test_fifty_orders_racing_a_close_each_commit_before_it_or_find_no_run(
    live_client: TestClient, live_run: int, settings: Settings, api_env: str
) -> None:
    """AC4, SD16: an order commits before the close (and is the run's) or is `no_live_run`.

    The race runs on the app's own loop. Each order re-quotes on `price_changed`,
    as the bar does, so its only outcomes are a commit or `no_live_run`.
    """
    state = live_client.app.state  # type: ignore[attr-defined]
    holder: MarketHolder = state.holder
    clock: Clock = state.clock
    drink = holder.drink_ids[0]

    async def order(k: int) -> int | None:
        await asyncio.sleep(0)
        price, version = _live_price(holder, drink), holder.state.version  # type: ignore[union-attr]
        while True:
            if not holder.is_empty:  # re-quote, as the bar does; else send the last quote
                price, version = _live_price(holder, drink), holder.state.version  # type: ignore[union-attr]
            try:
                placed = await place_order(
                    holder,
                    OrderRequest(
                        idempotency_key=f"race-{k:08d}",
                        quote_version=version,
                        lines=(QuotedLine(drink_id=drink, qty=1, unit_price_cents=price),),
                    ),
                    actor_key_id=None,
                    clock=clock,
                )
                return placed.receipt.order_id
            except PriceChangedError:
                continue
            except NoLiveRunError:
                return None

    async def race() -> list[int | None]:
        from app.runtime.close import close_in_process

        orders = [asyncio.ensure_future(order(k)) for k in range(25)]
        closing = asyncio.ensure_future(
            close_in_process(state, live_run, confirm_name="Borrel", author="test")
        )
        orders += [asyncio.ensure_future(order(k)) for k in range(25, 50)]
        results = await asyncio.gather(*orders)
        await closing
        return list(results)

    results = live_client.portal.call(race)  # type: ignore[union-attr]

    committed = sorted(r for r in results if r is not None)
    assert len(committed) + results.count(None) == 50
    assert 0 < len(committed) < 50
    ended_at = _ended_at_ms(settings, api_env, live_run)
    stored = _sql(
        settings,
        api_env,
        'SELECT order_id, wall_ts_ms FROM "order" WHERE run_id = :r ORDER BY order_id',
        r=live_run,
    )
    assert [order_id for order_id, _ in stored] == committed
    assert ended_at is not None
    assert all(wall_ts_ms <= ended_at for _, wall_ts_ms in stored)
    assert _sql(settings, api_env, "SELECT run_id, kind FROM export") == [(live_run, "final")]


def _live_price(holder: MarketHolder, drink_id: int) -> int:
    from app.db.codec import tick_prices
    from app.db.mapping import cents_from_quantised

    assert holder.spec is not None and holder.state is not None
    prices = tick_prices(holder.spec, holder.state, holder.drink_ids)
    return cents_from_quantised(prices[drink_id]["p_q"])


def test_after_a_close_a_new_borrel_can_start_and_the_old_one_is_kept(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC5: `POST /api/runs` is 201; the closed run's rows are untouched."""
    admin = login("admin")
    drink = live_client.app.state.holder.drink_ids[0]  # type: ignore[attr-defined]
    price = _live_price(live_client.app.state.holder, drink)  # type: ignore[attr-defined]
    placed = admin.post(
        "/api/orders",
        json={
            "quote_version": live_client.app.state.holder.state.version,  # type: ignore[attr-defined]
            "lines": [{"drink_id": drink, "qty": 2, "unit_price_cents": price}],
        },
        headers={"Idempotency-Key": "close-0000001"},
    )
    assert placed.status_code == 201, placed.text
    assert admin.post("/api/news", json={"level": "info", "text": "Proost"}).is_success
    counts = (
        'SELECT (SELECT count(*) FROM "order" WHERE run_id = :r),'
        ' (SELECT count(*) FROM order_line JOIN "order" USING (order_id) WHERE run_id = :r),'
        " (SELECT count(*) FROM price_tick WHERE run_id = :r),"
        " (SELECT count(*) FROM news WHERE run_id = :r)"
    )
    assert admin.post(f"/api/runs/{live_run}/close", json={"confirm_name": "Borrel"}).is_success
    before = _sql(settings, api_env, counts, r=live_run)

    created = admin.post("/api/runs", json={"name": "Volgende"})

    assert created.status_code == 201, created.text
    assert _sql(settings, api_env, counts, r=live_run) == before
    assert before[0][0] == 1 and before[0][3] == 1


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(
    live_client: TestClient, live_run: int, login: Login, role: str
) -> None:
    response = login(role).post(f"/api/runs/{live_run}/close", json={"confirm_name": "Borrel"})

    assert response.status_code == 403


def test_an_unknown_field_is_422(live_client: TestClient, live_run: int, login: Login) -> None:
    response = login("admin").post(
        f"/api/runs/{live_run}/close", json={"confirm_name": "Borrel", "force": True}
    )

    assert response.status_code == 422
    assert not live_client.app.state.holder.is_empty  # type: ignore[attr-defined]
