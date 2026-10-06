"""Runs over HTTP: create a draft, find the current run (Phase 6 T8: SD2, SD4; PD2, PD6)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
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
