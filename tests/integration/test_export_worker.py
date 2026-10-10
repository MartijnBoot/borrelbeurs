"""The export worker (Phase 7 T11: AC1, AC7, AC24; SD6; PD9, R13).

A close is run in-process on a booted runtime, as `test_close_in_process.py`
does, and the worker builds the final export it queues. Orders are inserted
straight into `"order"` and `order_line`: the export reads nothing else, and
rehydrate only sums them. The queue rules are driven through `build_next`
directly, without a runtime. Builds run in the real `BuildProcess` except where
a test monkeypatches the build, which only reaches a build in this process.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import multiprocessing
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, TypeVar

import openpyxl
import pytest
from fastapi import FastAPI
from sqlalchemy import insert, make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import app.db.exports as exports
import app.jobs.export_xlsx as export_xlsx
from app.core.config import Settings, get_settings
from app.db import models
from app.db.exports import ExportSnapshot
from app.db.runs import add_drink, create_draft_run, delete_run, go_live
from app.db.session import create_engine
from app.jobs.export_xlsx import BuildProcess, BuiltExport, build_export, build_next
from app.runtime.boot import start_runtime
from app.runtime.close import close_in_process
from exchange import Params
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000

T = TypeVar("T")


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _settings(settings: Settings, url: str) -> Settings:
    return settings.model_copy(update={"database_url": url})


def _with_engine(settings: Settings, url: str, body: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def scenario() -> T:
        engine = create_engine(_settings(settings, url))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


class InThread:
    """`BuildProcess`'s contract in a thread of this process, so a monkeypatch reaches
    the build. The real process is exercised by the close, failure and pruning tests."""

    async def build(self, settings: Settings, run_id: int, generated_at_ms: int) -> BuiltExport:
        return await asyncio.to_thread(build_export, settings, run_id, generated_at_ms)

    def close(self) -> None:
        pass


async def _run_with_orders(engine: AsyncEngine, *, live: bool, orders: int = 5) -> int:
    """A run of one drink holding `orders` one-line orders; live, or ended."""
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Vrijmibo", params=Params(step_quant=0.1), run_seed=7
        )
        drink_id = await add_drink(
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
    async with engine.begin() as conn:
        await _orders(conn, run_id, int(drink_id), orders)
        if not live:
            await conn.execute(
                text("UPDATE run SET status = 'ended', ended_at = now() WHERE run_id = :r"),
                {"r": run_id},
            )
    return run_id


async def _orders(conn: AsyncConnection, run_id: int, drink_id: int, count: int) -> None:
    for i in range(count):
        order_id = (
            await conn.execute(
                insert(models.Order).returning(models.Order.order_id),
                {
                    "run_id": run_id,
                    "idempotency_key": f"k-worker-{run_id}-{i}",
                    "version": 1_000 + i,
                    "wall_ts_ms": T0 + 500 + i,
                },
            )
        ).scalar_one()
        price = 250 + i
        await conn.execute(
            insert(models.OrderLine),
            {
                "order_id": order_id,
                "drink_id": drink_id,
                "qty": 2,
                "unit_price_cents": price,
                "line_total_cents": 2 * price,
                "p_cont": price / 100,
                "bar_price_cents": 260,
            },
        )


async def _exports(engine: AsyncEngine, run_id: int) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT export_id, kind, status, error, data, sha256, bytes, line_count,"
                " total_cents FROM export WHERE run_id = :r ORDER BY export_id"
            ),
            {"r": run_id},
        )
        return [dict(row._mapping) for row in rows]


async def _ledger(engine: AsyncEngine, run_id: int) -> tuple[int, int]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT coalesce(sum(l.line_total_cents), 0), count(*) FROM order_line l"
                    ' JOIN "order" o USING (order_id) WHERE o.run_id = :r'
                ),
                {"r": run_id},
            )
        ).one()
    return int(row[0]), int(row[1])


async def _settled(engine: AsyncEngine, run_id: int) -> list[dict[str, Any]]:
    """The run's exports once none is `queued` or `running` (bounded, so a hang fails)."""
    for _ in range(400):
        exports = await _exports(engine, run_id)
        if exports and all(e["status"] in {"done", "failed"} for e in exports):
            return exports
        await asyncio.sleep(0.025)
    raise AssertionError(f"exports never settled: {await _exports(engine, run_id)}")


async def _queue(engine: AsyncEngine, run_id: int, kind: str, *, count: int = 1) -> None:
    async with engine.begin() as conn:
        for _ in range(count):
            await conn.execute(
                insert(models.Export).values(
                    run_id=run_id, kind=kind, status="queued", requested_by="t"
                )
            )


