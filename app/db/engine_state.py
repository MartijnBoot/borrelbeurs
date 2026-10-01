"""Engine-state persistence: load, compare-and-set save, and the tick window.

`save_transition` is the one write path for an accepted transition (SD9,
SD10). In one transaction it moves `engine_state` from `expected_version` to
`state` -- the version check is in the `UPDATE`'s `WHERE`, never a prior
`SELECT` -- and inserts that version's `price_tick`. Under Postgres' default
READ COMMITTED a concurrent writer blocks on the row lock, re-reads the row,
finds the version moved and matches nothing, so it raises `StaleState` and
writes no tick.

The `json` columns are written and read as text (`CAST(... AS json)`,
`::text`), so the codec's text is stored and returned exactly as written
(PD7).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import JSON, Text, cast, func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import AppError
from app.db import models
from app.db.codec import EncodedState, decode_state, encode_state, tick_prices
from app.runtime.history import TickEntry
from exchange import EngineState, MarketSpec

_JSON_COLUMNS = ("y", "cum_orders", "flow_ema", "last_order_ts", "jumps")
_INT_COLUMNS = ("last_idle_ms", "last_bm_ms", "rng_counter", "version", "tick_index", "t_round")


class StaleState(AppError):
    """The stored engine state is no longer at the version the caller read (SD9)."""

    status_code = 409
    code = "stale_state"


def _row_values(encoded: EncodedState, wall_ts_ms: int) -> dict[str, Any]:
    return {
        **{name: cast(literal(getattr(encoded, name), Text), JSON) for name in _JSON_COLUMNS},
        **{name: getattr(encoded, name) for name in _INT_COLUMNS},
        "wall_ts_ms": wall_ts_ms,
    }


async def insert_tick(
    conn: AsyncConnection,
    *,
    run_id: int,
    state: EngineState,
    spec: MarketSpec,
    drink_ids: Sequence[int],
    source: str,
    wall_ts_ms: int,
) -> None:
    """The `price_tick` of `state`, at `state.version`."""
    await conn.execute(
        insert(models.PriceTick).values(
            run_id=run_id,
            version=state.version,
            source=source,
            prices={str(k): v for k, v in tick_prices(spec, state, drink_ids).items()},
            wall_ts_ms=wall_ts_ms,
        )
    )


async def insert_state(
    conn: AsyncConnection,
    *,
    run_id: int,
    state: EngineState,
    drink_ids: Sequence[int],
    wall_ts_ms: int,
) -> None:
    """The run's first `engine_state` row; go-live writes it."""
    await conn.execute(
        insert(models.EngineState).values(
            run_id=run_id, **_row_values(encode_state(state, drink_ids), wall_ts_ms)
        )
    )


async def load_state(
    conn: AsyncConnection, run_id: int, drink_ids: Sequence[int]
) -> tuple[EngineState, int] | None:
    """The stored state in `drink_ids` order and its `wall_ts_ms`, or `None` if never live."""
    table = models.EngineState
    row = (
        await conn.execute(
            select(
                *(cast(getattr(table, name), Text).label(name) for name in _JSON_COLUMNS),
                *(getattr(table, name) for name in _INT_COLUMNS),
                table.wall_ts_ms,
            ).where(table.run_id == run_id)
        )
    ).one_or_none()
    if row is None:
        return None
    values = row._asdict()
    wall_ts_ms = int(values.pop("wall_ts_ms"))
    return decode_state(EncodedState(**values), drink_ids), wall_ts_ms


async def compare_and_set(
    conn: AsyncConnection,
    *,
    run_id: int,
    expected_version: int,
    state: EngineState,
    drink_ids: Sequence[int],
    wall_ts_ms: int,
) -> None:
    """Move `engine_state` from `expected_version` to `state`, or raise `StaleState`."""
    table = models.EngineState
    result = await conn.execute(
        update(table)
        .where(table.run_id == run_id, table.version == expected_version)
        .values(**_row_values(encode_state(state, drink_ids), wall_ts_ms), updated_at=func.now())
    )
    if result.rowcount != 1:
        raise StaleState(
            f"run {run_id}'s engine state is not at version {expected_version}; reload it"
        )


async def save_transition(
    engine: AsyncEngine,
    *,
    run_id: int,
    expected_version: int,
    state: EngineState,
    spec: MarketSpec,
    drink_ids: Sequence[int],
    source: str,
    wall_ts_ms: int,
) -> None:
    """Compare-and-set `engine_state` and insert the tick, in one transaction, or `StaleState`."""
    async with engine.begin() as conn:
        await compare_and_set(
            conn,
            run_id=run_id,
            expected_version=expected_version,
            state=state,
            drink_ids=drink_ids,
            wall_ts_ms=wall_ts_ms,
        )
        await insert_tick(
            conn,
            run_id=run_id,
            state=state,
            spec=spec,
            drink_ids=drink_ids,
            source=source,
            wall_ts_ms=wall_ts_ms,
        )


async def load_ticks_in_window(
    conn: AsyncConnection, run_id: int, window_ms: int
) -> list[TickEntry]:
    """Ticks within `window_ms` of the highest version's wall time, ordered by version."""
    tick = models.PriceTick
    latest = (
        select(tick.wall_ts_ms)
        .where(tick.run_id == run_id)
        .order_by(tick.version.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await conn.execute(
        select(tick.version, tick.wall_ts_ms, tick.source, tick.prices)
        .where(tick.run_id == run_id, tick.wall_ts_ms >= latest - window_ms)
        .order_by(tick.version)
    )
    return [
        TickEntry(
            version=row.version,
            wall_ts_ms=row.wall_ts_ms,
            source=row.source,
            prices={
                int(drink_id): {key: float(value) for key, value in prices.items()}
                for drink_id, prices in row.prices.items()
            },
        )
        for row in result
    ]
