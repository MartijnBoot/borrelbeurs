"""AC18 in `check.sh`: a database outage is recovered by a restart policy alone (Phase 8 T14).

The real app (`tests/integration/realapp/harness.py`) talks to the scratch database
through `tests/support/proxy.py`'s `BlackholeProxy`, run on its own event loop thread.
The proxy goes dark -- every socket open, no byte moving -- and the app, unable to
prove it still holds the lock, exits 70. A supervisor loop here restarts it on any
non-zero exit, as `restart: on-failure` would, with exponential backoff capped at
5 s; restarts while the proxy is dark fail on the connect timeout. Then the database
comes back as a restarted Postgres does: every old session gone (`pg_terminate_backend`
-- the dead app's session, blackholed, never saw its client leave and would hold the
lock on), and the proxy moving bytes again. The app must be ready within 60 s with no
command issued to it.
Orders acknowledged before the outage are present. `tests/image/test_kill_drill.py`
is the same drill against the image and a real Postgres restart.
"""

from __future__ import annotations

import asyncio
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.realapp.harness import (
    AppProcess,
    Client,
    free_port,
    mint_key,
    order_until_acked,
    seed_live_run,
    spawn_app,
    start_app,
)
from tests.support.proxy import BlackholeProxy, proxied

# Serial (SD3): starts a real app, and asserts it ready within 60 s.
pytestmark = pytest.mark.serial

READY_AFTER_RESTORE_S = 60.0  # AC18
BACKOFF_CAP_S = 5.0

T = TypeVar("T")


class _ProxyThread:
    """`BlackholeProxy` on a loop of its own, so a synchronous test can drive it."""

    def __init__(self, database_url: str) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.proxy: BlackholeProxy
        self.proxy, self.url = self._call(proxied(database_url))

    def _call(self, coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)

    def go_dark(self) -> None:
        self.loop.call_soon_threadsafe(self.proxy.blackhole)

    def restore(self) -> None:
        self.loop.call_soon_threadsafe(setattr, self.proxy, "silent", False)

    def close(self) -> None:
        self._call(self.proxy.close())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)
        self.loop.close()


@pytest.fixture
def proxy(database_url: str) -> Iterator[_ProxyThread]:
    running = _ProxyThread(database_url)
    try:
        yield running
    finally:
        running.close()


def _ready(app: AppProcess) -> bool:
    try:
        with urllib.request.urlopen(f"{app.base}/readyz", timeout=2) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


async def _end_other_sessions(url: str) -> None:
    """What a Postgres restart does to this database's sessions: ends them all."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
    finally:
        await engine.dispose()


async def _order_ids(url: str) -> set[int]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            return {int(r[0]) for r in await conn.execute(text('SELECT order_id FROM "order"'))}
    finally:
        await engine.dispose()


def test_a_database_outage_is_recovered_by_restarting_the_app(
    database_url: str, proxy: _ProxyThread, tmp_path: Path
) -> None:
    seed_live_run(database_url)
    key = mint_key(database_url, "bar")
    stderr = tmp_path / "app.stderr"
    port = free_port()
    app = start_app(proxy.url, stderr)
    exits: list[int] = []
    try:
        client = Client(app.base)
        client.login(key)
        acked = [order_until_acked(client, f"db-restart-{k}") for k in range(3)]
        assert all(r is not None for r in acked)

        proxy.go_dark()
        exits.append(app.wait(timeout=30))
        assert exits == [70], app.stderr()

        # The supervisor: restart on a non-zero exit, backoff doubling up to 5 s. One
        # restart fails while the proxy is still dark, then the database comes back.
        backoff = 0.5
        restored_at: float | None = None
        app = spawn_app(proxy.url, stderr, port=port)
        while not _ready(app):
            if restored_at is not None:
                assert time.monotonic() - restored_at < READY_AFTER_RESTORE_S, app.stderr()
            if app.proc.poll() is not None:
                exits.append(app.wait(timeout=5))  # and cancels its watchdog timer
                if restored_at is None:
                    asyncio.run(_end_other_sessions(database_url))
                    proxy.restore()
                    restored_at = time.monotonic()
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP_S)
                app = spawn_app(proxy.url, stderr, port=port)
            time.sleep(0.1)
        assert restored_at is not None
        print(f"ready {time.monotonic() - restored_at:.1f} s after the database came back")
    finally:
        if app.proc.poll() is None:
            app.kill()

    assert all(code != 0 for code in exits), exits
    stored = asyncio.run(_order_ids(database_url))
    assert {r["order_id"] for r in acked if r is not None} <= stored
