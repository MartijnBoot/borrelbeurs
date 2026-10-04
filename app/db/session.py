"""The one place an engine is built from `Settings`."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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
