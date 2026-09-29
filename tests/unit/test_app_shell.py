"""T5 — the FastAPI shell: a lifespan that loads settings, and two probes.

Driven **without `fastapi.testclient`**. That module imports `httpx`, which this
project has deliberately not taken as a dependency (ruled 2026-09-27). A FastAPI
application is an ASGI callable, so these tests call it directly: one `http`
scope per request, and `app.router.lifespan_context` for startup.

That is not a workaround, it is the only way to assert the thing the plan
actually asks for. `/readyz` must answer 200 *only once the lifespan has
completed*, and a test client that starts the app for you can never observe the
"not yet" half. Here the un-booted app is one call away.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from fastapi import APIRouter, FastAPI

import app.main
from app.core.config import ConfigError, get_settings

# A complete, valid environment. Test values only -- no real credentials.
COMPLETE_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
    "JWT_SECRET": "0123456789abcdef0123456789abcdef",  # exactly 32 characters
    "PORT": "8123",
    "LOG_LEVEL": "WARNING",
    "APP_ENV": "ci",
}

ENV_VARS = tuple(COMPLETE_ENV)


@pytest.fixture(autouse=True)
def bootable_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A valid environment, a cold settings cache, and the root logger put back.

    The lifespan calls `configure_logging()`, which owns the root logger's
    handlers. Left alone that would swallow pytest's own capture for every test
    that ran afterwards, so the handlers and level are restored here.
    """
    for name, value in COMPLETE_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()

    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)

    get_settings.cache_clear()


class Response(NamedTuple):
    """Just enough of an HTTP response to assert on."""

    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


async def _request(target: FastAPI, path: str) -> Response:
    """Send one GET through the ASGI interface and collect the response."""
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

    start = sent[0]
    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    body = b"".join(message.get("body", b"") for message in sent[1:])
    return Response(int(start["status"]), headers, body)


def get(path: str, *, booted: bool = True) -> Response:
    """GET `path` against a freshly built app, with or without a completed boot."""
    target = app.main.create_app()

    async def scenario() -> Response:
        if not booted:
            return await _request(target, path)
        async with target.router.lifespan_context(target):
            return await _request(target, path)

    return asyncio.run(scenario())


def test_healthz_reports_ok() -> None:
    response = get("/healthz")

    assert response.status == 200
    assert response.json() == {"status": "ok"}


def test_healthz_answers_before_the_lifespan_has_run() -> None:
    """Liveness is not readiness: `/healthz` says "the process is up", nothing more."""
    assert get("/healthz", booted=False).status == 200


def test_readyz_is_not_ready_until_the_lifespan_completes() -> None:
    """AC2's other half: the app must not claim to be serving before it is."""
    assert get("/readyz", booted=False).status == 503
    assert get("/readyz").status == 200


def test_readyz_stops_being_ready_after_shutdown() -> None:
    target = app.main.create_app()

    async def scenario() -> Response:
        async with target.router.lifespan_context(target):
            pass
        return await _request(target, "/readyz")

    assert asyncio.run(scenario()).status == 503


def test_the_lifespan_loads_settings_and_publishes_them() -> None:
    """The settings are read once, during boot, and held on the app."""
    target = app.main.create_app()

    async def scenario() -> int:
        async with target.router.lifespan_context(target):
            port: int = target.state.settings.port
            return port

    assert asyncio.run(scenario()) == 8123


