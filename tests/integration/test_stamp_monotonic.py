"""AC16: whatever the wall clock does, committed stamps never go back (Phase 8 T4, SD15).

A seeded property loop. Each seed is a live run on the real ticker, holder, orders
and jumps, on a `FakeClock` behind `AppClock` (as `create_app` composes them).
Forty random steps each: let time run, move the wall clock up to two hours either
way, place an order at the live price, or schedule a jump. Then, for that run:

- `price_tick.wall_ts_ms` is non-decreasing in `version`;
- every order's `wall_ts_ms` is at or after the newest tick before its version.

`hypothesis` is not a dependency (SD20), so this is `random.Random(seed)`; a failure
names its seed, and `SEEDS` replays it.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.mapping import cents_from_quantised
from app.db.runs import add_drink, close_run, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.clock import AppClock
from app.runtime.grace import QuotedLine
from app.runtime.holder import DomainEvent, MarketHolder
from app.runtime.manipulation import schedule
from app.runtime.orders import OrderRequest, place_order
from app.runtime.rehydrate import RehydratedRun, rehydrate
from app.runtime.ticker import Ticker
from exchange import Params
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
INTERVAL = 1_000
SEEDS = range(30)
STEPS = 40
TWO_HOURS = 2 * 3_600_000


async def _go_live(engine: AsyncEngine, now_ms: int) -> int:
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
        )
        for slot, name in enumerate(("Bier", "Wijn")):
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
    await go_live(engine, run_id, now_ms=now_ms)
    return run_id


async def _settle(fake: FakeClock, ticker: Ticker) -> None:
    for _ in range(2_000):
        await asyncio.sleep(0.002)
        if fake.sleepers == 1 and not ticker.busy:
            return
    raise AssertionError("the ticker did not settle")


async def _one_seed(engine: AsyncEngine, seed: int) -> int:
    """Run one seed's steps on a fresh live run; its run id."""
    rng = random.Random(seed)
    fake = FakeClock(T0)
    clock = AppClock(fake)
    run_id = await _go_live(engine, clock.wall_ms())
    run = await rehydrate(engine, now_ms=clock.wall_ms())
    assert isinstance(run, RehydratedRun)

    def sink(batch: Sequence[DomainEvent]) -> None:
        pass

    holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=sink)
    ticker = Ticker(holder, clock=clock, interval_ms=INTERVAL)
    ticker.start()
    await _settle(fake, ticker)
    try:
        for n in range(STEPS):
            action = rng.choice(("advance", "wall", "order", "jump"))
            drink = rng.choice(holder.drink_ids)
            if action == "advance":
                fake.advance(rng.randint(200, 3_000))
                await _settle(fake, ticker)
            elif action == "wall":
                fake.set_wall(fake.wall_ms() + rng.randint(-TWO_HOURS, TWO_HOURS))
            elif action == "order":
                assert holder.spec is not None and holder.state is not None
                prices = tick_prices(holder.spec, holder.state, holder.drink_ids)
                price = cents_from_quantised(prices[drink]["p_q"])
                request = OrderRequest(
                    idempotency_key=f"seed-{seed}-{n}",
                    quote_version=holder.state.version,
                    lines=(
                        QuotedLine(drink_id=drink, qty=rng.randint(1, 3), unit_price_cents=price),
                    ),
                )
                await place_order(holder, request, actor_key_id=None, clock=clock)
            else:
                await schedule(
                    holder,
                    drink,
                    rng.randrange(150, 501, 10),
                    rng.randint(1_000, 60_000),
                    clock=clock,
                )
    finally:
        await ticker.stop()
    async with engine.begin() as conn:
        await close_run(
            conn,
            run_id,
            ended_at_ms=max(clock.wall_ms(), holder.last_commit_wall_ms or 0),
            requested_by="test",
        )
    return run_id


async def _faults(engine: AsyncEngine, run_id: int) -> list[str]:
    async with engine.connect() as conn:
        ticks = [
            (int(row[0]), int(row[1]))
            for row in await conn.execute(
                text(
                    "SELECT version, wall_ts_ms FROM price_tick WHERE run_id = :r ORDER BY version"
                ),
                {"r": run_id},
            )
        ]
        orders = [
            (int(row[0]), int(row[1]))
            for row in await conn.execute(
                text('SELECT version, wall_ts_ms FROM "order" WHERE run_id = :r ORDER BY version'),
                {"r": run_id},
            )
        ]
    faults = [
        f"tick v{v} at {w} is before v{pv} at {pw}"
        for (pv, pw), (v, w) in itertools.pairwise(ticks)
        if w < pw
    ]
    for version, wall in orders:
        before = [w for v, w in ticks if v < version]
        if before and wall < max(before):
            faults.append(f"order v{version} at {wall} is before the commit at {max(before)}")
    return faults


def test_committed_stamps_never_go_back_whatever_the_wall_clock_does(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> dict[int, list[str]]:
        engine = create_engine(settings.model_copy(update={"database_url": database_url}))
        try:
            failures = {}
            for seed in SEEDS:
                run_id = await _one_seed(engine, seed)
                if faults := await _faults(engine, run_id):
                    failures[seed] = faults
            return failures
        finally:
            await engine.dispose()

    failures = asyncio.run(scenario())

    assert failures == {}, f"failing seeds (replay with SEEDS = [seed]): {failures}"
