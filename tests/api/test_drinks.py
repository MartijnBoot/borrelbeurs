"""Drinks over HTTP: add (Phase 6 T12: SD5, SD12, SD17; AC4, AC11, AC21).

`POST /api/runs/{run_id}/drinks` on a draft or the live run. Absent optional
fields take the server defaults (AC4); a `null` is 422 naming the field; the
resulting row must satisfy SD8's per-drink checks (AC11); a name that matches an
active drink, trimmed and case-folded, is 409 `duplicate_drink_name` (AC21).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.runs import create_run
from app.db.session import create_engine
from tests.api.conftest import Login

BIER: dict[str, Any] = {"name": "Bier", "p_min_cents": 150, "p0_cents": 260, "p_max_cents": 500}


def _sql(settings: Settings, url: str, sql: str, **bind: Any) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), bind)
                return result.scalar_one() if result.returns_rows else None
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


@pytest.fixture
def draft(settings: Settings, api_env: str) -> int:
    async def scenario() -> int:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            return await create_run(engine, name="Concept", author="seed")
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _revisions(settings: Settings, url: str, run_id: int) -> int:
    return int(
        _sql(settings, url, "SELECT count(*) FROM run_config_revision WHERE run_id = :r", r=run_id)
    )


def _faults(response: Any) -> list[str]:
    return [fault["loc"][-1] for fault in response.json()["error"]["faults"]]


def test_an_add_with_blanks_stores_the_defaults(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC4, server half."""
    admin = login("admin", label="Bestuur")

    response = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "  Bier "})

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["revision"] == 2
    drinks = admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    assert drinks == [
        {
            "drink_id": created["drink_id"],
            "slot": 0,
            "name": "Bier",
            "active": True,
            "p_min_cents": 150,
            "p0_cents": 260,
            "p_max_cents": 500,
            "bar_price_cents": 260,
            "a": 10.0,
            "d": 0.6,
            "s0": 8.0,
            "c": 0.4,
        }
    ]
    assert _revisions(settings, api_env, draft) == 2


def test_given_optional_fields_are_stored(draft: int, client: TestClient, login: Login) -> None:
    admin = login("admin")
    body = {**BIER, "bar_price_cents": 300, "a": 1.5, "d": 0.2, "s0": 3.0, "c": 0.1}

    drink_id = admin.post(f"/api/runs/{draft}/drinks", json=body).json()["drink_id"]

    (stored,) = admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    assert stored["drink_id"] == drink_id
    assert {k: stored[k] for k in ("bar_price_cents", "a", "d", "s0", "c")} == {
        "bar_price_cents": 300,
        "a": 1.5,
        "d": 0.2,
        "s0": 3.0,
        "c": 0.1,
    }


def test_a_typed_emoji_in_the_name_is_stored_and_listed_as_typed(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """B-02 SD6, AC11: a drink name keeps the emoji it was typed with."""
    admin = login("admin")

    response = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "Bier 🍺"})

    assert response.status_code == 201, response.text
    drink_id = response.json()["drink_id"]
    stored = _sql(settings, api_env, "SELECT name FROM drink WHERE drink_id = :d", d=drink_id)
    assert stored == "Bier 🍺"
    (listed,) = admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    assert (listed["drink_id"], listed["name"]) == (drink_id, "Bier 🍺")


def test_the_new_slot_follows_every_row_removed_ones_included(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    admin.post(f"/api/runs/{draft}/drinks", json=BIER)
    _sql(settings, api_env, "UPDATE drink SET removed_at = now() WHERE run_id = :r", r=draft)

    admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "Wijn"})

    slots = [
        (d["name"], d["slot"]) for d in admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    ]
    assert slots == [("Bier", 0), ("Wijn", 1)]


