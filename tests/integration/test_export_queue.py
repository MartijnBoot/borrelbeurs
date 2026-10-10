"""A manual export request's rule (Phase 7 T12: AC20; SD6; PD8).

`request_export` is driven straight against the database, with no worker, so
every export stays where the test put it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db import models
from app.db.exports import ExportBusy, ExportRow, request_export
from app.db.runs import RunNotFound, close_run, create_draft_run
from app.db.session import create_engine
from exchange import Params

T0 = 1_759_312_800_000

T = TypeVar("T")


def _with_engine(settings: Settings, url: str, body: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _runs(engine: AsyncEngine, count: int) -> list[int]:
    async with engine.begin() as conn:
        return [
            await create_draft_run(
                conn, name=f"Borrel {i}", params=Params(step_quant=0.1), run_seed=i
            )
            for i in range(count)
        ]


async def _request(engine: AsyncEngine, run_id: int) -> ExportRow:
    async with engine.begin() as conn:
        return await request_export(conn, run_id, requested_by="Bestuur")


async def _set_status(engine: AsyncEngine, export_id: int, status: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE export SET status = :s WHERE export_id = :e"),
            {"s": status, "e": export_id},
        )


async def _statuses(conn: AsyncConnection) -> list[tuple[int, str, str]]:
    rows = await conn.execute(text("SELECT run_id, kind, status FROM export ORDER BY export_id"))
    return [(int(r[0]), r[1], r[2]) for r in rows]


def test_the_same_run_twice_is_one_export(settings: Settings, database_url: str) -> None:
    """AC20: a request for a run with a queued or running export returns that export."""

    async def body(engine: AsyncEngine) -> tuple[ExportRow, ExportRow, ExportRow]:
        (run_id,) = await _runs(engine, 1)
        first = await _request(engine, run_id)
        again = await _request(engine, run_id)
        await _set_status(engine, first.export_id, "running")
        running = await _request(engine, run_id)
        return first, again, running

    first, again, running = _with_engine(settings, database_url, body)

    assert (first.kind, first.status, first.requested_by) == ("manual", "queued", "Bestuur")
    assert again == first
    assert (running.export_id, running.status) == (first.export_id, "running")


def test_a_runs_queued_final_export_is_returned_too(settings: Settings, database_url: str) -> None:
    """PD8: the run's own in-flight export of either kind answers the request."""

    async def body(engine: AsyncEngine) -> tuple[int, ExportRow]:
        (run_id,) = await _runs(engine, 1)
        async with engine.begin() as conn:
            final = (
                await conn.execute(
                    insert(models.Export)
                    .values(run_id=run_id, kind="final", status="queued", requested_by="t")
                    .returning(models.Export.export_id)
                )
            ).scalar_one()
        return int(final), await _request(engine, run_id)

    final, returned = _with_engine(settings, database_url, body)

    assert (returned.export_id, returned.kind) == (final, "final")


def test_one_runs_one_waits_and_a_third_is_busy(settings: Settings, database_url: str) -> None:
    """AC20: another run queues while the slot is free; with it taken, `ExportBusy`."""

    async def body(engine: AsyncEngine) -> tuple[list[ExportRow], list[tuple[int, str, str]]]:
        a, b, c = await _runs(engine, 3)
        first = await _request(engine, a)
        await _set_status(engine, first.export_id, "running")
        second = await _request(engine, b)
        with pytest.raises(ExportBusy):
            await _request(engine, c)
        async with engine.connect() as conn:
            before = await _statuses(conn)
        await _set_status(engine, first.export_id, "failed")  # "done" would need its data
        third = await _request(engine, c)  # the slot moved up
        return [first, second, third], before

    (first, second, third), before = _with_engine(settings, database_url, body)

    assert [e.status for e in (second, third)] == ["queued", "queued"]
    assert [(kind, status) for _, kind, status in before] == [
        ("manual", "running"),
        ("manual", "queued"),
    ]
    assert len({first.export_id, second.export_id, third.export_id}) == 3


def test_concurrent_requests_for_one_run_make_one_export(
    settings: Settings, database_url: str
) -> None:
    """PD8's table lock: requests racing for one run see each other, never two free slots."""

    async def body(engine: AsyncEngine) -> tuple[set[int], int]:
        (run_id,) = await _runs(engine, 1)
        rows = await asyncio.gather(*(_request(engine, run_id) for _ in range(8)))
        async with engine.connect() as conn:
            count: int = (await conn.execute(text("SELECT count(*) FROM export"))).scalar_one()
        return {row.export_id for row in rows}, int(count)

    ids, count = _with_engine(settings, database_url, body)

    assert len(ids) == 1
    assert count == 1


def test_concurrent_requests_for_many_runs_fill_two_slots(
    settings: Settings, database_url: str
) -> None:
    """PD8: eight runs racing get exactly two exports; the other six are busy."""

    async def body(engine: AsyncEngine) -> tuple[int, int]:
        runs = await _runs(engine, 8)
        results = await asyncio.gather(
            *(_request(engine, run_id) for run_id in runs), return_exceptions=True
        )
        busy = [r for r in results if isinstance(r, ExportBusy)]
        assert all(isinstance(r, ExportRow | ExportBusy) for r in results), results
        async with engine.connect() as conn:
            count: int = (await conn.execute(text("SELECT count(*) FROM export"))).scalar_one()
        return len(busy), int(count)

    assert _with_engine(settings, database_url, body) == (6, 2)


def test_a_close_while_the_slot_is_full_still_queues_its_final_export(
    settings: Settings, database_url: str
) -> None:
    """AC20, SD6: a final export is never refused."""

    async def body(engine: AsyncEngine) -> list[tuple[int, str, str]]:
        live, a, b = await _runs(engine, 3)
        first = await _request(engine, a)
        await _set_status(engine, first.export_id, "running")
        await _request(engine, b)
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE run SET status = 'live' WHERE run_id = :r"), {"r": live}
            )
            await close_run(conn, live, ended_at_ms=T0, requested_by="Bestuur")
        async with engine.connect() as conn:
            return await _statuses(conn)

    statuses = _with_engine(settings, database_url, body)

    assert [(kind, status) for _, kind, status in statuses] == [
        ("manual", "running"),
        ("manual", "queued"),
        ("final", "queued"),
    ]


def test_an_unknown_run_is_run_not_found_with_nothing_written(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: AsyncEngine) -> int:
        with pytest.raises(RunNotFound):
            await _request(engine, 999_999)
        async with engine.connect() as conn:
            return int((await conn.execute(text("SELECT count(*) FROM export"))).scalar_one())

    assert _with_engine(settings, database_url, body) == 0
