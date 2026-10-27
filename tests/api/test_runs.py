"""Runs over HTTP: create a draft, find the current run (Phase 6 T8: SD2, SD4; PD2, PD6).

B-04 T5: a create carrying a profile (AC7, AC10, AC15, AC24).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.runs import DEFAULT_PARAMS
from app.db.session import create_engine
from app.runtime.config_patch import profile_settings
from tests.api.conftest import Login


def _insert_run(settings: Settings, url: str, *, status: str, name: str) -> None:
    async def scenario() -> None:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO run (status, name, params, run_seed) VALUES (:s, :n, '{}', 1)"
                    ),
                    {"s": status, "n": name},
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_create_on_an_empty_database_is_a_draft_and_the_current_run(login: Login) -> None:
    admin = login("admin", label="Bestuur")

    response = admin.post("/api/runs", json={"name": " Vrijmibo "})

    assert response.status_code == 201, response.text
    created = response.json()
    assert (created["name"], created["status"]) == ("Vrijmibo", "draft")
    assert admin.get("/api/runs/current").json() == created


def test_a_created_run_has_the_wallet_switch_on_and_no_credit(login: Login) -> None:
    """B-06 AC1 over HTTP: `POST /api/runs` makes a run with "Wallet verplicht" on."""
    admin = login("admin")
    run_id = admin.post("/api/runs", json={"name": "Vrijmibo"}).json()["run_id"]

    run = admin.get(f"/api/runs/{run_id}/config").json()["run"]

    assert (run["wallet_required"], run["credit_limit_cents"]) == (True, 0)


def test_a_second_create_is_409_draft_exists_carrying_the_drafts_id(login: Login) -> None:
    admin = login("admin")
    first = admin.post("/api/runs", json={"name": "Een"}).json()

    response = admin.post("/api/runs", json={"name": "Twee"})

    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["run_id"]) == ("draft_exists", first["run_id"])


def test_with_a_live_run_create_is_409_live_run_exists(
    live_client: TestClient, login: Login
) -> None:
    response = login("admin").post("/api/runs", json={"name": "Nog een"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "live_run_exists"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_a_blank_or_long_name_is_422_naming_name(login: Login, name: str) -> None:
    response = login("admin").post("/api/runs", json={"name": name})

    assert response.status_code == 422
    assert any(fault["loc"][-1] == "name" for fault in response.json()["error"]["faults"])


def test_current_is_404_with_no_run(login: Login) -> None:
    response = login("admin").get("/api/runs/current")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_current_run"


def test_current_prefers_the_live_run_over_a_draft(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    _insert_run(settings, api_env, status="draft", name="Concept")

    body = login("admin").get("/api/runs/current").json()

    assert body == {"run_id": live_run, "name": "Borrel", "status": "live"}


def test_an_ended_run_is_not_current(login: Login, settings: Settings, api_env: str) -> None:
    _insert_run(settings, api_env, status="ended", name="Oud")

    assert login("admin").get("/api/runs/current").status_code == 404


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(login: Login, role: str) -> None:
    client = login(role)

    assert client.post("/api/runs", json={"name": "x"}).status_code == 403
    assert client.get("/api/runs/current").status_code == 403


def test_create_copying_an_ended_run_holds_its_active_drinks(
    login: Login, settings: Settings, api_env: str
) -> None:
    """Phase 7 SD4, AC9 over HTTP: `copy_from_run_id` reaches `create_run`."""
    admin = login("admin")
    source = admin.post("/api/runs", json={"name": "Vorige"}).json()["run_id"]
    _add_drink(settings, api_env, run_id=source, name="Bier")
    _set_status(settings, api_env, run_id=source, status="ended")

    response = admin.post("/api/runs", json={"name": "Nieuw", "copy_from_run_id": source})

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Nieuw"
    assert _drink_names(settings, api_env, run_id=response.json()["run_id"]) == ["Bier"]


def test_create_copying_an_unknown_run_is_404_creating_nothing(login: Login) -> None:
    admin = login("admin")

    response = admin.post("/api/runs", json={"name": "Nieuw", "copy_from_run_id": 999})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"
    assert admin.get("/api/runs/current").status_code == 404


def _run_sql(settings: Settings, url: str, sql: str, values: dict[str, object]) -> list[object]:
    async def scenario() -> list[object]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), values)
                return list(result.scalars()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _add_drink(settings: Settings, url: str, *, run_id: int, name: str) -> None:
    _run_sql(
        settings,
        url,
        "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents, p0_cents, p_max_cents,"
        " a, d, s0, c, bar_price_cents) VALUES (:r, 0, :n, lower(:n), 100, 200, 300,"
        " 0, 0, 0, 0, 200)",
        {"r": run_id, "n": name},
    )


def _set_status(settings: Settings, url: str, *, run_id: int, status: str) -> None:
    _run_sql(
        settings, url, "UPDATE run SET status = :s WHERE run_id = :r", {"s": status, "r": run_id}
    )


def _drink_names(settings: Settings, url: str, *, run_id: int) -> list[object]:
    return _run_sql(
        settings, url, "SELECT name FROM drink WHERE run_id = :r ORDER BY slot", {"r": run_id}
    )


# --- B-04 T5: "Nieuwe borrel" with a profile (AC10, AC15, AC24; SD4, SD9) ---------


def _insert_profile(settings: Settings, url: str, values: dict[str, Any]) -> int:
    (profile_id,) = _run_sql(
        settings,
        url,
        "INSERT INTO settings_profile (name, name_key, settings, source_run_name, saved_by)"
        " VALUES ('Wilde beurs', 'wilde beurs', CAST(:s AS jsonb), 'Proef', 'a')"
        " RETURNING profile_id",
        {"s": json.dumps(values)},
    )
    return int(str(profile_id))


def _run_count(settings: Settings, url: str) -> int:
    (count,) = _run_sql(settings, url, "SELECT count(*) FROM run", {})
    return int(str(count))


def test_a_create_with_a_profile_takes_its_values(
    login: Login, settings: Settings, api_env: str
) -> None:
    """AC7 over HTTP: `profile_id` reaches `create_run`."""
    values = profile_settings(DEFAULT_PARAMS, 30_000) | {"eta": 0.33}
    profile_id = _insert_profile(settings, api_env, values)
    admin = login("admin")

    response = admin.post("/api/runs", json={"name": "Nieuw", "profile_id": profile_id})

    assert response.status_code == 201, response.text
    document = admin.get(f"/api/runs/{response.json()['run_id']}/config").json()
    assert (document["params"]["eta"], document["run"]["candle_interval_s"]) == (0.33, 30)


def test_a_create_with_an_unknown_profile_is_404_creating_nothing(
    login: Login, settings: Settings, api_env: str
) -> None:
    """AC10."""
    response = login("admin").post("/api/runs", json={"name": "Nieuw", "profile_id": 999_999})

    assert (response.status_code, response.json()["error"]["code"]) == (404, "profile_not_found")
    assert _run_count(settings, api_env) == 0


def test_a_create_with_an_out_of_range_profile_is_422_naming_it_creating_nothing(
    login: Login, settings: Settings, api_env: str
) -> None:
    """AC10, SD9: a range tightened since the profile was saved."""
    values = profile_settings(DEFAULT_PARAMS, 60_000) | {"y_clip": 25}
    profile_id = _insert_profile(settings, api_env, values)

    response = login("admin").post("/api/runs", json={"name": "Nieuw", "profile_id": profile_id})

    assert response.status_code == 422
    faults = response.json()["error"]["faults"]
    assert [fault["loc"] for fault in faults] == [["profile", "params", "y_clip"]]
    assert _run_count(settings, api_env) == 0


def test_a_field_the_profile_lacks_comes_from_the_latest_run(
    login: Login, settings: Settings, api_env: str
) -> None:
    """AC15: a profile saved before a field existed keeps that field's base value."""
    admin = login("admin")
    old = admin.post("/api/runs", json={"name": "Vorige"}).json()["run_id"]
    admin.patch(f"/api/runs/{old}/config", json={"params": {"eta": 0.33}})
    _set_status(settings, api_env, run_id=old, status="ended")
    values = profile_settings(DEFAULT_PARAMS, 60_000) | {"y_clip": 4.0}
    del values["eta"]
    profile_id = _insert_profile(settings, api_env, values)

    response = admin.post("/api/runs", json={"name": "Nieuw", "profile_id": profile_id})

    assert response.status_code == 201, response.text
    params = admin.get(f"/api/runs/{response.json()['run_id']}/config").json()["params"]
    assert (params["eta"], params["y_clip"]) == (0.33, 4.0)