@pytest.mark.parametrize("field", ["name", "p0_cents", "bar_price_cents", "a", "s0"])
def test_a_null_is_422_naming_the_field(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str, field: str
) -> None:
    """AC3, server half."""
    response = login("admin").post(f"/api/runs/{draft}/drinks", json={**BIER, field: None})

    assert response.status_code == 422, response.text
    assert field in _faults(response)
    assert _revisions(settings, api_env, draft) == 1


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"p_min_cents": -1, "p0_cents": 260}, "p_min_cents"),
        ({"p0_cents": 150}, "p0_cents"),
        ({"p0_cents": 500}, "p0_cents"),
        ({"p_max_cents": 100, "p0_cents": 120, "p_min_cents": 150}, "p0_cents"),
        ({"bar_price_cents": -1}, "bar_price_cents"),
        ({"p0_cents": 2.5}, "p0_cents"),
        ({"a": "1"}, "a"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 41}, "name"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_an_sd8_violation_is_422_naming_the_field_and_adds_nothing(
    draft: int,
    client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    change: dict[str, Any],
    field: str,
) -> None:
    """AC11: checked on the resulting row."""
    admin = login("admin")

    response = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, **change})

    assert response.status_code == 422, response.text
    assert field in _faults(response)
    assert admin.get(f"/api/runs/{draft}/config").json()["drinks"] == []
    assert _revisions(settings, api_env, draft) == 1


