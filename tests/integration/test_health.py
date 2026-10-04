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
from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.main
from app.core.config import Settings, get_settings
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from exchange import Params
from tests.support.clock import FakeClock
from tests.support.proxy import proxied


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
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full boot path -- lifespan, settings, logging, and since Phase 3 the runtime
    (lock, migrate, rehydrate, ticker) -- with no value faked but the database: the
    runtime writes, so it boots on the session's scratch database, never the
    developer's own (tests/integration/conftest.py)."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    target = app.main.create_app()

    async def scenario() -> tuple[tuple[int, Any], tuple[int, Any]]:
        async with target.router.lifespan_context(target):
            return await _get(target, "/healthz"), await _get(target, "/readyz")

    try:
        healthz, readyz = asyncio.run(scenario())
    finally:
        get_settings.cache_clear()

    assert healthz[0] == 200
    assert healthz[1]["status"] == "ok"
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


# --- Phase 3 T20: ticker liveness and database readiness (SD15; AC17, AC18c) ------

T0 = 1_759_312_800_000


@pytest.fixture
def scratch_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def test_with_no_live_run_readyz_is_200(scratch_env: str) -> None:
    """AC18c: no live run is a valid, ready state."""
    target = app.main.create_app(clock=FakeClock(T0), run_migrations=False)

    async def scenario() -> tuple[int, Any]:
        async with target.router.lifespan_context(target):
            assert target.state.holder.is_empty
            return await _get(target, "/readyz")

    assert asyncio.run(scenario()) == (200, {"status": "ready"})


def test_a_stalled_ticker_fails_healthz_after_three_intervals(scratch_env: str) -> None:
    """SD15: the ticker stops turning; past three intervals /healthz is 503 with its age."""
    clock = FakeClock(T0)
    target = app.main.create_app(clock=clock, run_migrations=False)

    async def scenario() -> tuple[tuple[int, Any], tuple[int, Any], tuple[int, Any]]:
        async with target.router.lifespan_context(target):
            # The ticker and the lock watchdog must both be asleep on the clock first.
            for _ in range(200):
                if clock.sleepers >= 2:
                    break
                await asyncio.sleep(0.005)
            clock.advance(1_000)
            for _ in range(50):
                await asyncio.sleep(0.01)
                if target.state.ticker.last_iteration_monotonic is not None:
                    break
            alive = await _get(target, "/healthz")
            await target.state.ticker.stop()
            clock.advance(3_000)
            at_limit = await _get(target, "/healthz")
            clock.advance(1)
            stale = await _get(target, "/healthz")
            return alive, at_limit, stale

    alive, at_limit, stale = asyncio.run(scenario())
    assert alive[0] == 200 and alive[1]["last_tick_age_ms"] == 0
    assert at_limit[0] == 200
    assert stale[0] == 503
    assert stale[1] == {"status": "stale", "last_tick_age_ms": 3_001, "last_commit_age_ms": None}


async def _go_live(settings: Settings, url: str) -> None:
    engine = create_engine(settings.model_copy(update={"database_url": url}))
    try:
        async with engine.begin() as conn:
            run_id = await create_draft_run(conn, params=Params(step_quant=0.1), run_seed=7)
            await add_drink(
                conn,
                run_id,
                name="Bier",
                slot=0,
                p_min_cents=150,
                p0_cents=260,
                p_max_cents=500,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )
        await go_live(engine, run_id, now_ms=T0)
    finally:
        await engine.dispose()


def test_a_silent_database_fails_readyz_but_not_healthz(
    database_url: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC17: the platform must not restart-loop a healthy process against a dead database.

    The database goes silent under a live run -- packets dropped, not refused -- on the
    very engine the ticker writes through. Every tick fails within the database timeout
    and the loop keeps turning, so /healthz stays 200 while /readyz is 503. Without the
    timeout a tick would hang inside the holder's lock and /healthz would go stale.
    """
    clock = FakeClock(T0)
    lost: list[str] = []

    async def scenario() -> tuple[tuple[int, Any], tuple[int, Any], int]:
        await _go_live(settings, database_url)
        proxy, url = await proxied(database_url)
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("DATABASE_TIMEOUT_SECONDS", "0.5")
        get_settings.cache_clear()
        target = app.main.create_app(
            clock=clock, run_migrations=False, on_lock_lost=lambda: lost.append("lost")
        )
        try:
            async with target.router.lifespan_context(target):
                ticker = target.state.ticker
                assert not target.state.holder.is_empty
                proxy.blackhole()
                for _ in range(5):
                    clock.advance(1_000)
                    for _ in range(500):  # real time: each failure takes up to the timeouts
                        await asyncio.sleep(0.01)
                        if ticker.last_iteration_monotonic == clock.monotonic():
                            break
                healthz, readyz = await _get(target, "/healthz"), await _get(target, "/readyz")
                committed = target.state.holder.state.version
                await proxy.close()  # let shutdown fail fast rather than wait on silence
                return healthz, readyz, committed
        finally:
            await proxy.close()
            get_settings.cache_clear()

    healthz, readyz, committed = asyncio.run(scenario())
    assert healthz[0] == 200, healthz
    assert healthz[1]["last_tick_age_ms"] == 0
    assert readyz[0] == 503
    assert readyz[1]["error"]["code"] == "not_ready"
    assert committed == 0  # nothing reached the silent database
    assert lost == ["lost"]  # the watchdog's probe timed out too
