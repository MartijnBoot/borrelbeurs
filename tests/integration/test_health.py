"""The integration layer is wired: the real app boots against the real environment and a
real Postgres answers.

Unlike `tests/unit/test_app_shell.py`, nothing here fakes the environment. These
tests run with whatever `scripts/check.sh` exported from `.env.local` (or CI
set), against the database that environment names, so they fail when the
stack a developer would actually start is broken -- a variable missing, the
DSN pointing nowhere, Postgres not up.

Driven through the ASGI interface directly, for the same reason the unit shell
tests are: `fastapi.testclient` would pull in `httpx`, which this project has
not taken as a dependency.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import MutableMapping
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.main
from app.core.config import Settings


async def _get(target: Any, path: str) -> tuple[int, Any]:
    """One GET through the ASGI interface; returns status and decoded JSON body."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await target(scope, receive, send)
    body = b"".join(message.get("body", b"") for message in sent[1:])
    return int(sent[0]["status"]), json.loads(body)


def test_the_app_boots_on_the_real_environment_and_answers_its_probes(
    settings: Settings,
) -> None:
    """The full boot path -- lifespan, settings, logging -- with no value faked."""
    target = app.main.create_app()

    async def scenario() -> tuple[tuple[int, Any], tuple[int, Any]]:
        async with target.router.lifespan_context(target):
            return await _get(target, "/healthz"), await _get(target, "/readyz")

    healthz, readyz = asyncio.run(scenario())

    assert healthz == (200, {"status": "ok"})
    assert readyz == (200, {"status": "ready"})


def test_the_configured_postgres_answers_a_query(settings: Settings) -> None:
    """`DATABASE_URL` reaches a live Postgres through the driver the app uses."""

    async def scenario() -> int:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text("SELECT 1"))
                return int(result.scalar_one())
        finally:
            await engine.dispose()

    try:
        answer = asyncio.run(scenario())
    except OSError as error:
        # Connection refused / host unreachable. The DSN is not echoed: it
        # carries the database password (R17).
        pytest.fail(
            f"could not reach the Postgres DATABASE_URL names ({error.__class__.__name__}). "
            "Locally: docker compose up -d --wait db"
        )

    assert answer == 1
