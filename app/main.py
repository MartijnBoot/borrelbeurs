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
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.news import router as news_router
from app.api.security import LoginLimiter, OriginGuard
from app.api.state import router as state_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, handle_app_error, handle_validation_error
from app.core.logging import configure_logging
from app.runtime.boot import exit_process, start_runtime
from app.runtime.clock import Clock, RealClock

logger = logging.getLogger(__name__)

# Every application route hangs here (docs/design/architecture.md:36-38). It is
# empty in Phase 0 and that is the point: the prefix is established before there
# is anything to move, so T6's SPA catch-all -- mounted after this router -- has
# one namespace to keep its hands off instead of twenty top-level paths.
api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(state_router)
api_router.include_router(news_router)

# `pnpm --dir web build` output (T6). Not built by every checkout -- a Python
# test run has no reason to have run pnpm first -- so its absence only means
# there is no frontend to serve, never a boot failure.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

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
    if settings.app_env != "production":
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
            extra={"app_env": settings.app_env, "port": settings.port},
        )
        yield
    logger.info("application stopped")


def _mount_docs(application: FastAPI) -> None:
    """SD3: `/openapi.json`, `/docs` and `/redoc`, outside production only (plan PD15).

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
    application.state.clock = clock if clock is not None else RealClock()
    application.state.run_migrations = run_migrations
    application.state.request_shutdown = request_shutdown
    application.state.runtime = runtime
    application.state.on_lock_lost = on_lock_lost

    # False until the lifespan says otherwise, so an app that is merely
    # constructed -- in a test, in `--reload`'s parent process -- is never ready.
    application.state.ready = False

    application.add_exception_handler(AppError, handle_app_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    # SD9. No CORS middleware, ever: one origin (AC6b).
    application.add_middleware(OriginGuard)
    application.include_router(health_router)
    application.include_router(api_router)

    # Mounted last, at "/", and after /api: everything above already owns its
    # namespace, so the SPA only ever catches what neither router claimed
    # (docs/design/architecture.md:36-38). `html=True` serves `index.html` for
    # "/" and other directory-style requests; it does not add history-mode
    # fallback for arbitrary unmatched paths -- Phase 0 has no client-side
    # routes yet to justify that, and `/probe` or `/api/nope` must keep
    # answering plain 404, not SPA HTML.
    if WEB_DIST.is_dir():
        application.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="spa")

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
        )
    )
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
