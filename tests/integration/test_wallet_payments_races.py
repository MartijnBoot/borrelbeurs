"""Concurrent wallet payments never break the ledger (B-06 T18: SD14, SD15, SD8; AC9).

Through the real app: one `create_app`, its lifespan running, and httpx clients on
its ASGI interface, so requests really overlap on the app's event loop. Orders
are serialised by the market's lock; what races them is the kassa's actions,
each its own transaction, and the wallet row lock (`FOR UPDATE`) both take.

- Two bar sessions charge one wallet at once, together over balance + limit:
  the orders that fit succeed, each refusal is a 409 `insufficient_balance` whose
  own numbers show the order did not fit, and the balance never goes below
  -limit.
- A seeded sequence of wallet orders, top-ups, reversals, moves and refunds over
  three wallets runs in concurrent batches, each batch under a deadline (no
  deadlock). After every batch: each balance equals its entries; after each
  payment, the wallet's running balance is ≥ -limit; a wallet that never took a
  moved debt is ≥ -limit; each payment is refunded at most once, by its own
  amount, on its own wallet; no reversal took a balance below zero.

A moved debt may leave a wallet lower than -limit: a move carries a balance as
it is (SD8, AC28), so two debts added together can pass it. The limit binds a
payment, and that is where it is checked.

This test changes no source: one failing means the locking or a transaction is
wrong.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.security import issue_key
from app.core.config import Settings, get_settings
from app.db import wallets
from app.db.keys import Role
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.main import create_app
from exchange import Params
from tests.support.clock import FakeClock

# Serial (SD3): asserts a deadline -- `wait_for`'s 30 s is the no-deadlock check.
pytestmark = pytest.mark.serial

T0 = 1_759_312_800_000
BASE_URL = "https://testserver"
LIMIT = 250
SEED = 20261026
OPERATIONS = 240
BATCH = 8
POOL = 3
BATCH_DEADLINE_S = 30.0

# What each operation may answer; anything else fails the test.
ALLOWED = {
    "order": {
        201,
        (409, "price_changed"),
        (409, "insufficient_balance"),
        (404, "wallet_not_found"),
    },
    "topup": {201, (404, "wallet_not_found")},
    "reverse": {
        201,
        (409, "already_reversed"),
        (409, "insufficient_balance"),
        (409, "wallet_deleted"),
    },
    "move": {201, (409, "nothing_to_move"), (404, "wallet_not_found")},
    "refund": {201, (409, "already_refunded"), (409, "wallet_deleted")},
}


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """The app's settings on the scratch database, as `tests/api/conftest.py` does."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


async def _key(engine: AsyncEngine, role: Role, label: str) -> str:
    async with engine.begin() as conn:
        issued = await issue_key(conn, role=role, label=label)
    return issued.key


async def _live_run(engine: AsyncEngine) -> int:
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
        )
        for slot, name in enumerate(("Bier", "Wijn", "Fris")):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=150,
                p0_cents=260,
                p_max_cents=500,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )
    await go_live(engine, run_id, now_ms=T0)
    return run_id


@asynccontextmanager
async def _app(settings: Settings, url: str) -> AsyncIterator[dict[str, Any]]:
    """The booted app with a live run, a limit of `LIMIT`, and three logged-in sessions."""
    engine = create_engine(settings.model_copy(update={"database_url": url}))
    run_id = await _live_run(engine)
    keys = {
        "bar1": await _key(engine, "bar", "Bar 1"),
        "bar2": await _key(engine, "bar", "Bar 2"),
        "admin": await _key(engine, "admin", "Bestuur"),
    }
    target = create_app(clock=FakeClock(T0), run_migrations=False)
    try:
        async with target.router.lifespan_context(target):
            clients = {
                name: httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=target),
                    base_url=BASE_URL,
                    headers={"origin": BASE_URL},
                )
                for name in keys
            }
            try:
                for name, key in keys.items():
                    login = await clients[name].post("/api/auth/login", json={"key": key})
                    assert login.status_code == 200, login.text
                patched = await clients["admin"].patch(
                    f"/api/runs/{run_id}/config", json={"credit_limit_cents": LIMIT}
                )
                assert patched.status_code == 200, patched.text
                yield {"engine": engine, **clients}
            finally:
                for client in clients.values():
                    await client.aclose()
    finally:
        await engine.dispose()


async def _wallet(engine: AsyncEngine, name: str) -> wallets.WalletRow:
    async with engine.begin() as conn:
        return await wallets.create_wallet(conn, name=name, cookie_hash=f"h-{name}", now_ms=T0)


async def _top_up(admin: httpx.AsyncClient, wallet_id: int, amount: int, key: str) -> Any:
    return await admin.post(
        f"/api/kassa/wallets/{wallet_id}/topups",
        json={"amount_cents": amount},
        headers={"Idempotency-Key": key},
    )