@pytest.mark.parametrize("literal", ["NaN", "Infinity"])
def test_a_non_finite_coefficient_is_422(
    draft: int, client: TestClient, login: Login, literal: str
) -> None:
    body = json.dumps({**BIER, "d": 0.6}).replace("0.6", literal)

    response = login("admin").post(
        f"/api/runs/{draft}/drinks", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 422, response.text
    assert "d" in _faults(response)


def test_a_name_beside_an_active_one_is_409_and_a_removed_name_gets_a_new_id(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC21."""
    admin = login("admin")
    first = admin.post(f"/api/runs/{draft}/drinks", json=BIER).json()["drink_id"]

    duplicate = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "  BIER "})

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_drink_name"
    _sql(settings, api_env, "UPDATE drink SET removed_at = now() WHERE drink_id = :d", d=first)
    again = admin.post(f"/api/runs/{draft}/drinks", json=BIER)
    assert again.status_code == 201, again.text
    assert again.json()["drink_id"] != first


def test_a_live_add_quotes_p0_and_broadcasts_config(
    live_run: int, live_client: TestClient, login: Login
) -> None:
    """AC12, AC14 (the new drink quotes p0), over HTTP and a real socket."""
    admin = login("admin")
    version = admin.get("/api/state").json()["version"]

    with admin.websocket_connect("wss://testserver/ws") as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
        ws.send_text(json.dumps({"type": "hello", "boot_id": "elsewhere", "last_seq": 0}))
        assert json.loads(ws.receive_text())["type"] == "snapshot"
        response = admin.post(
            f"/api/runs/{live_run}/drinks", json={**BIER, "name": "Cola", "p0_cents": 300}
        )
        frame = json.loads(ws.receive_text())
        while frame["type"] != "config":
            frame = json.loads(ws.receive_text())

    assert response.status_code == 201, response.text
    cola = response.json()["drink_id"]
    assert frame["version"] == version + 1
    assert (cola, "Cola", True) in [
        (d["drink_id"], d["name"], d["active"]) for d in frame["data"]["drinks"]
    ]
    state = admin.get("/api/state").json()
    assert state["prices"][str(cola)]["price_cents"] == 300


def test_an_ended_run_is_409_and_an_unknown_one_404(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    assert admin.post("/api/runs/999999/drinks", json=BIER).status_code == 404
    _sql(settings, api_env, "UPDATE run SET status = 'ended' WHERE run_id = :r", r=draft)

    response = admin.post(f"/api/runs/{draft}/drinks", json=BIER)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_ended"


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(draft: int, client: TestClient, login: Login, role: str) -> None:
    assert login(role).post(f"/api/runs/{draft}/drinks", json=BIER).status_code == 403


# --- T13: edit ---------------------------------------------------------------


def _bier(admin: TestClient, run_id: int) -> int:
    response = admin.post(f"/api/runs/{run_id}/drinks", json={**BIER, "p0_cents": 250})
    assert response.status_code == 201, response.text
    return int(response.json()["drink_id"])


def _drink(admin: TestClient, run_id: int, drink_id: int) -> dict[str, Any]:
    drinks = admin.get(f"/api/runs/{run_id}/config").json()["drinks"]
    return dict(next(d for d in drinks if d["drink_id"] == drink_id))


def test_an_edit_changes_only_present_fields_and_appends_a_revision(
    draft: int, client: TestClient, login: Login
) -> None:
    admin = login("admin")
    bier = _bier(admin, draft)
    before = _drink(admin, draft, bier)

    response = admin.patch(
        f"/api/runs/{draft}/drinks/{bier}", json={"a": 2.5, "bar_price_cents": 280}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"revision": 3}
    assert _drink(admin, draft, bier) == {**before, "a": 2.5, "bar_price_cents": 280}


@pytest.mark.parametrize("body", [{}, {"a": 10.0}])
def test_an_edit_that_changes_nothing_writes_no_revision(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str, body: Any
) -> None:
    """AC2 (empty drink PATCH)."""
    admin = login("admin")
    bier = _bier(admin, draft)

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == {"revision": 2}
    assert _revisions(settings, api_env, draft) == 2


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"p_min_cents": 300}, "p_min_cents"),
        ({"p_max_cents": 250}, "p_max_cents"),
        ({"p0_cents": 600}, "p0_cents"),
        ({"a": None}, "a"),
        ({"name": ""}, "name"),
        ({"bar_price_cents": -5}, "bar_price_cents"),
        ({"slot": 3}, "slot"),
    ],
)
def test_an_invalid_resulting_row_is_422_naming_the_field_and_stores_nothing(
    draft: int,
    client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    body: dict[str, Any],
    field: str,
) -> None:
    """AC11: `{"p_min_cents": 300}` against `p0 = 250` names `p_min_cents`."""
    admin = login("admin")
    bier = _bier(admin, draft)
    before = _drink(admin, draft, bier)

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json=body)

    assert response.status_code == 422, response.text
    assert field in _faults(response)
    assert _drink(admin, draft, bier) == before
    assert _revisions(settings, api_env, draft) == 2


def test_a_rename_rewrites_both_idle_target_lists(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC22 (rename), SD11."""
    admin = login("admin")
    bier = _bier(admin, draft)
    admin.patch(
        f"/api/runs/{draft}/config",
        json={"params": {"idle_targets": [bier], "idle_rise_targets": [bier]}},
    )

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json={"name": " Pils "})

    assert response.status_code == 200, response.text
    assert _drink(admin, draft, bier)["name"] == "Pils"
    params = _sql(settings, api_env, "SELECT params FROM run WHERE run_id = :r", r=draft)
    assert (params["idle_targets"], params["idle_rise_targets"]) == (["Pils"], ["Pils"])


def test_a_rename_onto_an_active_name_is_409(draft: int, client: TestClient, login: Login) -> None:
    """AC21 (rename)."""
    admin = login("admin")
    bier = _bier(admin, draft)
    admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "Wijn"})

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json={"name": "  WIJN"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_drink_name"
    assert _drink(admin, draft, bier)["name"] == "Bier"


def test_a_removed_drink_is_409_and_an_unknown_one_404(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    bier = _bier(admin, draft)
    missing = admin.patch(f"/api/runs/{draft}/drinks/999999", json={"a": 1.0})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "drink_not_found"
    _sql(settings, api_env, "UPDATE drink SET removed_at = now() WHERE drink_id = :d", d=bier)

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json={"a": 1.0})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "drink_removed"


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_may_not_edit(draft: int, client: TestClient, login: Login, role: str) -> None:
    assert login(role).patch(f"/api/runs/{draft}/drinks/1", json={}).status_code == 403


# --- T14: remove -------------------------------------------------------------


def test_removing_a_draft_drink_deletes_it_and_drops_it_from_idle_targets(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """SD13 (draft: a hard delete), AC22 (removal)."""
    admin = login("admin")
    bier = _bier(admin, draft)
    wijn = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "Wijn"}).json()["drink_id"]
    admin.patch(
        f"/api/runs/{draft}/config",
        json={"params": {"idle_targets": [bier, wijn], "idle_rise_targets": [bier]}},
    )

    response = admin.delete(f"/api/runs/{draft}/drinks/{bier}")

    assert response.status_code == 200, response.text
    assert response.json() == {"revision": 5}
    drinks = admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    assert [d["drink_id"] for d in drinks] == [wijn]
    assert _sql(settings, api_env, "SELECT count(*) FROM drink WHERE drink_id = :d", d=bier) == 0
    params = _sql(settings, api_env, "SELECT params FROM run WHERE run_id = :r", r=draft)
    assert (params["idle_targets"], params["idle_rise_targets"]) == (["Wijn"], [])


