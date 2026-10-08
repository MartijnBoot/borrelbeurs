"""SD4 — every route has an explicit role dependency, or is on the one public allowlist.

Authorization is checked mechanically, not by review (AC1, meta half). The walk
covers every HTTP route, WebSocket route and mount on `create_app()`. A route
passes if `require_role` (`app/api/deps.py`, found by the marker it carries)
appears anywhere in its dependant tree -- its own dependencies, a router's, or
a nested one -- or if it is in `PUBLIC_ROUTES`, which is SD1's public row plus
SD3's three docs paths plus `GET /theme.css` (Phase 4 SD8) and nothing else.
Adding to it needs the human (T17's autonomy note).

The docs routes exist only after a non-production lifespan has run, so they are
listed here even though a bare `create_app()` does not have them. The SPA mount
exists only when `web/dist` is built; the walk is run with a stand-in build so
the mount is always audited.

**A guard that cannot fail is worse than no guard**: the detector is run on a
fixture app with one guarded and one unguarded route, and on a nested
dependency, so a broken walk shows as a failing test.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Annotated, Any, Final

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIWebSocketRoute
from starlette.routing import BaseRoute, Mount, WebSocketRoute

import app.main
from app.api.deps import REQUIRE_ROLE_MARKER, Principal, require_role

# (kind, path): SD1's public row, SD3's docs, Phase 4 SD8's theme stylesheet and
# Phase 6 SD29's uploaded images.
# Nothing else, ever, without the human.
PUBLIC_ROUTES: Final = frozenset(
    {
        ("POST", "/api/auth/login"),
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("MOUNT", ""),  # the SPA's static assets at "/"
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/redoc"),
        ("GET", "/theme.css"),
        # Phase 6 SD29: the board and the login page paint with uploaded images.
        ("GET", "/assets/{asset_id:int}"),
    }
)


def _guarded(dependant: Dependant) -> bool:
    if getattr(dependant.call, REQUIRE_ROLE_MARKER, None):
        return True
    return any(_guarded(sub) for sub in dependant.dependencies)


def flatten(routes: Iterable[Any]) -> Iterator[Any]:
    """Every served route. FastAPI 0.141 keeps an included router as one
    `_IncludedRouter`; its `effective_route_contexts()` are the routes as served,
    with the full path and the dependant tree including the router's own
    dependencies."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        original = getattr(route, "original_route", None)
        if callable(contexts):
            yield from flatten(contexts())
        elif isinstance(original, APIWebSocketRoute | WebSocketRoute):
            # A WebSocket route's context has an empty `path`; the route as written
            # carries the real path and the dependant tree with its guard.
            yield original
        else:
            yield route


def _keys(route: Any) -> Iterator[tuple[str, str]]:
    if isinstance(route, Mount):
        yield "MOUNT", route.path
    elif isinstance(route, APIWebSocketRoute | WebSocketRoute):
        yield "WS", route.path
    elif getattr(route, "methods", None):
        for method in sorted(set(route.methods) - {"HEAD"}):
            yield method, route.path
    elif isinstance(getattr(route, "original_route", None), APIWebSocketRoute | WebSocketRoute):
        yield "WS", route.path
    else:
        yield type(route).__name__, getattr(route, "path", "?")


def unguarded_routes(routes: Iterable[BaseRoute]) -> list[str]:
    """Every route with no `require_role` in its dependant tree and not on the allowlist."""
    faults = []
    for route in flatten(routes):
        dependant = getattr(route, "dependant", None)
        if dependant is not None and _guarded(dependant):
            continue
        for key in _keys(route):
            if key not in PUBLIC_ROUTES:
                faults.append(f"{key[0]} {key[1] or '/'}")
    return faults


@pytest.fixture
def built_frontend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(app.main, "WEB_DIST", dist)


def test_every_route_of_the_real_app_is_guarded_or_public(built_frontend: None) -> None:
    """SD4 / AC1 (meta half), over `create_app()` exactly as served."""
    routes = app.main.create_app().routes

    assert unguarded_routes(routes) == [], "routes without a role dependency or allowlist entry"


def test_the_walk_reaches_the_routes_that_matter(built_frontend: None) -> None:
    """Anti-vacuity: the guarded and the public routes are both actually seen."""
    keys = {key for route in flatten(app.main.create_app().routes) for key in _keys(route)}

    assert {("POST", "/api/auth/login"), ("GET", "/api/auth/me"), ("MOUNT", "")} <= keys


def test_the_allowlist_is_exactly_sd1_sd3_and_phase_4_sd8() -> None:
    """`/theme.css` was authorised by the human in Phase 4 SD8: the login page must
    paint themed too, and the tokens are not secret. `/assets/{asset_id:int}` was, in
    the approved Phase 6 spec (SD29), for the same reason: uploaded theme images."""
    assert {path for _, path in PUBLIC_ROUTES} == {
        "/api/auth/login",
        "/healthz",
        "/readyz",
        "",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/theme.css",
        "/assets/{asset_id:int}",
    }


async def _nested(_: Annotated[Principal, Depends(require_role("display"))]) -> int:
    """A dependency that itself requires a role. Module-level: under `from __future__ import
    annotations` FastAPI resolves `Depends(...)` targets from module globals only."""
    return 1


def _fixture_app() -> FastAPI:
    fixture = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    guarded = APIRouter(dependencies=[Depends(require_role("admin"))])

    @fixture.get("/healthz")
    async def health() -> None: ...

    @fixture.get("/api/open")
    async def open_route() -> None: ...

    @fixture.get("/api/guarded")
    async def guarded_route(_: Annotated[Principal, Depends(require_role("bar"))]) -> None: ...

    @fixture.get("/api/nested")
    async def nested_route(_: Annotated[int, Depends(_nested)]) -> None: ...

    @guarded.get("/api/by-router")
    async def by_router() -> None: ...

    @fixture.websocket("/ws-open")
    async def ws_open() -> None: ...

    fixture.include_router(guarded)
    return fixture


def test_the_detector_flags_an_unguarded_route_and_passes_guarded_ones() -> None:
    assert unguarded_routes(_fixture_app().routes) == ["GET /api/open", "WS /ws-open"]
