"""B-11 AC11, AC13, AC14: the run lock, ownership and the owner-aware sweep, on the real server.

Each other "run" is a child process, because the locks are per session and
re-entrant: only another connection can show that an ownership lock protects a
database, or that a shared holder blocks an exclusive one. The run-lock steps use
a private key, since this session may already hold the real one.
"""

from __future__ import annotations

import asyncio
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import Settings
from tests.integration.conftest import _admin
from tests.support import pg_gate

# Verifies the lock itself: it kills and starts processes that take it (plan T4).
pytestmark = pytest.mark.serial

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFIX = "bb_test_pggate_"

# A child that owns and creates `argv[2]` (or takes the run lock `argv[2]` in mode
# `argv[3]`), says so, and holds on until its stdin closes.
CHILD = """
import sys
from tests.integration.conftest import _admin, _drop
from tests.support import pg_gate
import asyncio
url, what = sys.argv[1], sys.argv[2]
if what == "own":
    database = sys.argv[3]
    pg_gate.own(url, database)
    asyncio.run(_admin(url, f'CREATE DATABASE "{database}"'))
else:
    pg_gate.acquire_run_lock(url, sys.argv[3], key=what)
print("held", flush=True)
sys.stdin.read()
if what == "own":
    _drop(url, database)
else:
    pg_gate.release_run_lock()
"""


class Child:
    """A child process whose merged output is read line by line, with a wait."""

    def __init__(self, *args: str) -> None:
        env = {k: v for k, v in os.environ.items() if k != pg_gate.LOCK_HELD_ENV}
        self.proc = subprocess.Popen(
            [sys.executable, "-c", CHILD, *args],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.lines: list[str] = []
        self._queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._queue.put(line.rstrip("\n"))

    def wait_for(self, prefix: str, seconds: float = 30.0) -> str | None:
        """The first line starting with `prefix` within `seconds`, or `None`."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = self._queue.get(timeout=left)
            except queue.Empty:
                break
            self.lines.append(line)
            if line.startswith(prefix):
                return line
        return None

    def stop(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        self.proc.wait(timeout=30)

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=30)


@pytest.fixture
def url(settings: Settings) -> str:
    return settings.database_url


@pytest.fixture
def children() -> Iterator[list[Child]]:
    started: list[Child] = []
    yield started
    for child in started:
        if child.proc.poll() is None:
            child.kill()


def _name() -> str:
    return f"{PREFIX}{secrets.token_hex(6)}"


def _exists(url: str, database: str) -> bool:
    rows = asyncio.run(_admin(url, f"SELECT datname FROM pg_database WHERE datname = '{database}'"))
    return rows == [database]


def _own_and_create(url: str, database: str) -> None:
    pg_gate.own(url, database)
    asyncio.run(_admin(url, f'CREATE DATABASE "{database}"'))


def _drop_owned(url: str, database: str) -> None:
    asyncio.run(_admin(url, f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    pg_gate.release(database)


def test_a_sweep_spares_every_live_owner_and_drops_a_killed_ones(
    url: str, children: list[Child]
) -> None:
    """Spec steps 1-3 and the in-process case: AC13, AC14."""
    theirs, mine, also_mine, killed = _name(), _name(), _name(), _name()
    other = Child(url, "own", theirs)
    children.append(other)
    assert other.wait_for("held"), other.lines
    _own_and_create(url, mine)
    _own_and_create(url, also_mine)
    try:
        # (1, 2, 2b) another live run's database, and both of this one's, survive.
        assert pg_gate.sweep(url, (PREFIX,)) == []
        assert all(_exists(url, d) for d in (theirs, mine, also_mine))

        # (3) a run killed while it owns a database: the next sweep drops it.
        dead = Child(url, "own", killed)
        children.append(dead)
        assert dead.wait_for("held"), dead.lines
        dead.kill()
        # Postgres ends the dead session asynchronously; wait for its lock to go.
        deadline = time.monotonic() + 30
        dropped: list[str] = []
        while not dropped and time.monotonic() < deadline:
            dropped = pg_gate.sweep(url, (PREFIX,))
            time.sleep(0.2)
        assert dropped == [killed]
        assert not _exists(url, killed)
        assert all(_exists(url, d) for d in (theirs, mine, also_mine))
    finally:
        _drop_owned(url, mine)
        _drop_owned(url, also_mine)
        other.stop()
    assert not _exists(url, theirs)


def test_shared_and_exclusive_holders_exclude_each_other_and_say_so(
    url: str, children: list[Child]
) -> None:
    """Spec step 4: AC11, and the announcements of AC12."""
    key = f"bb-gate-test-{secrets.token_hex(4)}"

    def start(mode: str) -> Child:
        child = Child(url, key, mode)
        children.append(child)
        return child

    shared = start("shared")
    assert shared.wait_for("held"), shared.lines
    second_shared = start("shared")
    assert second_shared.wait_for("held"), second_shared.lines  # shared holders coexist

    exclusive = start("exclusive")
    assert exclusive.wait_for("pg_gate: waiting for the exclusive run lock"), exclusive.lines
    assert exclusive.wait_for("held", seconds=1.0) is None, exclusive.lines
    shared.stop()
    assert exclusive.wait_for("held", seconds=1.0) is None, exclusive.lines  # one still holds
    second_shared.stop()
    assert exclusive.wait_for("held"), exclusive.lines
    got = "pg_gate: got the exclusive run lock after"
    assert any(line.startswith(got) for line in exclusive.lines), exclusive.lines

    late = start("shared")
    assert late.wait_for("pg_gate: waiting for the shared run lock"), late.lines
    assert late.wait_for("held", seconds=1.0) is None, late.lines
    exclusive.stop()
    assert late.wait_for("held"), late.lines
    late.stop()


def test_a_run_covered_by_its_holder_takes_no_lock(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refinement of SD5: a child of a holder skips the acquire."""
    monkeypatch.setenv(pg_gate.LOCK_HELD_ENV, "1")
    assert pg_gate.acquire_run_lock(url, "exclusive", key="bb-gate-never-taken") is False


def test_a_port_claimed_by_one_run_is_refused_to_another(url: str, children: list[Child]) -> None:
    """SD14: the claim is per session, so only another process is refused."""
    port = 40_000 + secrets.randbelow(20_000)
    pg_gate.maintenance(url)
    assert pg_gate.claim_port(port)
    try:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from tests.support import pg_gate; pg_gate.maintenance(sys.argv[1]);"
                f" print(pg_gate.claim_port({port}))",
                url,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        assert probe.stdout.strip() == "False", probe.stderr
    finally:
        pg_gate.release_port(port)


def test_a_deferred_drop_is_released_and_the_next_sweep_removes_it(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under the gate a drop is left to the sweep (T10): the database stays, unowned."""
    from tests.integration.conftest import DEFER_DROPS_ENV, _drop

    database = _name()
    _own_and_create(url, database)
    monkeypatch.setenv(DEFER_DROPS_ENV, "1")
    _drop(url, database)
    assert _exists(url, database)
    assert pg_gate.sweep(url, (PREFIX,)) == [database]
    assert not _exists(url, database)
