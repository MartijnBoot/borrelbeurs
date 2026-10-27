"""Shared fixtures. Nothing here is autouse: a unit test that asks for none of
these pays for none of them.

**Why the integration fixtures read the real environment rather than start a
testcontainers Postgres.** The plan's Files table pencils testcontainers in
here, but two of its own tasks rule it out. T9's verification removes a
required variable from `.env.local` and expects the integration step to fail
*naming that variable*; T11 gives CI a Postgres service container for this
step. Both only work if the integration layer runs against whatever the
environment says -- the compose `db` locally (exported from `.env.local` by
`scripts/check.sh`), the service container in CI. A container URL substituted
here would make `DATABASE_URL` unfalsifiable.

**The run lock (B-11 SD5).** A session that selects a test under `tests/integration`
or `tests/api` takes `tests/support/pg_gate.py`'s lock on the Postgres server for
its life: exclusive if it selects any `serial` test, shared otherwise, so a serial
run never overlaps another run's database tests. A run that selects nothing
there (`unit`, `meta`, `engine`) opens no connection. An xdist controller takes
it once, shared, from its path arguments and tells its workers (`BB_GATE_LOCK_HELD`)
not to; a worker that finds a `serial` test refuses to run, since it could never
hold the lock exclusively. Under the gate, `check.sh`'s stage-2 holder covers
everything it starts the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

import tests.engine.golden  # noqa: F401  # pins numpy's SIMD dispatch before numpy loads
from app.core.config import ConfigError, Settings, get_settings
from tests.support import pg_gate

TESTS = Path(__file__).resolve().parent
DATABASE_DIRS = (TESTS / "integration", TESTS / "api")


def _is_database_path(path: Path) -> bool:
    return any(d == path or d in path.parents for d in DATABASE_DIRS)


def _arguments_reach_database_tests(args: Sequence[str]) -> bool:
    """Whether any path argument is, is inside, or contains a database test directory."""
    for arg in args:
        path = Path(arg.split("::", 1)[0]).resolve()
        if _is_database_path(path) or any(path in d.parents or path == d for d in DATABASE_DIRS):
            return True
    return False


def _database_url() -> str | None:
    try:
        return get_settings().database_url
    except ConfigError:
        return None  # the `settings` fixture reports it, naming the variable (AC2)


def _announcer(config: pytest.Config) -> pg_gate.Announce:
    reporter = config.pluginmanager.get_plugin("terminalreporter")

    def say(line: str) -> None:
        if reporter is not None:
            reporter.write_line(line)
        else:
            print(line, flush=True)

    return say


def _is_controller(config: pytest.Config) -> bool:
    return not hasattr(config, "workerinput") and bool(config.getoption("numprocesses", None))


def pytest_configure(config: pytest.Config) -> None:
    """An xdist controller holds the shared lock for its workers; it never collects."""
    if not _is_controller(config) or config.option.collectonly:
        return
    if not _arguments_reach_database_tests(config.args or [str(TESTS)]):
        return
    if (url := _database_url()) and pg_gate.acquire_run_lock(
        url, "shared", announce=_announcer(config)
    ):
        pg_gate.cover_children()


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    if config.option.collectonly or _is_controller(config):
        return
    database_items = [item for item in session.items if _is_database_path(Path(item.path))]
    if not database_items:
        return
    serial = any(item.get_closest_marker("serial") for item in database_items)
    if hasattr(config, "workerinput"):
        if serial:
            pytest.exit(
                "a `serial` test was selected under xdist; run `-m serial` without `-n` "
                "(B-11 SD3): a worker could never hold the run lock exclusively",
                returncode=4,
            )
        return  # the controller (or the gate's holder) holds it
    if url := _database_url():
        pg_gate.acquire_run_lock(
            url, "exclusive" if serial else "shared", announce=_announcer(config)
        )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    """After every scratch database is dropped (their fixtures finish first)."""
    pg_gate.release_run_lock()


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The settings this process was started with, validated exactly as at boot.

    A missing or malformed variable raises `ConfigError` here, so every test
    that depends on this one errors with the message naming the variable (AC2)
    rather than failing further down with something less specific.
    """
    # Unit tests monkeypatch the environment and prime the cache with it; a
    # session sharing a process with them must not inherit their fake values.
    get_settings.cache_clear()
    return get_settings()
