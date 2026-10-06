"""The order domain (Phase 3 T18: SD17-SD21, SD24; AC7, AC9-AC13, AC14a, AC23 charge half)."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.runtime.orders as orders_module
from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import save_transition
from app.db.mapping import cents_from_quantised
from app.db.orders import find_order_by_key
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.grace import QuotedLine
from app.runtime.history import TickEntry
from app.runtime.holder import (
    DomainEvent,
    MarketHolder,
    MarketView,
    OrderCommitted,
    Outcome,
    PersistenceUnavailable,
    TickCommitted,
)
from app.runtime.orders import (
    IdempotencyKeyReused,
    InvalidOrder,
    OrderRequest,
    PriceChangedError,
    Receipt,
    place_order,
)
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import Params, advance
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
STEP = 10  # step_quant 0.10 in cents


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


class Market:
    def __init__(self, engine: AsyncEngine, holder: MarketHolder, clock: FakeClock) -> None:
        self.engine = engine
        self.holder = holder
        self.clock = clock
        self.events: list[DomainEvent] = []

    @property
    def drinks(self) -> tuple[int, ...]:
        return self.holder.drink_ids

    @property
    def version(self) -> int:
        assert self.holder.state is not None
        return self.holder.state.version

    def live(self) -> dict[int, int]:
        assert self.holder.spec is not None and self.holder.state is not None
        prices = tick_prices(self.holder.spec, self.holder.state, self.drinks)
        return {d: cents_from_quantised(p["p_q"]) for d, p in prices.items()}

    def request(
        self, key: str, lines: dict[int, tuple[int, int]], quote: int | None = None
    ) -> OrderRequest:
        """`lines` is `{drink_id: (qty, unit_price_cents)}`."""
        return OrderRequest(
            idempotency_key=key,
            quote_version=self.version if quote is None else quote,
            lines=tuple(
                QuotedLine(drink_id=d, qty=q, unit_price_cents=c) for d, (q, c) in lines.items()
            ),
        )

    async def place(
        self, request: OrderRequest, actor: int | None = None
    ) -> orders_module.PlacedOrder:
        return await place_order(self.holder, request, actor_key_id=actor, clock=self.clock)

    async def tick(self) -> None:
        self.clock.advance(1_000)
        await self.holder.mutate("tick", self._tick_step(self.clock.wall_ms()))

    def _tick_step(self, now_ms: int):  # type: ignore[no-untyped-def]
        engine = self.engine

        async def step(view: MarketView) -> Outcome[int]:
            assert view.run_id is not None and view.spec is not None and view.state is not None
            candidate = advance(view.spec, view.state, now_ms=now_ms, run_seed=view.run_seed).state
            await save_transition(
                engine,
                run_id=view.run_id,
                expected_version=view.state.version,
                state=candidate,
                spec=view.spec,
                drink_ids=view.drink_ids,
                source="tick",
                wall_ts_ms=now_ms,
            )
            entry = TickEntry(
                candidate.version, now_ms, "tick", tick_prices(view.spec, candidate, view.drink_ids)
            )
            return Outcome(
                result=candidate.version,
                view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
                events=(TickCommitted(run_id=view.run_id, entry=entry),),
                ticks=(entry,),
            )

        return step

    async def counts(self) -> tuple[Any, ...]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        'SELECT (SELECT count(*) FROM "order"), (SELECT count(*) FROM order_line),'
                        " (SELECT count(*) FROM price_tick),"
                        " (SELECT row_to_json(e)::text FROM engine_state e)"
                    )
                )
            ).one()
        return tuple(row)


@asynccontextmanager
async def _market(settings: Settings, url: str, *, grace: int = 2) -> AsyncIterator[Market]:
    engine = _engine(settings, url)
    clock = FakeClock(T0)
    try:
        async with engine.begin() as conn:
            run_id = await create_draft_run(
                conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
            )
            for slot, name in enumerate(("Bier", "Wijn", "Fris")):
                await add_drink(
                    conn,
                    run_id,
                    name=name,
                    slot=slot,
                    p_min_cents=150,
                    p0_cents=260,
                    p_max_cents=500,
                    a=1.0,
                    d=0.1,
                    s0=1.0,
                    c=0.1,
                    bar_price_cents=260,
                )
            await conn.execute(
                text("UPDATE run SET quote_grace_versions = :g WHERE run_id = :r"),
                {"g": grace, "r": run_id},
            )
            removed = await add_drink(
                conn,
                run_id,
                name="Weg",
                slot=3,
                p_min_cents=150,
                p0_cents=260,
                p_max_cents=500,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )
            await conn.execute(
                text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": removed}
            )
        await go_live(engine, run_id, now_ms=T0)
        run = await rehydrate(engine, now_ms=T0)
        assert isinstance(run, RehydratedRun)
        market: Market

        def sink(batch: Sequence[DomainEvent]) -> None:
            assert not market.holder.lock.locked()
            market.events.extend(batch)

        holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=sink)
        market = Market(engine, holder, clock)
        market.removed_drink = removed  # type: ignore[attr-defined]
        yield market
    finally:
        await engine.dispose()


def test_an_order_at_the_live_price_is_charged_and_recorded(
    settings: Settings, database_url: str
) -> None:
    """AC12, AC23: the receipt matches `order_line`; charged = `price_cents`; one price move."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier, wijn, _ = m.drinks
            live = m.live()
            before = m.version
            placed = await m.place(
                m.request("k-00000001", {bier: (2, live[bier]), wijn: (1, live[wijn])}), actor=None
            )

            assert not placed.replay
            r = placed.receipt
            assert r.version == before + 1 == m.version
            assert r.quote_version == before
            assert [
                (ln.drink_id, ln.qty, ln.unit_price_cents, ln.line_total_cents) for ln in r.lines
            ] == [
                (bier, 2, live[bier], 2 * live[bier]),
                (wijn, 1, live[wijn], live[wijn]),
            ]
            assert r.total_cents == 2 * live[bier] + live[wijn]
            assert (
                placed.body == Receipt.model_validate_json(placed.body).model_dump_json().encode()
            )
            async with m.engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT drink_id, qty, unit_price_cents, line_total_cents"
                            " FROM order_line ORDER BY drink_id"
                        )
                    )
                ).all()
                stored = (await conn.execute(text('SELECT response, version FROM "order"'))).one()
                ticks = (
                    await conn.execute(text("SELECT source FROM price_tick WHERE source='order'"))
                ).all()
            assert sorted(
                (ln.drink_id, ln.qty, ln.unit_price_cents, ln.line_total_cents) for ln in r.lines
            ) == [tuple(row) for row in rows]
            assert Receipt.model_validate(stored[0]) == r and stored[1] == r.version
            assert len(ticks) == 1
            assert m.holder.earnings[bier].qty == 2
            (committed,) = [e for e in m.events if isinstance(e, OrderCommitted)]
            assert committed.order_id == r.order_id and committed.entry.version == r.version
            assert committed.earnings_delta[bier].revenue_cents == 2 * live[bier]

    asyncio.run(scenario())


