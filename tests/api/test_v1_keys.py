"""AC32 (Phase 8 T9, D-42): a v1 key grants nothing in v2.

v1 keys are free strings of 1-256 characters (v1 `backend/auth.py:40-48`, tag v2-rebuild-complete),
and `borrelbeurs-v1` published some. v2 parses a key as `bb_<key_id>_<secret>`
before it looks anything up or hashes anything (Phase 3 SD7), so every v1-shaped
key is a 401 having cost no database lookup and no argon2 verify. No production
code changes here: this pins that behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.auth as auth_module
from app.api import security
from app.db.keys import get_key

V1_SHAPED_KEYS = [
    pytest.param("TestTest", id="word"),
    pytest.param("3f2b8c4e-9a1d-4c6b-8e2f-7d5a1b9c0e3f", id="uuid"),
    pytest.param("bar-key-2024", id="dashed"),
    pytest.param("ab" * 32, id="64-hex"),
    pytest.param("bb_admin_secret", id="wrongly-prefixed"),
    pytest.param("k" * 256, id="256-characters"),
]


class Counter:
    def __init__(self, real: Any) -> None:
        self.calls = 0
        self._real = real

    async def lookup(self, *args: Any) -> Any:
        self.calls += 1
        return await self._real(*args)

    def verify(self, *args: Any) -> bool:
        self.calls += 1
        result: bool = self._real(*args)
        return result


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter]:
    counter = Counter(get_key)
    monkeypatch.setattr(auth_module, "get_key", counter.lookup)
    yield counter


@pytest.fixture
def verifies(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter]:
    counter = Counter(security.verify_secret)
    monkeypatch.setattr(security, "verify_secret", counter.verify)
    yield counter


@pytest.mark.parametrize("key", V1_SHAPED_KEYS)
def test_a_v1_shaped_key_is_401_with_no_lookup_and_no_verify(
    client: TestClient, lookups: Counter, verifies: Counter, key: str
) -> None:
    response = client.post("/api/auth/login", json={"key": key})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert "set-cookie" not in response.headers
    assert (lookups.calls, verifies.calls) == (0, 0)


def test_the_counters_see_a_v2_shaped_key(
    client: TestClient, lookups: Counter, verifies: Counter
) -> None:
    """Anti-vacuity: a well-formed `bb_` key does reach the lookup."""
    response = client.post("/api/auth/login", json={"key": "bb_999999_" + "x" * 43})

    assert response.status_code == 401
    assert lookups.calls == 1
