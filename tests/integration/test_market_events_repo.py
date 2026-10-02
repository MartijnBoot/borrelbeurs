"""The market-event repository (Phase 3 T12: SD23 persist)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db.market_events import active_events, end_event, insert_event, shift_active_events
from app.db.runs import create_draft_run
from app.db.session import create_engine
from app.runtime.market_events import ActiveEvent
from exchange import Params

T = TypeVar("T")


def _transaction(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _run(conn: AsyncConnection) -> int:
    return await create_draft_run(conn, params=Params(step_quant=0.1), run_seed=7)


def test_an_inserted_event_is_active_with_its_fields(settings: Settings, database_url: str) -> None:
    async def body(conn: AsyncConnection) -> tuple[int, tuple[ActiveEvent, ...]]:
        run_id = await _run(conn)
        event_id = await insert_event(
            conn,
            run_id=run_id,
            kind="crash",
            drink_ids=(3, 1, 2),
            t_start_ms=1_000,
            t_end_ms=31_000,
        )
        return event_id, await active_events(conn, run_id)

    event_id, active = _transaction(settings, database_url, body)

    assert active == (
        ActiveEvent(
            event_id=event_id, kind="crash", drink_ids=(3, 1, 2), t_start_ms=1_000, t_end_ms=31_000
        ),
    )


def test_ending_an_event_rewrites_its_end_and_removes_it_from_active(
    settings: Settings, database_url: str
) -> None:
    async def body(conn: AsyncConnection) -> tuple[tuple[ActiveEvent, ...], tuple[int, bool]]:
        run_id = await _run(conn)
        first = await insert_event(
            conn, run_id=run_id, kind="crash", drink_ids=(1,), t_start_ms=1_000, t_end_ms=31_000
        )
        await insert_event(
            conn, run_id=run_id, kind="bubble", drink_ids=(1,), t_start_ms=5_000, t_end_ms=9_000
        )
        await end_event(conn, first, t_end_ms=4_000)
        row = (
            await conn.execute(
                text("SELECT t_end_ms, ended_at IS NOT NULL FROM market_event WHERE event_id = :e"),
                {"e": first},
            )
        ).one()
        return await active_events(conn, run_id), (int(row[0]), bool(row[1]))

    active, ended = _transaction(settings, database_url, body)

    assert [e.kind for e in active] == ["bubble"]
    assert ended == (4_000, True)


@pytest.mark.parametrize("case", ["unknown", "already-ended"])
def test_ending_an_unknown_or_ended_event_raises(
    settings: Settings, database_url: str, case: str
) -> None:
    async def body(conn: AsyncConnection) -> None:
        run_id = await _run(conn)
        event_id = await insert_event(
            conn, run_id=run_id, kind="crash", drink_ids=(1,), t_start_ms=1_000, t_end_ms=2_000
        )
        if case == "already-ended":
            await end_event(conn, event_id, t_end_ms=2_000)
        await end_event(conn, event_id if case == "already-ended" else 999_999, t_end_ms=2_000)

    with pytest.raises(LookupError, match="no active market event"):
        _transaction(settings, database_url, body)


def test_shift_moves_only_this_runs_active_events(settings: Settings, database_url: str) -> None:
    async def body(conn: AsyncConnection) -> tuple[int, list[tuple[int, int]]]:
        run_id = await _run(conn)
        other = await _run(conn)
        ended = await insert_event(
            conn, run_id=run_id, kind="crash", drink_ids=(1,), t_start_ms=1_000, t_end_ms=2_000
        )
        await end_event(conn, ended, t_end_ms=2_000)
        await insert_event(
            conn, run_id=run_id, kind="bubble", drink_ids=(1,), t_start_ms=3_000, t_end_ms=4_000
        )
        await insert_event(
            conn, run_id=other, kind="correction", drink_ids=(1,), t_start_ms=5_000, t_end_ms=6_000
        )
        moved = await shift_active_events(conn, run_id, 100_000)
        rows = await conn.execute(
            text("SELECT t_start_ms, t_end_ms FROM market_event ORDER BY event_id")
        )
        return moved, [(int(row[0]), int(row[1])) for row in rows]

    moved, rows = _transaction(settings, database_url, body)

    assert moved == 1
    assert rows == [(1_000, 2_000), (103_000, 104_000), (5_000, 6_000)]


def test_active_events_are_in_event_id_order(settings: Settings, database_url: str) -> None:
    async def body(conn: AsyncConnection) -> list[str]:
        run_id = await _run(conn)
        for kind in ("bubble", "crash", "correction"):
            await insert_event(
                conn, run_id=run_id, kind=kind, drink_ids=(1,), t_start_ms=1, t_end_ms=2
            )
        return [e.kind for e in await active_events(conn, run_id)]

    assert _transaction(settings, database_url, body) == ["bubble", "crash", "correction"]
