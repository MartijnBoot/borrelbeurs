"""The xlsx export (Phase 7 SD6, SD8, SD15): a snapshot in, a workbook's bytes out.

`build_workbook` is pure: no clock (the generated-at stamp, which is also the
file's creation date, is passed in), no database, no file -- `xlsxwriter` writes
into a `BytesIO` in its `in_memory` mode. Three sheets, v1-shaped and extended:

- `Sales`: one row per order line, SD8's column order. `ts_iso` is UTC (SD15).
  `drink`, `p_min` and `p_max` are the drink's values at export time.
- `Per drink`: per product, removed drinks included; named after its newest
  drink in the run.
- `Summary`: label and value rows, as v1's.

Euros are `Decimal(cents) / 100` written with the `0.00` format; every total is
summed in integer cents first, never from the written numbers. Data text goes
through `write_string`, so a drink named `=1+1` stays text, not a formula.

**The worker** (PD9) is one task, `run_worker`, started by boot. It drains the
queue (`app/db/exports.py`), then sleeps on `wakeup`, which a close (and, from
T12, a request) sets; the event is cleared *before* each drain, so a set during
a build is never lost. Per export, `build_export` reads the snapshot on a
heavy-read engine and builds the workbook **in a separate process**
(`BuildProcess`); only the finished bytes cross back, and the result is written
on the main engine (the heavy engine is read-only, SD11). A thread was not
enough: AC21's timing test measured a 20 000-line build in `asyncio.to_thread`
holding the GIL long enough to take the p95 order latency from 29 ms to 933 ms
(R16; the process was chosen on 2026-10-10). A failed build records its error
and leaves the run as it is (AC7). Cancelling the worker terminates the
process, so shutdown waits for no build (SD6).
"""

from __future__ import annotations

import asyncio
import io
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Protocol

import xlsxwriter
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.exports import ExportSnapshot, claim_next, fail, finish, read_snapshot
from app.db.session import create_heavy_read_engine
from app.runtime.clock import Clock

logger = logging.getLogger(__name__)

SALES_HEADERS: Final = (
    "ts_iso",
    "ts_ms",
    "drink",
    "qty",
    "unit_price",
    "total_price",
    "p_cont",
    "p_min",
    "p_max",
    "order_id",
    "drink_id",
    "bar_price",
    "version",
)
PER_DRINK_HEADERS: Final = ("drink", "qty", "revenue", "bar_price_total", "avg_price")


def euros(cents: int) -> Decimal:
    return Decimal(cents) / 100


