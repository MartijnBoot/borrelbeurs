"""The `market_event` repository (Phase 3 SD23).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, so starting an event composes the event row, the
jumps' state, the `jump` tick and the news item into one unit (AC27), and the
gap write composes the event shift with the state and its `gap` tick (AC19a).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import MarketEvent
from app.runtime.market_events import ActiveEvent, EventKind


async def insert_event(
    conn: AsyncConnection,
    *,
    run_id: int,
    kind: EventKind,
    drink_ids: Sequence[int],
    t_start_ms: int,
    t_end_ms: int,
) -> int:
    result = await conn.execute(
        insert(MarketEvent)
        .values(
            run_id=run_id,
            kind=kind,
            drink_ids=list(drink_ids),
            t_start_ms=t_start_ms,
            t_end_ms=t_end_ms,
        )
        .returning(MarketEvent.event_id)
    )
    return int(result.scalar_one())


async def end_event(conn: AsyncConnection, event_id: int, *, t_end_ms: int) -> None:
    """End an active event at `t_end_ms` (rewritten), or `LookupError` if none is active."""
    result = await conn.execute(
        update(MarketEvent)
        .where(MarketEvent.event_id == event_id, MarketEvent.ended_at.is_(None))
        .values(t_end_ms=t_end_ms, ended_at=func.now())
        .returning(MarketEvent.event_id)
    )
    if result.scalar_one_or_none() is None:
        raise LookupError(f"no active market event {event_id}")


async def end_open_events(conn: AsyncConnection, run_id: int) -> int:
    """End every event of `run_id` still open, as a close does (Phase 7 SD2); rows ended."""
    result = await conn.execute(
        update(MarketEvent)
        .where(MarketEvent.run_id == run_id, MarketEvent.ended_at.is_(None))
        .values(ended_at=func.now())
        .returning(MarketEvent.event_id)
    )
    return len(result.all())


async def active_events(conn: AsyncConnection, run_id: int) -> tuple[ActiveEvent, ...]:
    """The run's events not yet ended, oldest first."""
    result = await conn.execute(
        select(
            MarketEvent.event_id,
            MarketEvent.kind,
            MarketEvent.drink_ids,
            MarketEvent.t_start_ms,
            MarketEvent.t_end_ms,
        )
        .where(MarketEvent.run_id == run_id, MarketEvent.ended_at.is_(None))
        .order_by(MarketEvent.event_id)
    )
    return tuple(
        ActiveEvent(
            event_id=int(row.event_id),
            kind=cast(EventKind, row.kind),
            drink_ids=tuple(int(d) for d in row.drink_ids),
            t_start_ms=int(row.t_start_ms),
            t_end_ms=int(row.t_end_ms),
        )
        for row in result
    )


async def shift_active_events(conn: AsyncConnection, run_id: int, shift_ms: int) -> int:
    """Move every active event's start and end by `shift_ms` (the gap rule's); rows moved."""
    result = await conn.execute(
        update(MarketEvent)
        .where(MarketEvent.run_id == run_id, MarketEvent.ended_at.is_(None))
        .values(
            t_start_ms=MarketEvent.t_start_ms + shift_ms,
            t_end_ms=MarketEvent.t_end_ms + shift_ms,
        )
        .returning(MarketEvent.event_id)
    )
    return len(result.all())
