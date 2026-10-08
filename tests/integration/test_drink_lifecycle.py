"""A drink added to the live run mid-borrel (Phase 6 T12: AC12, AC14; SD12, D-02).

A scripted market runs first -- orders, a running jump, a Brownian draw -- then
a drink is added in one `mutate("config")`. Every existing drink's state and
earnings must be bitwise what they were, and the new drink must quote its `p0`.

The runtime is assembled as boot assembles it, with no HTTP;
`tests/api/test_drinks.py` drives the same path through the route.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import save_transition
from app.db.mapping import cents_from_quantised
from app.db.orders import earnings_by_drink
from app.db.runs import (
    DuplicateDrinkName,
    LastActiveDrink,
    add_drink,
    append_config_revision,
    create_draft_run,
    go_live,
)
from app.db.session import create_engine
from app.runtime.config import ConfigPatch, write_live_config
from app.runtime.drinks import (
    DrinkCreate,
    DrinkPatch,
    add_live_drink,
    edit_live_drink,
    remove_live_drink,
)
from app.runtime.grace import QuotedLine
from app.runtime.history import TickEntry
from app.runtime.holder import (
    ConfigChanged,
    DomainEvent,
    MarketHolder,
    MarketView,
    Outcome,
    TickCommitted,
)
from app.runtime.manipulation import schedule, start_event
from app.runtime.orders import OrderRequest, place_order
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import EngineState, Params, advance
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
# A Brownian draw every 2 s, so a short script reaches one.
PARAMS = Params(step_quant=0.1, bm_dt_minutes=2 / 60)


class Market:
    def __init__(self, engine: AsyncEngine, run: RehydratedRun, clock: FakeClock) -> None:
        self.engine = engine
        self.clock = clock
        self.run_id = run.run_id
        self.events: list[DomainEvent] = []
        self.holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=self._sink)

    def _sink(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)

    @property
    def state(self) -> EngineState:
        assert self.holder.state is not None
        return self.holder.state

    def quoted(self) -> dict[int, int]:
        assert self.holder.spec is not None
        prices = tick_prices(self.holder.spec, self.state, self.holder.drink_ids)
        return {d: cents_from_quantised(p["p_q"]) for d, p in prices.items()}

    async def order(self, key: str, drink_id: int, qty: int) -> None:
        request = OrderRequest(
            idempotency_key=key,
            quote_version=self.state.version,
            lines=(
                QuotedLine(drink_id=drink_id, qty=qty, unit_price_cents=self.quoted()[drink_id]),
            ),
        )
        await place_order(self.holder, request, actor_key_id=None, clock=self.clock)

    async def tick(self) -> None:
        self.clock.advance(1_000)
        now_ms = self.clock.wall_ms()
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

        await self.holder.mutate("tick", step)

    async def add(self, **fields: Any) -> int:
        body = DrinkCreate.model_validate(
            {"name": "Cola", "p_min_cents": 100, "p0_cents": 300, "p_max_cents": 600, **fields}
        )
        created = await add_live_drink(
            self.holder, self.run_id, body, author="Bestuur", clock=self.clock
        )
        return created.drink_id


@asynccontextmanager
async def _live(settings: Settings, url: str) -> AsyncIterator[Market]:
    engine = create_engine(settings.model_copy(update={"database_url": url}))
    try:
        async with engine.begin() as conn:
            run_id = await create_draft_run(conn, name="Vrijmibo", params=PARAMS, run_seed=7)
            for slot, name in enumerate(("Bier", "Wijn", "Fris")):
                await add_drink(
                    conn,
                    run_id,
                    name=name,
                    slot=slot,
                    p_min_cents=150,
                    p0_cents=260 + 30 * slot,
                    p_max_cents=500,
                    a=10.0,
                    d=0.6,
                    s0=8.0,
                    c=0.4,
                    bar_price_cents=260,
                )
            await append_config_revision(conn, run_id, config={}, author="seed")
        await go_live(engine, run_id, now_ms=T0, author="seed")
        run = await rehydrate(engine, now_ms=T0)
        assert isinstance(run, RehydratedRun)
        yield Market(engine, run, FakeClock(T0))
    finally:
        await engine.dispose()


async def _scripted(market: Market) -> None:
    """Orders, a running jump and at least one Brownian draw."""
    bier, wijn, _ = market.holder.drink_ids
    for i in range(4):
        await market.tick()
        await market.order(f"k-script-{i:04d}", bier if i % 2 else wijn, 1 + i)
    await schedule(market.holder, wijn, 450, 120_000, clock=market.clock)
    for _ in range(3):
        await market.tick()


def _per_slot(state: EngineState, n: int) -> dict[str, bytes]:
    return {
        "y": state.y[:n].tobytes(),
        "cum_orders": state.cum_orders[:n].tobytes(),
        "flow_ema": state.flow_ema[:n].tobytes(),
        "last_order_ts": state.last_order_ts[:n].tobytes(),
    }


def test_a_live_add_mid_run_leaves_every_existing_drink_bitwise(
    settings: Settings, database_url: str
) -> None:
    """AC14, SD12."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            await _scripted(market)
            before = market.state
            assert before.jumps and before.rng_counter > 0
            assert before.cum_orders.any()
            earnings = dict(market.holder.earnings)
            ids = market.holder.drink_ids
            ring = market.holder.ring

            cola = await market.add()

            after = market.state
            assert market.holder.drink_ids == (*ids, cola)
            assert _per_slot(after, len(ids)) == _per_slot(before, len(ids))
            assert after.jumps == before.jumps
            assert after.rng_counter == before.rng_counter
            assert after.version == before.version + 1
            assert dict(market.holder.earnings) == earnings
            assert market.holder.ring[: len(ring)] == ring
            assert market.quoted()[cola] == 300
            assert market.holder.view.bar_price_cents[cola] == 300

    asyncio.run(scenario())