def test_a_tick_taking_the_lock_first_is_seen_by_the_order(
    settings: Settings, database_url: str
) -> None:
    """AC7: the order queues behind a tick; it is judged at the post-tick version.

    Grace is 0 and the quote is one step off the pre-tick price: judged before the
    tick (age 0) it would be honoured; judged after it (age 1) it is a 409.
    """

    async def scenario() -> tuple[int, int]:
        async with _market(settings, database_url, grace=0) as m:
            bier = m.drinks[0]
            quoted_at = m.version
            request = m.request("k-00000002", {bier: (1, m.live()[bier] + STEP)})
            await m.holder.lock.acquire()
            tick = asyncio.create_task(m.tick())
            await asyncio.sleep(0)
            order = asyncio.create_task(m.place(request))
            await asyncio.sleep(0)
            m.holder.lock.release()
            await tick
            with pytest.raises(PriceChangedError) as excinfo:
                await order
            assert excinfo.value.extra["version"] == quoted_at + 1
            return quoted_at, m.version

    quoted_at, now = asyncio.run(scenario())
    assert now == quoted_at + 1  # the tick moved the version; the order wrote nothing


def test_a_sequential_replay_is_byte_identical_and_writes_nothing(
    settings: Settings, database_url: str
) -> None:
    """AC9: one order row, one price move, the same bytes."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier = m.drinks[0]
            request = m.request("k-00000003", {bier: (3, m.live()[bier])})
            first = await m.place(request)
            after_first = await m.counts()
            await m.tick()
            after_tick = await m.counts()
            again = await m.place(request)

            assert again.replay and not first.replay
            assert again.body == first.body
            assert await m.counts() == after_tick
            assert after_first[:2] == (1, 1)
            assert len([e for e in m.events if isinstance(e, OrderCommitted)]) == 1

    asyncio.run(scenario())


def test_two_identical_concurrent_requests_give_one_order(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier = m.drinks[0]
            request = m.request("k-00000004", {bier: (1, m.live()[bier])})
            a, b = await asyncio.gather(m.place(request), m.place(request))

            assert a.body == b.body
            assert sorted([a.replay, b.replay]) == [False, True]
            assert (await m.counts())[:2] == (1, 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["qty", "price", "quote_version", "drink"])
def test_a_reused_key_with_a_different_body_is_422_and_changes_nothing(
    settings: Settings, database_url: str, change: str
) -> None:
    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier, wijn, _ = m.drinks
            live = m.live()
            await m.place(m.request("k-00000005", {bier: (2, live[bier])}))
            before, state = await m.counts(), m.holder.state
            variants = {
                "qty": m.request("k-00000005", {bier: (3, live[bier])}, quote=m.version - 1),
                "price": m.request(
                    "k-00000005", {bier: (2, live[bier] + STEP)}, quote=m.version - 1
                ),
                "quote_version": m.request("k-00000005", {bier: (2, live[bier])}),
                "drink": m.request("k-00000005", {wijn: (2, live[bier])}, quote=m.version - 1),
            }
            with pytest.raises(IdempotencyKeyReused) as excinfo:
                await m.place(variants[change])
            assert (excinfo.value.status_code, excinfo.value.code) == (
                422,
                "idempotency_key_reused",
            )
            assert await m.counts() == before
            assert m.holder.state is state

    asyncio.run(scenario())


def test_a_unique_violation_at_commit_is_replayed(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SD20: the UNIQUE index is the final arbiter. A writer that won the race between
    our key check and our INSERT is replayed, not reported as a failure."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier = m.drinks[0]
            request = m.request("k-00000006", {bier: (1, m.live()[bier])})
            first = await m.place(request)
            state_after_first = m.holder.state
            real = find_order_by_key
            calls = {"n": 0}

            async def miss_once(conn: Any, key: str) -> Any:
                calls["n"] += 1
                return None if calls["n"] == 1 else await real(conn, key)

            monkeypatch.setattr(orders_module, "find_order_by_key", miss_once)
            again = await m.place(dataclasses.replace(request))

            assert calls["n"] == 2
            assert again.replay and again.body == first.body
            assert m.holder.state is state_after_first
            assert (await m.counts())[:2] == (1, 1)

    asyncio.run(scenario())


@pytest.mark.parametrize(("offset", "age"), [(STEP, 2), (-STEP, 1), (0, 3)])
def test_within_grace_the_quoted_price_is_charged(
    settings: Settings, database_url: str, offset: int, age: int
) -> None:
    """AC10: one step off and at most `grace` (2) versions old; equal, even older than grace."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier = m.drinks[0]
            quoted_at, live = m.version, m.live()[bier]
            for _ in range(age):
                await m.tick()
            assert m.live()[bier] == live, "premise: ticks within a second do not move the price"
            placed = await m.place(
                m.request("k-00000007", {bier: (2, live + offset)}, quote=quoted_at)
            )

            assert placed.receipt.lines[0].unit_price_cents == live + offset
            assert placed.receipt.total_cents == 2 * (live + offset)

    asyncio.run(scenario())


