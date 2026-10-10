"""A run's export: the snapshot a workbook is built from (Phase 7 SD6, SD8, SD13).

`read_snapshot` reads everything the workbook shows in one `REPEATABLE READ`,
read-only transaction, so the lines, `line_count` and `total_cents` all describe
the same committed orders: an order committed after the snapshot opened is in
none of them (AC23). It is meant for a heavy-read connection (SD11), never the
order path's pool.

SD13's fallbacks for rows a rolled-back image wrote: a line without a bar price
takes its drink's current one, and a drink without a product groups by its
`name_key`.

The worker's queue (PD9) is the `export` rows themselves. `claim_next` takes the
oldest `queued` row and marks it `running`; `finish` writes the file and prunes
the run's manual exports to the three newest completed (SD6 retention; finals
never) in the same transaction; `fail` records the error. Both match only a
`running` row, so a result for a row deleted meanwhile (its run was deleted)
matches nothing and says so. `interrupt_unfinished` is boot's: a `queued` or
`running` row left by a stopped process becomes `failed`, `onderbroken`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import BigInteger, delete, func, select, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import models
from app.db.runs import RunNotFound

INTERRUPTED: Final = "onderbroken"
KEEP_MANUAL: Final = 3


@dataclass(frozen=True)
class SnapshotDrink:
    """A drink of the run, removed ones included, as it is at the snapshot."""

    drink_id: int
    name: str
    product_key: str
    slot: int
    p_min_cents: int  # the bounds at export time (SD8)
    p_max_cents: int


@dataclass(frozen=True)
class SnapshotLine:
    """One order line, joined to its order and its drink's values at the snapshot."""

    ts_ms: int
    order_id: int
    version: int
    drink_id: int
    qty: int
    unit_price_cents: int
    line_total_cents: int
    p_cont: float
    bar_price_cents: int


@dataclass(frozen=True)
class ExportSnapshot:
    run_id: int
    name: str
    t0_ms: int | None  # the first tick's wall time (PD12); a draft has none
    ended_at: datetime | None
    drinks: tuple[SnapshotDrink, ...]
    lines: tuple[SnapshotLine, ...]
    line_count: int
    total_cents: int


def product_key(product_id: int | None, name_key: str) -> str:
    """A drink's analytics key: its product, or its `name_key` without one (SD13, PD14)."""
    return f"product:{product_id}" if product_id is not None else f"name:{name_key}"


async def read_snapshot(conn: AsyncConnection, run_id: int) -> ExportSnapshot:
    """The run's export contents, or `RunNotFound`. `conn` must not be in a transaction."""
    await conn.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
    order, line, drink = models.Order, models.OrderLine, models.Drink
    async with conn.begin():
        run = (
            await conn.execute(
                select(models.Run.name, models.Run.ended_at).where(models.Run.run_id == run_id)
            )
        ).one_or_none()
        if run is None:
            raise RunNotFound(f"no run {run_id}")
        t0_ms = (
            await conn.execute(
                select(models.PriceTick.wall_ts_ms)
                .where(models.PriceTick.run_id == run_id)
                .order_by(models.PriceTick.version)
                .limit(1)
            )
        ).scalar_one_or_none()
        drink_rows = (
            await conn.execute(
                select(
                    drink.drink_id,
                    drink.name,
                    drink.name_key,
                    drink.product_id,
                    drink.slot,
                    drink.p_min_cents,
                    drink.p_max_cents,
                )
                .where(drink.run_id == run_id)
                .order_by(drink.drink_id)
            )
        ).all()
        line_rows = await conn.execute(
            select(
                order.wall_ts_ms,
                order.order_id,
                order.version,
                line.drink_id,
                line.qty,
                line.unit_price_cents,
                line.line_total_cents,
                line.p_cont,
                func.coalesce(line.bar_price_cents, drink.bar_price_cents).label("bar_price"),
            )
            .join(order, order.order_id == line.order_id)
            .join(drink, drink.drink_id == line.drink_id)
            .where(order.run_id == run_id)
            .order_by(order.wall_ts_ms, order.order_id, line.order_line_id)
        )
        lines = tuple(
            SnapshotLine(
                ts_ms=int(row.wall_ts_ms),
                order_id=int(row.order_id),
                version=int(row.version),
                drink_id=int(row.drink_id),
                qty=int(row.qty),
                unit_price_cents=int(row.unit_price_cents),
                line_total_cents=int(row.line_total_cents),
                p_cont=float(row.p_cont),
                bar_price_cents=int(row.bar_price),
            )
            for row in line_rows
        )
        count, total = (
            await conn.execute(
                select(
                    func.count(line.order_line_id),
                    type_coerce(func.coalesce(func.sum(line.line_total_cents), 0), BigInteger),
                )
                .join(order, order.order_id == line.order_id)
                .where(order.run_id == run_id)
            )
        ).one()
    return ExportSnapshot(
        run_id=run_id,
        name=run.name,
        t0_ms=None if t0_ms is None else int(t0_ms),
        ended_at=run.ended_at,
        drinks=tuple(
            SnapshotDrink(
                drink_id=int(row.drink_id),
                name=row.name,
                product_key=product_key(row.product_id, row.name_key),
                slot=int(row.slot),
                p_min_cents=int(row.p_min_cents),
                p_max_cents=int(row.p_max_cents),
            )
            for row in drink_rows
        ),
        lines=lines,
        line_count=int(count),
        total_cents=int(total),
    )


