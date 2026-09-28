"""Alembic's entry point — async, and taking its DSN from the config module.

Two things here are not the stock template, and both are deliberate.

**The URL comes from `app.core.config`.** Not from `alembic.ini` (a second,
committed source of truth that would drift from `.env.example`) and not from
`os.environ` (spec AC3 — `tests/meta/test_config_boundary.py` scans `db/` for
exactly that, and this file is in its scope). `get_settings()` means a
malformed DSN fails here the same way it fails the app's boot, with the same
message naming the same variable.

**The engine is async.** ADR 0004 puts Postgres under an asyncpg driver, and
`app/core/config.py` now rejects any DSN that is not `postgresql+asyncpg://`.
A sync `engine_from_config` would therefore refuse the only URL this project
ever supplies. The shape below — `create_async_engine` plus
`connection.run_sync` — is Alembic's own documented pattern for that case,
because the migration operations themselves are synchronous.

The URL is passed straight to `create_async_engine` rather than through
`config.set_main_option("sqlalchemy.url", ...)`: the ini file is read by
ConfigParser, so a percent-encoded password (`p%40ss`) written into it would
be mangled by string interpolation.

One consequence worth stating for `scripts/setup.sh` (T8): `get_settings()`
validates the *whole* environment, not just `DATABASE_URL`, so running a
migration needs the same variables a boot needs — including a `JWT_SECRET`
long enough to pass. That is the intended shape: one schema, one validation,
no second definition of "configured enough".
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, MetaData, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No declarative models exist yet — Phase 2 owns the schema. Until then
# `--autogenerate` has nothing to compare against, which is correct: Phase 0's
# baseline creates no tables.
target_metadata: MetaData | None = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (`alembic upgrade --sql`).

    Kept from the stock template. It costs four lines and it is the only way to
    review a migration's SQL without a database, which Phase 2 will want.
    """
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """The synchronous half, handed a real DBAPI connection by `run_sync`."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect with asyncpg and run the migrations on that connection.

    `NullPool`: this process opens one connection, runs to completion and
    exits. A pool would only add a connection to leave behind.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)

    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
