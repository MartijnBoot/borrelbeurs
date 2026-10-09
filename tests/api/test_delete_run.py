"""Deleting a run over HTTP (Phase 7 T7: AC8, AC34, AC35; SD3)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import Login


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


def _ended(settings: Settings, url: str, name: str) -> int:
    [(run_id,)] = _sql(
        settings,
        url,
        "INSERT INTO run (status, name, params, run_seed) VALUES ('ended', :n, '{}', 1)"
        " RETURNING run_id",
        n=name,
    )
    return int(run_id)


def test_an_ended_run_is_deleted_with_204(login: Login, settings: Settings, api_env: str) -> None:
    run_id = _ended(settings, api_env, "Vrijmibo")

    response = login("admin").request(
        "DELETE", f"/api/runs/{run_id}", json={"confirm_name": "Vrijmibo"}
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert _sql(settings, api_env, "SELECT count(*) FROM run") == [(0,)]


def test_a_draft_is_deleted(login: Login, settings: Settings, api_env: str) -> None:
    admin = login("admin")
    run_id = admin.post("/api/runs", json={"name": "Concept"}).json()["run_id"]

    response = admin.request("DELETE", f"/api/runs/{run_id}", json={"confirm_name": "Concept"})

    assert response.status_code == 204
    assert admin.get("/api/runs/current").status_code == 404


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("live", 409, "run_live"),
        ("mismatch", 422, "name_mismatch"),
        ("unknown", 404, "run_not_found"),
    ],
)
def test_each_refusal_removes_nothing(
    case: str,
    status: int,
    code: str,
    live_client: TestClient,
    live_run: int,
    login: Login,
    settings: Settings,
    api_env: str,
) -> None:
    target = {"live": live_run, "mismatch": _ended(settings, api_env, "Oud"), "unknown": 999_999}[
        case
    ]
    name = {"live": "Borrel", "mismatch": "oud", "unknown": "x"}[case]
    before = _sql(settings, api_env, "SELECT run_id, status FROM run ORDER BY run_id")

    response = login("admin").request("DELETE", f"/api/runs/{target}", json={"confirm_name": name})

    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert _sql(settings, api_env, "SELECT run_id, status FROM run ORDER BY run_id") == before
    assert not live_client.app.state.holder.is_empty  # type: ignore[attr-defined]


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(login: Login, settings: Settings, api_env: str, role: str) -> None:
    run_id = _ended(settings, api_env, "Vrijmibo")

    response = login(role).request(
        "DELETE", f"/api/runs/{run_id}", json={"confirm_name": "Vrijmibo"}
    )

    assert response.status_code == 403
    assert _sql(settings, api_env, "SELECT count(*) FROM run") == [(1,)]
