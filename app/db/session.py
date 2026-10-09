"""The one place an engine is built from `Settings`."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """An async engine on `settings.database_url`, already validated as `postgresql+asyncpg`.

    Connecting and every statement are bounded by `database_timeout_seconds`, so a
    silent database fails a commit (SD14) instead of hanging it.
    """
    timeout = settings.database_timeout_seconds
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"timeout": timeout, "command_timeout": timeout},
    )


def create_heavy_read_engine(settings: Settings) -> AsyncEngine:
    """The export and analytics engine (Phase 7 SD11, PD2): the same database, other connections.

    `NullPool` opens a fresh connection per use, so a long read never holds one
    of the order path's pooled connections, and `heavy_read_timeout_seconds`
    bounds it instead of the live path's 5 s.
    """
    timeout = settings.heavy_read_timeout_seconds
    return create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"timeout": timeout, "command_timeout": timeout},
    )
