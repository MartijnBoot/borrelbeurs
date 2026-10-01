"""The one place an engine is built from `Settings`."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """An async engine on `settings.database_url`, already validated as `postgresql+asyncpg`."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)
