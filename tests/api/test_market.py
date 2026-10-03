"""Market manipulation over HTTP (Phase 3 T25: SD23; AC26, AC27, AC19)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
from app.realtime.messages import Envelope
from tests.api.conftest import Login


@pytest.fixture
def broadcasts(live_client: TestClient) -> Iterator[list[Envelope]]:
    hub = live_client.app.state.hub  # type: ignore[attr-defined]
    seen: list[Envelope] = []
    real = hub.broadcast

    def spy(envelope: Envelope) -> int:
        seen.append(envelope)
        return int(real(envelope))

    hub.broadcast = spy
    yield seen
    hub.broadcast = real


@pytest.fixture
def bar(live_client: TestClient, login: Login) -> TestClient:
    return login("bar")


def _counts(settings: Settings, url: str) -> tuple[Any, ...]:
    async def scenario() -> tuple[Any, ...]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                return tuple(
                    (
                        await conn.execute(
                            text(
                                "SELECT (SELECT count(*) FROM price_tick),"
                                " (SELECT count(*) FROM market_event),"
                                " (SELECT count(*) FROM news),"
                                " (SELECT row_to_json(e)::text FROM engine_state e)"
                            )
                        )
                    ).one()
                )
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _drink(client: TestClient) -> int:
    drinks: tuple[int, ...] = client.app.state.holder.drink_ids  # type: ignore[attr-defined]
    return drinks[0]


def test_a_valid_jump_is_201_with_the_next_version(bar: TestClient) -> None:
    version = bar.app.state.holder.state.version  # type: ignore[attr-defined]

    response = bar.post(
        "/api/market/jumps",
        json={"drink_id": _drink(bar), "target_price_cents": 450, "duration_ms": 5_000},
    )

    assert response.status_code == 201
    assert response.json() == {"version": version + 1}


@pytest.mark.parametrize(
    "change",
    [
        {"target_price_cents": 149},
        {"target_price_cents": 501},
        {"duration_ms": 999},
        {"duration_ms": 1_800_001},
        {"drink_id": 999_999},
    ],
    ids=["below-p-min", "above-p-max", "too-short", "too-long", "inactive-drink"],
)
def test_each_jump_bound_is_422_and_writes_nothing(
    bar: TestClient, settings: Settings, api_env: str, change: dict[str, int]
) -> None:
    """AC26."""
    before = _counts(settings, api_env)
    body = {"drink_id": _drink(bar), "target_price_cents": 300, "duration_ms": 5_000, **change}

    response = bar.post("/api/market/jumps", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert _counts(settings, api_env) == before


@pytest.mark.parametrize("target", [150, 500])
def test_the_bounds_themselves_are_accepted(bar: TestClient, target: int) -> None:
    response = bar.post(
        "/api/market/jumps",
        json={"drink_id": _drink(bar), "target_price_cents": target, "duration_ms": 1_000},
    )

    assert response.status_code == 201


def test_an_event_broadcasts_market_event_with_absolute_times_and_news(
    bar: TestClient, broadcasts: list[Envelope]
) -> None:
    """AC19, AC27 over HTTP; the default duration is 30 s."""
    response = bar.post("/api/market/events", json={"kind": "correction"})

    assert response.status_code == 201
    event = response.json()
    assert event["kind"] == "correction"
    assert event["t_end_ms"] - event["t_start_ms"] == 30_000
    kinds = [e.type for e in broadcasts]
    assert kinds == ["market_event", "news"]
    start = broadcasts[0].model_dump(mode="json")["data"]
    assert start == {"op": "start", **event}
    news = broadcasts[1].model_dump(mode="json")["data"]
    assert news["item"]["level"] == "info"
    assert news["item"]["text"] == "Marktcorrectie: Prijzen keren terug naar startpositie."


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "boom"},
        {"kind": "Crash"},
        {"kind": "crash", "duration_ms": 999},
        {"kind": "crash", "duration_ms": 600_001},
    ],
    ids=["unknown-kind", "capitalised-kind", "too-short", "too-long"],
)
def test_each_event_bound_is_422_and_writes_nothing(
    bar: TestClient, settings: Settings, api_env: str, body: dict[str, Any]
) -> None:
    before = _counts(settings, api_env)

    response = bar.post("/api/market/events", json=body)

    assert response.status_code == 422
    assert _counts(settings, api_env) == before


def test_display_may_not_manipulate(live_client: TestClient, login: Login) -> None:
    client = login("display")

    assert client.post("/api/market/events", json={"kind": "crash"}).status_code == 403
    assert (
        client.post(
            "/api/market/jumps",
            json={"drink_id": 1, "target_price_cents": 300, "duration_ms": 1_000},
        ).status_code
        == 403
    )


def test_with_no_live_run_manipulation_is_409(login: Login) -> None:
    client = login("admin")

    for path, body in (
        ("/api/market/events", {"kind": "crash"}),
        ("/api/market/jumps", {"drink_id": 1, "target_price_cents": 300, "duration_ms": 1_000}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 409, path
        assert response.json()["error"]["code"] == "no_live_run"
