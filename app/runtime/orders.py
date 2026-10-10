"""The order domain: one order, judged and charged under the holder's lock (SD17-SD21).

`place_order` is one `holder.mutate("order", ...)`. Inside the lock, in order:

1. **Idempotency (SD20).** The stored key is checked before any price is read.
   A match whose body is the same -- the receipt's `quote_version` and the set
   of `(drink_id, qty, unit_price_cents)` (plan PD6) -- replays the stored
   receipt and changes nothing; any difference is 422 `idempotency_key_reused`.
2. **Domain checks (SD17).** `quote_version` ahead of the current version, a
   drink that is not a drink of the live run, or a drink named twice, is 422
   `invalid_request`. A drink removed from the live run (Phase 6 SD13) is 422
   `drink_unavailable`, decided from the in-memory mask.
3. **The grace rule (SD18)** against the live `price_cents` (`cents_from_quantised`
   of `p_q`, SD24). A rejection is 409 `price_changed` with the current version
   and every line's live price; nothing is charged, written or moved.
4. `advance(orders=qty_vector)` on the live state: the engine moves on the
   ordered quantities, whatever the honoured price (SD19).
5. `write_order` in one transaction: the state, the order, its lines at the
   charged (= quoted) prices, the receipt and the price tick.
6. The receipt, built from what was written, and `OrderCommitted`.

The receipt is one model, `Receipt`. The first response and every replay are
`Receipt.model_validate(stored).model_dump_json()`, so a replay is
byte-identical even though `jsonb` reorders keys (plan PD7).

A unique violation on the key at commit -- another writer won the race -- is
re-read and replayed (SD20). Any other failure leaves memory as it was and
surfaces as 503 `persistence_unavailable` through the holder (SD21).

**No live run (Phase 7 SD2).** An order that committed before a close is still
replayed after it: on `no_live_run` the key is looked up once more, outside
the lock -- a closed run's orders no longer change -- and only a key with no
stored order is 409 `no_live_run`. A bar whose first answer was lost would
otherwise be told its booked order was refused.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.errors import AppError
from app.db.codec import tick_prices
from app.db.mapping import cents_from_quantised
from app.db.orders import OrderLineInput, StoredOrder, find_order_by_key, write_order
from app.runtime.clock import Clock
from app.runtime.earnings import DrinkEarnings
from app.runtime.grace import PriceChanged, QuotedLine, judge, step_cents_from
from app.runtime.history import TickEntry
from app.runtime.holder import (
    CommittedLine,
    MarketHolder,
    MarketView,
    NoLiveRunError,
    OrderCommitted,
    Outcome,
    PersistenceUnavailable,
)
from exchange import advance

_UNIQUE_KEY = "order_idempotency_key_key"


class InvalidOrder(AppError):
    status_code = 422
    code = "invalid_request"


class DrinkUnavailable(AppError):
    """An order line names a drink removed from the live run (Phase 6 SD13)."""

    status_code = 422
    code = "drink_unavailable"


class PriceChangedError(AppError):
    status_code = 409
    code = "price_changed"


class IdempotencyKeyReused(AppError):
    status_code = 422
    code = "idempotency_key_reused"


class ReceiptLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    drink_id: int
    qty: int
    unit_price_cents: int
    line_total_cents: int


class Receipt(BaseModel):
    """SD19's receipt, plus `quote_version` (PD6), exactly as returned and replayed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: int
    version: int
    wall_ts_ms: int
    quote_version: int
    lines: Annotated[list[ReceiptLine], Field(min_length=1)]
    total_cents: int

    def body(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


@dataclass(frozen=True)
class OrderRequest:
    idempotency_key: str
    quote_version: int
    lines: tuple[QuotedLine, ...]


@dataclass(frozen=True)
class PlacedOrder:
    receipt: Receipt
    body: bytes
    replay: bool


def _signature(
    lines: Sequence[QuotedLine] | Sequence[ReceiptLine],
) -> frozenset[tuple[int, int, int]]:
    return frozenset((line.drink_id, line.qty, line.unit_price_cents) for line in lines)


def _replay(stored: StoredOrder, request: OrderRequest) -> PlacedOrder:
    """The stored receipt if `request` is the same order (PD6), else `IdempotencyKeyReused`."""
    reused = IdempotencyKeyReused("this Idempotency-Key was already used for a different order")
    if stored.response is None:
        raise reused
    try:
        receipt = Receipt.model_validate(stored.response)
    except ValidationError:
        raise reused from None
    if receipt.quote_version != request.quote_version or _signature(receipt.lines) != _signature(
        request.lines
    ):
        raise reused
    return PlacedOrder(receipt=receipt, body=receipt.body(), replay=True)


async def place_order(
    holder: MarketHolder, request: OrderRequest, *, actor_key_id: int | None, clock: Clock
) -> PlacedOrder:
    """Judge, charge and record one order, or raise; see the module docstring.

    `now_ms` is read from `clock` inside the lock, so an order is never stamped
    before a tick that committed while it waited.
    """
    engine = holder.engine

    async def step(view: MarketView) -> Outcome[PlacedOrder]:
        assert view.run_id is not None and view.spec is not None and view.state is not None
        async with engine.connect() as conn:
            stored = await find_order_by_key(conn, request.idempotency_key)
        if stored is not None:
            return Outcome(result=_replay(stored, request), view=view)

        state, spec, drink_ids = view.state, view.spec, view.drink_ids
        if request.quote_version > state.version:
            raise InvalidOrder(
                f"quote_version {request.quote_version} is ahead of version {state.version}"
            )
        named = [line.drink_id for line in request.lines]
        if not named or len(set(named)) != len(named):
            raise InvalidOrder("an order names each drink once, and at least one")
        unknown = sorted(set(named) - set(drink_ids))
        if unknown:
            raise InvalidOrder(f"not a drink of the live run: {unknown}")
        removed = sorted(d for d in named if not spec.active[drink_ids.index(d)])
        if removed:
            raise DrinkUnavailable(f"removed from the live run: {removed}")
        if any(line.qty < 1 for line in request.lines):
            raise InvalidOrder("every qty must be at least 1")

        prices = tick_prices(spec, state, drink_ids)
        live_cents = {d: cents_from_quantised(p["p_q"]) for d, p in prices.items()}
        judged = judge(
            request.lines,
            live_cents,
            step_cents=step_cents_from(spec.params.step_quant),
            current_version=state.version,
            quote_version=request.quote_version,
            grace_versions=view.quote_grace_versions,
        )
        if isinstance(judged, PriceChanged):
            raise PriceChangedError(
                "prices changed since the quote",
                extra={
                    "version": judged.version,
                    "prices": [
                        {"drink_id": d, "price_cents": cents} for d, cents in judged.prices.items()
                    ],
                },
            )

        now_ms = clock.wall_ms()
        qty = {line.drink_id: line.qty for line in judged.lines}
        orders = np.array([float(qty.get(d, 0)) for d in drink_ids])
        candidate = advance(spec, state, now_ms=now_ms, orders=orders, run_seed=view.run_seed).state
        receipt_lines = [
            ReceiptLine(
                drink_id=line.drink_id,
                qty=line.qty,
                unit_price_cents=line.unit_price_cents,
                line_total_cents=line.qty * line.unit_price_cents,
            )
            for line in judged.lines
        ]

        def receipt_for(order_id: int) -> Receipt:
            return Receipt(
                order_id=order_id,
                version=candidate.version,
                wall_ts_ms=now_ms,
                quote_version=request.quote_version,
                lines=receipt_lines,
                total_cents=sum(line.line_total_cents for line in receipt_lines),
            )

        try:
            written = await write_order(
                engine,
                run_id=view.run_id,
                idempotency_key=request.idempotency_key,
                expected_version=state.version,
                state=candidate,
                spec=spec,
                drink_ids=drink_ids,
                lines=[
                    OrderLineInput(
                        drink_id=line.drink_id,
                        qty=line.qty,
                        unit_price_cents=line.unit_price_cents,
                        p_cont=prices[line.drink_id]["p_cont"],
                    )
                    for line in judged.lines
                ],
                wall_ts_ms=now_ms,
                actor_key_id=actor_key_id,
                response=lambda order_id: receipt_for(order_id).model_dump(mode="json"),
            )
        except IntegrityError as error:
            if _UNIQUE_KEY not in str(error.orig):
                raise
            async with engine.connect() as conn:
                winner = await find_order_by_key(conn, request.idempotency_key)
            if winner is None:
                raise
            return Outcome(result=_replay(winner, request), view=view)

        receipt = receipt_for(written.order_id)
        entry = TickEntry(
            version=candidate.version,
            wall_ts_ms=now_ms,
            source="order",
            prices=tick_prices(spec, candidate, drink_ids),
        )
        earnings_lines = tuple((ln.drink_id, ln.qty, ln.line_total_cents) for ln in receipt_lines)
        event = OrderCommitted(
            run_id=view.run_id,
            order_id=written.order_id,
            lines=tuple(
                CommittedLine(
                    drink_id=ln.drink_id,
                    qty=ln.qty,
                    unit_price_cents=ln.unit_price_cents,
                    line_total_cents=ln.line_total_cents,
                )
                for ln in receipt_lines
            ),
            total_cents=receipt.total_cents,
            earnings_delta={
                ln.drink_id: DrinkEarnings(qty=ln.qty, revenue_cents=ln.line_total_cents)
                for ln in receipt_lines
            },
            entry=entry,
        )
        return Outcome(
            result=PlacedOrder(receipt=receipt, body=receipt.body(), replay=False),
            view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
            events=(event,),
            ticks=(entry,),
            earnings_lines=earnings_lines,
        )

    try:
        return await holder.mutate("order", step)
    except NoLiveRunError:
        try:
            async with engine.connect() as conn:
                stored = await find_order_by_key(conn, request.idempotency_key)
        except (SQLAlchemyError, OSError) as error:
            raise PersistenceUnavailable("the database did not answer the replay") from error
        if stored is None:
            raise
        return _replay(stored, request)
