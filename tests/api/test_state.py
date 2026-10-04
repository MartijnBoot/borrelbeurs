"""`GET /api/state` (Phase 3 T22: SD16, SD26; AC15, AC18c HTTP half)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.models import Base
from app.db.session import create_engine
from app.realtime.messages import Snapshot
from tests.api.conftest import Login


def _database(settings: Settings, url: str) -> tuple[Any, ...]:
    """The whole `engine_state` row (rng_counter and version included) and every row count."""

    async def scenario() -> tuple[Any, ...]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                state = (
                    await conn.execute(text("SELECT row_to_json(e)::text FROM engine_state e"))
                ).all()
                counts = [
                    int((await conn.execute(text(f'SELECT count(*) FROM "{t.name}"'))).scalar_one())
                    for t in Base.metadata.sorted_tables
                ]
            return tuple(state), tuple(counts)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_a_hundred_polls_change_nothing(
    live_client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC15 (D-06): no engine advance, no write, whatever the poll rate."""
    client = login("display")
    before = _database(settings, api_env)
    version = client.app.state.holder.state.version  # type: ignore[attr-defined]

    bodies = [client.get("/api/state") for _ in range(100)]

    assert {r.status_code for r in bodies} == {200}
    assert _database(settings, api_env) == before
    assert client.app.state.holder.state.version == version  # type: ignore[attr-defined]


def test_the_state_is_the_snapshot(live_client: TestClient, login: Login, live_run: int) -> None:
    client = login("bar")

    data = Snapshot.model_validate(client.get("/api/state").json())

    assert data.run.run_id == live_run
    assert [d.name for d in data.drinks] == ["Bier", "Wijn", "Fris"]
    assert set(data.prices) == {d.drink_id for d in data.drinks}
    assert data.earnings == {}


def test_the_state_carries_the_version_its_prices_belong_to(
    live_client: TestClient, login: Login, live_run: int
) -> None:
    """realtime-protocol.md: the snapshot holds `version`, so a client polling this route
    can quote honestly (`quote_version`, SD18) without a WebSocket."""
    client = login("bar")

    body = client.get("/api/state").json()

    assert body["version"] == client.app.state.holder.state.version  # type: ignore[attr-defined]


def test_with_no_live_run_state_is_409(login: Login) -> None:
    """AC18c (HTTP half), SD16."""
    client = login("display")

    response = client.get("/api/state")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_live_run"


def test_state_needs_a_session(live_client: TestClient) -> None:
    assert live_client.get("/api/state").status_code == 401
