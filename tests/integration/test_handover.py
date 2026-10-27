"""AC13: one instance hands over to the standby one, as a deploy does (Phase 8 T7; AC29 test half).

Two real processes on one database (`tests/integration/realapp/harness.py`). A boots
live and holds the lock; B boots after it and waits in standby (SD4). Orders stream
to A from a thread. A then stops -- gracefully (`POST /api/admin/shutdown`, the
lifespan's exit releases the lock) or killed -- and B must take the lock within 2 s
of A's exit and become ready. An order A did not acknowledge is retried against B
with the same `Idempotency-Key`, as a phone would.

Across the handover:
- `price_tick` versions are contiguous from 0, and no two `tick` rows share a stamp;
- every acknowledged `order_id` is stored;
- the two processes never wrote at the same time: by `created_at`, every row A wrote
  comes before every row B wrote (A's rows are those committed before A had exited).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.realapp.harness import (
    AppProcess,
    Client,
    mint_key,
    order_until_acked,
    seed_live_run,
    spawn_app,
    start_app,
    stop_gracefully,
)

# Serial (SD3): starts real apps, and asserts the takeover within 2 s.
pytestmark = pytest.mark.serial

TAKEOVER_S = 2.0


async def _query(url: str, sql: str) -> list[tuple[Any, ...]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in await conn.execute(text(sql))]
    finally:
        await engine.dispose()


def _rows(url: str, sql: str) -> list[tuple[Any, ...]]:
    return asyncio.run(_query(url, sql))


def _status(base: str, path: str) -> tuple[int, Any]:
    try:
        return Client(base).request("GET", path)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, None


def _wait_for(condition: Any, seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _log_time(app: AppProcess, message: str) -> float:
    """When `app` logged `message`, from its own JSON log line's timestamp."""
    for line in app.stderr().splitlines():
        if line.startswith("{") and f'"message": "{message}"' in line:
            return datetime.fromisoformat(json.loads(line)["timestamp"]).timestamp()
    raise AssertionError(f"{message!r} not logged:\n{app.stderr()}")


class _Stream:
    """Orders one after another on a thread; each key is retried, on A and then on B
    once B is ready, until it is acknowledged."""

    def __init__(self, a: AppProcess, b: AppProcess, bar_key: str) -> None:
        self.bases = [a.base, b.base]
        self.bar_key = bar_key
        self.acked: list[dict[str, Any]] = []
        self.retried_on_b: list[str] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run)

    def _client(self, target: int) -> Client | None:
        """A logged-in client for a ready target, or `None` to try again shortly."""
        if _status(self.bases[target], "/readyz")[0] != 200:
            return None
        client = Client(self.bases[target])
        try:
            client.login(self.bar_key)
        except (AssertionError, OSError, urllib.error.URLError, ValueError):
            return None
        return client

    def _run(self) -> None:
        target = 0
        client = self._client(target)
        for k in range(10_000):
            if self.stop.is_set():
                return
            key = f"handover-{k:05d}"
            tried_a = False
            while not self.stop.is_set():
                try:
                    if client is None:
                        raise ConnectionError("not ready")
                    receipt = order_until_acked(client, key)
                except (AssertionError, OSError, urllib.error.URLError, ValueError):
                    receipt = None
                if receipt is not None:
                    self.acked.append(receipt)
                    if target == 1 and tried_a:
                        self.retried_on_b.append(key)
                    break
                tried_a = tried_a or target == 0
                target = 1  # A refused or is gone: B, with the same key
                time.sleep(0.05)
                client = self._client(target)


def _handover(database_url: str, tmp_path: Path, *, graceful: bool) -> dict[str, Any]:
    seed_live_run(database_url)
    bar_key = mint_key(database_url, "bar")
    admin_key = mint_key(database_url, "admin")
    a = start_app(database_url, tmp_path / "a.stderr")
    b = spawn_app(database_url, tmp_path / "b.stderr")
    stream = _Stream(a, b, bar_key)
    try:
        _wait_for(lambda: _in_standby(b), 30, "B in standby")
        stream.thread.start()
        time.sleep(2.0)
        acked_by_a = len(stream.acked)
        code = stop_gracefully(a, admin_key) if graceful else a.kill()
        a_exited = time.time()
        ((a_exited_db,),) = _rows(database_url, "SELECT now()")
        _wait_for(lambda: _status(b.base, "/readyz")[0] == 200, 30, "B ready")
        time.sleep(2.0)
        stream.stop.set()
        stream.thread.join(timeout=30)
        acked_after = len(stream.acked)
    finally:
        stream.stop.set()
        for app in (a, b):
            if app.proc.poll() is None:
                app.kill()
    return {
        "code": code,
        "takeover_s": _log_time(b, "lock_acquired") - a_exited,
        "acked": stream.acked,
        "acked_by_a": acked_by_a,
        "acked_after": acked_after,
        "a_exited_db": a_exited_db,
        "b": b,
    }


def _in_standby(app: AppProcess) -> bool:
    status, body = _status(app.base, "/healthz")
    return status == 200 and bool(body) and body.get("status") == "standby"


@pytest.mark.parametrize("graceful", [True, False], ids=["graceful", "death"])
def test_the_standby_instance_takes_over_with_one_writer_and_no_lost_order(
    database_url: str, tmp_path: Path, graceful: bool
) -> None:
    result = _handover(database_url, tmp_path, graceful=graceful)
    # Shown with `-s`: the evidence the plan asks for when the bound is near.
    print(f"takeover {result['takeover_s']:.3f} s, orders acked {result['acked_after']}")

    if graceful:
        assert result["code"] == 0
    assert result["takeover_s"] <= TAKEOVER_S, result["takeover_s"]
    assert result["acked_by_a"] > 0, "no order reached A before the stop"
    assert result["acked_after"] > result["acked_by_a"], "no order reached B after it"

    ticks = _rows(
        database_url,
        "SELECT version, source, wall_ts_ms, created_at FROM price_tick ORDER BY version",
    )
    assert [int(v) for v, _, _, _ in ticks] == list(range(len(ticks)))
    tick_stamps = [int(w) for _, source, w, _ in ticks if source == "tick"]
    assert len(tick_stamps) == len(set(tick_stamps))

    stored = {int(row[0]) for row in _rows(database_url, 'SELECT order_id FROM "order"')}
    acked_ids = [r["order_id"] for r in result["acked"]]
    assert set(acked_ids) <= stored
    # Idempotency: a key retried on B after A committed it answers with A's order, never a
    # second one -- each key is acknowledged once, and the only order stored without an
    # acknowledgement is the one in flight when the stream stopped.
    assert len(set(acked_ids)) == len(acked_ids), "two keys acknowledged the same order"
    assert len(stored) <= len(acked_ids) + 1, (len(stored), len(acked_ids))

    # One writer at a time: A's rows (committed before it exited), then B's, never mixed.
    writers = ["A" if created <= result["a_exited_db"] else "B" for *_, created in ticks]
    assert writers == sorted(writers), writers
    assert writers[-1] == "B"
