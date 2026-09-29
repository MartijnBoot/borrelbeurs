"""Shared fixtures. Nothing here is autouse: a unit test that asks for none of
these pays for none of them.

**Why the integration fixtures read the real environment rather than start a
testcontainers Postgres.** The plan's Files table pencils testcontainers in
here, but two of its own tasks rule it out. T9's verification removes a
required variable from `.env.local` and expects the integration step to fail
*naming that variable*; T11 gives CI a Postgres service container for this
step. Both only work if the integration layer runs against whatever the
environment says -- the compose `db` locally (exported from `.env.local` by
`scripts/check.sh`), the service container in CI. A container URL substituted
here would make `DATABASE_URL` unfalsifiable.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The settings this process was started with, validated exactly as at boot.

    A missing or malformed variable raises `ConfigError` here, so every test
    that depends on this one errors with the message naming the variable (AC2)
    rather than failing further down with something less specific.
    """
    # Unit tests monkeypatch the environment and prime the cache with it; a
    # session sharing a process with them must not inherit their fake values.
    get_settings.cache_clear()
    return get_settings()
