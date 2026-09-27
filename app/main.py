"""The application shell: build the app, boot it, answer two probes.

**Nothing happens at import except building the object graph.** `create_app()`
constructs routers; it reads no variable, opens no file and binds no socket.
The environment is read inside `lifespan`, on the first line of boot, and
nowhere else (`app/core/config.py:5-11`).

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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.errors import AppError, handle_app_error
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

# Every application route hangs here (docs/design/architecture.md:36-38). It is
# empty in Phase 0 and that is the point: the prefix is established before there
# is anything to move, so T6's SPA catch-all -- mounted after this router -- has
# one namespace to keep its hands off instead of twenty top-level paths.
api_router = APIRouter(prefix="/api")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load settings, configure logging, declare the instance ready.

    The seams Phase 3 fills are here, in order: after `configure_logging` come
    the migration, the ADR 0003 advisory lock, rehydration and the ticker. None
    of them exist yet, and stubbing them would be inventing an interface a
    phase early.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    application.state.settings = settings
    application.state.ready = True
    logger.info(
        "application started",
        extra={"app_env": settings.app_env, "port": settings.port},
    )

    try:
        yield
    finally:
        # Shutdown flips readiness first: a drain that keeps reporting 200 is
        # how a load balancer keeps sending traffic at a closing process.
        application.state.ready = False
        logger.info("application stopped")


def create_app() -> FastAPI:
    """Build the application. Pure: no environment, no I/O, no socket."""
    application = FastAPI(
        title="BorrelBeurs",
        version="0.0.0",
        lifespan=lifespan,
    )

    # False until the lifespan says otherwise, so an app that is merely
    # constructed -- in a test, in `--reload`'s parent process -- is never ready.
    application.state.ready = False

    application.add_exception_handler(AppError, handle_app_error)
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()


def main() -> None:
    """Run the server on `settings.port` (plan D11: `PORT`, defaulting to 8000)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "app.main:app",
        # All interfaces: inside a container there is nothing else to bind.
        host="0.0.0.0",
        port=settings.port,
        # Our JSON formatter owns the root logger; uvicorn's default dictConfig
        # would replace it with plain text half a second later.
        log_config=None,
    )


if __name__ == "__main__":
    main()
