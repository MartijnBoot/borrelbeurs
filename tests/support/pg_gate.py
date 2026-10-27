"""Sharing one Postgres server between test runs (B-11 SD5, SD6, SD14).

Everything here is an advisory lock on the **maintenance database**, the one
`DATABASE_URL` names and scratch databases are created from. Locks write nothing,
and a dead process's connection drops them, so a killed run never blocks the next.

- **The run lock** (SD5), on `GATE_KEY`: a gate's stage 2 and every non-serial
  database run hold it shared, a serial run holds it exclusive. Postgres queues
  waiters in order, so a waiting serial run is not starved -- and, for the same
  reason, a *new* shared request queues behind a waiting exclusive one. So a holder
  passes `BB_GATE_LOCK_HELD=1` to the processes it starts (`check.sh`'s stage 2,
  an xdist controller's workers) and they skip the acquire; otherwise they would
  queue behind a serial run that waits for their own holder.
- **Ownership** (SD6): `own` locks `bb-owner:<name>` *before* the database is
  created, so a sweeper never sees a live database without its owner's lock, and
  `sweep` drops a `bb_test_*` / `borrelbeurs_e2e_*` only if it can take that lock.
  No age, no clock: a killed run's databases go at the next run's start.
- **Ports** (SD14): `claim_port` try-locks `bb-port:<n>`, so two runs of the
  real-app harness are never handed the same number.

One connection per process, made on first use from the `base_url` its first
caller passes -- never re-read from the environment later, since a test may have
pointed `DATABASE_URL` at its scratch database, where no other process would see
these locks. It lives on a daemon thread's own event loop, so the locks outlive
any `asyncio.run` and die with the process. A process that never asks opens
nothing (AC16).

    uv run python -m tests.support.pg_gate hold [shared|exclusive]

takes the run lock, prints `held`, and keeps it until its stdin closes:
`check.sh`'s stage-2 holder.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, Literal, TypeVar

from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

GATE_KEY = "bb-gate"
LOCK_HELD_ENV = "BB_GATE_LOCK_HELD"
PREFIXES = ("bb_test_", "borrelbeurs_e2e_")

Mode = Literal["shared", "exclusive"]
Announce = Callable[[str], None]
T = TypeVar("T")


def _say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


class MaintenanceConnection:
    """One AUTOCOMMIT connection to the maintenance database, on its own loop thread."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._engine = create_async_engine(
            base_url, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool
        )
        self._conn: AsyncConnection = self._call(self._engine.connect().start())

    def _call(self, coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def scalar(self, sql: str, **params: object) -> object:
        async def run() -> object:
            return (await self._conn.execute(text(sql), params)).scalar()

        return self._call(run())

    def close(self) -> None:
        async def run() -> None:
            await self._conn.close()
            await self._engine.dispose()

        self._call(run())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)


_connection: MaintenanceConnection | None = None
_connection_lock = threading.Lock()
_owned: set[str] = set()
_held: list[tuple[str, Mode]] = []


def _same(a: str, b: str) -> bool:
    return make_url(a) == make_url(b)


def maintenance(base_url: str | None = None) -> MaintenanceConnection:
    """This process's connection, made from `base_url` on first use.

    Without `base_url`, the connection must already exist (`claim_port`'s callers
    have always owned a database first). A second, different `base_url` is an
    error: the locks would be split across two servers or databases.
    """
    global _connection
    with _connection_lock:
        if _connection is None:
            if base_url is None:
                raise RuntimeError("pg_gate: no maintenance connection yet; own a database first")
            _connection = MaintenanceConnection(base_url)
        elif base_url is not None and not _same(base_url, _connection.base_url):
            first, second = make_url(_connection.base_url).database, make_url(base_url).database
            raise RuntimeError(
                f"pg_gate: a second maintenance database ({second!r} after {first!r})"
            )
        return _connection


def reset() -> None:
    """Close this process's connection, dropping every lock it holds (tests only)."""
    global _connection
    with _connection_lock:
        if _connection is not None:
            _connection.close()
        _connection = None
        _owned.clear()
        _held.clear()


# Every lock is keyed by a name, hashed by the server, bound as `:k`.
_KEY = "hashtextextended(:k, 0)"


# --- the run lock (SD5) ------------------------------------------------------------


