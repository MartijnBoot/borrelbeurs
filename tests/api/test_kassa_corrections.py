"""Kassa: reversal, search and move, new code (B-05 T8: SD11, SD12, SD14; AC21-AC28, AC37, AC44)."""

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
from app.db.runs import create_draft_run
from app.db.session import create_engine
from app.db.wallets import EntryKind, InsufficientBalance, WalletRow
from app.runtime import wallets as actions
from app.runtime.wallet_codes import cookie_hash, display_short_code
from exchange import Params
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


def _sql(settings: Settings, url: str, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async def body(conn: AsyncConnection) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in await conn.execute(text(sql), params)]

    return list(_db(settings, url, body))


def _wallet(settings: Settings, url: str, name: str = "Jan", now_ms: int = 0) -> WalletRow:
    wallet: WalletRow = _db(
        settings,
        url,
        lambda conn: wallets.create_wallet(
            conn, name=name, cookie_hash=cookie_hash(f"cookie-{name}"), now_ms=now_ms
        ),
    )
    return wallet


def _entry(
    settings: Settings,
    url: str,
    wallet_id: int,
    amount: int,
    kind: EntryKind = "topup",
    run_id: int | None = None,
) -> int:
    entry = _db(
        settings,
        url,
        lambda conn: wallets.insert_entry(
            conn, wallet_id=wallet_id, kind=kind, amount_cents=amount, now_ms=0, run_id=run_id
        ),
    )
    return int(entry.entry_id)


def _count(settings: Settings, url: str) -> int:
    ((count,),) = _sql(settings, url, "SELECT count(*) FROM wallet_entry")
    return int(count)


def _balance(settings: Settings, url: str, wallet_id: int) -> int:
    ((total,),) = _sql(
        settings,
        url,
        "SELECT coalesce(sum(amount_cents), 0) FROM wallet_entry WHERE wallet_id = :w",
        w=wallet_id,
    )
    return int(total)


@pytest.fixture
def kassa(login: Login) -> TestClient:
    return login("kassa", "Kassa 1")


def _reverse(client: TestClient, entry_id: int, key: str = "k-reverse-001") -> Any:
    return client.post(f"/api/kassa/topups/{entry_id}/reversal", headers={"Idempotency-Key": key})


def _move(client: TestClient, to: int, source: int, key: str = "k-move-00001") -> Any:
    return client.post(
        f"/api/kassa/wallets/{to}/move",
        json={"from_wallet_id": source},
        headers={"Idempotency-Key": key},
    )


