"""Integration fixtures: a scratch database per session, empty tables per test (PD15).

**Never the developer's own database.** Every test that touches the schema runs
in a database this module creates, named `bb_test_<hex>`, on the server
`DATABASE_URL` names (the compose `db` locally, the service container in CI,
SD16). The configured database is only ever used for the `CREATE DATABASE` and
`DROP DATABASE` statements themselves, on an AUTOCOMMIT connection. A run that
was killed before its teardown leaves a `bb_test_*` behind; the next session
sweeps those first.

**Why migrations run in a subprocess with `DATABASE_URL` overridden.**
`db/migrations/env.py` takes its URL from `get_settings()`, which is cached for
the life of a process, so an in-process `alembic upgrade` would migrate whatever
database the cache happened to hold -- quite possibly the developer's own. A
child process sees exactly the environment it is given, so the scratch URL is the
only URL it can reach. That is also the real `python -m alembic` the gate and
`scripts/setup.sh` run, not an in-process approximation of it.

Overriding the environment here does not breach Phase 0's AC3 (one module reads
the environment): that rule is about `app/` and `db/`, the roots
`tests/meta/test_config_boundary.py` scans. `tests/` is not one of them.

**Why TRUNCATE rather than a rolled-back transaction per test.** The concurrency
tests race two connections and the durability harness writes from another
process, so committed rows have to be visible across connections. Each test that
asks for `database_url` therefore starts from empty tables instead: every table in
`Base.metadata`, so a table added by a later migration is covered without editing
this file.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRATCH_PREFIX = "bb_test_"

RunAlembic = Callable[..., subprocess.CompletedProcess[str]]


def scratch_url(base_url: str, database: str) -> str:
    """`base_url` with its database name replaced; credentials kept."""
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


async def _admin(base_url: str, *statements: str) -> list[str]:
    """Run statements on an AUTOCOMMIT connection; return the first column of the last."""
    engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            rows: list[str] = []
            for statement in statements:
                result = await connection.execute(text(statement))
                rows = [str(row[0]) for row in result] if result.returns_rows else []
            return rows
    finally:
        await engine.dispose()


def _drop(base_url: str, database: str) -> None:
    asyncio.run(_admin(base_url, f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))


def _sweep_leftovers(base_url: str) -> None:
    """Drop every `bb_test_*` a killed run left behind."""
    leftovers = asyncio.run(
        _admin(
            base_url,
            f"SELECT datname FROM pg_database WHERE datname LIKE '{SCRATCH_PREFIX}%'",
        )
    )
    for database in leftovers:
        _drop(base_url, database)


def _create(base_url: str) -> tuple[str, str]:
    """Create an empty scratch database; return its name and URL."""
    database = f"{SCRATCH_PREFIX}{secrets.token_hex(6)}"
    asyncio.run(_admin(base_url, f'CREATE DATABASE "{database}"'))
    return database, scratch_url(base_url, database)


def run_alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """`python -m alembic -c db/alembic.ini <args>` against `url`, in a child process."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def scratch_database(settings: Settings) -> Iterator[str]:
    """A freshly migrated `bb_test_<hex>` for this session; dropped afterwards."""
    _sweep_leftovers(settings.database_url)
    database, url = _create(settings.database_url)
    try:
        migrated = run_alembic(url, "upgrade", "head")
        assert migrated.returncode == 0, f"alembic upgrade head failed:\n{migrated.stderr}"
        yield url
    finally:
        _drop(settings.database_url, database)


async def _truncate_all(url: str) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture
def database_url(scratch_database: str) -> str:
    """The session's scratch database, with every application table emptied first."""
    asyncio.run(_truncate_all(scratch_database))
    return scratch_database


@pytest.fixture
def empty_database(settings: Settings) -> Iterator[str]:
    """A second scratch database with no schema at all, for migration round trips."""
    database, url = _create(settings.database_url)
    try:
        yield url
    finally:
        _drop(settings.database_url, database)


@pytest.fixture
def alembic() -> RunAlembic:
    """`run_alembic`, as a fixture, so test modules need not import this conftest."""
    return run_alembic