def test_a_close_builds_its_final_export_equal_to_the_database(on: str, settings: Settings) -> None:
    """AC1: the close queues the final export and wakes the worker, which builds it."""

    async def scenario() -> tuple[list[dict[str, Any]], tuple[int, int]]:
        engine = create_engine(_settings(settings, on))
        try:
            run_id = await _run_with_orders(engine, live=True)
            app = FastAPI()
            app.state.clock = clock = FakeClock(T0 + 1_000)  # `create_app` sets it in production
            async with start_runtime(
                app, _settings(settings, on), clock=clock, run_migrations=False
            ):
                await close_in_process(app.state, run_id, confirm_name="Vrijmibo", author="t")
                exports = await _settled(engine, run_id)
            return exports, await _ledger(engine, run_id)
        finally:
            await engine.dispose()

    exports, (total, count) = asyncio.run(scenario())

    (final,) = exports
    assert (final["kind"], final["status"], final["error"]) == ("final", "done", None)
    assert (final["total_cents"], final["line_count"]) == (total, count) == (2 * 1260, 5)
    assert final["bytes"] == len(final["data"])
    assert final["sha256"] == hashlib.sha256(final["data"]).hexdigest()
    book = openpyxl.load_workbook(io.BytesIO(final["data"]))
    assert book.sheetnames == ["Sales", "Per drink", "Summary"]


def test_a_failed_build_is_recorded_and_the_next_request_builds(
    on: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC7: the export is `failed` with its error, the run stays ended, a new one builds."""
    real = export_xlsx.build_workbook

    def broken(snapshot: ExportSnapshot, *, generated_at_ms: int) -> bytes:
        raise RuntimeError("disk full, somehow")

    monkeypatch.setattr(export_xlsx, "build_workbook", broken)
    monkeypatch.setattr(export_xlsx, "BuildProcess", InThread)

    async def scenario() -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        engine = create_engine(_settings(settings, on))
        try:
            run_id = await _run_with_orders(engine, live=True)
            app = FastAPI()
            app.state.clock = clock = FakeClock(T0 + 1_000)
            async with start_runtime(
                app, _settings(settings, on), clock=clock, run_migrations=False
            ):
                await close_in_process(app.state, run_id, confirm_name="Vrijmibo", author="t")
                failed = await _settled(engine, run_id)
                monkeypatch.setattr(export_xlsx, "build_workbook", real)
                await _queue(engine, run_id, "manual")
                app.state.export_wakeup.set()
                again = await _settled(engine, run_id)
            async with engine.connect() as conn:
                status: str = (
                    await conn.execute(
                        text("SELECT status FROM run WHERE run_id = :r"), {"r": run_id}
                    )
                ).scalar_one()
            return failed, again, str(status)
        finally:
            await engine.dispose()

    failed, again, status = asyncio.run(scenario())

    assert [(e["kind"], e["status"]) for e in failed] == [("final", "failed")]
    assert failed[0]["error"] == "RuntimeError: disk full, somehow"
    assert failed[0]["data"] is None
    assert status == "ended"
    assert [(e["kind"], e["status"]) for e in again] == [("final", "failed"), ("manual", "done")]


def test_a_failure_in_the_build_process_comes_back_as_its_error(
    settings: Settings, database_url: str
) -> None:
    """AC7 across the process boundary: the child's error is recorded, nothing raised here."""
    nowhere = (
        make_url(database_url)
        .set(database="bb_no_such_database")
        .render_as_string(hide_password=False)
    )

    async def body(engine: AsyncEngine) -> list[dict[str, Any]]:
        run_id = await _run_with_orders(engine, live=False)
        await _queue(engine, run_id, "manual")
        process = BuildProcess()
        try:
            assert await build_next(
                engine=engine,
                builder=process,
                settings=_settings(settings, nowhere),
                clock=FakeClock(T0),
            )
        finally:
            process.close()
        return await _exports(engine, run_id)

    (export,) = _with_engine(settings, database_url, body)

    assert export["status"] == "failed"
    assert export["error"].startswith("DBAPIError: "), export["error"]
    assert '"bb_no_such_database" does not exist' in export["error"]
    assert export["data"] is None


def test_a_build_process_killed_mid_build_fails_its_export_and_the_next_builds(
    settings: Settings, database_url: str
) -> None:
    """AC7: a child killed mid-build (out of memory, say) is a recorded failure, not a
    worker waiting forever on a result that will never come; the next build runs."""
    url_settings = _settings(settings, database_url)

    async def until_blocked(engine: AsyncEngine) -> None:
        for _ in range(600):
            async with engine.connect() as conn:
                waiting: int = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity"
                            " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                        )
                    )
                ).scalar_one()
            if waiting:
                return
            await asyncio.sleep(0.1)
        raise AssertionError("the build never reached the locked table")

    async def body(engine: AsyncEngine) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        run_id = await _run_with_orders(engine, live=False)
        await _queue(engine, run_id, "manual")
        process = BuildProcess()
        try:
            async with engine.connect() as blocker:
                # The build's snapshot read waits on this lock, so the kill lands mid-build.
                await blocker.execute(text("LOCK TABLE order_line IN ACCESS EXCLUSIVE MODE"))
                building = asyncio.create_task(
                    build_next(
                        engine=engine, builder=process, settings=url_settings, clock=FakeClock(T0)
                    )
                )
                await until_blocked(engine)
                for child in multiprocessing.active_children():
                    child.kill()
                assert await asyncio.wait_for(building, 30)
                await blocker.rollback()
            (killed,) = await _exports(engine, run_id)
            await _queue(engine, run_id, "manual")
            assert await asyncio.wait_for(
                build_next(
                    engine=engine, builder=process, settings=url_settings, clock=FakeClock(T0)
                ),
                60,
            )
            return killed, await _exports(engine, run_id)
        finally:
            process.close()

    killed, after = _with_engine(settings, database_url, body)

    assert killed["status"] == "failed"
    assert killed["error"].startswith("BrokenProcessPool: "), killed["error"]
    assert [e["status"] for e in after] == ["failed", "done"]


