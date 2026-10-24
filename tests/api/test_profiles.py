"""Setting profiles over HTTP (B-04 T3: save, list, delete).

AC1 (a save stores the run's 22 as committed), AC2 (`profile_exists`, and an
overwrite that keeps the stored name), AC4 (a run value outside today's rules is
422 naming it), AC5 (ended, unknown, bad names), AC6 (nothing but the 22), AC17
(delete), AC18 (no run touched), AC24 (admin only).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.runs import create_run
from app.db.session import create_engine
from app.runtime.config_patch import PROFILE_FIELDS
from tests.api.conftest import Login


def _sql(settings: Settings, url: str, sql: str, **bind: Any) -> list[Any]:
    async def scenario() -> list[Any]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), bind)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _draft(settings: Settings, url: str, name: str = "Proef") -> int:
    async def scenario() -> int:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await create_run(engine, name=name, author="seed")
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _stored(settings: Settings, url: str) -> list[dict[str, Any]]:
    rows = _sql(
        settings,
        url,
        "SELECT name, settings, source_run_name, saved_by FROM settings_profile "
        "ORDER BY profile_id",
    )
    return [dict(row._mapping) for row in rows]


def _run_state(settings: Settings, url: str) -> list[tuple[Any, ...]]:
    """Every run's params, Kaarsbreedte and revision count: what AC18 says stays."""
    return [
        tuple(row)
        for row in _sql(
            settings,
            url,
            "SELECT run_id, params, candle_interval_ms, "
            "(SELECT count(*) FROM run_config_revision r WHERE r.run_id = run.run_id) "
            "FROM run ORDER BY run_id",
        )
    ]


def _document_values(client: TestClient, run_id: int) -> dict[str, Any]:
    """The run's 22 as the page shows them: `GET config`'s params and Kaarsbreedte."""
    document = client.get(f"/api/runs/{run_id}/config").json()
    values = {**document["params"], "candle_interval_s": document["run"]["candle_interval_s"]}
    return {name: values[name] for name in PROFILE_FIELDS}


def _save(client: TestClient, run_id: int, name: str, **extra: Any) -> Any:
    return client.post("/api/profiles", json={"name": name, "run_id": run_id, **extra})


@pytest.fixture
def draft(settings: Settings, api_env: str) -> int:
    return _draft(settings, api_env)