def test_a_live_add_is_one_config_transition(settings: Settings, database_url: str) -> None:
    """AC12: version + 1, one `config` tick and one revision, then one `ConfigChanged`."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            await market.tick()
            version = market.state.version

            cola = await market.add()

            async with market.engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT (SELECT version FROM engine_state WHERE run_id = :r),"
                            " (SELECT count(*) FROM price_tick WHERE run_id = :r"
                            "   AND source = 'config'),"
                            " (SELECT max(revision) FROM run_config_revision WHERE run_id = :r),"
                            " (SELECT author FROM run_config_revision WHERE run_id = :r"
                            "   ORDER BY revision DESC LIMIT 1)"
                        ),
                        {"r": market.run_id},
                    )
                ).one()
            assert tuple(row) == (version + 1, 1, 2, "Bestuur")
            changed = [e for e in market.events if isinstance(e, ConfigChanged)]
            assert len(changed) == 1
            assert (cola, "Cola", True) in changed[0].drinks

    asyncio.run(scenario())


def test_the_added_drink_survives_a_restart(settings: Settings, database_url: str) -> None:
    """The rehydrated market holds the new slot, at the state committed."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            await _scripted(market)
            cola = await market.add()
            committed = market.state

            run = await rehydrate(market.engine, now_ms=market.clock.wall_ms())

            assert isinstance(run, RehydratedRun)
            assert run.drink_ids[-1] == cola
            assert run.state.y.tobytes() == committed.y.tobytes()
            assert run.state.version >= committed.version

    asyncio.run(scenario())


def test_a_duplicate_active_name_is_refused_and_changes_nothing(
    settings: Settings, database_url: str
) -> None:
    """AC21 on the live run."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            state = market.state

            try:
                await market.add(name="  BIER ")
            except DuplicateDrinkName:
                pass
            else:
                raise AssertionError("a duplicate name was accepted")

            assert market.state is state
            assert len(market.holder.drink_ids) == 3

    asyncio.run(scenario())


# --- T13: edit on the live run ----------------------------------------------


async def _edit(market: Market, drink_id: int, **fields: Any) -> int:
    return await edit_live_drink(
        market.holder,
        market.run_id,
        drink_id,
        DrinkPatch.model_validate(fields),
        author="Bestuur",
        clock=market.clock,
    )


def test_a_bound_change_holds_the_quote_and_cancels_that_drinks_jump(
    settings: Settings, database_url: str
) -> None:
    """AC8, AC10: clamped and re-quantised; others' `y` bitwise; the jump gone in that version."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            bier, wijn, _ = market.holder.drink_ids
            await schedule(market.holder, bier, 480, 20_000, clock=market.clock)
            await schedule(market.holder, wijn, 450, 120_000, clock=market.clock)
            for _ in range(12):
                await market.tick()
            before = market.state
            assert market.quoted()[bier] > 330
            assert sorted(j.i for j in before.jumps) == [0, 1]  # both still running

            # 3.25 is half a 0.10 step off the grid: clamped, it would round to 3.30,
            # outside the bound, so the hold steps back to 3.20 (AC8, R6).
            await _edit(market, bier, p_max_cents=325)

            after = market.state
            assert after.version == before.version + 1
            assert market.quoted()[bier] == 320
            assert [j.i for j in after.jumps] == [1]  # Wijn's jump stays, Bier's is gone
            assert after.y[1:].tobytes() == before.y[1:].tobytes()

    asyncio.run(scenario())


def test_a_coefficient_p0_or_bar_price_change_moves_no_y(
    settings: Settings, database_url: str
) -> None:
    """AC9."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            bier = market.holder.drink_ids[0]
            await market.tick()
            changes: list[dict[str, Any]] = [
                {"a": 2.0, "s0": 3.0},
                {"p0_cents": 300},
                {"bar_price_cents": 199},
            ]
            for fields in changes:
                y = market.state.y.tobytes()

                await _edit(market, bier, **fields)

                assert market.state.y.tobytes() == y, fields
            assert market.holder.view.bar_price_cents[bier] == 199
            assert market.holder.spec is not None
            assert float(market.holder.spec.p0[0]) == 3.0
            assert float(market.holder.spec.a[0]) == 2.0

    asyncio.run(scenario())


def test_a_live_rename_reaches_the_spec_and_idle_targets(
    settings: Settings, database_url: str
) -> None:
    """AC22 (rename) on the live run, in the same transition."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            bier = market.holder.drink_ids[0]
            await write_live_config(
                market.holder,
                market.run_id,
                ConfigPatch.model_validate({"params": {"idle_targets": [bier]}}),
                author="Bestuur",
                clock=market.clock,
            )

            await _edit(market, bier, name="Pils")

            assert market.holder.spec is not None
            assert market.holder.spec.names[0] == "Pils"
            assert market.holder.spec.params.idle_targets == ("Pils",)
            changed = [e for e in market.events if isinstance(e, ConfigChanged)]
            assert (bier, "Pils", True) in changed[-1].drinks

    asyncio.run(scenario())