def test_a_result_that_cannot_be_written_fails_its_export(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC7: the build succeeded but writing it did not; the export is `failed`, not left
    `running` for every later request of the run to coalesce onto."""

    async def unwritable(*args: Any, **kwargs: Any) -> bool:
        raise OSError("injected: result too large to write")

    monkeypatch.setattr(export_xlsx, "finish", unwritable)

    async def body(engine: AsyncEngine) -> list[dict[str, Any]]:
        run_id = await _run_with_orders(engine, live=False)
        await _queue(engine, run_id, "manual")
        assert await build_next(
            engine=engine,
            builder=InThread(),
            settings=_settings(settings, database_url),
            clock=FakeClock(T0),
        )
        return await _exports(engine, run_id)

    (export,) = _with_engine(settings, database_url, body)

    assert export["status"] == "failed"
    assert export["error"] == "OSError: injected: result too large to write"
    assert export["data"] is None


def test_a_fourth_manual_export_prunes_the_oldest_and_finals_stay(
    settings: Settings, database_url: str
) -> None:
    """AC24, SD6 retention: three manual exports kept per run; final exports never pruned."""

    async def body(engine: AsyncEngine) -> tuple[list[Any], list[Any]]:
        run_id = await _run_with_orders(engine, live=False)
        other = await _run_with_orders(engine, live=False)
        await _queue(engine, run_id, "final", count=2)
        await _queue(engine, run_id, "manual", count=4)
        await _queue(engine, other, "manual")
        process = BuildProcess()
        try:
            while await build_next(
                engine=engine,
                builder=process,
                settings=_settings(settings, database_url),
                clock=FakeClock(T0),
            ):
                pass
        finally:
            process.close()
        return await _exports(engine, run_id), await _exports(engine, other)

    exports, others = _with_engine(settings, database_url, body)

    assert [(e["kind"], e["status"]) for e in exports] == [
        ("final", "done"),
        ("final", "done"),
        ("manual", "done"),
        ("manual", "done"),
        ("manual", "done"),
    ]
    ids = [e["export_id"] for e in exports]
    assert ids[2] == ids[1] + 2  # the first manual one (ids[1] + 1) is the one pruned
    assert [(e["kind"], e["status"]) for e in others] == [("manual", "done")]


def test_a_run_deleted_during_its_build_drops_the_result(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R13, PD9: the result `UPDATE` matches no row; the worker logs it and goes on."""
    real = exports.read_snapshot
    scoped = _settings(settings, database_url)
    deleted: list[int] = []

    async def read_then_delete(conn: AsyncConnection, read_id: int) -> ExportSnapshot:
        snapshot = await real(conn, read_id)
        if not deleted:
            # The build's thread runs its own loop, so it needs its own engine.
            engine = create_engine(scoped)
            try:
                await delete_run(engine, read_id, confirm_name="Vrijmibo")
            finally:
                await engine.dispose()
            deleted.append(read_id)
        return snapshot

    monkeypatch.setattr(export_xlsx, "read_snapshot", read_then_delete)

    async def body(engine: AsyncEngine) -> tuple[bool, bool, int, str]:
        run_id = await _run_with_orders(engine, live=False)
        next_run = await _run_with_orders(engine, live=False)
        await _queue(engine, run_id, "manual")
        await _queue(engine, next_run, "manual")
        builder, clock = InThread(), FakeClock(T0)
        first = await build_next(engine=engine, builder=builder, settings=scoped, clock=clock)
        second = await build_next(engine=engine, builder=builder, settings=scoped, clock=clock)
        assert deleted == [run_id]
        (after,) = await _exports(engine, next_run)
        return first, second, len(await _exports(engine, run_id)), after["status"]

    assert _with_engine(settings, database_url, body) == (True, True, 0, "done")
