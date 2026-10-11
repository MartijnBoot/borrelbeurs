"""Exports on the host, and the 15-minute auto export (Phase 8 T8: SD14, AC21; PD6, PD7).

The worker runs in this process on a `FakeClock`, with `EXPORT_DIR` a `tmp_path` and
the build in a thread (`InThread`, as `test_export_worker.py` does) so nothing here
waits for a spawned process. Queued rows are inserted directly, as the API would.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db import models
from app.db.exports import get_export
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.jobs.export_xlsx import (
    AUTO_EXPORT_INTERVAL_MS,
    BuiltExport,
    build_export,
    run_worker,
)
from app.jobs.naming import host_filename
from exchange import Params
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
NAME = "Vrijmibo"


class InThread:
    async def build(self, settings: Settings, run_id: int, generated_at_ms: int) -> BuiltExport:
        return await asyncio.to_thread(build_export, settings, run_id, generated_at_ms)

    def close(self) -> None:
        pass


class Worker:
    def __init__(
        self, engine: AsyncEngine, clock: FakeClock, wakeup: asyncio.Event, *, timed: bool
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.wakeup = wakeup
        # With an `EXPORT_DIR` the idle worker also sleeps on the clock (the auto export).
        self.sleepers = 1 if timed else 0

    async def idle(self) -> None:
        """Until the worker sleeps again with nothing queued or running."""
        for _ in range(1_000):
            await asyncio.sleep(0.02)
            if self.clock.sleepers == self.sleepers and not await self._pending():
                await asyncio.sleep(0.05)
                if self.clock.sleepers == self.sleepers:
                    return
        raise AssertionError("the worker never went idle")

    async def _pending(self) -> bool:
        async with self.engine.connect() as conn:
            count: int = (
                await conn.execute(
                    text("SELECT count(*) FROM export WHERE status IN ('queued', 'running')")
                )
            ).scalar_one()
        return bool(count)

    async def advance(self, ms: int) -> None:
        self.clock.advance(ms)
        await self.idle()

    async def queue(self, run_id: int, kind: str) -> int:
        async with self.engine.begin() as conn:
            export_id = (
                await conn.execute(
                    insert(models.Export)
                    .values(run_id=run_id, kind=kind, status="queued", requested_by="t")
                    .returning(models.Export.export_id)
                )
            ).scalar_one()
        return int(export_id)


@asynccontextmanager
async def _worker(
    settings: Settings, url: str, export_dir: Path | None
) -> AsyncIterator[tuple[Worker, AsyncEngine]]:
    scoped = settings.model_copy(update={"database_url": url, "export_dir": export_dir})
    engine = create_engine(scoped)
    clock = FakeClock(T0)
    wakeup = asyncio.Event()
    task = asyncio.create_task(
        run_worker(engine=engine, settings=scoped, clock=clock, wakeup=wakeup, builder=InThread())
    )
    worker = Worker(engine, clock, wakeup, timed=export_dir is not None)
    try:
        await worker.idle()
        yield worker, engine
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


async def _run(engine: AsyncEngine, *, live: bool) -> int:
    async with engine.begin() as conn:
        run_id = await create_draft_run(conn, name=NAME, params=Params(step_quant=0.1), run_seed=7)
        await add_drink(
            conn,
            run_id,
            name="Bier",
            slot=0,
            p_min_cents=150,
            p0_cents=260,
            p_max_cents=500,
            a=1.0,
            d=0.1,
            s0=1.0,
            c=0.1,
            bar_price_cents=260,
        )
    await go_live(engine, run_id, now_ms=T0)
    if not live:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE run SET status = 'ended', ended_at = now() WHERE run_id = :r"),
                {"r": run_id},
            )
    return run_id


def _files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def _scenario(body: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(body())


def test_a_manual_and_a_final_export_each_land_on_the_host(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    exports = tmp_path / "exports"

    async def body() -> None:
        async with _worker(settings, database_url, exports) as (worker, engine):
            run_id = await _run(engine, live=False)
            names = []
            for kind in ("manual", "final"):
                export_id = await worker.queue(run_id, kind)
                worker.wakeup.set()
                await worker.idle()
                async with engine.connect() as conn:
                    row = await get_export(conn, export_id)
                assert row.status == "done"
                names.append(host_filename(NAME, run_id, row.created_at_ms, kind))
                assert (exports / names[-1]).read_bytes()[:2] == b"PK"
            assert _files(exports) == sorted(names)

    _scenario(body)


def test_fifteen_minutes_of_a_live_run_write_one_auto_export_and_no_row(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    async def body() -> None:
        async with _worker(settings, database_url, tmp_path) as (worker, engine):
            run_id = await _run(engine, live=True)
            await worker.advance(AUTO_EXPORT_INTERVAL_MS - 1)
            assert _files(tmp_path) == []
            await worker.advance(1)
            stamp_ms = worker.clock.wall_ms()
            assert _files(tmp_path) == [host_filename(NAME, run_id, stamp_ms, "auto")]
            async with engine.connect() as conn:
                rows = (await conn.execute(select(models.Export.export_id))).all()
            assert rows == []

    _scenario(body)


def test_a_queued_export_at_the_due_time_skips_the_auto_export(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    """PD6: an auto export never starts ahead of a queued one; skipped, not deferred."""

    async def body() -> None:
        async with _worker(settings, database_url, tmp_path) as (worker, engine):
            run_id = await _run(engine, live=True)
            await worker.queue(run_id, "manual")  # queued, the worker not woken
            await worker.advance(AUTO_EXPORT_INTERVAL_MS)
            files = _files(tmp_path)
            assert [f for f in files if f.endswith("-auto.xlsx")] == []
            assert len([f for f in files if f.endswith("-manual.xlsx")]) == 1
            # The next one is due 15 minutes later, and then nothing is queued.
            await worker.advance(AUTO_EXPORT_INTERVAL_MS)
            assert len([f for f in _files(tmp_path) if f.endswith("-auto.xlsx")]) == 1

    _scenario(body)


def test_nine_auto_exports_leave_the_newest_eight(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    async def body() -> None:
        async with _worker(settings, database_url, tmp_path) as (worker, engine):
            run_id = await _run(engine, live=True)
            stamps = []
            for _ in range(9):
                await worker.advance(AUTO_EXPORT_INTERVAL_MS)
                stamps.append(worker.clock.wall_ms())
            assert _files(tmp_path) == sorted(
                host_filename(NAME, run_id, ms, "auto") for ms in stamps[1:]
            )

    _scenario(body)


def test_without_a_live_run_there_is_no_auto_export(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    async def body() -> None:
        async with _worker(settings, database_url, tmp_path) as (worker, engine):
            await _run(engine, live=False)
            await worker.advance(AUTO_EXPORT_INTERVAL_MS)
            assert _files(tmp_path) == []

    _scenario(body)


def test_without_an_export_dir_nothing_reaches_the_host(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    """Identical to before Phase 8: the export is built into its row, and that is all."""

    async def body() -> None:
        async with _worker(settings, database_url, None) as (worker, engine):
            run_id = await _run(engine, live=True)
            export_id = await worker.queue(run_id, "manual")
            worker.wakeup.set()
            await worker.idle()
            async with engine.connect() as conn:
                assert (await get_export(conn, export_id)).status == "done"
            await worker.advance(AUTO_EXPORT_INTERVAL_MS)
            assert _files(tmp_path) == []

    _scenario(body)


def test_a_failed_host_write_leaves_the_export_done(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    """The database copy is the one that counts (ADR 0004): a full disk on the host is
    logged as `export_host_write_failed`, never a failed export."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_bytes(b"a file where the folder should be")

    async def body() -> None:
        async with _worker(settings, database_url, blocked) as (worker, engine):
            run_id = await _run(engine, live=False)
            export_id = await worker.queue(run_id, "manual")
            worker.wakeup.set()
            await worker.idle()
            async with engine.connect() as conn:
                assert (await get_export(conn, export_id)).status == "done"

    _scenario(body)


def test_a_failed_auto_export_is_its_own_event_and_the_worker_carries_on(
    settings: Settings,
    database_url: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A full disk is `auto_export_failed`, not `export_worker_failed` (the database)."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_bytes(b"a file where the folder should be")

    async def body() -> None:
        async with _worker(settings, database_url, blocked) as (worker, engine):
            run_id = await _run(engine, live=True)
            await worker.advance(AUTO_EXPORT_INTERVAL_MS)
            export_id = await worker.queue(run_id, "manual")
            worker.wakeup.set()
            await worker.idle()
            async with engine.connect() as conn:
                assert (await get_export(conn, export_id)).status == "done"

    with caplog.at_level("ERROR"):
        _scenario(body)

    messages = [record.getMessage() for record in caplog.records]
    assert "auto_export_failed" in messages
    assert "export_worker_failed" not in messages