def test_removing_the_last_active_drink_is_409_and_changes_nothing(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC17."""
    admin = login("admin")
    bier = _bier(admin, draft)

    response = admin.delete(f"/api/runs/{draft}/drinks/{bier}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_active_drink"
    assert len(admin.get(f"/api/runs/{draft}/config").json()["drinks"]) == 1
    assert _revisions(settings, api_env, draft) == 2


def test_removing_an_unknown_or_removed_drink(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    bier = _bier(admin, draft)
    _bier_too = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "name": "Wijn"})
    assert _bier_too.status_code == 201

    missing = admin.delete(f"/api/runs/{draft}/drinks/999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "drink_not_found"
    _sql(settings, api_env, "UPDATE drink SET removed_at = now() WHERE drink_id = :d", d=bier)
    removed = admin.delete(f"/api/runs/{draft}/drinks/{bier}")
    assert removed.status_code == 409
    assert removed.json()["error"]["code"] == "drink_removed"


def test_a_live_removal_masks_the_drink_and_keeps_its_sales(
    live_run: int, live_client: TestClient, login: Login
) -> None:
    """SD13 (live), AC15, AC23 (server): the snapshot lists it inactive, its earnings stay."""
    admin = login("admin")
    state = admin.get("/api/state").json()
    bier = state["drinks"][0]["drink_id"]
    order = admin.post(
        "/api/orders",
        json={
            "quote_version": state["version"],
            "lines": [
                {
                    "drink_id": bier,
                    "qty": 2,
                    "unit_price_cents": state["prices"][str(bier)]["price_cents"],
                }
            ],
        },
        headers={"Idempotency-Key": "k-remove-0001"},
    )
    assert order.status_code in (200, 201), order.text

    response = admin.delete(f"/api/runs/{live_run}/drinks/{bier}")

    assert response.status_code == 200, response.text
    after = admin.get("/api/state").json()
    assert (after["drinks"][0]["drink_id"], after["drinks"][0]["active"]) == (bier, False)
    assert str(bier) not in after["prices"]
    assert after["earnings"][str(bier)]["qty"] == 2
    assert after["version"] > state["version"]


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_may_not_remove(
    draft: int, client: TestClient, login: Login, role: str
) -> None:
    assert login(role).delete(f"/api/runs/{draft}/drinks/1").status_code == 403


# --- B-07 T2: bounds on the Prijsstap grid -----------------------------------


def _step(admin: TestClient, run_id: int, step_quant: float) -> None:
    response = admin.patch(
        f"/api/runs/{run_id}/config", json={"params": {"step_quant": step_quant}}
    )
    assert response.status_code == 200, response.text


def _grid_faults(response: Any) -> list[tuple[str, str]]:
    return [(f["loc"][-1], f["msg"]) for f in response.json()["error"]["faults"]]


TEN = "Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30."
QUARTER = "Moet een veelvoud van de Prijsstap (0,25) zijn: 1,50 of 1,75."


@pytest.mark.parametrize(
    ("step", "change", "field", "msg"),
    [
        (0.1, {"p_min_cents": 124}, "p_min_cents", TEN),
        (0.1, {"p_max_cents": 124, "p_min_cents": 0, "p0_cents": 100}, "p_max_cents", TEN),
        (0.25, {"p_min_cents": 160}, "p_min_cents", QUARTER),
    ],
)
def test_an_off_grid_bound_on_add_is_422_with_its_neighbours_and_adds_nothing(
    draft: int,
    client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    step: float,
    change: dict[str, Any],
    field: str,
    msg: str,
) -> None:
    """B-07 AC1, on an add."""
    admin = login("admin")
    _step(admin, draft, step)
    revisions = _revisions(settings, api_env, draft)

    response = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, **change})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert _grid_faults(response) == [(field, msg)]
    assert admin.get(f"/api/runs/{draft}/config").json()["drinks"] == []
    assert _revisions(settings, api_env, draft) == revisions


@pytest.mark.parametrize(
    ("step", "bounds"),
    [(0.1, (120, 500)), (0.1, (0, 500)), (0.25, (150, 500)), (0.25, (175, 500))],
)
def test_an_on_grid_bound_on_add_is_stored(
    draft: int, client: TestClient, login: Login, step: float, bounds: tuple[int, int]
) -> None:
    """B-07 AC1, the accepted values."""
    admin = login("admin")
    _step(admin, draft, step)
    body = {**BIER, "p_min_cents": bounds[0], "p_max_cents": bounds[1]}

    response = admin.post(f"/api/runs/{draft}/drinks", json=body)

    assert response.status_code == 201, response.text
    (stored,) = admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    assert (stored["p_min_cents"], stored["p_max_cents"]) == bounds


@pytest.mark.parametrize(
    ("step", "body", "field", "msg"),
    [
        (0.1, {"p_min_cents": 124}, "p_min_cents", TEN),
        (0.25, {"p_max_cents": 160, "p_min_cents": 0, "p0_cents": 100}, "p_max_cents", QUARTER),
    ],
)
def test_an_off_grid_bound_on_edit_is_422_and_stores_nothing(
    draft: int,
    client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    step: float,
    body: dict[str, Any],
    field: str,
    msg: str,
) -> None:
    """B-07 AC1, on an edit."""
    admin = login("admin")
    _step(admin, draft, step)
    bier = _bier(admin, draft)
    before = _drink(admin, draft, bier)
    revisions = _revisions(settings, api_env, draft)

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json=body)

    assert response.status_code == 422, response.text
    assert _grid_faults(response) == [(field, msg)]
    assert _drink(admin, draft, bier) == before
    assert _revisions(settings, api_env, draft) == revisions


@pytest.mark.parametrize(
    ("step", "body"),
    [
        (0.1, {"p_min_cents": 120}),
        (0.1, {"p_min_cents": 0}),
        (0.25, {"p_max_cents": 175, "p_min_cents": 0, "p0_cents": 100}),
    ],
)
def test_an_on_grid_bound_on_edit_is_stored(
    draft: int, client: TestClient, login: Login, step: float, body: dict[str, Any]
) -> None:
    """B-07 AC1, the accepted values on an edit."""
    admin = login("admin")
    _step(admin, draft, step)
    bier = _bier(admin, draft)

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json=body)

    assert response.status_code == 200, response.text
    assert {k: _drink(admin, draft, bier)[k] for k in body} == body


@pytest.mark.parametrize(
    "body", [{"p0_cents": 300}, {"p_max_cents": 450}, {"name": "Pils", "a": 2.0}]
)
def test_an_edit_without_the_stored_off_grid_bound_keeps_it(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str, body: Any
) -> None:
    """B-07 AC2, SD6: only a bound present in the request is checked."""
    admin = login("admin")
    bier = _bier(admin, draft)
    _sql(settings, api_env, "UPDATE drink SET p_min_cents = 124 WHERE drink_id = :d", d=bier)

    response = admin.patch(f"/api/runs/{draft}/drinks/{bier}", json=body)

    assert response.status_code == 200, response.text
    after = _drink(admin, draft, bier)
    assert after["p_min_cents"] == 124
    assert {k: after[k] for k in body} == body


def test_an_off_grid_startprijs_between_on_grid_bounds_is_accepted(
    draft: int, client: TestClient, login: Login
) -> None:
    """B-07 AC3, SD2: on an add and on an edit."""
    admin = login("admin")

    added = admin.post(f"/api/runs/{draft}/drinks", json={**BIER, "p0_cents": 263})
    assert added.status_code == 201, added.text
    drink_id = added.json()["drink_id"]
    edited = admin.patch(f"/api/runs/{draft}/drinks/{drink_id}", json={"p0_cents": 277})

    assert edited.status_code == 200, edited.text
    assert _drink(admin, draft, drink_id)["p0_cents"] == 277


def test_a_live_off_grid_add_or_edit_takes_no_transition(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """B-07 AC1 on the live run: refused inside the step, so the version stays."""
    admin = login("admin")
    version = admin.get("/api/state").json()["version"]
    revisions = _revisions(settings, api_env, live_run)
    bier = admin.get(f"/api/runs/{live_run}/config").json()["drinks"][0]

    added = admin.post(
        f"/api/runs/{live_run}/drinks", json={**BIER, "name": "Cola", "p_min_cents": 124}
    )
    edited = admin.patch(
        f"/api/runs/{live_run}/drinks/{bier['drink_id']}", json={"p_max_cents": 455}
    )

    assert added.status_code == 422, added.text
    assert _grid_faults(added) == [("p_min_cents", TEN)]
    assert edited.status_code == 422, edited.text
    assert _grid_faults(edited) == [
        ("p_max_cents", "Moet een veelvoud van de Prijsstap (0,10) zijn: 4,50 of 4,60.")
    ]
    assert admin.get("/api/state").json()["version"] == version
    assert _revisions(settings, api_env, live_run) == revisions
    assert _drink(admin, live_run, bier["drink_id"]) == bier