async def _order(
    bar: httpx.AsyncClient, key: str, token: str, lines: list[tuple[int, int]]
) -> httpx.Response:
    """One wallet order of `lines` (drink index, qty) at the prices the bar sees now."""
    state = (await bar.get("/api/state")).json()
    drinks = sorted(int(d) for d in state["prices"])
    body = {
        "quote_version": state["version"],
        "lines": [
            {
                "drink_id": drinks[index],
                "qty": qty,
                "unit_price_cents": state["prices"][str(drinks[index])]["price_cents"],
            }
            for index, qty in lines
        ],
        "wallet": {"qr_token": token},
    }
    return await bar.post("/api/orders", json=body, headers={"Idempotency-Key": key})


def _outcome(response: httpx.Response) -> Any:
    if response.status_code in (200, 201):
        return 201
    error = response.json().get("error", {})
    return (response.status_code, error.get("code"))


def _total(response: httpx.Response) -> int:
    lines = json.loads(response.request.content)["lines"]
    return sum(line["qty"] * line["unit_price_cents"] for line in lines)


async def _rows(engine: AsyncEngine, sql: str) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        return [tuple(row) for row in await conn.execute(text(sql))]


def test_two_bars_charging_one_wallet_at_once_never_pass_the_limit(
    settings: Settings, on: str
) -> None:
    """AC9."""

    async def scenario() -> tuple[list[Any], list[httpx.Response], int]:
        async with _app(settings, on) as app:
            jan = await _wallet(app["engine"], "Jan")
            assert (
                await _top_up(app["admin"], jan.wallet_id, 1000, "k-race-fund")
            ).status_code == 201

            async def charge(bar: httpx.AsyncClient, n: int) -> httpx.Response:
                # A 409 price_changed is the bar's to confirm: a new key at the new price.
                for attempt in range(20):
                    response = await _order(bar, f"k-race-{n}-{attempt}", jan.qr_token, [(0, 1)])
                    if _outcome(response) != (409, "price_changed"):
                        return response
                raise AssertionError(f"order {n} never priced")

            responses = await asyncio.wait_for(
                asyncio.gather(*(charge(app["bar1" if n % 2 else "bar2"], n) for n in range(10))),
                BATCH_DEADLINE_S,
            )
            async with app["engine"].connect() as conn:
                balance = await wallets.balance(conn, jan.wallet_id)
            return [_outcome(r) for r in responses], list(responses), balance

    outcomes, responses, balance = asyncio.run(scenario())

    assert set(outcomes) <= {201, (409, "insufficient_balance")}, outcomes
    accepted = [r.json() for r in responses if _outcome(r) == 201]
    refused = [r for r in responses if _outcome(r) != 201]
    assert accepted and refused, outcomes  # anti-vacuity: some fit, some did not
    assert balance == 1000 - sum(receipt["total_cents"] for receipt in accepted)
    assert balance >= -LIMIT
    assert all(receipt["wallet"]["balance_after_cents"] >= -LIMIT for receipt in accepted)
    for response in refused:
        error = response.json()["error"]
        assert error["credit_limit_cents"] == LIMIT
        assert _total(response) > error["balance_cents"] + LIMIT, error


async def _check(engine: AsyncEngine) -> None:
    sums = {
        int(w): (int(total), bool(deleted))
        for w, total, deleted in await _rows(
            engine,
            "SELECT w.wallet_id, coalesce(sum(e.amount_cents), 0), w.deleted_at IS NOT NULL"
            " FROM wallet w LEFT JOIN wallet_entry e USING (wallet_id) GROUP BY w.wallet_id",
        )
    }
    async with engine.connect() as conn:
        for wallet_id, (total, deleted) in sums.items():
            if deleted:
                assert total == 0, (wallet_id, total)
            else:
                assert await wallets.balance(conn, wallet_id) == total
    # Entries of one wallet are written under its row lock, so their ids are in commit
    # order and a running sum by id is the balance after each entry.
    running = await _rows(
        engine,
        "SELECT wallet_id, entry_id, kind, amount_cents,"
        " sum(amount_cents) OVER (PARTITION BY wallet_id ORDER BY entry_id) FROM wallet_entry",
    )
    low_payments = [r for r in running if r[2] == "payment" and r[4] < -LIMIT]
    low_reversals = [r for r in running if r[2] == "reversal" and r[4] < 0]
    assert (low_payments, low_reversals) == ([], [])
    moved_debt = {
        int(r[0])
        for r in await _rows(
            engine, "SELECT wallet_id FROM wallet_entry WHERE kind = 'move_in' AND amount_cents < 0"
        )
    }
    assert all(total >= -LIMIT for w, (total, deleted) in sums.items() if w not in moved_debt), sums
    wrong_refunds = await _rows(
        engine,
        "SELECT r.entry_id FROM wallet_entry r JOIN wallet_entry p"
        " ON p.entry_id = r.refunds_entry_id WHERE r.kind = 'refund'"
        " AND (p.kind <> 'payment' OR r.amount_cents <> -p.amount_cents"
        " OR r.wallet_id <> p.wallet_id)",
    )
    twice = await _rows(
        engine,
        "SELECT refunds_entry_id FROM wallet_entry WHERE refunds_entry_id IS NOT NULL"
        " GROUP BY refunds_entry_id HAVING count(*) > 1",
    )
    assert (wrong_refunds, twice) == ([], [])