@pytest.mark.parametrize("role", ["display", "bar", None])
def test_a_create_carrying_a_profile_is_admin_only(
    client: TestClient, login: Login, settings: Settings, api_env: str, role: str | None
) -> None:
    """AC24."""
    profile_id = _insert_profile(settings, api_env, profile_settings(DEFAULT_PARAMS, 60_000))
    if role is not None:
        login(role)

    response = client.post("/api/runs", json={"name": "Nieuw", "profile_id": profile_id})

    assert response.status_code == (401 if role is None else 403)
    assert _run_count(settings, api_env) == 0


# --- B-07 T5: a copy that leaves a drink no room (AC13, server half) ----------


def test_a_colliding_copy_is_422_bounds_collision_creating_no_draft(
    login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    source = admin.post("/api/runs", json={"name": "Vorige"}).json()["run_id"]
    _add_drink(settings, api_env, run_id=source, name="Bier")
    # On a 2,00 step, Bier's 1,00-3,00 becomes 2,00-2,00.
    _run_sql(
        settings,
        api_env,
        "UPDATE run SET status = 'ended', params = jsonb_set(params, '{step_quant}', '2.0')"
        " WHERE run_id = :r",
        {"r": source},
    )
    runs = _run_count(settings, api_env)

    response = admin.post("/api/runs", json={"name": "Nieuw", "copy_from_run_id": source})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "bounds_collision"
    assert error["faults"] == [
        {"loc": ["body", "copy_from_run_id"], "msg": error["message"]},
    ]
    assert error["message"].startswith("Past niet bij Bier: de grenzen worden 2,00")
    assert _run_count(settings, api_env) == runs
    assert admin.get("/api/runs/current").status_code == 404