def utc(ms: int) -> datetime:
    """`ms` since the epoch as an aware UTC datetime, exactly (no float division)."""
    return datetime.fromtimestamp(ms // 1000, tz=UTC) + timedelta(milliseconds=ms % 1000)


def iso_utc(ms: int) -> str:
    return utc(ms).isoformat(timespec="milliseconds")


@dataclass
class _ProductTotal:
    name: str
    qty: int = 0
    revenue_cents: int = 0
    bar_price_cents: int = 0


def _per_product(snapshot: ExportSnapshot) -> list[_ProductTotal]:
    """Per product in the order its first drink was added; the newest drink names it."""
    totals: dict[str, _ProductTotal] = {}
    key_of: dict[int, str] = {}
    for drink in sorted(snapshot.drinks, key=lambda d: d.drink_id):
        key_of[drink.drink_id] = drink.product_key
        totals.setdefault(drink.product_key, _ProductTotal(drink.name)).name = drink.name
    for line in snapshot.lines:
        total = totals[key_of[line.drink_id]]
        total.qty += line.qty
        total.revenue_cents += line.line_total_cents
        total.bar_price_cents += line.qty * line.bar_price_cents
    return list(totals.values())


def build_workbook(snapshot: ExportSnapshot, *, generated_at_ms: int) -> bytes:
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True})
    book.set_properties({"title": snapshot.name, "created": utc(generated_at_ms)})
    money = book.add_format({"num_format": "0.00"})
    bold = book.add_format({"bold": True})
    drinks = {drink.drink_id: drink for drink in snapshot.drinks}

    sales = book.add_worksheet("Sales")
    sales.write_row(0, 0, SALES_HEADERS, bold)
    sales.set_column(0, 0, 26)
    sales.set_column(2, 2, 20)
    for row, line in enumerate(snapshot.lines, start=1):
        drink = drinks[line.drink_id]
        sales.write_string(row, 0, iso_utc(line.ts_ms))
        sales.write_number(row, 1, line.ts_ms)
        sales.write_string(row, 2, drink.name)
        sales.write_number(row, 3, line.qty)
        sales.write_number(row, 4, euros(line.unit_price_cents), money)
        sales.write_number(row, 5, euros(line.line_total_cents), money)
        sales.write_number(row, 6, line.p_cont)
        sales.write_number(row, 7, euros(drink.p_min_cents), money)
        sales.write_number(row, 8, euros(drink.p_max_cents), money)
        sales.write_number(row, 9, line.order_id)
        sales.write_number(row, 10, line.drink_id)
        sales.write_number(row, 11, euros(line.bar_price_cents), money)
        sales.write_number(row, 12, line.version)

    per_drink = book.add_worksheet("Per drink")
    per_drink.write_row(0, 0, PER_DRINK_HEADERS, bold)
    per_drink.set_column(0, 0, 20)
    products = _per_product(snapshot)
    for row, product in enumerate(products, start=1):
        per_drink.write_string(row, 0, product.name)
        per_drink.write_number(row, 1, product.qty)
        per_drink.write_number(row, 2, euros(product.revenue_cents), money)
        per_drink.write_number(row, 3, euros(product.bar_price_cents), money)
        if product.qty:
            average = (Decimal(product.revenue_cents) / product.qty).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
            per_drink.write_number(row, 4, average / 100, money)

    summary = book.add_worksheet("Summary")
    summary.set_column(0, 0, 18)
    summary.set_column(1, 1, 30)
    revenue_cents = sum(line.line_total_cents for line in snapshot.lines)
    rows: list[tuple[str, str | int | Decimal | None]] = [
        ("run", snapshot.name),
        ("started", None if snapshot.t0_ms is None else iso_utc(snapshot.t0_ms)),
        (
            "ended",
            None
            if snapshot.ended_at is None
            else snapshot.ended_at.astimezone(UTC).isoformat(timespec="milliseconds"),
        ),
        ("total_revenue", euros(revenue_cents)),
        ("total_qty", sum(line.qty for line in snapshot.lines)),
        ("bar_price_total", euros(sum(p.bar_price_cents for p in products))),
        ("line_count", len(snapshot.lines)),
        ("generated_at", iso_utc(generated_at_ms)),
    ]
    for row, (label, value) in enumerate(rows):
        summary.write_string(row, 0, label, bold)
        if isinstance(value, str):
            summary.write_string(row, 1, value)
        elif isinstance(value, Decimal):
            summary.write_number(row, 1, value, money)
        elif value is not None:
            summary.write_number(row, 1, value)

    book.close()
    return buffer.getvalue()


@dataclass(frozen=True)
class BuiltExport:
    data: bytes
    line_count: int
    total_cents: int


def build_export(settings: Settings, run_id: int, generated_at_ms: int) -> BuiltExport:
    """Read the run's snapshot and build its workbook; blocking, in the build process."""

    async def read() -> ExportSnapshot:
        heavy_engine = create_heavy_read_engine(settings)
        try:
            async with heavy_engine.connect() as conn:
                return await read_snapshot(conn, run_id)
        finally:
            await heavy_engine.dispose()

    snapshot = asyncio.run(read())
    return BuiltExport(
        data=build_workbook(snapshot, generated_at_ms=generated_at_ms),
        line_count=snapshot.line_count,
        total_cents=snapshot.total_cents,
    )