def test_a_random_concurrent_sequence_keeps_every_ledger_whole(settings: Settings, on: str) -> None:
    """AC9, SD14: orders, top-ups, reversals, moves and refunds in concurrent batches."""
    rng = random.Random(SEED)
    keys = iter(f"k-mix-{n:06d}" for n in range(10 * OPERATIONS))
    names = iter(f"Speler {n}" for n in range(10 * OPERATIONS))

    async def scenario() -> Counter[str]:
        outcomes: Counter[str] = Counter()
        async with _app(settings, on) as app:
            engine: AsyncEngine = app["engine"]
            admin: httpx.AsyncClient = app["admin"]
            topups: list[int] = []
            for batch in range(OPERATIONS // BATCH):
                live = {
                    int(w): str(t)
                    for w, t in await _rows(
                        engine, "SELECT wallet_id, qr_token FROM wallet WHERE deleted_at IS NULL"
                    )
                }
                for _ in range(POOL - len(live)):
                    fresh = await _wallet(engine, next(names))
                    live[fresh.wallet_id] = fresh.qr_token
                payments = [
                    int(p)
                    for (p,) in await _rows(
                        engine, "SELECT entry_id FROM wallet_entry WHERE kind = 'payment'"
                    )
                ]
                planned: list[tuple[str, Any]] = []
                for _ in range(BATCH):
                    kind = rng.choices(
                        ["order", "topup", "reverse", "move", "refund"], weights=[45, 22, 10, 8, 15]
                    )[0]
                    wallet_id = rng.choice(list(live))
                    if kind == "reverse" and topups:
                        planned.append(
                            (
                                kind,
                                admin.post(
                                    f"/api/kassa/topups/{rng.choice(topups)}/reversal",
                                    headers={"Idempotency-Key": next(keys)},
                                ),
                            )
                        )
                    elif kind == "move":
                        planned.append(
                            (
                                kind,
                                admin.post(
                                    f"/api/kassa/wallets/{wallet_id}/move",
                                    json={"from_wallet_id": rng.choice(list(live))},
                                    headers={"Idempotency-Key": next(keys)},
                                ),
                            )
                        )
                    elif kind == "refund" and payments:
                        planned.append(
                            (
                                kind,
                                admin.post(
                                    # The latest few, so some payment is refunded twice.
                                    f"/api/payments/{rng.choice(payments[-3:])}/refund",
                                    headers={"Idempotency-Key": next(keys)},
                                ),
                            )
                        )
                    elif kind == "order":
                        lines = [(index, rng.randint(1, 3)) for index in rng.sample(range(3), 2)]
                        bar = app[rng.choice(["bar1", "bar2"])]
                        planned.append((kind, _order(bar, next(keys), live[wallet_id], lines)))
                    else:
                        planned.append(("topup", _top_up(admin, wallet_id, 1000, next(keys))))
                responses = await asyncio.wait_for(
                    asyncio.gather(*(action for _, action in planned)), BATCH_DEADLINE_S
                )
                for (kind, _), response in zip(planned, responses, strict=True):
                    outcome = _outcome(response)
                    assert outcome in ALLOWED[kind], (
                        batch,
                        kind,
                        response.status_code,
                        response.text,
                    )
                    outcomes[kind if outcome == 201 else f"{kind}:{outcome[1]}"] += 1
                    if kind == "topup" and outcome == 201:
                        topups.append(int(response.json()["entry_id"]))
                await _check(engine)
        return outcomes

    outcomes = asyncio.run(scenario())

    assert sum(outcomes.values()) == OPERATIONS
    print(dict(outcomes))
    # Anti-vacuity: every kind booked, an order was refused for its balance, a refund
    # was refused as a repeat.
    for kind in ("order", "topup", "reverse", "move", "refund"):
        assert outcomes[kind] > 0, outcomes
    assert outcomes["order:insufficient_balance"] > 0, outcomes
    assert outcomes["refund:already_refunded"] > 0, outcomes
