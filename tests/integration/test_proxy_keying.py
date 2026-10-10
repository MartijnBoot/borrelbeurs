"""AC26: the login limiter keys on the client the trusted proxy names, and only then.

On Render the app sits behind Render's proxy, so every request's peer is the proxy;
without `X-Forwarded-For` every phone at a borrel would share one limiter bucket. At
the venue there is no proxy, and honouring the header would let anyone on the LAN
pick a fresh bucket per attempt. `TRUSTED_PROXY_IPS` decides, and `main()` hands it
to uvicorn explicitly (Phase 8 T1), so uvicorn's own `FORWARDED_ALLOW_IPS` default
cannot switch the header back on.

The real process, over real HTTP (`tests/integration/realapp/harness.py`): the
keying happens in uvicorn's proxy middleware, which no in-process ASGI test passes
through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.realapp.harness import Client, start_app

RATE = 10
NOT_A_KEY = "bb_1_not-a-real-secret"


def _logins_from_distinct_addresses(base: str) -> list[int]:
    client = Client(base)
    return [
        client.request(
            "POST",
            "/api/auth/login",
            {"key": NOT_A_KEY},
            headers={"X-Forwarded-For": f"203.0.113.{n}"},
        )[0]
        for n in range(1, RATE + 2)
    ]


def test_behind_a_trusted_proxy_each_forwarded_client_has_its_own_bucket(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGIN_RATE_PER_MINUTE", str(RATE))
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "*")
    app = start_app(database_url, tmp_path / "app.stderr")
    try:
        statuses = _logins_from_distinct_addresses(app.base)
    finally:
        app.kill()

    assert 429 not in statuses, statuses
    assert set(statuses) == {401}


def test_with_no_trusted_proxy_the_forwarded_header_is_ignored(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`FORWARDED_ALLOW_IPS=*` in the child's environment: uvicorn's CLI default would
    trust everyone, and `main()` must not let it."""
    monkeypatch.setenv("LOGIN_RATE_PER_MINUTE", str(RATE))
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    app = start_app(database_url, tmp_path / "app.stderr")
    try:
        statuses = _logins_from_distinct_addresses(app.base)
    finally:
        app.kill()

    assert statuses[:RATE] == [401] * RATE
    assert statuses[RATE] == 429
