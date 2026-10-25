"""The application shell: build the app, boot it, answer two probes, serve the SPA.

**Nothing happens at import except building the object graph.** `create_app()`
constructs routers, reads no variable and binds no socket; the one filesystem
check it does make -- whether `web/dist` exists, to decide if there is a built
frontend to mount -- is a directory stat, not a file open, and its absence is
not an error (a Python test run need not have built the frontend first). The
environment is read inside `lifespan`, on the first line of boot, and nowhere
else (`app/core/config.py:5-11`).

That placement is what makes spec AC2 -- "shall fail at boot ... and shall not
serve traffic" -- true by construction rather than by care. `uvicorn.Server.startup`
awaits the lifespan and exits with `STARTUP_FAILURE` *before* it calls
`create_server`, so a `ConfigError` raised here is a process that never binds a
port. There is no window in which a misconfigured app answers a request.

Two ways to start it, and neither may use `uvicorn --env-file`: that flag
switches on python-dotenv, a second source of environment values reading the
very file the config module deliberately refuses to read (R12).

    uv run uvicorn app.main:app --port 8000     # the port is the caller's
    uv run python -m app.main                   # the port is settings.port
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Final

import uvicorn
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import PathLike
from starlette.types import Scope

from app.api.admin import router as admin_router
from app.api.analytics import router as analytics_router
from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.config import router as config_router
from app.api.drinks import router as drinks_router
from app.api.earnings import router as earnings_router
from app.api.exports import router as exports_router
from app.api.health import router as health_router
from app.api.keys import router as keys_router
from app.api.market import router as market_router
from app.api.news import router as news_router
from app.api.orders import router as orders_router
from app.api.profiles import router as profiles_router
from app.api.runs import router as runs_router
from app.api.security import ROLE_ROUTES, LoginLimiter, OriginGuard
from app.api.standby import StandbyGate
from app.api.state import router as state_router
from app.api.theme import theme_css_router, theme_router
from app.api.wallet import router as wallet_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, handle_app_error, handle_validation_error
from app.core.logging import configure_logging
from app.realtime.ws import router as ws_router
from app.runtime.boot import exit_process, start_runtime
from app.runtime.clock import AppClock, Clock, RealClock

logger = logging.getLogger(__name__)

# Every application route hangs here (docs/design/architecture.md:36-38). It is
# empty in Phase 0 and that is the point: the prefix is established before there
# is anything to move, so T6's SPA catch-all -- mounted after this router -- has
# one namespace to keep its hands off instead of twenty top-level paths.
api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(state_router)
api_router.include_router(news_router)
api_router.include_router(orders_router)
api_router.include_router(market_router)
api_router.include_router(admin_router)
api_router.include_router(theme_router)
api_router.include_router(earnings_router)
api_router.include_router(runs_router)
api_router.include_router(config_router)
api_router.include_router(drinks_router)
api_router.include_router(keys_router)
api_router.include_router(analytics_router)
api_router.include_router(exports_router)
api_router.include_router(profiles_router)
api_router.include_router(wallet_router)

# `pnpm --dir web build` output (T6). Not built by every checkout -- a Python
# test run has no reason to have run pnpm first -- so its absence only means
# there is no frontend to serve, never a boot failure.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

# The client-side routes (Phase 4 PD8): the login page, the player's page (B-05
# SD20) and every route the role table grants, taken from the server's own table
# rather than copied.
SPA_ROUTES: Final = frozenset(
    {"/login", "/speler"} | {r for routes in ROLE_ROUTES.values() for r in routes}
)

# SD3, Phase 8 AC25: an allowlist, so a new environment -- `venue`, the borrel's
# LAN -- hides the docs until someone decides otherwise.
DOCS_ENVS: Final = frozenset({"local", "ci"})


class SpaStaticFiles(StaticFiles):
    """`StaticFiles` with a history-mode fallback for the SPA's own routes only.

    A `GET` of exactly one of `SPA_ROUTES` that matches no file serves
    `index.html`, so a reload of `/koers` or a `/login?next=` redirect renders the
    app. Every other unknown path stays a plain 404.

    Phase 8 AC27: `index.html` is `no-store`, so a phone picks up a deploy on its
    next load; Vite's content-hashed `assets/*` are cached for good. Set on
    whatever `file_response` returns, so a 304 keeps it too. Other files are left
    as they were.
    """

    def file_response(
        self,
        full_path: PathLike,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        served = Path(full_path)
        # `full_path` is a realpath (`StaticFiles.lookup_path`); compare like with like.
        assets = Path(os.path.realpath(self.directory or "")) / "assets"
        if served.name == "index.html":
            response.headers["Cache-Control"] = "no-store"
        elif served.parent == assets:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as missing:
            if missing.status_code != 404 or scope["method"] != "GET":
                raise
            if scope["path"] not in SPA_ROUTES:
                raise
            return await super().get_response("index.html", scope)


# `start_runtime`'s shape (app/runtime/boot.py); tests pass a no-op one.
Runtime = Callable[..., AbstractAsyncContextManager[None]]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load settings, configure logging, then boot the runtime and serve.

    `start_runtime` (app/runtime/boot.py) does the rest in SD11's order -- lock,
    migrate, rehydrate, ticker -- and sets `ready` last; its exit is the
    shutdown path (not ready first, then drain). A failure there raises out of
    the lifespan, so uvicorn exits before it ever binds a port.
    """
    settings: Settings = get_settings()
    configure_logging(settings.log_level)

    application.state.settings = settings
    application.state.login_limiter = LoginLimiter(
        settings.login_rate_per_minute, application.state.clock
    )
    application.state.signup_limiter = LoginLimiter(
        settings.signup_rate_per_minute, application.state.clock
    )
    if settings.app_env in DOCS_ENVS:
        _mount_docs(application)

    runtime: Runtime = application.state.runtime
    async with runtime(
        application,
        settings,
        clock=application.state.clock,
        run_migrations=application.state.run_migrations,
        on_lock_lost=application.state.on_lock_lost,
    ):
        logger.info(
            "application started",
            extra={
                "app_env": settings.app_env,
                "port": settings.port,
                "build_sha": settings.build_sha,
            },
        )
        yield
    logger.info("application stopped")


