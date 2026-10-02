"""News over HTTP (Phase 3 T22: SD1, SD26; AC28, AC18c)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
from app.realtime.messages import Envelope
from tests.api.conftest import Login


@pytest.fixture
def broadcasts(live_client: TestClient) -> Iterator[list[Envelope]]:
    """A spy on the hub: every envelope broadcast, in order."""
    hub = live_client.app.state.hub  # type: ignore[attr-defined]
    seen: list[Envelope] = []
    real = hub.broadcast

    def spy(envelope: Envelope) -> int:
        seen.append(envelope)
        return int(real(envelope))

    hub.broadcast = spy
    yield seen
    hub.broadcast = real


def _rows(settings: Settings, url: str) -> list[tuple[str, str, bool]]:
    async def scenario() -> list[tuple[str, str, bool]]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT level, text, deleted_at IS NOT NULL FROM news ORDER BY news_id")
                )
                return [(str(r[0]), str(r[1]), bool(r[2])) for r in rows]
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_posting_news_persists_trims_and_broadcasts(
    live_client: TestClient,
    login: Login,
    broadcasts: list[Envelope],
    settings: Settings,
    api_env: str,
) -> None:
    """AC28: persisted, broadcast as `news {op: add, item}`."""
    client = login("bar")

    response = client.post("/api/news", json={"level": "warning", "text": "  Happy hour!  "})

    assert response.status_code == 201
    item = response.json()
    assert (item["level"], item["text"]) == ("warning", "Happy hour!")
    assert _rows(settings, api_env) == [("warning", "Happy hour!", False)]
    (envelope,) = [e for e in broadcasts if e.type == "news"]
    frame = json.loads(envelope.model_dump_json())
    assert frame["data"] == {"op": "add", "item": item}
    assert client.get("/api/news").json() == [item]


def test_news_is_listed_newest_first(live_client: TestClient, login: Login) -> None:
    client = login("bar")
    for text_ in ("one", "two", "three"):
        assert client.post("/api/news", json={"level": "info", "text": text_}).status_code == 201

    assert [n["text"] for n in client.get("/api/news").json()] == ["three", "two", "one"]


@pytest.mark.parametrize(
    "body",
    [
        {"level": "Info", "text": "x"},
        {"level": "INFO", "text": "x"},
        {"level": "urgent", "text": "x"},
        {"level": "info", "text": ""},
        {"level": "info", "text": "   "},
        {"level": "info", "text": "x" * 501},
        {"level": "info"},
        {"level": "info", "text": "x", "extra": 1},
    ],
    ids=["capitalised", "upper", "unknown", "empty", "blank", "501-chars", "no-text", "extra"],
)
def test_a_bad_level_or_text_is_422_and_writes_nothing(
    live_client: TestClient,
    login: Login,
    broadcasts: list[Envelope],
    settings: Settings,
    api_env: str,
    body: dict[str, object],
) -> None:
    """AC28; SD26: the lowercase four only -- `Info` is refused here, unlike the import."""
    client = login("admin")

    response = client.post("/api/news", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert _rows(settings, api_env) == []
    assert [e for e in broadcasts if e.type == "news"] == []


def test_five_hundred_characters_are_accepted(live_client: TestClient, login: Login) -> None:
    client = login("bar")

    assert client.post("/api/news", json={"level": "danger", "text": "x" * 500}).status_code == 201


def test_deleting_twice_is_404_the_second_time(
    live_client: TestClient,
    login: Login,
    broadcasts: list[Envelope],
    settings: Settings,
    api_env: str,
) -> None:
    """AC28: soft delete, broadcast `op: delete`; absent or already deleted is 404."""
    client = login("bar")
    item = client.post("/api/news", json={"level": "info", "text": "weg"}).json()

    first = client.delete(f"/api/news/{item['news_id']}")
    second = client.delete(f"/api/news/{item['news_id']}")
    unknown = client.delete("/api/news/999999")

    assert first.status_code == 200 and first.json() == item
    assert second.status_code == 404 and second.json()["error"]["code"] == "news_not_found"
    assert unknown.status_code == 404
    assert _rows(settings, api_env) == [("info", "weg", True)]
    assert [
        json.loads(e.model_dump_json())["data"]["op"] for e in broadcasts if e.type == "news"
    ] == [
        "add",
        "delete",
    ]
    assert client.get("/api/news").json() == []


def test_display_may_read_news_but_not_write_it(live_client: TestClient, login: Login) -> None:
    client = login("display")

    assert client.get("/api/news").status_code == 200
    assert client.post("/api/news", json={"level": "info", "text": "x"}).status_code == 403


def test_with_no_live_run_posting_news_is_409(login: Login) -> None:
    """AC18c: every mutation is 409 `no_live_run`; reading lists nothing."""
    client = login("bar")

    response = client.post("/api/news", json={"level": "info", "text": "x"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_live_run"
    assert client.get("/api/news").json() == []
