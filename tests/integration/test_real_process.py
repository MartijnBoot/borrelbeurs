"""Real-process proofs (Phase 3 T29: AC18, AC18d; SD34; "Kill test", "Second instance").

Everything here runs the production entrypoint, `python -m app.main`, as a
subprocess against the scratch database, and drives it over stdlib `urllib`
(`tests/integration/realapp/harness.py`). No `TestClient`, no fake clock: the
real ticker on the real clock.

- **AC18d**: killed at five points -- mid order stream, right after an
  acknowledged order, mid tick (twice, at different moments), and while idle --
  then restarted. Every acknowledged order is present, at most one tick was
  lost, and `version` / `rng_counter` continue from the last committed row.
- **AC12** (Phase 8, was AC18's fail-fast): a second instance against the held
  lock waits in standby, logs `lock_wait`, and never migrates (the alembic
  version of a database one revision behind is unchanged). A boot failure once
  it gets the lock exits 3 (AC8). And `pg_terminate_backend` on the first
  instance's lock connection makes it exit non-zero.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.advisory_lock import ADVISORY_LOCK_KEY
from tests.integration.conftest import RunAlembic, head_and_previous
from tests.integration.realapp.harness import (
    Client,
    mint_key,
    order_until_acked,
    seed_live_run,
    spawn_app,
    start_app,
)

# Serial (SD3): starts real apps, and asserts the kill test within 600 s.
pytestmark = pytest.mark.serial

KILL_POINTS = ("mid-order-stream", "after-ack", "mid-tick-early", "mid-tick-late", "idle")


async def _query(url: str, sql: str) -> list[tuple[Any, ...]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in await conn.execute(text(sql))]
    finally:
        await engine.dispose()


async def _write(url: str, *statements: str) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


def _rows(url: str, sql: str) -> list[tuple[Any, ...]]:
    return asyncio.run(_query(url, sql))


def _committed(url: str) -> tuple[int, int, int]:
    """The last committed engine row's version and rng_counter, and the newest tick's wall time."""
    ((version, rng, wall),) = _rows(
        url, "SELECT version, rng_counter, wall_ts_ms FROM engine_state"
    )
    return int(version), int(rng), int(wall)


def test_a_killed_app_loses_no_acknowledged_order_and_at_most_one_tick(
    database_url: str, tmp_path: Path
) -> None:
    """AC18d at five kill points, each followed by a restart on the same database."""
    seed_live_run(database_url)
    key = mint_key(database_url, "bar")
    acked: list[dict[str, Any]] = []
    stderr = tmp_path / "app.stderr"
    started = time.monotonic()

    for n, point in enumerate(KILL_POINTS):
        app = start_app(database_url, stderr)
        try:
            client = Client(app.base)
            client.login(key)
            if point == "mid-order-stream":
                # Orders on a background thread; the kill lands while they stream.
                def stream(client: Client = client, n: int = n) -> None:
                    for k in range(50):
                        try:
                            receipt = order_until_acked(client, f"k-stream-{n}-{k:03d}")
                        except Exception:
                            return
                        if receipt is not None:
                            acked.append(receipt)

                worker = threading.Thread(target=stream)
                worker.start()
                time.sleep(1.5)
                before_kill = _committed(database_url)
                app.kill()
                worker.join(timeout=30)
            elif point == "after-ack":
                receipt = order_until_acked(client, f"k-ack-{n:04d}")
                assert receipt is not None
                acked.append(receipt)
                before_kill = _committed(database_url)
                app.kill()
            else:
                time.sleep({"mid-tick-early": 1.2, "mid-tick-late": 2.7, "idle": 0.4}[point])
                before_kill = _committed(database_url)
                app.kill()
        finally:
            if app.proc.poll() is None:
                app.kill()

        after_kill = _committed(database_url)
        # Nothing went backwards; whatever was in flight at the kill is simply not there.
        assert after_kill[0] >= before_kill[0]

        stored = {
            int(r[0]): int(r[1])
            for r in _rows(database_url, 'SELECT order_id, version FROM "order"')
        }
        for receipt in acked:
            assert stored.get(receipt["order_id"]) == receipt["version"], (point, receipt)

        # Restart: the app resumes from exactly the committed row.
        app = start_app(database_url, stderr)
        try:
            resumed = Client(app.base)
            resumed.login(key)
            state = resumed.state()
            assert state["run"]["run_id"] is not None
            time.sleep(1.5)
            version, rng, _ = _committed(database_url)
            # Continued from the last committed row: new versions on top, no gap, and the
            # noise stream's counter never rewinds.
            assert version > after_kill[0], (point, version, after_kill)
            assert rng >= after_kill[1]
            resumed_versions = [
                int(r[0])
                for r in _rows(
                    database_url,
                    f"SELECT version FROM price_tick WHERE version > {after_kill[0]}"
                    " ORDER BY version",
                )
            ]
            assert resumed_versions[0] == after_kill[0] + 1, (point, resumed_versions[:3])
        finally:
            app.kill()

    versions = [
        int(r[0]) for r in _rows(database_url, "SELECT version FROM price_tick ORDER BY version")
    ]
    assert versions == list(range(len(versions))), "a version is missing or duplicated"
    assert acked, "no order was acknowledged; the kill test proves nothing about orders"
    assert time.monotonic() - started < 600


def _get(base: str, path: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_a_second_instance_waits_in_standby(
    database_url: str, empty_database: str, alembic: RunAlembic, tmp_path: Path
) -> None:
    """AC12 (Phase 8 SD4; was AC18's fail-fast): lock before migrate. The first instance
    holds the lock on `empty_database`, migrated to head; a second, pointed at the same
    database after it is downgraded one revision, stays alive in standby without
    touching the schema, while the first ticks on alone."""
    assert alembic(empty_database, "upgrade", "head").returncode == 0
    first = start_app(empty_database, tmp_path / "first.stderr")
    second = None
    try:
        # The first instance holds the lock; the schema is now one revision behind.
        downgraded = alembic(empty_database, "downgrade", "-1")
        assert downgraded.returncode == 0, downgraded.stderr
        before = _rows(empty_database, "SELECT version_num FROM alembic_version")
        assert before == [(head_and_previous()[1],)]
        ticks_before = _rows(empty_database, "SELECT count(*) FROM price_tick")
        second = spawn_app(empty_database, tmp_path / "second.stderr")
        time.sleep(5)
        alive = second.proc.poll() is None
        health = _get(second.base, "/healthz")
        ready = _get(second.base, "/readyz")[0]
        first_health = _get(first.base, "/healthz")
        after = _rows(empty_database, "SELECT version_num FROM alembic_version")
        ticks_after = _rows(empty_database, "SELECT count(*) FROM price_tick")
    finally:
        if second is not None:
            second.kill()
        first.kill()

    assert alive, second.stderr()
    assert health[0] == 200 and health[1]["status"] == "standby"
    assert ready == 503
    assert first_health[1]["status"] == "ok"
    assert "lock_wait" in second.stderr()
    assert after == before
    # No live run in `empty_database`: the first instance idles and nobody writes ticks.
    assert ticks_after == ticks_before


def test_a_boot_failure_after_standby_exits_3_and_is_never_ready(
    empty_database: str, alembic: RunAlembic, tmp_path: Path
) -> None:
    """AC8 after standby (PD1): the second instance waits, the first dies, and the schema
    it then finds is ahead of its image and incompatible: `boot_failed`, exit 3 -- the
    code uvicorn uses for a startup failure -- and `/readyz` never 200."""
    assert alembic(empty_database, "upgrade", "head").returncode == 0
    first = start_app(empty_database, tmp_path / "first.stderr")
    second = None
    readies: list[int] = []
    try:
        asyncio.run(
            _write(
                empty_database,
                "UPDATE alembic_version SET version_num = 'ci_ahead_fixture'",
                "UPDATE schema_compat SET min_code_revision = 'ci_ahead_fixture'",
            )
        )
        second = spawn_app(empty_database, tmp_path / "second.stderr")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and _health_status(second.base) != "standby":
            time.sleep(0.2)
        first.kill()
        deadline = time.monotonic() + 30
        while second.proc.poll() is None and time.monotonic() < deadline:
            readies.append(_status(second.base, "/readyz"))
            time.sleep(0.2)
        code = second.wait(timeout=5)
    finally:
        if second is not None and second.proc.poll() is None:
            second.kill()
        if first.proc.poll() is None:
            first.kill()

    assert code == 3, second.stderr()
    assert 200 not in readies
    assert "schema ahead of image" in second.stderr()


def _status(base: str, path: str) -> int:
    try:
        return _get(base, path)[0]
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0


def _health_status(base: str) -> str | None:
    try:
        return str(_get(base, "/healthz")[1]["status"])
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def test_a_dropped_lock_connection_makes_the_app_exit_non_zero(
    database_url: str, tmp_path: Path
) -> None:
    """AC18 / PD5: it can no longer prove it is the only writer, so it stops."""
    app = start_app(database_url, tmp_path / "app.stderr")
    try:
        # pg_locks is cluster-wide: only this test database's app lock, never a dev stack's.
        terminated = _rows(
            database_url,
            "SELECT pg_terminate_backend(pid) FROM pg_locks"
            " WHERE locktype = 'advisory' AND granted"
            " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            f" AND classid = 0 AND objid = {ADVISORY_LOCK_KEY}",
        )
        assert terminated and all(row[0] for row in terminated)
        code = app.wait(timeout=15)
    finally:
        if app.proc.poll() is None:
            app.kill()

    # Exit code only: `os._exit` may cut the log short (plan R8).
    assert code == 70