@pytest.mark.parametrize(("offset", "age"), [(2 * STEP, 0), (STEP, 3), (STEP + 1, 0)])
def test_outside_grace_the_order_is_409_and_nothing_moves(
    settings: Settings, database_url: str, offset: int, age: int
) -> None:
    """AC11: no rows, `engine_state` and memory unchanged, the live prices returned."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier, wijn, _ = m.drinks
            quoted_at, live = m.version, m.live()
            for _ in range(age):
                await m.tick()
            before, state, ring = await m.counts(), m.holder.state, m.holder.ring
            request = m.request(
                "k-00000008",
                {wijn: (1, live[wijn]), bier: (1, live[bier] + offset)},
                quote=quoted_at,
            )
            with pytest.raises(PriceChangedError) as excinfo:
                await m.place(request)

            error = excinfo.value
            assert (error.status_code, error.code) == (409, "price_changed")
            assert error.extra["version"] == m.version
            assert error.extra["prices"] == [
                {"drink_id": wijn, "price_cents": m.live()[wijn]},
                {"drink_id": bier, "price_cents": m.live()[bier]},
            ]
            assert await m.counts() == before
            assert m.holder.state is state and m.holder.ring == ring
            assert not any(isinstance(e, OrderCommitted) for e in m.events)

    asyncio.run(scenario())


# write_order's statements, in order (tests/integration/test_orders.py pins them).
WRITE_ORDER_STATEMENTS = (
    "UPDATE engine_state",
    'INSERT INTO "order"',
    "INSERT INTO order_line",
    'UPDATE "order"',
    "INSERT INTO price_tick",
)


@pytest.mark.parametrize("statement", WRITE_ORDER_STATEMENTS)
def test_a_failure_at_any_statement_is_503_and_changes_nothing(
    settings: Settings, database_url: str, statement: str
) -> None:
    """AC13: memory, `engine_state` and the ledger as before; a retry with the key then succeeds."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier = m.drinks[0]
            request = m.request("k-00000009", {bier: (2, m.live()[bier])})
            before, state, earnings = await m.counts(), m.holder.state, dict(m.holder.earnings)

            def fail(*args: Any) -> None:
                if args[2].startswith(statement):
                    raise OSError(f"injected at {statement}")

            event.listen(m.engine.sync_engine, "before_cursor_execute", fail)
            try:
                with pytest.raises(PersistenceUnavailable) as excinfo:
                    await m.place(request)
            finally:
                event.remove(m.engine.sync_engine, "before_cursor_execute", fail)

            assert excinfo.value.status_code == 503
            assert await m.counts() == before
            assert m.holder.state is state and dict(m.holder.earnings) == earnings
            assert not any(isinstance(e, OrderCommitted) for e in m.events)
            placed = await m.place(request)
            assert not placed.replay and (await m.counts())[:2] == (1, 1)

    asyncio.run(scenario())


