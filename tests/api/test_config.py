"""Config over HTTP: read and draft writes (Phase 6 T10: SD5, SD6, SD8, SD11; PD4, PD6, PD7).

AC2 (an empty body writes nothing), AC3 (`null` is 422 naming the field), AC11
(SD8 violations are 422 naming the field and change nothing), AC28 (the candle
interval's 422). SD8's "a-b" ranges include both ends (the user, 2026-10-08).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.runs import add_drink, create_run
from app.db.session import create_engine
from tests.api.conftest import Login


def _draft_with_drinks(settings: Settings, url: str, *, removed: tuple[str, ...] = ()) -> int:
    """A draft made the way `POST /api/runs` makes one, with Bier, Wijn and Fris."""

    async def scenario() -> int:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            run_id = await create_run(engine, name="Concept", author="seed")
            async with engine.begin() as conn:
                for slot, name in enumerate(("Bier", "Wijn", "Fris")):
                    await add_drink(
                        conn,
                        run_id,
                        name=name,
                        slot=slot,
                        p_min_cents=150,
                        p0_cents=260,
                        p_max_cents=500,
                        a=10.0,
                        d=0.6,
                        s0=8.0,
                        c=0.4,
                        bar_price_cents=260,
                    )
                for name in removed:
                    await conn.execute(
                        text("UPDATE drink SET removed_at = now() WHERE run_id = :r AND name = :n"),
                        {"r": run_id, "n": name},
                    )
            return run_id
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _scalar(settings: Settings, url: str, sql: str, **bind: Any) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return (await conn.execute(text(sql), bind)).scalar_one()
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _revisions(settings: Settings, url: str, run_id: int) -> int:
    return int(
        _scalar(
            settings, url, "SELECT count(*) FROM run_config_revision WHERE run_id = :r", r=run_id
        )
    )


def _set_status(settings: Settings, url: str, run_id: int, status: str) -> None:
    async def scenario() -> None:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE run SET status = :s WHERE run_id = :r"), {"s": status, "r": run_id}
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _fault_fields(response: Any) -> list[str]:
    return [fault["loc"][-1] for fault in response.json()["error"]["faults"]]


@pytest.fixture
def draft(settings: Settings, api_env: str) -> int:
    return _draft_with_drinks(settings, api_env)


def test_get_config_is_the_documented_shape(draft: int, client: TestClient, login: Login) -> None:
    body = login("admin").get(f"/api/runs/{draft}/config").json()

    assert body["revision"] == 1
    assert body["run"] == {
        "run_id": draft,
        "name": "Concept",
        "status": "draft",
        "candle_interval_s": 60,
    }
    assert set(body["params"]) == {
        "step_quant",
        "eta",
        "K",
        "lambda_orders",
        "alpha_price",
        "phi_persist",
        "decay_rho",
        "history_window_minutes",
        "refresh_minutes",
        "idle_decay_minutes",
        "idle_rise_minutes",
        "idle_strength",
        "idle_rise_strength",
        "idle_targets",
        "idle_rise_targets",
        "demand_enabled",
        "auto_calibrate_s0",
    }
    assert [d["name"] for d in body["drinks"]] == ["Bier", "Wijn", "Fris"]
    assert body["drinks"][0] == {
        "drink_id": body["drinks"][0]["drink_id"],
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


def test_a_removed_drink_is_listed_inactive(
    settings: Settings, api_env: str, client: TestClient, login: Login
) -> None:
    run_id = _draft_with_drinks(settings, api_env, removed=("Wijn",))

    drinks = login("admin").get(f"/api/runs/{run_id}/config").json()["drinks"]

    assert [(d["name"], d["active"]) for d in drinks] == [
        ("Bier", True),
        ("Wijn", False),
        ("Fris", True),
    ]


@pytest.mark.parametrize("body", [{}, {"params": {}}])
def test_an_empty_patch_returns_the_current_revision_and_writes_nothing(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str, body: Any
) -> None:
    """AC2, server half."""
    response = login("admin").patch(f"/api/runs/{draft}/config", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == {"revision": 1}
    assert _revisions(settings, api_env, draft) == 1


def test_a_patch_merges_only_present_keys_and_appends_a_revision(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin", label="Bestuur")
    before = admin.get(f"/api/runs/{draft}/config").json()

    response = admin.patch(
        f"/api/runs/{draft}/config",
        json={"name": " Vrijmibo ", "candle_interval_s": 30, "params": {"eta": 0.9}},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"revision": 2}
    after = admin.get(f"/api/runs/{draft}/config").json()
    assert after["revision"] == 2
    assert (after["run"]["name"], after["run"]["candle_interval_s"]) == ("Vrijmibo", 30)
    assert after["params"] == {**before["params"], "eta": 0.9}
    assert after["drinks"] == before["drinks"]
    author, stored = _stored_revision(settings, api_env, draft, 2)
    assert author == "Bestuur"
    assert stored == after  # PD6: the revision holds the GET body


def _stored_revision(settings: Settings, url: str, run_id: int, revision: int) -> tuple[str, Any]:
    async def scenario() -> tuple[str, Any]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT author, config FROM run_config_revision "
                            "WHERE run_id = :r AND revision = :v"
                        ),
                        {"r": run_id, "v": revision},
                    )
                ).one()
                return str(row.author), row.config
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_a_patch_that_changes_nothing_writes_no_revision(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    eta = admin.get(f"/api/runs/{draft}/config").json()["params"]["eta"]

    response = admin.patch(f"/api/runs/{draft}/config", json={"params": {"eta": eta}})

    assert response.json() == {"revision": 1}
    assert _revisions(settings, api_env, draft) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"params": {"eta": None}},
        {"name": None},
        {"candle_interval_s": None},
        {"params": None},
        {"params": {"demand_enabled": None}},
        {"params": {"idle_targets": None}},
    ],
)
def test_an_explicit_null_is_422_naming_the_field_and_stores_nothing(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str, body: Any
) -> None:
    """AC3, server half: never stored as 0."""
    admin = login("admin")
    before = admin.get(f"/api/runs/{draft}/config").json()

    response = admin.patch(f"/api/runs/{draft}/config", json=body)

    assert response.status_code == 422, response.text
    field = next(iter(body["params"])) if body.get("params") else next(iter(body))
    assert field in _fault_fields(response)
    assert admin.get(f"/api/runs/{draft}/config").json() == before
    assert _revisions(settings, api_env, draft) == 1


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"params": {"bm_sigma_y": 0.2}}, "bm_sigma_y"),
        ({"params": {"y_clip": 5.0}}, "y_clip"),
        ({"params": {"decay_rho": 1.5}}, "decay_rho"),
        ({"params": {"decay_rho": -0.01}}, "decay_rho"),
        ({"params": {"history_window_minutes": 0.5}}, "history_window_minutes"),
        ({"params": {"history_window_minutes": 241}}, "history_window_minutes"),
        ({"params": {"refresh_minutes": 0.05}}, "refresh_minutes"),
        ({"params": {"refresh_minutes": 10.5}}, "refresh_minutes"),
        ({"params": {"step_quant": 0}}, "step_quant"),
        ({"params": {"step_quant": 0.015}}, "step_quant"),
        ({"params": {"step_quant": 5.01}}, "step_quant"),
        ({"params": {"K": 0}}, "K"),
        ({"params": {"eta": -1}}, "eta"),
        ({"params": {"eta": "0.5"}}, "eta"),
        ({"params": {"idle_decay_minutes": 0.4}}, "idle_decay_minutes"),
        ({"params": {"idle_rise_strength": -0.1}}, "idle_rise_strength"),
        ({"params": {"demand_enabled": 0}}, "demand_enabled"),
        ({"candle_interval_s": 7}, "candle_interval_s"),
        ({"candle_interval_s": 0}, "candle_interval_s"),
        ({"candle_interval_s": 3605}, "candle_interval_s"),
        ({"name": "  "}, "name"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_an_sd8_violation_is_422_naming_the_field_and_changes_nothing(
    draft: int,
    client: TestClient,
    login: Login,
    settings: Settings,
    api_env: str,
    body: Any,
    field: str,
) -> None:
    """AC11, AC28 (422 half)."""
    admin = login("admin")
    before = admin.get(f"/api/runs/{draft}/config").json()

    response = admin.patch(f"/api/runs/{draft}/config", json=body)

    assert response.status_code == 422, response.text
    assert field in _fault_fields(response)
    assert admin.get(f"/api/runs/{draft}/config").json() == before
    assert _revisions(settings, api_env, draft) == 1


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_number_is_422_naming_the_field(
    draft: int, client: TestClient, login: Login, literal: str
) -> None:
    response = login("admin").patch(
        f"/api/runs/{draft}/config",
        content=f'{{"params": {{"eta": {literal}}}}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text
    assert "eta" in _fault_fields(response)


@pytest.mark.parametrize(
    "params",
    [
        {"decay_rho": 0},
        {"decay_rho": 1},
        {"history_window_minutes": 1},
        {"history_window_minutes": 240},
        {"refresh_minutes": 0.1},
        {"refresh_minutes": 10},
        {"step_quant": 5},
        {"step_quant": 0.01},
        {"idle_decay_minutes": 0.5},
    ],
)
def test_range_ends_are_inclusive(
    draft: int, client: TestClient, login: Login, params: dict[str, float]
) -> None:
    """SD8's a-b ranges include both ends (the user, 2026-10-08)."""
    admin = login("admin")

    response = admin.patch(f"/api/runs/{draft}/config", json={"params": params})

    assert response.status_code == 200, response.text
    ((field, value),) = params.items()
    assert admin.get(f"/api/runs/{draft}/config").json()["params"][field] == value


