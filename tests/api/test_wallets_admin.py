"""Admin: the wallet list, the totals, delete and the settings (B-05 T9: SD6, SD15, SD16;
AC30, AC32-AC34, AC37, AC44)."""

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
from app.db.wallets import EntryKind, WalletRow, WalletSettingsRow, at
from app.runtime.wallet_codes import cookie_hash
from exchange import Params
from tests.api.conftest import Login

DAY_MS = 24 * 3600 * 1000
T0 = 1_759_312_800_000  # 2025-10-01T10:00:00Z


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


def _wallet(settings: Settings, url: str, name: str, now_ms: int = T0) -> WalletRow:
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
    *,
    kind: EntryKind = "topup",
    run_id: int | None = None,
    now_ms: int = T0,
    reverses: int | None = None,
) -> int:
    entry = _db(
        settings,
        url,
        lambda conn: wallets.insert_entry(
            conn,
            wallet_id=wallet_id,
            kind=kind,
            amount_cents=amount,
            now_ms=now_ms,
            run_id=run_id,
            reverses_entry_id=reverses,
        ),
    )
    return int(entry.entry_id)


def _run(settings: Settings, url: str, name: str, started_ms: int) -> int:
    async def body(conn: AsyncConnection) -> int:
        run_id = await create_draft_run(conn, name=name, params=Params(), run_seed=3)
        await conn.execute(
            text("UPDATE run SET started_at = :at WHERE run_id = :r"),
            {"at": at(started_ms), "r": run_id},
        )
        return run_id

    run_id: int = _db(settings, url, body)
    return run_id


def _iso(ms: int) -> str:
    return at(ms).isoformat().replace("+00:00", "Z")


@pytest.fixture
def admin(login: Login) -> TestClient:
    return login("admin", "Bestuur")