def test_a_save_from_a_draft_stores_its_22_as_committed(
    draft: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC1, AC6."""
    admin = login("admin", label="Bestuur")
    admin.patch(
        f"/api/runs/{draft}/config",
        json={"candle_interval_s": 30, "params": {"bm_sigma_y": 0.5}},
    )

    response = _save(admin, draft, " Wilde beurs ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"profile_id", "name", "saved_at", "source_run_name"}
    assert (body["name"], body["source_run_name"]) == ("Wilde beurs", "Proef")
    (stored,) = _stored(settings, api_env)
    assert set(stored["settings"]) == set(PROFILE_FIELDS)
    assert stored["settings"] == _document_values(admin, draft)
    assert (stored["settings"]["candle_interval_s"], stored["settings"]["bm_sigma_y"]) == (30, 0.5)
    assert (stored["source_run_name"], stored["saved_by"]) == ("Proef", "Bestuur")
    assert admin.get("/api/profiles").json() == [body]


def test_a_save_from_the_live_run_stores_its_22(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC1: a live run can be saved from, too."""
    admin = login("admin")

    response = _save(admin, live_run, "Live")

    assert response.status_code == 201, response.text
    (stored,) = _stored(settings, api_env)
    assert stored["settings"] == _document_values(admin, live_run)
    assert stored["source_run_name"] == "Borrel"


def test_an_existing_name_is_409_and_stores_nothing(
    draft: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC2, SD5: compared trimmed and case-folded; the error carries the profile's id."""
    admin = login("admin")
    first = _save(admin, draft, "Wilde beurs").json()
    before = _stored(settings, api_env)
    admin.patch(f"/api/runs/{draft}/config", json={"params": {"eta": 0.33}})

    response = _save(admin, draft, "  WILDE beurs")

    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["profile_id"]) == ("profile_exists", first["profile_id"])
    assert _stored(settings, api_env) == before


def test_an_overwrite_is_200_keeps_the_stored_name_and_replaces_the_values(
    draft: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC2."""
    admin = login("admin", label="Een")
    first = _save(admin, draft, "Wilde beurs").json()
    admin.patch(f"/api/runs/{draft}/config", json={"name": "Hernoemd", "params": {"eta": 0.33}})

    response = _save(login("admin", label="Twee"), draft, "wilde BEURS", overwrite=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["profile_id"], body["name"], body["source_run_name"]) == (
        first["profile_id"],
        "Wilde beurs",
        "Hernoemd",
    )
    assert body["saved_at"] >= first["saved_at"]
    (stored,) = _stored(settings, api_env)
    assert (stored["settings"]["eta"], stored["saved_by"]) == (0.33, "Twee")


def test_a_run_value_outside_todays_rules_is_422_naming_it(
    draft: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC4, SD9: an old run can carry a value today's range refuses."""
    _sql(
        settings,
        api_env,
        "UPDATE run SET params = jsonb_set(params, '{y_clip}', '25') WHERE run_id = :r",
        r=draft,
    )

    response = _save(login("admin"), draft, "Te wild")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert [fault["loc"] for fault in error["faults"]] == [["run", "params", "y_clip"]]
    assert _stored(settings, api_env) == []


def test_an_ended_run_is_409_run_ended(
    draft: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC5."""
    _sql(settings, api_env, "UPDATE run SET status = 'ended' WHERE run_id = :r", r=draft)

    response = _save(login("admin"), draft, "Oud")

    assert (response.status_code, response.json()["error"]["code"]) == (409, "run_ended")
    assert _stored(settings, api_env) == []


def test_an_unknown_run_is_404(login: Login, settings: Settings, api_env: str) -> None:
    """AC5."""
    response = _save(login("admin"), 999_999, "Niets")

    assert (response.status_code, response.json()["error"]["code"]) == (404, "run_not_found")
    assert _stored(settings, api_env) == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_a_blank_or_long_name_is_422_naming_name(draft: int, login: Login, name: str) -> None:
    """AC5, SD14."""
    response = _save(login("admin"), draft, name)

    assert response.status_code == 422
    assert any(fault["loc"][-1] == "name" for fault in response.json()["error"]["faults"])


def test_the_list_is_sorted_by_case_folded_name(draft: int, login: Login) -> None:
    """SD12: and carries no values (AC20)."""
    admin = login("admin")
    for name in ("gamma", "Beta", "alpha"):
        _save(admin, draft, name)

    listed = admin.get("/api/profiles").json()

    assert [p["name"] for p in listed] == ["alpha", "Beta", "gamma"]
    assert all(set(p) == {"profile_id", "name", "saved_at", "source_run_name"} for p in listed)


def test_a_delete_is_204_then_gone_and_an_unknown_one_is_404(draft: int, login: Login) -> None:
    """AC17."""
    admin = login("admin")
    profile_id = _save(admin, draft, "Weg").json()["profile_id"]

    deleted = admin.delete(f"/api/profiles/{profile_id}")
    again = admin.delete(f"/api/profiles/{profile_id}")

    assert deleted.status_code == 204
    assert admin.get("/api/profiles").json() == []
    assert (again.status_code, again.json()["error"]["code"]) == (404, "profile_not_found")


def test_delete_and_overwrite_change_no_run(
    draft: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC18, SD7: a profile has no link to a run."""
    admin = login("admin")
    profile_id = _save(admin, draft, "Wilde beurs").json()["profile_id"]
    before = _run_state(settings, api_env)

    _save(admin, draft, "Wilde beurs", overwrite=True)
    admin.delete(f"/api/profiles/{profile_id}")

    assert _run_state(settings, api_env) == before


def test_deleting_the_source_run_keeps_the_source_name(draft: int, login: Login) -> None:
    """AC18: the source name is copied text (SD7)."""
    admin = login("admin")
    _save(admin, draft, "Wilde beurs")

    deleted = admin.request("DELETE", f"/api/runs/{draft}", json={"confirm_name": "Proef"})

    assert deleted.status_code == 204, deleted.text
    assert [p["source_run_name"] for p in admin.get("/api/profiles").json()] == ["Proef"]


@pytest.mark.parametrize("role", ["display", "bar", None])
def test_the_profile_routes_are_admin_only(
    draft: int, client: TestClient, login: Login, role: str | None
) -> None:
    """AC24: 403 for display and bar, 401 without a session."""
    if role is not None:
        login(role)
    expected = 401 if role is None else 403

    assert client.get("/api/profiles").status_code == expected
    assert _save(client, draft, "x").status_code == expected
    assert client.delete("/api/profiles/1").status_code == expected
