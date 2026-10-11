"""A cancelled boot waits for a running migration (Phase 8 review of T6).

`asyncio.to_thread` cannot interrupt its thread: cancelling the `await` leaves Alembic
running. A standby cancelled by SIGTERM mid-migration must not release the advisory lock
until that thread is done, or a second instance could migrate beside it.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

import app.runtime.boot as boot
from app.db.schema_compat import Decision


class _Conn:
    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def test_a_cancelled_migrate_returns_only_after_the_migration_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release_thread, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_upgrade() -> None:
        started.set()
        release_thread.wait(5)
        finished.set()

    async def state(conn: object) -> Any:
        return SimpleNamespace(db_revision="0010", min_code_revision=None)

    monkeypatch.setattr(boot, "upgrade_to_head", slow_upgrade)
    monkeypatch.setattr(boot, "read_db_state", state)
    monkeypatch.setattr(boot, "known_revisions", lambda: frozenset({"0010", "0011"}))
    monkeypatch.setattr(boot, "decide", lambda *_: Decision.MIGRATE)
    engine: Any = SimpleNamespace(connect=_Conn)

    async def scenario() -> None:
        task = asyncio.ensure_future(boot.migrate(engine))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.1)
        assert not task.done(), "migrate returned while its thread still ran"

        release_thread.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(scenario())
