"""AC32 (Phase 8 T9, D-42): a v1 key grants nothing in v2.

v1 keys are free strings of 1-256 characters (v1 `backend/auth.py:40-48`, tag v2-rebuild-complete),
and `borrelbeurs-v1` published some. v2 reads a key as exactly 9 Crockford
symbols before it hashes or looks anything up (B-08 SD2, SD3), so every
v1-shaped key below is a 401 having cost no argon2 hash and no database lookup.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.auth as auth_module
from app.api import security
from app.db.keys import get_key_by_hash

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

    def hash(self, *args: Any) -> str:
        self.calls += 1
        result: str = self._real(*args)
        return result


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter]:
    counter = Counter(get_key_by_hash)
    monkeypatch.setattr(auth_module, "get_key_by_hash", counter.lookup)
    yield counter


@pytest.fixture
def hashes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter]:
    counter = Counter(security.key_hash)
    monkeypatch.setattr(security, "key_hash", counter.hash)
    yield counter


@pytest.mark.parametrize("key", V1_SHAPED_KEYS)
def test_a_v1_shaped_key_is_401_with_no_lookup_and_no_hash(
    client: TestClient, lookups: Counter, hashes: Counter, key: str
) -> None:
    response = client.post("/api/auth/login", json={"key": key})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert "set-cookie" not in response.headers
    assert (lookups.calls, hashes.calls) == (0, 0)


def test_the_counters_see_a_v2_shaped_key(
    client: TestClient, lookups: Counter, hashes: Counter
) -> None:
    """Anti-vacuity: a well-formed 9-symbol key does reach the hash and the lookup."""
    response = client.post("/api/auth/login", json={"key": "K7M-4QX-9PR"})

    assert response.status_code == 401
    assert (lookups.calls, hashes.calls) == (1, 1)
