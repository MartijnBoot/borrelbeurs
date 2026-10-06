"""Draining refuses every write (Phase 6 T4: AC40, SD24, PD19).

While the process shuts down (`app.state.draining`), every write route answers
503 `shutting_down`. Reads still answer. Authorization runs first, so a role
that may not write is still 403 while draining, never 503.

`DRAINING_WRITES` is the list later tasks extend: every write route this phase
adds gets a row here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import Login

# (method, path, JSON body). A body is valid where that matters, so a refusal can
# only be the drain.
DRAINING_WRITES: Final[list[tuple[str, str, dict[str, Any] | None]]] = [
    (
        "POST",
        "/api/orders",
        {"quote_version": 0, "lines": [{"drink_id": 1, "qty": 1, "unit_price_cents": 1}]},
    ),
    ("POST", "/api/news", {"level": "info", "text": "x"}),
    ("DELETE", "/api/news/999999", None),
    ("POST", "/api/market/jumps", {"drink_id": 1, "target_price_cents": 100, "duration_ms": 5_000}),
    ("POST", "/api/market/events", {"kind": "crash", "duration_ms": 30_000}),
    ("PUT", "/api/theme", {"preset": "blauw"}),
    ("POST", "/api/runs", {"name": "Nieuw"}),
]

READS: Final = ("/api/state", "/api/news", "/api/auth/me", "/theme.css")


def _ids(rows: list[tuple[str, str, Any]]) -> list[str]:
    return [f"{method} {path}" for method, path, _ in rows]


@pytest.fixture
def draining(live_client: TestClient) -> Iterator[TestClient]:
    live_client.app.state.draining = True  # type: ignore[attr-defined]
    try:
        yield live_client
    finally:
        live_client.app.state.draining = False  # type: ignore[attr-defined]


def _send(client: TestClient, method: str, path: str, body: dict[str, Any] | None) -> Any:
    return client.request(method, path, json=body, headers={"Idempotency-Key": "k-drain-0001"})


@pytest.mark.parametrize(("method", "path", "body"), DRAINING_WRITES, ids=_ids(DRAINING_WRITES))
def test_an_admin_write_while_draining_is_503(
    draining: TestClient, login: Login, method: str, path: str, body: dict[str, Any] | None
) -> None:
    login("admin")

    response = _send(draining, method, path, body)

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "shutting_down"


@pytest.mark.parametrize(("method", "path", "body"), DRAINING_WRITES, ids=_ids(DRAINING_WRITES))
def test_a_display_write_while_draining_is_still_403(
    draining: TestClient, login: Login, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """PD19: `require_role` runs before the drain check."""
    login("display")

    assert _send(draining, method, path, body).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), DRAINING_WRITES, ids=_ids(DRAINING_WRITES))
def test_an_anonymous_write_while_draining_is_still_401(
    draining: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    draining.cookies.clear()

    assert _send(draining, method, path, body).status_code == 401


@pytest.mark.parametrize("path", READS)
def test_reads_still_answer_while_draining(draining: TestClient, login: Login, path: str) -> None:
    login("admin")

    assert draining.get(path).status_code == 200


def test_writes_answer_again_once_not_draining(live_client: TestClient, login: Login) -> None:
    """Anti-vacuity: the same admin write is not 503 outside a drain."""
    login("admin")

    assert live_client.put("/api/theme", json={"preset": "blauw"}).status_code == 200