def _overview(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/admin/wallets")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _settings_body(**changes: Any) -> dict[str, Any]:
    return {"signup_code": "Borrel", "unfunded_days": 30, "inactive_months": 12, **changes}


# --- the list and the totals (SD16) -------------------------------------------------


def test_the_list_is_by_case_folded_name_with_balance_and_last_activity(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    """AC34 (API half), PD18: last activity is the newest entry, else the creation."""
    gamma = _wallet(settings, api_env, "gamma", now_ms=T0)
    beta = _wallet(settings, api_env, "Beta", now_ms=T0 + 1_000)
    alpha = _wallet(settings, api_env, "alpha", now_ms=T0 + 2_000)
    _entry(settings, api_env, beta.wallet_id, 1500, now_ms=T0 + 5_000)
    _entry(settings, api_env, beta.wallet_id, 2000, now_ms=T0 + 9_000)

    listed = _overview(admin)["wallets"]

    assert [(w["wallet_id"], w["name"], w["balance_cents"]) for w in listed] == [
        (alpha.wallet_id, "alpha", 0),
        (beta.wallet_id, "Beta", 3500),
        (gamma.wallet_id, "gamma", 0),
    ]
    assert [w["last_activity_at"] for w in listed] == [_iso(T0 + 2_000), _iso(T0 + 9_000), _iso(T0)]


def test_the_outstanding_total_is_every_live_wallets_balance(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    """AC34: a deleted wallet's ledger sums to zero, so it adds nothing."""
    jan, piet, gone = (_wallet(settings, api_env, n) for n in ("Jan", "Piet", "Weg"))
    _entry(settings, api_env, jan.wallet_id, 1500)
    _entry(settings, api_env, piet.wallet_id, 2500)
    _entry(settings, api_env, gone.wallet_id, 4000)
    _db(settings, api_env, lambda conn: wallets.delete_wallet(conn, gone.wallet_id, now_ms=T0))

    body = _overview(admin)

    assert body["outstanding_cents"] == 4000
    assert [w["name"] for w in body["wallets"]] == ["Jan", "Piet"]


def test_the_per_borrel_totals_are_net_of_reversals_newest_first(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    """AC34, SD12, PD18: a reversal counts against its top-up's borrel."""
    older = _run(settings, api_env, "Oktoberborrel", T0)
    newer = _run(settings, api_env, "Novemberborrel", T0 + 30 * DAY_MS)
    jan = _wallet(settings, api_env, "Jan")
    _entry(settings, api_env, jan.wallet_id, 1000, run_id=older)
    reversed_ = _entry(settings, api_env, jan.wallet_id, 2000, run_id=older)
    _entry(
        settings, api_env, jan.wallet_id, -2000, kind="reversal", run_id=older, reverses=reversed_
    )
    _entry(settings, api_env, jan.wallet_id, 5000, run_id=newer)

    assert _overview(admin)["per_borrel"] == [
        {"run_id": newer, "name": "Novemberborrel", "net_topup_cents": 5000},
        {"run_id": older, "name": "Oktoberborrel", "net_topup_cents": 1000},
    ]


def test_top_ups_without_a_run_are_a_last_row_only_when_they_sum_to_something(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    """PD2 reading A: "Zonder borrel" is the row with `run_id` null."""
    run = _run(settings, api_env, "Borrel", T0)
    jan = _wallet(settings, api_env, "Jan")
    _entry(settings, api_env, jan.wallet_id, 1000, run_id=run)
    loose = _entry(settings, api_env, jan.wallet_id, 1500)

    assert _overview(admin)["per_borrel"][-1] == {
        "run_id": None,
        "name": None,
        "net_topup_cents": 1500,
    }

    _entry(settings, api_env, jan.wallet_id, -1500, kind="reversal", reverses=loose)

    assert [row["run_id"] for row in _overview(admin)["per_borrel"]] == [run]


def test_moves_and_closings_are_no_top_ups(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    run = _run(settings, api_env, "Borrel", T0)
    jan = _wallet(settings, api_env, "Jan")
    _entry(settings, api_env, jan.wallet_id, 3000, run_id=run)
    _entry(settings, api_env, jan.wallet_id, -1000, kind="move_out", run_id=run)
    _entry(settings, api_env, jan.wallet_id, -500, kind="closing", run_id=run)

    assert _overview(admin)["per_borrel"] == [
        {"run_id": run, "name": "Borrel", "net_topup_cents": 3000}
    ]


def test_an_empty_section_is_all_zero(admin: TestClient) -> None:
    assert _overview(admin) == {"outstanding_cents": 0, "per_borrel": [], "wallets": []}


# --- delete (SD15) -------------------------------------------------------------------


def test_an_admin_delete_is_a_players_delete_with_the_key_on_the_closing_entry(
    live_run: int, admin: TestClient, settings: Settings, api_env: str
) -> None:
    """AC30, as AC29: a closing entry of minus the balance, the row blank, the name free."""
    jan = _wallet(settings, api_env, "Jan")
    _entry(settings, api_env, jan.wallet_id, 3500, run_id=live_run)

    response = admin.delete(f"/api/admin/wallets/{jan.wallet_id}")

    assert response.status_code == 204
    assert _sql(
        settings,
        api_env,
        "SELECT kind, amount_cents, run_id, actor_label FROM wallet_entry WHERE kind = 'closing'",
    ) == [("closing", -3500, live_run, "Bestuur")]
    assert _sql(
        settings,
        api_env,
        "SELECT name, qr_token, short_code, cookie_hash, deleted_at IS NOT NULL FROM wallet",
    ) == [(None, None, None, None, True)]
    admin.cookies.set("bb_wallet", "cookie-Jan")
    assert admin.get("/api/wallet").status_code == 401
    assert _wallet(settings, api_env, "jan").name == "jan"


def test_an_admin_delete_of_a_wallet_in_debt_writes_the_debt_off(
    live_run: int, admin: TestClient, settings: Settings, api_env: str
) -> None:
    """B-06 AC27, SD8: at -350 a 204 and a closing of +350 with the live run and label."""
    jan = _wallet(settings, api_env, "Jan")
    _entry(settings, api_env, jan.wallet_id, 500, run_id=live_run)
    _entry(settings, api_env, jan.wallet_id, -850, kind="payment", run_id=live_run)

    response = admin.delete(f"/api/admin/wallets/{jan.wallet_id}")

    assert response.status_code == 204
    assert _sql(
        settings,
        api_env,
        "SELECT kind, amount_cents, run_id, actor_label FROM wallet_entry WHERE kind = 'closing'",
    ) == [("closing", 350, live_run, "Bestuur")]
    assert _sql(settings, api_env, "SELECT sum(amount_cents) FROM wallet_entry") == [(0,)]
    assert _sql(settings, api_env, "SELECT name FROM wallet") == [(None,)]


def test_deleting_an_unknown_or_deleted_wallet_is_404(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    jan = _wallet(settings, api_env, "Jan")
    assert admin.delete(f"/api/admin/wallets/{jan.wallet_id}").status_code == 204

    for wallet_id in (jan.wallet_id, 999_999):
        response = admin.delete(f"/api/admin/wallets/{wallet_id}")
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "wallet_not_found",
        )


def test_a_borrels_top_up_total_is_the_same_after_any_delete(
    live_run: int, admin: TestClient, settings: Settings, api_env: str
) -> None:
    """AC32: by the player, by admin and by the repository (the clean-up's path)."""
    names = ("Speler", "Beheer", "Opruimen")
    funded = {name: _wallet(settings, api_env, name) for name in names}
    for amount, wallet in enumerate(funded.values(), start=1):
        _entry(settings, api_env, wallet.wallet_id, 1000 * amount, run_id=live_run)
    before = _overview(admin)["per_borrel"]
    assert before == [{"run_id": live_run, "name": "Borrel", "net_topup_cents": 6000}]

    admin.cookies.set("bb_wallet", "cookie-Speler")
    assert admin.delete("/api/wallet").status_code == 204
    assert _overview(admin)["per_borrel"] == before
    assert admin.delete(f"/api/admin/wallets/{funded['Beheer'].wallet_id}").status_code == 204
    assert _overview(admin)["per_borrel"] == before
    _db(
        settings,
        api_env,
        lambda conn: wallets.delete_wallet(conn, funded["Opruimen"].wallet_id, now_ms=T0),
    )
    after = _overview(admin)
    assert after["per_borrel"] == before
    assert (after["outstanding_cents"], after["wallets"]) == (0, [])


# --- settings (SD6, SD15, PD12) ------------------------------------------------------


def test_the_settings_default_to_closed_thirty_days_and_twelve_months(admin: TestClient) -> None:
    assert admin.get("/api/admin/wallet-settings").json() == {
        "signup_code": None,
        "unfunded_days": 30,
        "inactive_months": 12,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"unfunded_days": 0},
        {"unfunded_days": 366},
        {"inactive_months": 0},
        {"inactive_months": 61},
        {"unfunded_days": 1.5},
        {"unfunded_days": "30"},
        {"inactive_months": True},
        {"signup_code": "x" * 41},
        {"signup_code": 1234},
        {"colour": "rood"},
    ],
)
def test_a_period_or_code_off_the_rules_is_422_and_stores_nothing(
    admin: TestClient, changes: dict[str, Any]
) -> None:
    """AC33."""
    response = admin.put("/api/admin/wallet-settings", json=_settings_body(**changes))

    assert response.status_code == 422, changes
    assert admin.get("/api/admin/wallet-settings").json()["signup_code"] is None


@pytest.mark.parametrize(("days", "months"), [(1, 1), (365, 60), (30, 12)])
def test_the_period_bounds_are_accepted(admin: TestClient, days: int, months: int) -> None:
    """AC33."""
    body = _settings_body(unfunded_days=days, inactive_months=months)

    assert admin.put("/api/admin/wallet-settings", json=body).json() == body
    assert admin.get("/api/admin/wallet-settings").json() == body


def test_a_code_is_trimmed_and_a_blank_one_closes_sign_up(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    """PD12, SD6: `"  "` stores null; a sign-up afterwards is `signup_closed`."""
    stored = admin.put("/api/admin/wallet-settings", json=_settings_body(signup_code=" ABC "))
    assert stored.json()["signup_code"] == "ABC"
    assert admin.post("/api/wallet", json={"name": "Jan", "code": "abc"}).status_code == 201
    admin.cookies.delete("bb_wallet")

    cleared = admin.put("/api/admin/wallet-settings", json=_settings_body(signup_code="  "))

    assert cleared.json()["signup_code"] is None
    assert _db(settings, api_env, wallets.get_settings) == WalletSettingsRow(None, 30, 12)
    refused = admin.post("/api/wallet", json={"name": "Piet", "code": "abc"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "signup_closed")


def test_a_null_code_closes_sign_up(admin: TestClient) -> None:
    admin.put("/api/admin/wallet-settings", json=_settings_body())

    response = admin.put("/api/admin/wallet-settings", json=_settings_body(signup_code=None))

    assert response.json()["signup_code"] is None


# --- draining (AC44) -----------------------------------------------------------------


def test_the_admin_writes_while_draining_are_503_and_write_nothing(
    admin: TestClient, settings: Settings, api_env: str
) -> None:
    jan = _wallet(settings, api_env, "Jan")
    admin.app.state.draining = True  # type: ignore[attr-defined]
    try:
        responses = [
            admin.delete(f"/api/admin/wallets/{jan.wallet_id}"),
            admin.put("/api/admin/wallet-settings", json=_settings_body()),
        ]
    finally:
        admin.app.state.draining = False  # type: ignore[attr-defined]

    assert [r.status_code for r in responses] == [503, 503]
    assert [w["name"] for w in _overview(admin)["wallets"]] == ["Jan"]
    assert admin.get("/api/admin/wallet-settings").json()["signup_code"] is None