def _error(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# --- reversal (SD12) ------------------------------------------------------------


def test_a_reversal_writes_minus_the_amount_with_the_label_and_the_originals_run(
    live_run: int, kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC21: the reversal carries the original's run, not the run live now."""

    async def other_run(conn: AsyncConnection) -> int:
        return await create_draft_run(conn, name="Vorige", params=Params(), run_seed=1)

    earlier: int = _db(settings, api_env, other_run)
    wallet = _wallet(settings, api_env)
    topup = _entry(settings, api_env, wallet.wallet_id, 1500, run_id=earlier)

    response = _reverse(kassa, topup)

    assert response.status_code == 201, response.text
    assert response.json()["amount_cents"] == -1500
    ((kind, amount, reverses, run_id, label),) = _sql(
        settings,
        api_env,
        "SELECT kind, amount_cents, reverses_entry_id, run_id, actor_label FROM wallet_entry"
        " WHERE kind = 'reversal'",
    )
    assert (kind, amount, reverses, run_id, label) == ("reversal", -1500, topup, earlier, "Kassa 1")
    assert run_id != live_run
    listed = kassa.get(f"/api/kassa/wallets/{wallet.wallet_id}/topups").json()
    assert [t["reversed"] for t in listed] == [True]


def test_a_reversal_of_a_top_up_without_a_run_has_none(
    live_run: int, kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """SD12: the original's run even when that is NULL and a run is live."""
    wallet = _wallet(settings, api_env)
    topup = _entry(settings, api_env, wallet.wallet_id, 1500)

    assert _reverse(kassa, topup).status_code == 201
    assert _sql(settings, api_env, "SELECT run_id FROM wallet_entry WHERE kind = 'reversal'") == [
        (None,)
    ]


def test_a_reversal_replay_returns_the_stored_entry(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """PD9: the same key on the same top-up is a 200; on another top-up 422."""
    wallet = _wallet(settings, api_env)
    first, second = (_entry(settings, api_env, wallet.wallet_id, 1500) for _ in range(2))

    booked = _reverse(kassa, first)
    replay = _reverse(kassa, first)
    reused = _reverse(kassa, second)

    assert (booked.status_code, replay.status_code) == (201, 200)
    assert replay.json() == booked.json()
    assert _error(reused) == (422, "idempotency_key_reused")
    assert _count(settings, api_env) == 3


def test_a_second_reversal_is_already_reversed(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC22."""
    wallet = _wallet(settings, api_env)
    _entry(settings, api_env, wallet.wallet_id, 5000)
    topup = _entry(settings, api_env, wallet.wallet_id, 1500)
    assert _reverse(kassa, topup, key="k-reverse-001").status_code == 201

    again = _reverse(kassa, topup, key="k-reverse-002")

    assert _error(again) == (409, "already_reversed")
    assert _count(settings, api_env) == 3


def test_a_reversal_past_zero_is_insufficient_balance(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC22: 1500 topped up, 1000 moved away."""
    wallet = _wallet(settings, api_env)
    topup = _entry(settings, api_env, wallet.wallet_id, 1500)
    _entry(settings, api_env, wallet.wallet_id, -1000, kind="closing")

    assert _error(_reverse(kassa, topup)) == (409, "insufficient_balance")
    assert _count(settings, api_env) == 2


def test_a_reversal_on_a_deleted_wallet_is_wallet_deleted(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC22, SD12."""
    wallet = _wallet(settings, api_env)
    topup = _entry(settings, api_env, wallet.wallet_id, 1500)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=0))
    before = _count(settings, api_env)

    assert _error(_reverse(kassa, topup)) == (409, "wallet_deleted")
    assert _count(settings, api_env) == before


@pytest.mark.parametrize("kind", ["reversal", "move_in", "move_out", "closing", "unknown"])
def test_only_a_top_up_is_reversible(
    kassa: TestClient, settings: Settings, api_env: str, kind: str
) -> None:
    """AC24: any other entry answers as an unknown one does, 404."""
    wallet = _wallet(settings, api_env)
    topup = _entry(settings, api_env, wallet.wallet_id, 5000)
    entry_id = 999_999
    if kind == "reversal":
        entry_id = int(
            _db(
                settings,
                api_env,
                lambda conn: wallets.insert_entry(
                    conn,
                    wallet_id=wallet.wallet_id,
                    kind="reversal",
                    amount_cents=-5000,
                    reverses_entry_id=topup,
                    now_ms=0,
                ),
            ).entry_id
        )
        _entry(settings, api_env, wallet.wallet_id, 5000)
    elif kind == "move_in":
        out = _entry(settings, api_env, wallet.wallet_id, -1000, kind="move_out")
        entry_id = int(
            _db(
                settings,
                api_env,
                lambda conn: wallets.insert_entry(
                    conn,
                    wallet_id=wallet.wallet_id,
                    kind="move_in",
                    amount_cents=1000,
                    counterpart_entry_id=out,
                    now_ms=0,
                ),
            ).entry_id
        )
    elif kind in {"move_out", "closing"}:
        entry_id = _entry(settings, api_env, wallet.wallet_id, -1000, kind=kind)  # type: ignore[arg-type]
    before = _count(settings, api_env)

    assert _error(_reverse(kassa, entry_id)) == (404, "topup_not_found")
    assert _count(settings, api_env) == before


def test_two_concurrent_reversals_past_the_balance_book_at_most_its_worth(
    settings: Settings, api_env: str, kassa: TestClient
) -> None:
    """AC23, AC46 (API half): 1000 and 1500 reversed at once on a 2000 balance."""
    wallet = _wallet(settings, api_env)
    small = _entry(settings, api_env, wallet.wallet_id, 1000)
    large = _entry(settings, api_env, wallet.wallet_id, 1500)
    _entry(settings, api_env, wallet.wallet_id, -500, kind="closing")
    actor = actions.Actor(key_id=1, label="Kassa 1")

    async def scenario() -> list[Any]:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            return await asyncio.gather(
                *(
                    actions.reverse(
                        engine,
                        entry_id=entry,
                        idempotency_key=f"k-race-{entry:06d}",
                        actor=actor,
                        now_ms=0,
                    )
                    for entry in (small, large)
                ),
                return_exceptions=True,
            )
        finally:
            await engine.dispose()

    results = asyncio.run(scenario())

    booked = [r for r in results if isinstance(r, actions.Booked)]
    refused = [r for r in results if isinstance(r, InsufficientBalance)]
    assert (len(booked), len(refused)) == (1, 1), results
    assert _balance(settings, api_env, wallet.wallet_id) >= 0


# --- search (SD11, PD17) ----------------------------------------------------------


def test_the_search_lists_every_wallet_whose_name_contains_the_fragment(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC25: case-folded, with name, sign-up date, balance and last top-up."""
    jan = _wallet(settings, api_env, "Jan", now_ms=1_000)
    anna = _wallet(settings, api_env, "Anna", now_ms=2_000)
    _wallet(settings, api_env, "Piet")
    _entry(settings, api_env, jan.wallet_id, 1500)

    found = kassa.get("/api/kassa/wallets", params={"name": "AN"}).json()

    assert [row["name"] for row in found] == ["Anna", "Jan"]
    by_name = {row["name"]: row for row in found}
    assert by_name["Jan"]["wallet_id"] == jan.wallet_id
    assert by_name["Jan"]["balance_cents"] == 1500
    assert by_name["Jan"]["last_topup_at"] is not None
    assert by_name["Anna"]["balance_cents"] == 0
    assert by_name["Anna"]["last_topup_at"] is None
    assert by_name["Anna"]["created_at"] == anna.created_at.isoformat().replace("+00:00", "Z")


def test_a_typed_short_code_finds_its_wallet_first(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC25: a short code, typed in any spelling, finds one exactly."""
    _wallet(settings, api_env, "Aaron")
    piet = _wallet(settings, api_env, "Piet")

    typed = display_short_code(piet.short_code).lower()
    found = kassa.get("/api/kassa/wallets", params={"name": typed}).json()

    assert found[0]["wallet_id"] == piet.wallet_id


def test_the_search_escapes_like_wildcards_and_skips_deleted_wallets(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    gone = _wallet(settings, api_env, "Jannie")
    _wallet(settings, api_env, "Jan")
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, gone.wallet_id, now_ms=0))

    assert [r["name"] for r in kassa.get("/api/kassa/wallets", params={"name": "jan"}).json()] == [
        "Jan"
    ]
    assert kassa.get("/api/kassa/wallets", params={"name": "%"}).json() == []
    assert kassa.get("/api/kassa/wallets", params={"name": "_"}).json() == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_the_search_takes_one_to_forty_characters(kassa: TestClient, name: str) -> None:
    assert kassa.get("/api/kassa/wallets", params={"name": name}).status_code == 422


# --- move (SD11) -----------------------------------------------------------------


def test_a_move_carries_the_balance_and_the_name_and_deletes_the_old_wallet(
    live_run: int, kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC26."""
    old = _wallet(settings, api_env, "Jan")
    new = _wallet(settings, api_env, "Jan 2")
    _entry(settings, api_env, old.wallet_id, 1500)

    response = _move(kassa, new.wallet_id, old.wallet_id)

    assert response.status_code == 201, response.text
    assert (response.json()["wallet_id"], response.json()["amount_cents"]) == (new.wallet_id, 1500)
    entries = _sql(
        settings,
        api_env,
        "SELECT wallet_id, kind, amount_cents, run_id, actor_label, counterpart_entry_id"
        " FROM wallet_entry WHERE kind IN ('move_out', 'move_in') ORDER BY entry_id",
    )
    ((out_id,),) = _sql(
        settings, api_env, "SELECT entry_id FROM wallet_entry WHERE kind = 'move_out'"
    )
    assert entries == [
        (old.wallet_id, "move_out", -1500, live_run, "Kassa 1", None),
        (new.wallet_id, "move_in", 1500, live_run, "Kassa 1", out_id),
    ]
    assert _sql(
        settings,
        api_env,
        "SELECT name, qr_token, short_code, cookie_hash, deleted_at IS NOT NULL FROM wallet"
        " WHERE wallet_id = :w",
        w=old.wallet_id,
    ) == [(None, None, None, None, True)]
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet_entry WHERE kind = 'closing'") == [
        (0,)
    ]
    assert (
        _balance(settings, api_env, old.wallet_id),
        _balance(settings, api_env, new.wallet_id),
    ) == (
        0,
        1500,
    )

    kassa.cookies.set("bb_wallet", "cookie-Jan 2")
    page = kassa.get("/api/wallet")
    assert page.status_code == 200
    assert (page.json()["name"], page.json()["balance_cents"]) == ("Jan", 1500)


def test_a_move_replay_returns_the_stored_entry(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """PD9: same target and source; a key reused for another move is 422."""
    old = _wallet(settings, api_env, "Jan")
    new = _wallet(settings, api_env, "Jan 2")
    other = _wallet(settings, api_env, "Piet")
    _entry(settings, api_env, old.wallet_id, 1500)
    booked = _move(kassa, new.wallet_id, old.wallet_id)
    before = _count(settings, api_env)

    replay = _move(kassa, new.wallet_id, old.wallet_id)
    reused = _move(kassa, new.wallet_id, other.wallet_id)

    assert (booked.status_code, replay.status_code) == (201, 200)
    assert replay.json() == booked.json()
    assert _error(reused) == (422, "idempotency_key_reused")
    assert _count(settings, api_env) == before


def test_a_move_onto_itself_or_of_nothing_is_nothing_to_move(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC27."""
    jan = _wallet(settings, api_env, "Jan")
    empty = _wallet(settings, api_env, "Piet")
    _entry(settings, api_env, jan.wallet_id, 1500)

    assert _error(_move(kassa, jan.wallet_id, jan.wallet_id, key="k-move-self")) == (
        409,
        "nothing_to_move",
    )
    assert _error(_move(kassa, jan.wallet_id, empty.wallet_id, key="k-move-none")) == (
        409,
        "nothing_to_move",
    )
    assert _count(settings, api_env) == 1
    assert _sql(settings, api_env, "SELECT count(*) FROM wallet WHERE deleted_at IS NULL") == [(2,)]


def test_a_move_with_an_unknown_or_deleted_wallet_is_404(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    jan = _wallet(settings, api_env, "Jan")
    gone = _wallet(settings, api_env, "Piet")
    _entry(settings, api_env, jan.wallet_id, 1500)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, gone.wallet_id, now_ms=0))

    for to, source in (
        (gone.wallet_id, jan.wallet_id),
        (jan.wallet_id, gone.wallet_id),
        (999_999, jan.wallet_id),
        (jan.wallet_id, 999_999),
    ):
        response = _move(kassa, to, source, key=f"k-move-{to:06d}-{source:06d}")
        assert _error(response) == (404, "wallet_not_found"), (to, source)
    assert _count(settings, api_env) == 1


# --- new code (SD14) -------------------------------------------------------------


def test_a_new_code_replaces_the_token_and_short_code_and_keeps_the_cookie(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC28."""
    old = _wallet(settings, api_env)

    response = kassa.post(f"/api/kassa/wallets/{old.wallet_id}/new-code")

    assert response.status_code == 200, response.text
    fresh = response.json()
    assert fresh["qr_token"] != old.qr_token
    assert fresh["short_code"] != display_short_code(old.short_code)
    assert len(fresh["short_code"]) == 9 and fresh["short_code"][4] == "-"
    for body in ({"qr_token": old.qr_token}, {"short_code": old.short_code}):
        assert _error(kassa.post("/api/kassa/lookup", json=body)) == (404, "wallet_not_found")
    for body in ({"qr_token": fresh["qr_token"]}, {"short_code": fresh["short_code"]}):
        assert kassa.post("/api/kassa/lookup", json=body).json()["wallet_id"] == old.wallet_id
    kassa.cookies.set("bb_wallet", "cookie-Jan")
    page = kassa.get("/api/wallet")
    assert page.status_code == 200
    assert (page.json()["qr_token"], page.json()["short_code"]) == (
        fresh["qr_token"],
        fresh["short_code"],
    )


def test_a_new_code_for_an_unknown_or_deleted_wallet_is_404(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    gone = _wallet(settings, api_env)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, gone.wallet_id, now_ms=0))

    for wallet_id in (gone.wallet_id, 999_999):
        response = kassa.post(f"/api/kassa/wallets/{wallet_id}/new-code")
        assert _error(response) == (404, "wallet_not_found")


# --- who, and draining (AC37, AC44) ----------------------------------------------


def test_an_admin_key_may_reverse_move_and_renew(
    login: Login, settings: Settings, api_env: str
) -> None:
    """AC37."""
    admin = login("admin", "Bestuur")
    old = _wallet(settings, api_env, "Jan")
    new = _wallet(settings, api_env, "Piet")
    topup = _entry(settings, api_env, old.wallet_id, 3000)
    _entry(settings, api_env, old.wallet_id, 1000)

    assert _reverse(admin, topup).status_code == 201
    assert _move(admin, new.wallet_id, old.wallet_id).status_code == 201
    assert admin.post(f"/api/kassa/wallets/{new.wallet_id}/new-code").status_code == 200
    assert admin.get("/api/kassa/wallets", params={"name": "jan"}).status_code == 200


def test_the_writes_while_draining_are_503_and_write_nothing(
    kassa: TestClient, settings: Settings, api_env: str
) -> None:
    """AC44."""
    old = _wallet(settings, api_env, "Jan")
    new = _wallet(settings, api_env, "Piet")
    topup = _entry(settings, api_env, old.wallet_id, 1500)
    kassa.app.state.draining = True  # type: ignore[attr-defined]
    try:
        responses = [
            _reverse(kassa, topup),
            _move(kassa, new.wallet_id, old.wallet_id),
            kassa.post(f"/api/kassa/wallets/{old.wallet_id}/new-code"),
        ]
    finally:
        kassa.app.state.draining = False  # type: ignore[attr-defined]

    assert [_error(r) for r in responses] == [(503, "shutting_down")] * 3
    assert _count(settings, api_env) == 1
    assert _sql(
        settings, api_env, "SELECT qr_token FROM wallet WHERE wallet_id = :w", w=old.wallet_id
    ) == [(old.qr_token,)]