@pytest.mark.parametrize("seconds", [5, 3600])
def test_candle_interval_ends_are_inclusive(
    draft: int, client: TestClient, login: Login, seconds: int
) -> None:
    admin = login("admin")

    assert (
        admin.patch(f"/api/runs/{draft}/config", json={"candle_interval_s": seconds}).status_code
        == 200
    )
    assert admin.get(f"/api/runs/{draft}/config").json()["run"]["candle_interval_s"] == seconds


def test_idle_targets_are_drink_ids_on_the_wire_and_names_in_params(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """SD11, PD7."""
    admin = login("admin")
    ids = {
        d["name"]: d["drink_id"] for d in admin.get(f"/api/runs/{draft}/config").json()["drinks"]
    }

    response = admin.patch(
        f"/api/runs/{draft}/config",
        json={"params": {"idle_targets": [ids["Fris"], ids["Bier"]], "idle_rise_targets": []}},
    )

    assert response.status_code == 200, response.text
    params = admin.get(f"/api/runs/{draft}/config").json()["params"]
    assert params["idle_targets"] == [ids["Bier"], ids["Fris"]]
    assert params["idle_rise_targets"] == []
    stored = _scalar(settings, api_env, "SELECT params FROM run WHERE run_id = :r", r=draft)
    assert stored["idle_targets"] == ["Bier", "Fris"]


def test_an_unknown_or_removed_idle_target_is_422_naming_the_field(
    settings: Settings, api_env: str, client: TestClient, login: Login
) -> None:
    run_id = _draft_with_drinks(settings, api_env, removed=("Wijn",))
    admin = login("admin")
    ids = {
        d["name"]: d["drink_id"] for d in admin.get(f"/api/runs/{run_id}/config").json()["drinks"]
    }

    for body in (
        {"params": {"idle_rise_targets": [ids["Wijn"]]}},
        {"params": {"idle_rise_targets": [999_999]}},
    ):
        response = admin.patch(f"/api/runs/{run_id}/config", json=body)

        assert response.status_code == 422, response.text
        assert "idle_rise_targets" in _fault_fields(response)
    assert _revisions(settings, api_env, run_id) == 1


def test_a_stored_target_with_no_active_drink_is_dropped_from_the_response(
    settings: Settings, api_env: str, client: TestClient, login: Login
) -> None:
    """PD7."""
    run_id = _draft_with_drinks(settings, api_env, removed=("Wijn",))
    _set_params = """UPDATE run SET params = params || '{"idle_targets": ["Wijn", "Bier", "Weg"]}'
                     WHERE run_id = :r"""
    _scalar(settings, api_env, _set_params + " RETURNING run_id", r=run_id)
    admin = login("admin")
    body = admin.get(f"/api/runs/{run_id}/config").json()
    bier = next(d["drink_id"] for d in body["drinks"] if d["name"] == "Bier")

    assert body["params"]["idle_targets"] == [bier]


def test_a_live_patch_is_one_transition_and_one_config_frame(
    live_run: int, live_client: TestClient, login: Login
) -> None:
    """T11: AC9, AC12 over HTTP and a real socket."""
    admin = login("admin", label="Bestuur")
    before = admin.get(f"/api/runs/{live_run}/config").json()
    version = admin.get("/api/state").json()["version"]

    with admin.websocket_connect("wss://testserver/ws") as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
        ws.send_text(json.dumps({"type": "hello", "boot_id": "elsewhere", "last_seq": 0}))
        assert json.loads(ws.receive_text())["type"] == "snapshot"
        response = admin.patch(f"/api/runs/{live_run}/config", json={"params": {"eta": 0.9}})
        frame = json.loads(ws.receive_text())
        while frame["type"] != "config":
            frame = json.loads(ws.receive_text())

    assert response.status_code == 200, response.text
    assert response.json() == {"revision": before["revision"] + 1}
    assert frame["version"] == version + 1
    assert frame["data"]["revision"] == before["revision"] + 1
    assert frame["data"]["params"]["eta"] == 0.9
    after = admin.get(f"/api/runs/{live_run}/config").json()
    assert after["params"] == {**before["params"], "eta": 0.9}
    assert after["run"]["status"] == "live"


def test_an_ended_run_is_409_run_ended(
    draft: int, client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    _set_status(settings, api_env, draft, "ended")
    admin = login("admin")

    for response in (
        admin.get(f"/api/runs/{draft}/config"),
        admin.patch(f"/api/runs/{draft}/config", json={"params": {"eta": 0.9}}),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "run_ended"


def test_an_unknown_run_is_404_run_not_found(client: TestClient, login: Login) -> None:
    admin = login("admin")

    for response in (
        admin.get("/api/runs/999999/config"),
        admin.patch("/api/runs/999999/config", json={"params": {"eta": 0.9}}),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "run_not_found"


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(draft: int, client: TestClient, login: Login, role: str) -> None:
    session = login(role)

    assert session.get(f"/api/runs/{draft}/config").status_code == 403
    assert session.patch(f"/api/runs/{draft}/config", json={}).status_code == 403


def test_the_nan_literal_is_valid_json_to_the_server() -> None:
    """Anti-vacuity for the NaN test: Python's parser accepts the literal at all."""
    assert json.loads('{"eta": NaN}')["eta"] != json.loads('{"eta": NaN}')["eta"]