@dataclass(frozen=True)
class ExportJob:
    export_id: int
    run_id: int
    kind: str


async def claim_next(conn: AsyncConnection) -> ExportJob | None:
    """The oldest `queued` export, now `running`; `None` when nothing waits."""
    export = models.Export
    oldest = (
        select(export.export_id)
        .where(export.status == "queued")
        .order_by(export.export_id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    row = (
        await conn.execute(
            update(export)
            .where(export.export_id == oldest)
            .values(status="running", started_at=func.now())
            .returning(export.export_id, export.run_id, export.kind)
        )
    ).one_or_none()
    return None if row is None else ExportJob(int(row.export_id), int(row.run_id), row.kind)


async def finish(
    conn: AsyncConnection, job: ExportJob, *, data: bytes, line_count: int, total_cents: int
) -> bool:
    """Store the built file on the `running` row and prune; `False` if the row is gone."""
    export = models.Export
    result = await conn.execute(
        update(export)
        .where(export.export_id == job.export_id, export.status == "running")
        .values(
            status="done",
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
            line_count=line_count,
            total_cents=total_cents,
            finished_at=func.now(),
        )
    )
    if result.rowcount != 1:
        return False
    await prune_manual(conn, job.run_id)
    return True


async def fail(conn: AsyncConnection, export_id: int, *, error: str) -> bool:
    """Mark the `running` export `failed` with `error`; `False` if the row is gone."""
    export = models.Export
    result = await conn.execute(
        update(export)
        .where(export.export_id == export_id, export.status == "running")
        .values(status="failed", error=error, finished_at=func.now())
    )
    return bool(result.rowcount == 1)


async def prune_manual(conn: AsyncConnection, run_id: int, *, keep: int = KEEP_MANUAL) -> int:
    """Delete the run's completed manual exports beyond the `keep` newest; how many went."""
    export = models.Export
    completed = (export.run_id == run_id, export.kind == "manual", export.status == "done")
    newest = (
        select(export.export_id).where(*completed).order_by(export.export_id.desc()).limit(keep)
    )
    result = await conn.execute(
        delete(export).where(*completed, export.export_id.not_in(newest.scalar_subquery()))
    )
    return int(result.rowcount)


async def interrupt_unfinished(conn: AsyncConnection) -> int:
    """Boot's: every `queued` or `running` export becomes `failed`, `onderbroken` (AC6)."""
    export = models.Export
    result = await conn.execute(
        update(export)
        .where(export.status.in_(("queued", "running")))
        .values(status="failed", error=INTERRUPTED, finished_at=func.now())
    )
    return int(result.rowcount)