def acquire_run_lock(
    base_url: str,
    mode: Mode,
    *,
    key: str = GATE_KEY,
    announce: Announce = _say,
) -> bool:
    """Take the run lock; `False` without asking when a holder covers this process.

    A try first, so an uncontended run says nothing; then, announced, the blocking
    call, which joins Postgres's fair queue (AC12).
    """
    if os.environ.get(LOCK_HELD_ENV):
        return False
    conn = maintenance(base_url)
    suffix = "_shared" if mode == "shared" else ""
    if conn.scalar(f"SELECT pg_try_advisory_lock{suffix}({_KEY})", k=key):
        _held.append((key, mode))
        return True
    announce(f"pg_gate: waiting for the {mode} run lock -- another test run holds it")
    started = time.monotonic()
    conn.scalar(f"SELECT pg_advisory_lock{suffix}({_KEY})", k=key)
    _held.append((key, mode))
    announce(f"pg_gate: got the {mode} run lock after {time.monotonic() - started:.1f} s")
    return True


def cover_children() -> None:
    """Tell the processes this one starts that it holds the run lock for them."""
    os.environ[LOCK_HELD_ENV] = "1"


def release_run_lock() -> None:
    """Release every run lock this process took."""
    if not _held:
        return
    conn = maintenance()
    while _held:
        key, mode = _held.pop()
        suffix = "_shared" if mode == "shared" else ""
        conn.scalar(f"SELECT pg_advisory_unlock{suffix}({_KEY})", k=key)


# --- ownership and the sweep (SD6) --------------------------------------------------


def _owner(database: str) -> str:
    return f"bb-owner:{database}"


def own(base_url: str, database: str) -> None:
    """Hold `database`'s ownership lock for this process's life, or until `release`."""
    maintenance(base_url).scalar(f"SELECT pg_advisory_lock({_KEY})", k=_owner(database))
    _owned.add(database)


def release(database: str) -> None:
    """Give up ownership of `database`; after it is dropped, so a sweeper finds nothing."""
    if database in _owned:
        maintenance().scalar(f"SELECT pg_advisory_unlock({_KEY})", k=_owner(database))
        _owned.discard(database)


def sweep(base_url: str, prefixes: Sequence[str] = PREFIXES) -> list[str]:
    """Drop every database under `prefixes` whose owner is dead; return their names.

    The try-locks go over a short-lived connection of their own: advisory locks are
    re-entrant per session, so the maintenance connection would win its own
    databases' locks. This process's own databases are skipped by name for the
    same reason.
    """

    async def run() -> list[str]:
        engine = create_async_engine(
            base_url, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool
        )
        dropped: list[str] = []
        try:
            async with engine.connect() as conn:
                like = " OR ".join(f"datname LIKE '{p}%'" for p in prefixes)
                rows = await conn.execute(text(f"SELECT datname FROM pg_database WHERE {like}"))
                for database in sorted(str(row[0]) for row in rows):
                    if database in _owned:
                        continue
                    key = {"k": _owner(database)}
                    locked = await conn.execute(text(f"SELECT pg_try_advisory_lock({_KEY})"), key)
                    if not locked.scalar():
                        continue  # its owner is alive (AC13)
                    try:
                        await conn.execute(
                            text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
                        )
                        dropped.append(database)
                    finally:
                        await conn.execute(text(f"SELECT pg_advisory_unlock({_KEY})"), key)
        finally:
            await engine.dispose()
        return dropped

    return asyncio.run(run())


# --- ports (SD14) ------------------------------------------------------------------


def claim_port(port: int) -> bool:
    """Claim `port` for this process; `False` if another run of the harness has it."""
    return bool(maintenance().scalar(f"SELECT pg_try_advisory_lock({_KEY})", k=f"bb-port:{port}"))


def release_port(port: int) -> None:
    maintenance().scalar(f"SELECT pg_advisory_unlock({_KEY})", k=f"bb-port:{port}")


# --- the stage-2 holder -------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    if (
        len(argv) not in (1, 2)
        or argv[0] != "hold"
        or argv[1:] not in ([], ["shared"], ["exclusive"])
    ):
        _say("usage: python -m tests.support.pg_gate hold [shared|exclusive]")
        return 2
    mode: Mode = "exclusive" if argv[1:] == ["exclusive"] else "shared"
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        _say("pg_gate: DATABASE_URL is not set (scripts/check.sh exports .env.local)")
        return 2
    os.environ.pop(LOCK_HELD_ENV, None)  # the holder is the one that takes it
    acquire_run_lock(base_url, mode)
    print("held", flush=True)
    sys.stdin.read()
    release_run_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