# --- T14: remove on the live run ----------------------------------------------


async def _remove(market: Market, drink_id: int) -> int:
    return await remove_live_drink(
        market.holder, market.run_id, drink_id, author="Bestuur", clock=market.clock
    )


async def _ledger(market: Market) -> tuple[int, list[tuple[int, int, int]]]:
    async with market.engine.connect() as conn:
        total: Any = (
            await conn.execute(text("SELECT coalesce(sum(line_total_cents), 0) FROM order_line"))
        ).scalar_one()
        return int(total), await earnings_by_drink(conn, market.run_id)


def _bitwise(state: EngineState) -> tuple[bytes, ...]:
    return (
        state.y.tobytes(),
        state.cum_orders.tobytes(),
        state.flow_ema.tobytes(),
        state.last_order_ts.tobytes(),
    )


def test_the_scripted_borrel_adds_d4_then_removes_d2(settings: Settings, database_url: str) -> None:
    """AC15, AC20, AC21, AC22: orders on three drinks, add D4, remove D2."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            d1, d2, d3 = market.holder.drink_ids
            for i, drink in enumerate((d1, d2, d3, d2, d1)):
                await market.tick()
                await market.order(f"k-borrel-{i:04d}", drink, 1 + i % 2)
            d4 = await market.add(name="Cola")
            await market.tick()
            await write_live_config(
                market.holder,
                market.run_id,
                ConfigPatch.model_validate({"params": {"idle_targets": [d2, d3]}}),
                author="Bestuur",
                clock=market.clock,
            )
            before = market.state
            ledger = await _ledger(market)
            earnings = dict(market.holder.earnings)
            assert earnings[d2].qty > 0

            await _remove(market, d2)

            after = market.state
            i2 = market.holder.drink_ids.index(d2)
            others = [i for i in range(len(market.holder.drink_ids)) if i != i2]
            assert after.y[others].tobytes() == before.y[others].tobytes()
            assert after.version == before.version + 1
            assert await _ledger(market) == ledger
            assert dict(market.holder.earnings) == earnings
            assert market.holder.spec is not None
            assert market.holder.spec.active.tolist() == [True, False, True, True]
            assert market.holder.spec.params.idle_targets == ("Fris",)

            for _ in range(3):
                await market.tick()
            run = await rehydrate(market.engine, now_ms=market.clock.wall_ms())
            assert isinstance(run, RehydratedRun)
            assert run.drink_ids == market.holder.drink_ids == (d1, d2, d3, d4)
            assert run.spec.active.tolist() == [True, False, True, True]
            assert _bitwise(run.state) == _bitwise(market.state)
            assert run.state.version == market.state.version

            again = await market.add(name="Wijn")
            assert again not in (d1, d2, d3, d4)

    asyncio.run(scenario())


def test_a_running_jump_on_a_removed_drink_survives_nowhere(
    settings: Settings, database_url: str
) -> None:
    """AC18, PD17: its own jump and a market event's are cancelled; its `y` stays frozen."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            _, wijn, _ = market.holder.drink_ids
            i = market.holder.drink_ids.index(wijn)
            await start_event(market.holder, "bubble", 10_000, clock=market.clock)
            await schedule(market.holder, wijn, 450, 10_000, clock=market.clock)
            await market.tick()
            assert any(j.i == i for j in market.state.jumps)

            await _remove(market, wijn)

            frozen = market.state.y[i].tobytes()
            assert all(j.i != i for j in market.state.jumps)
            for _ in range(15):  # past both jumps' end
                await market.tick()
                assert market.state.y[i].tobytes() == frozen
                assert all(j.i != i for j in market.state.jumps)

    asyncio.run(scenario())


def test_removing_the_last_active_live_drink_is_refused(
    settings: Settings, database_url: str
) -> None:
    """AC17 on the live run: 409, and nothing changes."""

    async def scenario() -> None:
        async with _live(settings, database_url) as market:
            d1, d2, d3 = market.holder.drink_ids
            await _remove(market, d1)
            await _remove(market, d2)
            state = market.state

            try:
                await _remove(market, d3)
            except LastActiveDrink:
                pass
            else:
                raise AssertionError("the last active drink was removed")

            assert market.state is state
            async with market.engine.connect() as conn:
                removed: Any = (
                    await conn.execute(
                        text("SELECT count(*) FROM drink WHERE removed_at IS NOT NULL")
                    )
                ).scalar_one()
            assert removed == 2

    asyncio.run(scenario())