def test_a_missing_variable_fails_the_boot_before_anything_is_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 over the real boot path, not just over `get_settings()`.

    uvicorn awaits the lifespan *before* it creates the socket
    (`uvicorn.Server.startup` calls `self.lifespan.startup()` and exits on
    failure ahead of `create_server`), so a lifespan that raises is a process
    that never binds a port.
    """
    monkeypatch.delenv("DATABASE_URL")
    get_settings.cache_clear()
    target = app.main.create_app()

    async def scenario() -> None:
        async with target.router.lifespan_context(target):
            pass  # pragma: no cover - the boot above is expected to raise

    with pytest.raises(ConfigError) as excinfo:
        asyncio.run(scenario())

    assert "DATABASE_URL" in str(excinfo.value)


def test_the_api_namespace_is_mounted_at_api_and_nowhere_else() -> None:
    """`api_router` is included, and it hangs at `/api` -- proved with a probe.

    Phase 0 puts no routes on that router, so there is nothing in the product to
    exercise the namespace with; this test registers one itself and takes it
    back off afterwards. `/api/probe` answering 200 while `/probe` 404s is what
    separates "the router is mounted under the right prefix" from "FastAPI 404s
    unknown paths", and only the first of those is a fact about this app: a bare
    `FastAPI()` with no router at all passes the second.

    That distinction is load-bearing for T6, which mounts the SPA catch-all
    *after* this router and needs `/api/*` to already be claimed. The trailing
    assertion records the shape T6 must preserve: an unknown path under `/api`
    answers JSON, never a page of HTML.
    """
    probe = APIRouter()

    @probe.get("/probe")
    async def probe_endpoint() -> dict[str, str]:
        return {"probe": "ok"}

    # The router is a module-level singleton, so the probe has to come back off
    # again -- otherwise every test after this one sees a route the app has not
    # got.
    saved_routes = list(app.main.api_router.routes)
    app.main.api_router.include_router(probe)
    try:
        under_the_prefix = get("/api/probe")
        at_the_root = get("/probe")
        unknown = get("/api/nope")
    finally:
        app.main.api_router.routes[:] = saved_routes

    assert under_the_prefix.status == 200
    assert under_the_prefix.json() == {"probe": "ok"}
    assert at_the_root.status == 404

    assert unknown.status == 404
    assert unknown.headers["content-type"].startswith("application/json")
    assert unknown.json()


@pytest.fixture
def built_frontend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in `web/dist`, so the SPA mount is exercised whether or not pnpm ran.

    The real `web/dist` exists only on machines that built the frontend; a test
    leaning on it would pass vacuously on a fresh clone or in CI. A file beside
    the dist folder stands in for anything a traversal might try to reach.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>BorrelBeurs</title>")
    (tmp_path / "secret.txt").write_text("outside the dist folder")
    monkeypatch.setattr(app.main, "WEB_DIST", dist)
    return dist


def test_the_root_serves_the_built_frontend(built_frontend: Path) -> None:
    response = get("/")

    assert response.status == 200
    assert response.headers["content-type"].startswith("text/html")
    assert b"<title>BorrelBeurs</title>" in response.body


def test_the_spa_mount_leaves_unknown_paths_a_json_404(built_frontend: Path) -> None:
    """The mount sits after /api and adds no history fallback (app/main.py:99-105).

    A catch-all that answered `index.html` for everything would turn a client's
    typo in `/api/...` into a 200 page of HTML; these must stay plain 404s.
    """
    for path in ("/api/nope", "/nope", "/nope/deep"):
        response = get(path)
        assert response.status == 404, path
        assert response.headers["content-type"].startswith("application/json"), path


def test_the_spa_mount_serves_nothing_outside_the_dist_folder(built_frontend: Path) -> None:
    assert get("/../secret.txt").status == 404
    assert get("/healthz").json() == {"status": "ok"}


def test_a_missing_frontend_build_is_not_a_boot_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `web/dist` means nothing to serve at `/` -- never an app that will not start."""
    monkeypatch.setattr(app.main, "WEB_DIST", tmp_path / "not-built")

    assert get("/readyz").status == 200
    assert get("/").status == 404


def test_importing_the_app_reads_no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import does no work: with an empty environment the module still imports.

    `app/core/config.py:5-11` promises it, and a lifespan is exactly where
    hoisting `get_settings()` to module scope feels natural. It must stay inside.
    """
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    importlib.reload(app.main)

    assert isinstance(app.main.app, FastAPI)


def test_the_entrypoint_binds_the_configured_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """`settings.port` is what the server binds -- not a hard-coded 8000 (plan D11)."""
    recorded: dict[str, Any] = {}

    def fake_run(target: str, **kwargs: Any) -> None:
        recorded["target"] = target
        recorded.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)

    app.main.main()

    assert recorded["target"] == "app.main:app"
    assert recorded["port"] == 8123
