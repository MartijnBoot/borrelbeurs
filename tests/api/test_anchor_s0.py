"""Anchor s0 over HTTP (Phase 6 T15: SD5, SD26; AC12, AC16).

`POST /api/runs/{run_id}/anchor-s0` is v1's "📌 Zet huidige prijs als
evenwicht": on the live run, `anchor_s0_to_current_y` over the active drinks,
writing every active drink's `s0` in one config transition. No `y` moves; a
removed drink's `s0` is kept; the mean is over active drinks only (AC16).
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
from tests.api.conftest import Login


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


def test_anchor_uses_the_active_mean_and_moves_no_y(
    live_run: int, live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC16 end to end, AC12."""
    admin = login("admin", label="Bestuur")
    before = admin.get(f"/api/runs/{live_run}/config").json()
    bier, wijn, fris = (d["drink_id"] for d in before["drinks"])
    assert admin.delete(f"/api/runs/{live_run}/drinks/{wijn}").status_code == 200
    holder = live_client.app.state.holder  # type: ignore[attr-defined]
    y = holder.state.y.tobytes()
    version = holder.state.version
    state = admin.get("/api/state").json()
    p_q = {d: state["prices"][str(d)]["price_cents"] / 100 for d in (bier, fris)}
    mean = sum(p_q.values()) / len(p_q)

    response = admin.post(f"/api/runs/{live_run}/anchor-s0")

    assert response.status_code == 200, response.text
    revision = response.json()["revision"]
    after = admin.get(f"/api/runs/{live_run}/config").json()
    assert after["revision"] == revision
    s0 = {d["drink_id"]: d["s0"] for d in after["drinks"]}
    for d in (bier, fris):
        # live_run's drinks: a = 1, d = 0.1, c = 0.1.
        assert s0[d] == pytest.approx(0.1 * p_q[d] - 1.0 - 0.1 * (mean - p_q[d]), abs=1e-12)
    assert s0[wijn] == 1.0
    assert holder.state.y.tobytes() == y
    assert holder.state.version == version + 1
    assert holder.spec.s0.tolist() == [s0[bier], 1.0, s0[fris]]
    author = _sql(
        settings,
        api_env,
        "SELECT author FROM run_config_revision WHERE run_id = :r AND revision = :v",
        r=live_run,
        v=revision,
    )
    assert author == "Bestuur"
    ticks = _sql(
        settings,
        api_env,
        "SELECT count(*) FROM price_tick WHERE run_id = :r AND source = 'config'",
        r=live_run,
    )
    assert ticks == 2  # the removal's and the anchor's


def test_a_draft_is_409_run_not_live(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    async def scenario() -> int:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            return await create_run(engine, name="Concept", author="seed")
        finally:
            await engine.dispose()

    draft = asyncio.run(scenario())

    response = login("admin").post(f"/api/runs/{draft}/anchor-s0")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_not_live"


def test_an_unknown_run_is_404(client: TestClient, login: Login) -> None:
    response = login("admin").post("/api/runs/999999/anchor-s0")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_are_403(
    live_run: int, live_client: TestClient, login: Login, role: str
) -> None:
    assert login(role).post(f"/api/runs/{live_run}/anchor-s0").status_code == 403
