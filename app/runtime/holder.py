"""`MarketHolder`: the one process-wide owner of the live market (Phase 3 SD12, SD22).

Every mutation -- a tick, an order, a jump, a market event, a news item -- goes
through `mutate(op, step)`, in this order:

1. take the lock;
2. `step(view)` computes the candidate with the pure engine and runs **one**
   database transaction, returning an `Outcome`;
3. only after that commit, publish the outcome's view, ticks and earnings to
   memory;
4. release the lock, and log `lock_hold_ms` if it was held over 50 ms (SD22);
5. hand the outcome's domain events to the sink.

If the step raises, nothing is published, the lock is released and the error
propagates; a stale state or a database error becomes 503
`persistence_unavailable` (SD21, plan PD21). The sink is injected (plan PD11):
in production the publisher (T19) turns domain events into messages for the
hub, so this module never imports the hub, and the sink is never called with
the lock held (AC14). Inside the lock there is pure computation and one short
transaction, nothing else.

Time comes from the injected `Clock` (SD32), never from `time`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import AppError
from app.db.engine_state import StaleState
from app.db.news import NewsItem
from app.runtime.clock import Clock
from app.runtime.earnings import DrinkEarnings, EarningsAggregate
from app.runtime.history import HistoryRing, TickEntry
from app.runtime.market_events import ActiveEvent
from app.runtime.rehydrate import RehydratedRun
from exchange import EngineState, MarketSpec

logger = logging.getLogger(__name__)

T = TypeVar("T")

# SD22: a lock held longer than this is logged, naming the operation.
LOCK_HOLD_WARNING_MS = 50


class NoLiveRunError(AppError):
    """There is no live run to mutate (SD16)."""

    status_code = 409
    code = "no_live_run"


class PersistenceUnavailable(AppError):
    """The mutation's transaction failed; memory is exactly as before (SD21)."""

    status_code = 503
    code = "persistence_unavailable"


# --- domain events (PD11): what happened, for the sink, after commit ------------


@dataclass(frozen=True)
class TickCommitted:
    """A committed transition with no order: `tick`, `gap` or `jump`."""

    run_id: int
    entry: TickEntry


@dataclass(frozen=True)
class CommittedLine:
    drink_id: int
    qty: int
    unit_price_cents: int
    line_total_cents: int


@dataclass(frozen=True)
class OrderCommitted:
    """An accepted order; `entry` is its price tick, so it carries the new prices (PD12)."""

    run_id: int
    order_id: int
    lines: tuple[CommittedLine, ...]
    total_cents: int
    earnings_delta: Mapping[int, DrinkEarnings]
    entry: TickEntry


@dataclass(frozen=True)
class NewsChanged:
    run_id: int
    version: int
    op: Literal["add", "delete"]
    item: NewsItem


@dataclass(frozen=True)
class MarketEventStarted:
    run_id: int
    version: int
    event: ActiveEvent


@dataclass(frozen=True)
class MarketEventEnded:
    run_id: int
    version: int
    event: ActiveEvent


DomainEvent = TickCommitted | OrderCommitted | NewsChanged | MarketEventStarted | MarketEventEnded
Sink = Callable[[Sequence[DomainEvent]], None]


# --- the view a step reads, and what it hands back ------------------------------


@dataclass(frozen=True)
class MarketView:
    """The immutable part of the market a step computes from and replaces.

    The ring and the earnings aggregate are not here: a step returns the ticks
    and order lines it committed, and the holder folds them in after commit.
    """

    run_id: int | None
    run_seed: int
    spec: MarketSpec | None
    state: EngineState | None
    drink_ids: tuple[int, ...]
    bar_price_cents: Mapping[int, int]
    last_commit_wall_ms: int | None
    news: tuple[NewsItem, ...]
    market_events: tuple[ActiveEvent, ...]
    quote_grace_versions: int
    candle_interval_ms: int


@dataclass(frozen=True)
class Outcome(Generic[T]):
    """A step's result: what `mutate` returns, the new view, and what to publish after commit.

    `earnings_lines` are `(drink_id, qty, line_total_cents)`, as
    `EarningsAggregate.add_lines` takes them.
    """

    result: T
    view: MarketView
    events: tuple[DomainEvent, ...] = ()
    ticks: tuple[TickEntry, ...] = ()
    earnings_lines: tuple[tuple[int, int, int], ...] = field(default=())


Step = Callable[[MarketView], Awaitable[Outcome[T]]]