def _mount_docs(application: FastAPI) -> None:
    """SD3: `/openapi.json`, `/docs` and `/redoc`, for `DOCS_ENVS` only (plan PD15).

    Put in front of the SPA mount, which would otherwise catch them.
    """

    async def openapi(request: Request) -> JSONResponse:
        return JSONResponse(application.openapi())

    async def swagger(request: Request) -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title="BorrelBeurs API")

    async def redoc(request: Request) -> HTMLResponse:
        return get_redoc_html(openapi_url="/openapi.json", title="BorrelBeurs API")

    before = len(application.router.routes)
    application.add_route("/openapi.json", openapi, include_in_schema=False)
    application.add_route("/docs", swagger, include_in_schema=False)
    application.add_route("/redoc", redoc, include_in_schema=False)
    added = application.router.routes[before:]
    del application.router.routes[before:]
    application.router.routes[0:0] = added


def create_app(
    *,
    clock: Clock | None = None,
    run_migrations: bool = True,
    request_shutdown: Callable[[], None] | None = None,
    runtime: Runtime = start_runtime,
    on_lock_lost: Callable[[], None] = exit_process,
) -> FastAPI:
    """Build the application. Pure: no environment, no I/O, no socket.

    The keyword arguments are the test seam (plan PD16): a fake clock, no
    migration at boot (the test database is migrated once per session), a
    shutdown hook (PD17), the runtime itself (a no-op one for the shell tests)
    and the reaction to a lost advisory lock (PD5). Production passes none.
    """
    application = FastAPI(
        title="BorrelBeurs",
        version="0.0.0",
        lifespan=lifespan,
        # SD3: no docs routes here; a non-production lifespan adds them (PD15).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Phase 8 SD15: one app clock for every caller, its offset raised by the ticker
    # and at boot; a test's `FakeClock` still drives it, since it only adds.
    application.state.clock = AppClock(clock if clock is not None else RealClock())
    application.state.run_migrations = run_migrations
    application.state.request_shutdown = request_shutdown
    application.state.runtime = runtime
    application.state.on_lock_lost = on_lock_lost

    # False until the lifespan says otherwise, so an app that is merely
    # constructed -- in a test, in `--reload`'s parent process -- is never ready.
    application.state.ready = False
    application.state.standby = False

    application.add_exception_handler(AppError, handle_app_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    # SD9. No CORS middleware, ever: one origin (AC6b).
    application.add_middleware(OriginGuard)
    # Added last, so outermost: in standby nothing behind it runs (Phase 8 SD4).
    application.add_middleware(StandbyGate)
    application.include_router(health_router)
    application.include_router(api_router)
    application.include_router(ws_router)
    # Public (Phase 4 SD8), and in front of the SPA mount, which would otherwise catch it.
    application.include_router(theme_css_router)
    # Public (Phase 6 SD29); `{asset_id:int}`, so the SPA's own `/assets/*.js` fall through.
    application.include_router(assets_router)

    # Mounted last, at "/", and after /api: everything above already owns its
    # namespace, so the SPA only ever catches what neither router claimed
    # (docs/design/architecture.md:36-38). It serves the files in `web/dist`;
    # `html=True` adds `index.html` for "/" and directory-style requests, and
    # `SpaStaticFiles` adds it for a reload of one of the client's own routes
    # (`SPA_ROUTES`, Phase 4 PD8). Nothing else falls back: `/probe` and
    # `/koers/x` stay a plain 404, and `/api/nope` is the API's JSON 404. The SPA
    # paths are not FastAPI routes, so the public allowlist stays as it is.
    if WEB_DIST.is_dir():
        application.mount("/", SpaStaticFiles(directory=WEB_DIST, html=True), name="spa")

    return application


app = create_app()


def main() -> None:
    """Run the server on `settings.port` (plan D11: `PORT`, defaulting to 8000).

    The server is built here rather than by `uvicorn.run`, so the app can ask it
    to stop: `request_shutdown` sets `should_exit`, uvicorn's own graceful path
    (lifespan shutdown, exit 0) on every OS (plan PD17).
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            # All interfaces: inside a container there is nothing else to bind.
            host="0.0.0.0",
            port=settings.port,
            # Our JSON formatter owns the root logger; uvicorn's default dictConfig
            # would replace it with plain text half a second later.
            log_config=None,
            # Phase 8 SD9, AC26: said explicitly. With `proxy_headers` on, uvicorn
            # trusts `FORWARDED_ALLOW_IPS` (loopback by default); off, it reads no
            # `X-Forwarded-For` at all, so the login limiter keys on the real peer.
            proxy_headers=bool(settings.trusted_proxy_ips),
            forwarded_allow_ips=settings.trusted_proxy_ips or None,
        )
    )
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