def _build_or_error(settings: Settings, run_id: int, generated_at_ms: int) -> BuiltExport | str:
    """`build_export`, with a failure turned into its message: an exception raised in
    the child may not unpickle in the parent, and a string always does."""
    try:
        return build_export(settings, run_id, generated_at_ms)
    except Exception as error:
        return f"{type(error).__name__}: {error}"


class Builder(Protocol):
    async def build(self, settings: Settings, run_id: int, generated_at_ms: int) -> BuiltExport:
        """The built export, or an exception naming why it could not be built."""
        ...


class BuildFailed(Exception):
    """The build process reported a failure; the message is the child's."""


class BuildProcess:
    """Builds in one spawned process (R16): its own GIL, so neither decoding the
    snapshot nor writing the workbook can hold the event loop's.

    The process starts on the first build, not at boot, and is kept for the
    next. A process that dies mid-build (out of memory, say) fails that build
    with `BrokenProcessPool`, and the next build starts a new one (AC7). `close`
    kills it, so shutdown waits for no build (SD6).
    """

    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None

    async def build(self, settings: Settings, run_id: int, generated_at_ms: int) -> BuiltExport:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        loop = asyncio.get_running_loop()
        try:
            built = await loop.run_in_executor(
                self._pool, _build_or_error, settings, run_id, generated_at_ms
            )
        except BrokenProcessPool:
            self.close()
            raise
        if isinstance(built, str):
            raise BuildFailed(built)
        return built

    def close(self) -> None:
        if self._pool is not None:
            # Python 3.14's `terminate_workers`; until then, the executor's own map.
            for process in list(self._pool._processes.values()):
                process.kill()
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None


async def build_next(
    *, engine: AsyncEngine, builder: Builder, settings: Settings, clock: Clock
) -> bool:
    """Build the oldest queued export, if any; whether there was one."""
    async with engine.begin() as conn:
        job = await claim_next(conn)
    if job is None:
        return False
    log = {"export_id": job.export_id, "run_id": job.run_id, "kind": job.kind}
    logger.info("export_started", extra=log)
    try:
        built = await builder.build(settings, job.run_id, clock.wall_ms())
    except Exception as error:
        message = (
            str(error) if isinstance(error, BuildFailed) else f"{type(error).__name__}: {error}"
        )
        logger.error("export_failed", extra={**log, "error": message})
        async with engine.begin() as conn:
            recorded = await fail(conn, job.export_id, error=message)
    else:
        try:
            async with engine.begin() as conn:
                recorded = await finish(
                    conn,
                    job,
                    data=built.data,
                    line_count=built.line_count,
                    total_cents=built.total_cents,
                )
        except Exception as error:
            # Left `running`, every later request of the run would coalesce onto it.
            message = f"{type(error).__name__}: {error}"
            logger.error("export_failed", extra={**log, "error": message})
            async with engine.begin() as conn:
                recorded = await fail(conn, job.export_id, error=message)
        else:
            if recorded:
                logger.info("export_done", extra={**log, "bytes": len(built.data)})
    if not recorded:
        logger.warning("export_dropped", extra=log)
    return True


async def run_worker(
    *,
    engine: AsyncEngine,
    settings: Settings,
    clock: Clock,
    wakeup: asyncio.Event,
    builder: Builder | None = None,
) -> None:
    """Drain the queue, then sleep until `wakeup`; forever, until cancelled.

    Without a `builder` it owns a `BuildProcess`, terminated when it is cancelled.
    """
    process = BuildProcess()
    try:
        while True:
            wakeup.clear()
            try:
                while await build_next(
                    engine=engine, builder=builder or process, settings=settings, clock=clock
                ):
                    pass
            except Exception:
                # The database itself failed; the rows stay as they are until the next wake-up.
                logger.exception("export_worker_failed")
            await wakeup.wait()
    finally:
        process.close()