class MarketHolder:
    def __init__(
        self,
        view: MarketView,
        *,
        ring: HistoryRing,
        earnings: EarningsAggregate,
        engine: AsyncEngine,
        clock: Clock,
        sink: Sink,
    ) -> None:
        self._view = view
        self._ring = ring
        self._earnings = earnings
        self._engine = engine
        self._clock = clock
        self._sink = sink
        self._lock = asyncio.Lock()

    @classmethod
    def from_rehydrated(
        cls, run: RehydratedRun, *, engine: AsyncEngine, clock: Clock, sink: Sink
    ) -> MarketHolder:
        view = MarketView(
            run_id=run.run_id,
            run_seed=run.run_seed,
            spec=run.spec,
            state=run.state,
            drink_ids=run.drink_ids,
            bar_price_cents=run.bar_price_cents,
            last_commit_wall_ms=run.wall_ts_ms,
            news=run.news,
            market_events=run.market_events,
            quote_grace_versions=run.quote_grace_versions,
            candle_interval_ms=run.candle_interval_ms,
        )
        return cls(
            view, ring=run.ring, earnings=run.earnings, engine=engine, clock=clock, sink=sink
        )

    @classmethod
    def empty(cls, *, engine: AsyncEngine, clock: Clock, sink: Sink) -> MarketHolder:
        """No live run (SD16): readable, and every `mutate` is 409 `no_live_run`."""
        view = MarketView(
            run_id=None,
            run_seed=0,
            spec=None,
            state=None,
            drink_ids=(),
            bar_price_cents={},
            last_commit_wall_ms=None,
            news=(),
            market_events=(),
            quote_grace_versions=0,
            candle_interval_ms=60_000,
        )
        return cls(
            view,
            ring=HistoryRing(0),
            earnings=EarningsAggregate(),
            engine=engine,
            clock=clock,
            sink=sink,
        )

    # --- read-only properties ---------------------------------------------------

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def view(self) -> MarketView:
        return self._view

    @property
    def is_empty(self) -> bool:
        return self._view.run_id is None

    @property
    def run_id(self) -> int | None:
        return self._view.run_id

    @property
    def spec(self) -> MarketSpec | None:
        return self._view.spec

    @property
    def state(self) -> EngineState | None:
        return self._view.state

    @property
    def drink_ids(self) -> tuple[int, ...]:
        return self._view.drink_ids

    @property
    def last_commit_wall_ms(self) -> int | None:
        return self._view.last_commit_wall_ms

    @property
    def news(self) -> tuple[NewsItem, ...]:
        return self._view.news

    @property
    def market_events(self) -> tuple[ActiveEvent, ...]:
        return self._view.market_events

    @property
    def quote_grace_versions(self) -> int:
        return self._view.quote_grace_versions

    @property
    def candle_interval_ms(self) -> int:
        return self._view.candle_interval_ms

    @property
    def ring(self) -> tuple[TickEntry, ...]:
        return self._ring.window()

    @property
    def earnings(self) -> Mapping[int, DrinkEarnings]:
        return self._earnings.snapshot()

    # --- the one mutation path ----------------------------------------------------

    async def mutate(self, op: str, step: Step[T]) -> T:
        """Run `step` under the lock; publish after commit; call the sink after release."""
        async with self._lock:
            started = self._clock.monotonic()
            try:
                if self.is_empty:
                    raise NoLiveRunError("there is no live run")
                outcome = await self._run(op, step)
                self._publish(outcome)
            finally:
                held_ms = round((self._clock.monotonic() - started) * 1000)
                if held_ms > LOCK_HOLD_WARNING_MS:
                    logger.warning("lock_hold_ms", extra={"op": op, "lock_hold_ms": held_ms})
        if outcome.events:
            self._sink(outcome.events)
        return outcome.result

    async def _run(self, op: str, step: Step[T]) -> Outcome[T]:
        before = self._view.state
        try:
            return await step(self._view)
        except StaleState as error:
            logger.error(
                "stale_state",
                extra={"op": op, "memory_version": None if before is None else before.version},
            )
            raise PersistenceUnavailable(
                "the market's state moved underneath this process"
            ) from error
        except (SQLAlchemyError, OSError) as error:
            logger.error("persistence_failed", extra={"op": op, "error": type(error).__name__})
            raise PersistenceUnavailable("the database did not accept the change") from error

    def _publish(self, outcome: Outcome[T]) -> None:
        """Fold a committed outcome into memory. Pure memory: no I/O, no await."""
        for entry in outcome.ticks:
            self._ring.append(entry)
        if outcome.earnings_lines:
            self._earnings.add_lines(outcome.earnings_lines)
        self._view = outcome.view