def test_every_statement_is_covered(settings: Settings, database_url: str) -> None:
    """Anti-vacuity for the parametrisation above: these are the statements an order runs."""

    async def scenario() -> list[str]:
        async with _market(settings, database_url) as m:
            seen: list[str] = []

            def record(*args: Any) -> None:
                seen.append(args[2])

            bier = m.drinks[0]
            event.listen(m.engine.sync_engine, "before_cursor_execute", record)
            try:
                await m.place(m.request("k-00000010", {bier: (1, m.live()[bier])}))
            finally:
                event.remove(m.engine.sync_engine, "before_cursor_execute", record)
            return seen

    seen = asyncio.run(scenario())
    writes = [s for s in seen if not s.lstrip().upper().startswith("SELECT")]
    assert [next(p for p in WRITE_ORDER_STATEMENTS if s.startswith(p)) for s in writes] == list(
        WRITE_ORDER_STATEMENTS
    )


@pytest.mark.parametrize(
    "case", ["inactive-drink", "unknown-drink", "future-quote", "duplicate-drink"]
)
def test_domain_checks_are_422_and_write_nothing(
    settings: Settings, database_url: str, case: str
) -> None:
    """AC14a."""

    async def scenario() -> None:
        async with _market(settings, database_url) as m:
            bier = m.drinks[0]
            live = m.live()[bier]
            requests = {
                "inactive-drink": m.request("k-00000011", {m.removed_drink: (1, live)}),  # type: ignore[attr-defined]
                "unknown-drink": m.request("k-00000011", {999_999: (1, live)}),
                "future-quote": m.request("k-00000011", {bier: (1, live)}, quote=m.version + 1),
                "duplicate-drink": OrderRequest(
                    idempotency_key="k-00000011",
                    quote_version=m.version,
                    lines=(QuotedLine(bier, 1, live), QuotedLine(bier, 2, live)),
                ),
            }
            before, state = await m.counts(), m.holder.state
            with pytest.raises(InvalidOrder) as excinfo:
                await m.place(requests[case])
            assert (excinfo.value.status_code, excinfo.value.code) == (422, "invalid_request")
            assert await m.counts() == before
            assert m.holder.state is state

    asyncio.run(scenario())


def test_the_engine_moves_by_the_ordered_qty_not_the_honoured_price(
    settings: Settings, database_url: str
) -> None:
    """SD19: an order honoured a step off moves the engine exactly as one at the live price."""

    async def scenario() -> tuple[bytes, bytes]:
        results = []
        for offset in (0, STEP):
            async with _market(settings, database_url) as m:
                bier = m.drinks[0]
                await m.place(
                    m.request(f"k-offset-{offset:04d}", {bier: (4, m.live()[bier] + offset)})
                )
                assert m.holder.state is not None
                results.append(m.holder.state.y.tobytes())
            cleaner = _engine(settings, database_url)
            try:
                async with cleaner.begin() as conn:
                    await conn.execute(
                        text(
                            'TRUNCATE "order", order_line, price_tick, engine_state, drink, run'
                            " RESTART IDENTITY CASCADE"
                        )
                    )
            finally:
                await cleaner.dispose()
        return results[0], results[1]

    at_live, honoured = asyncio.run(scenario())
    assert at_live == honoured
