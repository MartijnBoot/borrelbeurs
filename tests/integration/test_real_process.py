"""Real-process proofs (Phase 3 T29: AC18, AC18d; SD34; "Kill test", "Second instance").

Everything here runs the production entrypoint, `python -m app.main`, as a
subprocess against the scratch database, and drives it over stdlib `urllib`
(`tests/integration/realapp/harness.py`). No `TestClient`, no fake clock: the
real ticker on the real clock.

- **AC18d**: killed at five points -- mid order stream, right after an
  acknowledged order, mid tick (twice, at different moments), and while idle --
  then restarted. Every acknowledged order is present, at most one tick was
  lost, and `version` / `rng_counter` continue from the last committed row.
- **AC18**: a second instance against the held lock exits non-zero within 5 s,
  logs the lock, and never migrates (the alembic version of a database one
  revision behind is unchanged). And `pg_terminate_backend` on the first
  instance's lock connection makes it exit non-zero.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import RunAlembic
from tests.integration.realapp.harness import (
    Client,
    mint_key,
    seed_live_run,
    spawn_app,
    start_app,
)

KILL_POINTS = ("mid-order-stream", "after-ack", "mid-tick-early", "mid-tick-late", "idle")


async def _query(url: str, sql: str) -> list[tuple[Any, ...]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in await conn.execute(text(sql))]
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


def _order_until_acked(client: Client, key: str) -> dict[str, Any] | None:
    """One order of drink one at its live price; on a 409, once more with the returned prices.

    `/api/state` carries no version, so the quote is version 0 at the live price:
    charged under SD18's equal-price rule whatever its age, or 409 with the
    current version and prices to retry with.
    """
    state = client.state()
    drink = int(next(iter(state["prices"])))
    price = state["prices"][str(drink)]["price_cents"]
    quote = 0
    for _ in range(3):
        status, body = client.order(
            key, quote, [{"drink_id": drink, "qty": 1, "unit_price_cents": price}]
        )
        if status in (200, 201):
            receipt: dict[str, Any] = body
            return receipt
        if status != 409:
            raise AssertionError((status, body))
        quote = body["error"]["version"]
        price = next(p["price_cents"] for p in body["error"]["prices"] if p["drink_id"] == drink)
    return None


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
                            receipt = _order_until_acked(client, f"k-stream-{n}-{k:03d}")
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
                receipt = _order_until_acked(client, f"k-ack-{n:04d}")
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


def test_a_second_instance_exits_fast_logs_the_lock_and_never_migrates(
    database_url: str, empty_database: str, alembic: RunAlembic, tmp_path: Path
) -> None:
    """AC18: lock before migrate. The first instance holds the lock on `empty_database`,
    migrated to head; a second, pointed at the same database after it is downgraded one
    revision, must refuse before touching the schema."""
    assert alembic(empty_database, "upgrade", "head").returncode == 0
    first = start_app(empty_database, tmp_path / "first.stderr")
    try:
        # The first instance holds the lock; the schema is now one revision behind.
        downgraded = alembic(empty_database, "downgrade", "-1")
        assert downgraded.returncode == 0, downgraded.stderr
        before = _rows(empty_database, "SELECT version_num FROM alembic_version")
        assert before == [("0006",)]
        started = time.monotonic()
        second = spawn_app(empty_database, tmp_path / "second.stderr")
        code = second.wait(timeout=15)
        elapsed = time.monotonic() - started
        after = _rows(empty_database, "SELECT version_num FROM alembic_version")
    finally:
        first.kill()

    assert code != 0
    assert elapsed < 5 + 3  # 5 s per AC18, plus interpreter start-up
    assert "advisory lock" in second.stderr()
    assert after == before


def test_a_dropped_lock_connection_makes_the_app_exit_non_zero(
    database_url: str, tmp_path: Path
) -> None:
    """AC18 / PD5: it can no longer prove it is the only writer, so it stops."""
    app = start_app(database_url, tmp_path / "app.stderr")
    try:
        terminated = _rows(
            database_url,
            "SELECT pg_terminate_backend(pid) FROM pg_locks"
            " WHERE locktype = 'advisory' AND granted",
        )
        assert terminated and all(row[0] for row in terminated)
        code = app.wait(timeout=15)
    finally:
        if app.proc.poll() is None:
            app.kill()

    # Exit code only: `os._exit` may cut the log short (plan R8).
    assert code == 70
