"""Concurrency proof (Phase 3 T21: AC8, AC18e; the spec's Verification "Concurrency").

Fifty orders from distinct keys, with random lines, are gathered while the real
ticker runs on the fake clock and jumps are interleaved through
`holder.mutate`. Some orders are rejected by the grace rule as prices move
underneath them; that is the system working, and only accepted orders count.
Afterwards the database and memory must tell one consistent story.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import load_state, save_transition
from app.db.mapping import cents_from_quantised
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.grace import QuotedLine
from app.runtime.holder import (
    DomainEvent,
    MarketHolder,
    MarketView,
    OrderCommitted,
    Outcome,
    TickCommitted,
)
from app.runtime.orders import OrderRequest, PlacedOrder, PriceChangedError, place_order
from app.runtime.rehydrate import RehydratedRun, rehydrate
from app.runtime.ticker import Ticker
from exchange import Params, schedule_jump
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
SEED = 20261002
ORDERS = 50
JUMPS = 5


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _live(engine: AsyncEngine) -> RehydratedRun:
    async with engine.begin() as conn:
        run_id = await create_draft_run(conn, params=Params(step_quant=0.1), run_seed=7)
        for slot, name in enumerate(("Bier", "Wijn", "Fris", "Shot")):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=150,
                p0_cents=260 + 20 * slot,
                p_max_cents=600,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )
    await go_live(engine, run_id, now_ms=T0)
    run = await rehydrate(engine, now_ms=T0)
    assert isinstance(run, RehydratedRun)
    return run


def _jump_step(engine: AsyncEngine, clock: FakeClock, drink: int, target: float):  # type: ignore[no-untyped-def]
    """A test-local jump: `schedule_jump` plus a `jump` tick, through the one mutation path."""

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id is not None and view.spec is not None and view.state is not None
        now_ms = clock.wall_ms()
        candidate = schedule_jump(
            view.spec, view.state, drink=drink, p_target=target, duration_ms=5_000, now_ms=now_ms
        )
        await save_transition(
            engine,
            run_id=view.run_id,
            expected_version=view.state.version,
            state=candidate,
            spec=view.spec,
            drink_ids=view.drink_ids,
            source="jump",
            wall_ts_ms=now_ms,
        )
        return Outcome(
            result=candidate.version,
            view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
        )

    return step


def test_fifty_concurrent_orders_with_ticks_and_jumps_tell_one_story(
    settings: Settings, database_url: str
) -> None:
    rng = random.Random(SEED)

    async def scenario() -> tuple[
        list[PlacedOrder], int, list[DomainEvent], MarketHolder, AsyncEngine
    ]:
        engine = _engine(settings, database_url)
        clock = FakeClock(T0)
        events: list[DomainEvent] = []
        holder: MarketHolder

        def sink(batch: Sequence[DomainEvent]) -> None:
            assert not holder.lock.locked()
            events.extend(batch)

        holder = MarketHolder.from_rehydrated(
            await _live(engine), engine=engine, clock=clock, sink=sink
        )
        ticker = Ticker(holder, clock=clock, interval_ms=1_000)
        ticker.start()

        async def order(n: int) -> PlacedOrder | None:
            await asyncio.sleep(rng.random() * 0.05)
            assert holder.spec is not None and holder.state is not None
            prices = tick_prices(holder.spec, holder.state, holder.drink_ids)
            drinks = rng.sample(holder.drink_ids, rng.randint(1, len(holder.drink_ids)))
            request = OrderRequest(
                idempotency_key=f"k-concurrent-{n:03d}",
                quote_version=holder.state.version,
                lines=tuple(
                    QuotedLine(d, rng.randint(1, 5), cents_from_quantised(prices[d]["p_q"]))
                    for d in drinks
                ),
            )
            try:
                return await place_order(holder, request, actor_key_id=None, clock=clock)
            except PriceChangedError:
                return None

        async def time_passes() -> None:
            for _ in range(40):
                await asyncio.sleep(0.003)
                clock.advance(250)

        async def jumps() -> None:
            for k in range(JUMPS):
                await asyncio.sleep(rng.random() * 0.05)
                drink = k % len(holder.drink_ids)
                await holder.mutate("jump", _jump_step(engine, clock, drink, 1.8 + 0.4 * k))

        try:
            results = await asyncio.gather(
                *(order(n) for n in range(ORDERS)), time_passes(), jumps()
            )
        finally:
            await ticker.stop()
        placed = [r for r in results[:ORDERS] if r is not None]
        rejected = ORDERS - len(placed)
        return placed, rejected, events, holder, engine

    async def check() -> None:
        placed, rejected, events, holder, engine = await scenario()
        try:
            assert placed, "no order was accepted; the scenario proves nothing"
            assert holder.run_id is not None and holder.state is not None
            async with engine.connect() as conn:
                ticks = (
                    await conn.execute(
                        text("SELECT version, source, prices FROM price_tick ORDER BY version")
                    )
                ).all()
                orders = (await conn.execute(text('SELECT order_id, version FROM "order"'))).all()
                ledger: int = (
                    await conn.execute(
                        text("SELECT coalesce(sum(line_total_cents), 0) FROM order_line")
                    )
                ).scalar_one()
                stored = await load_state(conn, holder.run_id, holder.drink_ids)

            versions = [int(row[0]) for row in ticks]
            # Gap-free and strictly increasing, from go-live's reset tick at 0.
            assert versions == list(range(len(versions)))
            sources = {int(row[0]): str(row[1]) for row in ticks}
            assert {"tick", "order", "jump"} <= set(sources.values())
            # Every accepted order has its own `order` tick at its version.
            assert sorted(int(row[1]) for row in orders) == sorted(
                p.receipt.version for p in placed
            )
            assert all(sources[p.receipt.version] == "order" for p in placed)
            # No two distinct price vectors share a version (the PK, and one row per version).
            assert len({int(row[0]) for row in ticks}) == len(ticks)
            # Memory is exactly the committed row.
            assert stored is not None
            state, _ = stored
            assert state.version == holder.state.version == versions[-1]
            for key in ("y", "cum_orders", "flow_ema", "last_order_ts"):
                assert getattr(state, key).tobytes() == getattr(holder.state, key).tobytes(), key
            # The ledger equals the receipts, and the in-memory earnings agree.
            assert int(ledger) == sum(p.receipt.total_cents for p in placed)
            assert sum(e.revenue_cents for e in holder.earnings.values()) == int(ledger)
            # AC18e: the sink saw versions strictly increasing, and only committed ones.
            seen = [
                e.entry.version for e in events if isinstance(e, TickCommitted | OrderCommitted)
            ]
            assert seen == sorted(set(seen))
            assert set(seen) <= set(versions)
            assert len([e for e in events if isinstance(e, OrderCommitted)]) == len(placed)
            assert rejected + len(placed) == ORDERS
        finally:
            await engine.dispose()

    asyncio.run(check())
