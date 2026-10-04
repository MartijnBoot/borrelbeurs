"""The ticker: one writer of time, on a monotonic grid with wall-clock stamps (Phase 3 SD13, SD14).

At start, and at every re-anchor, it records an anchor pair `(wall_ms,
monotonic)`. Slot `k` fires at `monotonic_anchor + k * interval` and is stamped
`wall_anchor + k * interval` -- or with the last commit's time if an order or a
jump committed later than that, so stamps never go back. Every slot is one
`holder.mutate("tick", ...)`: `advance(orders=None)` and a `tick` row, even
when no price moved (Phase 2 SD10/SD11: one row per accepted transition, never
deduplicated). After a slot, any active market event whose `t_end_ms` has
passed is ended in a second mutate, which emits `MarketEventEnded` (SD23, AC19).

**Lag.** Missed slots whose total lag is within the catch-up budget run back to
back, each with its own stamp. Beyond the budget -- or when wall and monotonic
time diverge by more than it (a clock change) -- the ticker re-anchors and
applies the gap rule to the live state as one `gap` mutate: the state's anchors
and the active events' start and end move by the same `gap_shift_ms`, with no
`advance` across the gap (Phase 2 SD2, AC19a).

**A failed commit (SD14)** is logged with the version and the slot skipped:
memory keeps the last committed state and the next slot computes from it. It
is never retried. The exception is a failed `gap`: the grid still re-anchors,
but the next slot is a `gap` again rather than a `tick`, so no `advance` ever
runs across an uncommitted gap (AC18a).

**No live run (SD16):** the ticker idles on the grid, mutating nothing.

Time is the injected `Clock` only (SD32). `last_iteration_monotonic` is when an
iteration last completed (committed, failed or idle), for `/healthz` (SD15).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.db.codec import tick_prices
from app.db.engine_state import compare_and_set, insert_tick, save_transition
from app.db.market_events import end_event, shift_active_events
from app.runtime.clock import Clock
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS, apply_gap_rule, gap_shift_ms
from app.runtime.history import TickEntry
from app.runtime.holder import (
    MarketEventEnded,
    MarketHolder,
    MarketView,
    Outcome,
    PersistenceUnavailable,
    Step,
    TickCommitted,
)
from app.runtime.market_events import shift_events
from exchange import advance

logger = logging.getLogger(__name__)


class Ticker:
    def __init__(
        self,
        holder: MarketHolder,
        *,
        clock: Clock,
        interval_ms: int,
        budget_ms: int = DEFAULT_CATCH_UP_BUDGET_MS,
    ) -> None:
        if interval_ms <= 0:
            raise ValueError(f"tick interval must be positive, got {interval_ms} ms")
        self._holder = holder
        self._clock = clock
        self._interval_ms = interval_ms
        self._budget_ms = budget_ms
        self._wall_anchor = 0
        self._mono_anchor = 0.0
        self._k = 0
        self._gap_pending = False
        self._stopping = False
        self._busy = False
        self._task: asyncio.Task[None] | None = None
        self.last_iteration_monotonic: float | None = None

    @property
    def last_commit_wall_ms(self) -> int | None:
        return self._holder.last_commit_wall_ms

    @property
    def busy(self) -> bool:
        """Whether a slot is being computed and committed right now."""
        return self._busy

    def start(self) -> asyncio.Task[None]:
        self._task = asyncio.get_running_loop().create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Stop after the current iteration: a slot in progress commits; a sleep is cut short."""
        self._stopping = True
        task = self._task
        if task is None or task.done():
            return
        if not self._busy:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def run(self) -> None:
        self._anchor()
        while not self._stopping:
            due = self._mono_anchor + (self._k + 1) * self._interval_ms / 1000
            await self._clock.sleep_until(due)
            if self._stopping:
                return
            self._busy = True
            try:
                await self._iterate(due)
            finally:
                self._busy = False
            self.last_iteration_monotonic = self._clock.monotonic()

    def _anchor(self) -> None:
        self._wall_anchor = self._clock.wall_ms()
        self._mono_anchor = self._clock.monotonic()
        self._k = 0

    async def _iterate(self, due: float) -> None:
        if self._holder.is_empty:
            self._k += 1
            return
        now_mono = self._clock.monotonic()
        now_wall = self._clock.wall_ms()
        lag_ms = (now_mono - due) * 1000
        drift_ms = abs((now_wall - self._wall_anchor) - (now_mono - self._mono_anchor) * 1000)
        if self._gap_pending or lag_ms > self._budget_ms or drift_ms > self._budget_ms:
            self._gap_pending = not await self._guarded("gap", self._gap_step(now_wall))
            self._anchor()
            return
        while self._mono_anchor + (self._k + 1) * self._interval_ms / 1000 <= now_mono:
            self._k += 1
            stamp = self._wall_anchor + self._k * self._interval_ms
            if await self._guarded("tick", self._tick_step(stamp)):
                await self._end_due_events(stamp)
            if self._stopping:
                return

    async def _guarded(self, op: str, step: Step[Any]) -> bool:
        """One mutate; a failed commit is logged and skipped (SD14). Whether it committed."""
        version = None if self._holder.state is None else self._holder.state.version
        try:
            await self._holder.mutate(op, step)
        except PersistenceUnavailable:
            logger.error("tick_commit_failed", extra={"op": op, "version": version})
            return False
        return True

    def _tick_step(self, grid_ms: int) -> Callable[[MarketView], Awaitable[Outcome[int]]]:
        holder = self._holder

        async def step(view: MarketView) -> Outcome[int]:
            assert view.run_id is not None and view.spec is not None and view.state is not None
            # Never before the commit this tick follows: an order or a jump that took
            # the lock between slots is stamped with the wall clock, which can be ahead
            # of the grid (catch-up, small drift). A stamp going back would reopen the
            # previous candle (SD25).
            now_ms = max(grid_ms, view.last_commit_wall_ms or grid_ms)
            candidate = advance(view.spec, view.state, now_ms=now_ms, run_seed=view.run_seed).state
            await save_transition(
                holder.engine,
                run_id=view.run_id,
                expected_version=view.state.version,
                state=candidate,
                spec=view.spec,
                drink_ids=view.drink_ids,
                source="tick",
                wall_ts_ms=now_ms,
            )
            entry = TickEntry(
                version=candidate.version,
                wall_ts_ms=now_ms,
                source="tick",
                prices=tick_prices(view.spec, candidate, view.drink_ids),
            )
            return Outcome(
                result=candidate.version,
                view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
                events=(TickCommitted(run_id=view.run_id, entry=entry),),
                ticks=(entry,),
            )

        return step

    def _gap_step(self, now_ms: int) -> Callable[[MarketView], Awaitable[Outcome[int | None]]]:
        holder = self._holder
        budget_ms = self._budget_ms

        async def step(view: MarketView) -> Outcome[int | None]:
            assert view.run_id is not None and view.spec is not None and view.state is not None
            assert view.last_commit_wall_ms is not None
            gap = {
                "last_wall_ts_ms": view.last_commit_wall_ms,
                "now_ms": now_ms,
                "budget_ms": budget_ms,
            }
            shifted = apply_gap_rule(view.state, **gap)
            shift_ms = gap_shift_ms(**gap)
            if shifted is None or shift_ms is None:
                return Outcome(result=None, view=view)  # a clock that went backwards
            async with holder.engine.begin() as conn:
                await compare_and_set(
                    conn,
                    run_id=view.run_id,
                    expected_version=view.state.version,
                    state=shifted,
                    drink_ids=view.drink_ids,
                    wall_ts_ms=now_ms,
                )
                await insert_tick(
                    conn,
                    run_id=view.run_id,
                    state=shifted,
                    spec=view.spec,
                    drink_ids=view.drink_ids,
                    source="gap",
                    wall_ts_ms=now_ms,
                )
                await shift_active_events(conn, view.run_id, shift_ms)
            entry = TickEntry(
                version=shifted.version,
                wall_ts_ms=now_ms,
                source="gap",
                prices=tick_prices(view.spec, shifted, view.drink_ids),
            )
            return Outcome(
                result=shifted.version,
                view=dataclasses.replace(
                    view,
                    state=shifted,
                    last_commit_wall_ms=now_ms,
                    market_events=shift_events(view.market_events, shift_ms),
                ),
                events=(TickCommitted(run_id=view.run_id, entry=entry),),
                ticks=(entry,),
            )

        return step

    async def _end_due_events(self, now_ms: int) -> None:
        if not any(e.t_end_ms <= now_ms for e in self._holder.market_events):
            return
        holder = self._holder

        async def step(view: MarketView) -> Outcome[int]:
            assert view.run_id is not None and view.state is not None
            due = tuple(e for e in view.market_events if e.t_end_ms <= now_ms)
            async with holder.engine.begin() as conn:
                for event in due:
                    await end_event(conn, event.event_id, t_end_ms=event.t_end_ms)
            return Outcome(
                result=len(due),
                view=dataclasses.replace(
                    view, market_events=tuple(e for e in view.market_events if e not in due)
                ),
                events=tuple(
                    MarketEventEnded(run_id=view.run_id, version=view.state.version, event=e)
                    for e in due
                ),
            )

        await self._guarded("event_end", step)
