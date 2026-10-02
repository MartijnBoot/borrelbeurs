"""Rehydrate: the live run rebuilt from Postgres at boot (T14).

AC4, AC5, AC7, AC8, AC12, AC14, AC17, AC21 end to end; D-01, D-30.
"""

from __future__ import annotations

import asyncio
import builtins
import io
import os
import pathlib
from typing import Any

import numpy as np
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import StateDrinkMismatch, tick_prices
from app.db.engine_state import insert_tick, load_state, save_transition
from app.db.mapping import cents_from_quantised, spec_from_rows
from app.db.market_events import end_event, insert_event
from app.db.orders import OrderLineInput, write_order
from app.db.runs import active_drinks, add_drink, create_draft_run, go_live, set_bar_price
from app.db.session import create_engine
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS
from app.runtime.rehydrate import NoLiveRun, RehydratedRun, rehydrate
from exchange import EngineState, MarketSpec, Params, advance, schedule_jump
from tests.engine.golden.scenarios import LIVE_CONFIG

SEED = 2024
T0 = 1_700_000_000_000
BUDGET = DEFAULT_CATCH_UP_BUDGET_MS
TABLES = ("run", "drink", "engine_state", "price_tick", '"order"', "order_line", "news")


class Injected(Exception):
    """Raised by a listener in place of a statement."""


def assert_states_identical(left: EngineState, right: EngineState) -> None:
    """`EngineState` is `eq=False`; compare every field, floats by their bits."""
    for key in ("y", "cum_orders", "flow_ema"):
        assert getattr(left, key).tobytes() == getattr(right, key).tobytes(), key
    assert left.last_order_ts.tobytes() == right.last_order_ts.tobytes()
    assert [(j.i, j.t0_ms, j.t1_ms) for j in left.jumps] == [
        (j.i, j.t0_ms, j.t1_ms) for j in right.jumps
    ]
    assert np.array([[j.y0, j.y1] for j in left.jumps]).tobytes() == (
        np.array([[j.y0, j.y1] for j in right.jumps]).tobytes()
    )
    for key in ("last_idle_ms", "last_bm_ms", "rng_counter", "version", "tick_index", "t_round"):
        assert getattr(left, key) == getattr(right, key), key


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _draft(engine: AsyncEngine) -> int:
    """A draft run holding the live config's six drinks, in cents, and one news item."""
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, params=Params.from_dict(LIVE_CONFIG["params"]), run_seed=SEED
        )
        for slot, name in enumerate(LIVE_CONFIG["names"]):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=round(LIVE_CONFIG["p_min"][slot] * 100),
                p0_cents=round(LIVE_CONFIG["p0"][slot] * 100),
                p_max_cents=round(LIVE_CONFIG["p_max"][slot] * 100),
                a=LIVE_CONFIG["a"][slot],
                d=LIVE_CONFIG["d"][slot],
                s0=LIVE_CONFIG["s0"][slot],
                c=LIVE_CONFIG["c"][slot],
                bar_price_cents=round(LIVE_CONFIG["p0"][slot] * 100),
            )
        await conn.execute(
            text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, 5, 'info', 'Open')"),
            {"r": run_id},
        )
    return run_id


async def _spec(engine: AsyncEngine, run_id: int) -> tuple[MarketSpec, tuple[int, ...]]:
    async with engine.connect() as conn:
        drinks = await active_drinks(conn, run_id)
    return spec_from_rows(drinks, Params.from_dict(LIVE_CONFIG["params"]))


async def _trade(
    engine: AsyncEngine, run_id: int, steps: int = 12, step_ms: int = 1_000
) -> tuple[MarketSpec, tuple[int, ...], EngineState, int]:
    """Go live, then `steps` transitions: ticks, a jump at step 3, an order at step 5.

    Returns the spec, the drink ids, the last state and its wall time.
    """
    spec, drink_ids = await _spec(engine, run_id)
    state = await go_live(engine, run_id, now_ms=T0)
    wall = T0
    for step in range(1, steps + 1):
        wall = T0 + step * step_ms
        if step == 3:
            candidate = schedule_jump(
                spec, state, drink=2, p_target=6.5, duration_ms=120_000, now_ms=wall
            )
            source = "jump"
        elif step == 5:
            prices = tick_prices(spec, state, drink_ids)
            qtys = {drink_ids[0]: 3, drink_ids[4]: 1}
            orders = np.array([float(qtys.get(d, 0)) for d in drink_ids])
            candidate = advance(spec, state, now_ms=wall, orders=orders, run_seed=SEED).state
            await write_order(
                engine,
                run_id=run_id,
                idempotency_key="k-5",
                expected_version=state.version,
                state=candidate,
                spec=spec,
                drink_ids=drink_ids,
                lines=[
                    OrderLineInput(
                        drink_id=d,
                        qty=q,
                        unit_price_cents=cents_from_quantised(prices[d]["p_q"]),
                        p_cont=prices[d]["p_cont"],
                    )
                    for d, q in qtys.items()
                ],
                wall_ts_ms=wall,
            )
            state = candidate
            continue
        else:
            candidate = advance(spec, state, now_ms=wall, run_seed=SEED).state
            source = "tick"
        await save_transition(
            engine,
            run_id=run_id,
            expected_version=state.version,
            state=candidate,
            spec=spec,
            drink_ids=drink_ids,
            source=source,
            wall_ts_ms=wall,
        )
        state = candidate
    return spec, drink_ids, state, wall


async def _snapshot(engine: AsyncEngine) -> tuple[Any, ...]:
    """Every table's row count, plus every `engine_state` row as JSON text."""
    async with engine.connect() as conn:
        counts = [
            int((await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one())
            for t in TABLES
        ]
        states = (await conn.execute(text("SELECT row_to_json(e)::text FROM engine_state e"))).all()
    return tuple(counts), sorted(tuple(row) for row in states)


async def _stored(engine: AsyncEngine, run_id: int, drink_ids: tuple[int, ...]) -> EngineState:
    async with engine.connect() as conn:
        loaded = await load_state(conn, run_id, drink_ids)
    assert loaded is not None
    return loaded[0]


def test_a_restart_within_the_budget_changes_nothing(settings: Settings, database_url: str) -> None:
    """AC4."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, drink_ids, state, wall = await _trade(engine, run_id)
            before = await _snapshot(engine)

            result = await rehydrate(engine, now_ms=wall + BUDGET)

            assert isinstance(result, RehydratedRun)
            assert (result.run_id, result.run_seed, result.drink_ids) == (run_id, SEED, drink_ids)
            assert_states_identical(result.state, state)
            assert result.state.version == state.version == 12
            assert result.wall_ts_ms == wall
            assert await _snapshot(engine) == before
            assert [e.version for e in result.ring.window()] == list(range(13))
            assert result.earnings.snapshot()[drink_ids[0]].qty == 3
            assert [n.text for n in result.news] == ["Open"]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_long_outage_shifts_every_anchor_and_writes_one_gap_tick(
    settings: Settings, database_url: str
) -> None:
    """AC5: shift `gap - budget`, prices bitwise unchanged, one 'gap' tick at version + 1."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids, state, wall = await _trade(engine, run_id)
            assert state.jumps, "the jump must still be in flight for its anchors to shift"
            now = wall + BUDGET + 600_000

            result = await rehydrate(engine, now_ms=now)

            assert isinstance(result, RehydratedRun)
            shifted = result.state
            assert shifted.y.tobytes() == state.y.tobytes()
            assert tick_prices(spec, shifted, drink_ids) == tick_prices(spec, state, drink_ids)
            assert (shifted.last_order_ts - state.last_order_ts).tolist() == [600_000] * 6
            assert shifted.last_idle_ms - state.last_idle_ms == 600_000
            assert shifted.last_bm_ms - state.last_bm_ms == 600_000
            assert [
                (j.t0_ms - k.t0_ms, j.t1_ms - k.t1_ms)
                for j, k in zip(shifted.jumps, state.jumps, strict=True)
            ] == [(600_000, 600_000)]
            assert (shifted.tick_index, shifted.rng_counter) == (
                state.tick_index,
                state.rng_counter,
            )
            assert shifted.version == state.version + 1
            assert result.wall_ts_ms == now
            assert_states_identical(await _stored(engine, run_id, drink_ids), shifted)

            async with engine.connect() as conn:
                gap_ticks = (
                    await conn.execute(
                        text(
                            "SELECT version, wall_ts_ms FROM price_tick"
                            " WHERE run_id = :r AND source = 'gap'"
                        ),
                        {"r": run_id},
                    )
                ).all()
            assert [tuple(row) for row in gap_ticks] == [(state.version + 1, now)]
            last = result.ring.window()[-1]
            assert (last.version, last.source, last.wall_ts_ms) == (shifted.version, "gap", now)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_failed_gap_write_leaves_neither_change(settings: Settings, database_url: str) -> None:
    """AC5: the tick insert fails, so the anchor shift does not persist either."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)

        def fail_on_tick(*args: Any) -> None:
            if args[2].startswith("INSERT INTO price_tick"):
                raise Injected(args[2])

        try:
            run_id = await _draft(engine)
            _, drink_ids, state, wall = await _trade(engine, run_id)
            before = await _snapshot(engine)

            event.listen(engine.sync_engine, "before_cursor_execute", fail_on_tick)
            try:
                with pytest.raises(Injected):
                    await rehydrate(engine, now_ms=wall + BUDGET + 600_000)
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", fail_on_tick)

            assert await _snapshot(engine) == before
            assert_states_identical(await _stored(engine, run_id, drink_ids), state)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_no_live_run_is_reported_and_nothing_is_written(
    settings: Settings, database_url: str
) -> None:
    """AC7: an empty database, then one holding only a draft."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            empty = await _snapshot(engine)
            assert isinstance(await rehydrate(engine, now_ms=T0), NoLiveRun)
            assert await _snapshot(engine) == empty

            await _draft(engine)
            drafts_only = await _snapshot(engine)
            assert isinstance(await rehydrate(engine, now_ms=T0), NoLiveRun)
            assert await _snapshot(engine) == drafts_only
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_drink_added_behind_the_states_back_raises_naming_it(
    settings: Settings, database_url: str
) -> None:
    """AC8."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, _, _, wall = await _trade(engine, run_id, steps=3)
            async with engine.begin() as conn:
                extra = int(
                    (
                        await conn.execute(
                            text(
                                "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents,"
                                " p0_cents, p_max_cents, a, d, s0, c, bar_price_cents)"
                                " VALUES (:r, 6, 'Extra', 'extra', 100, 200, 300,"
                                " 10, 0.6, 8, 0.4, 200) RETURNING drink_id"
                            ),
                            {"r": run_id},
                        )
                    ).scalar_one()
                )
            before = await _snapshot(engine)

            with pytest.raises(StateDrinkMismatch, match=rf"\b{extra}\b"):
                await rehydrate(engine, now_ms=wall + BUDGET + 600_000)

            assert await _snapshot(engine) == before
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_bar_price_set_before_trading_survives_rehydrate(
    settings: Settings, database_url: str
) -> None:
    """AC12: `set_bar_price`, ten transitions, then rehydrate."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, drink_ids = await _spec(engine, run_id)
            async with engine.begin() as conn:
                await set_bar_price(conn, drink_ids[1], 333)
            _, _, _, wall = await _trade(engine, run_id, steps=10)

            result = await rehydrate(engine, now_ms=wall)

            assert isinstance(result, RehydratedRun)
            assert result.bar_price_cents[drink_ids[1]] == 333
            assert result.bar_price_cents[drink_ids[0]] == round(LIVE_CONFIG["p0"][0] * 100)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_values_follow_their_drink_ids_when_slots_are_swapped(
    settings: Settings, database_url: str
) -> None:
    """AC14."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids, state, wall = await _trade(engine, run_id)
            first, last = drink_ids[0], drink_ids[4]
            async with engine.begin() as conn:
                for drink_id, slot in ((first, 1000), (last, 0), (first, 4)):
                    await conn.execute(
                        text("UPDATE drink SET slot = :s WHERE drink_id = :d"),
                        {"s": slot, "d": drink_id},
                    )

            result = await rehydrate(engine, now_ms=wall)

            assert isinstance(result, RehydratedRun)
            assert result.drink_ids[0] == last and result.drink_ids[4] == first
            names = list(spec.names)
            names[0], names[4] = names[4], names[0]
            assert result.spec.names == tuple(names)
            before = dict(zip(drink_ids, state.y.tolist(), strict=True))
            after = dict(zip(result.drink_ids, result.state.y.tolist(), strict=True))
            assert after == before
            assert {k: v.qty for k, v in result.earnings.snapshot().items()} == {
                first: 3,
                last: 1,
            }
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_reading_the_rehydrated_market_touches_no_database_and_no_file(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC17."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        statements: list[str] = []
        opens: list[str] = []

        def record(*args: Any) -> None:
            statements.append(args[2])

        def refuse(name: str) -> Any:
            def opener(*args: Any, **kwargs: Any) -> Any:
                opens.append(name)
                raise AssertionError(f"{name} called")

            return opener

        try:
            run_id = await _draft(engine)
            _, drink_ids, _, wall = await _trade(engine, run_id)
            result = await rehydrate(engine, now_ms=wall)
            assert isinstance(result, RehydratedRun)

            event.listen(engine.sync_engine, "before_cursor_execute", record)
            with monkeypatch.context() as patch:
                patch.setattr(builtins, "open", refuse("builtins.open"))
                patch.setattr(io, "open", refuse("io.open"))
                patch.setattr(os, "open", refuse("os.open"))
                patch.setattr(pathlib.Path, "open", refuse("pathlib.Path.open"))
                window = result.ring.window()
                earnings = result.earnings.snapshot()
                news = result.news
            event.remove(engine.sync_engine, "before_cursor_execute", record)

            assert (statements, opens) == ([], [])
            assert len(window) == 13
            assert earnings[drink_ids[0]].qty == 3
            assert [n.level for n in news] == ["info"]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_the_ring_holds_exactly_the_committed_ticks_in_the_window(
    settings: Settings, database_url: str
) -> None:
    """AC21: twenty minutes of ticks, a fifteen-minute window, a rolled-back tick absent."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids, state, wall = await _trade(engine, run_id, steps=20, step_ms=60_000)
            async with engine.connect() as conn:
                transaction = await conn.begin()
                ghost = advance(spec, state, now_ms=wall + 60_000, run_seed=SEED).state
                await insert_tick(
                    conn,
                    run_id=run_id,
                    state=ghost,
                    spec=spec,
                    drink_ids=drink_ids,
                    source="tick",
                    wall_ts_ms=wall + 60_000,
                )
                await transaction.rollback()

            result = await rehydrate(engine, now_ms=wall)

            assert isinstance(result, RehydratedRun)
            window = result.ring.window()
            # Latest is T0 + 20 min, so the window opens at T0 + 5 min: versions 5..20.
            assert [e.version for e in window] == list(range(5, 21))
            assert [e.wall_ts_ms for e in window] == [T0 + v * 60_000 for v in range(5, 21)]
            assert ghost.version not in [e.version for e in window]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


# --- Phase 3 T12: market events and the run's grace and candle columns --------


async def _event(engine: AsyncEngine, run_id: int, *, start: int, end: int) -> int:
    async with engine.begin() as conn:
        return await insert_event(
            conn, run_id=run_id, kind="crash", drink_ids=(1, 2), t_start_ms=start, t_end_ms=end
        )


async def _event_rows(engine: AsyncEngine) -> list[tuple[int, int, bool]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT t_start_ms, t_end_ms, ended_at IS NULL FROM market_event ORDER BY event_id"
            )
        )
        return [(int(row[0]), int(row[1]), bool(row[2])) for row in rows]


def test_rehydrate_reads_the_runs_grace_and_candle_interval(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> tuple[int, int, tuple[object, ...]]:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE run SET quote_grace_versions = 3, candle_interval_ms = 30000"
                        " WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            _, _, _, wall = await _trade(engine, run_id)
            result = await rehydrate(engine, now_ms=wall)
            assert isinstance(result, RehydratedRun)
            return result.quote_grace_versions, result.candle_interval_ms, result.market_events
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == (3, 30_000, ())


def test_within_the_budget_active_events_are_rehydrated_unshifted(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, _, _, wall = await _trade(engine, run_id)
            event_id = await _event(engine, run_id, start=wall - 5_000, end=wall + 25_000)
            ended = await _event(engine, run_id, start=wall - 9_000, end=wall - 8_000)
            async with engine.begin() as conn:
                await end_event(conn, ended, t_end_ms=wall - 8_000)

            result = await rehydrate(engine, now_ms=wall + BUDGET)

            assert isinstance(result, RehydratedRun)
            assert [(e.event_id, e.t_start_ms, e.t_end_ms) for e in result.market_events] == [
                (event_id, wall - 5_000, wall + 25_000)
            ]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_long_outage_shifts_active_events_by_exactly_the_jump_anchor_shift(
    settings: Settings, database_url: str
) -> None:
    """AC19a: the event's start and end move as far as the jump's `t0_ms` / `t1_ms`, in memory
    and in the database; an already-ended event does not move."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, _, state, wall = await _trade(engine, run_id)
            assert state.jumps
            await _event(engine, run_id, start=wall - 5_000, end=wall + 25_000)
            ended = await _event(engine, run_id, start=wall - 9_000, end=wall - 8_000)
            async with engine.begin() as conn:
                await end_event(conn, ended, t_end_ms=wall - 8_000)

            result = await rehydrate(engine, now_ms=wall + BUDGET + 600_000)

            assert isinstance(result, RehydratedRun)
            (jump_before,) = state.jumps
            (jump_after,) = result.state.jumps
            moved = jump_after.t0_ms - jump_before.t0_ms
            assert moved == jump_after.t1_ms - jump_before.t1_ms == 600_000
            (event,) = result.market_events
            assert (event.t_start_ms, event.t_end_ms) == (
                wall - 5_000 + moved,
                wall + 25_000 + moved,
            )
            assert await _event_rows(engine) == [
                (wall - 5_000 + moved, wall + 25_000 + moved, True),
                (wall - 9_000, wall - 8_000, False),
            ]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_an_event_that_ended_during_the_outage_stays_active_for_the_ticker(
    settings: Settings, database_url: str
) -> None:
    """Its shifted end is still at or before now; the ticker's first slot ends it (AC19)."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, _, _, wall = await _trade(engine, run_id)
            await _event(engine, run_id, start=wall - 60_000, end=wall - 50_000)
            now = wall + BUDGET + 600_000

            result = await rehydrate(engine, now_ms=now)

            assert isinstance(result, RehydratedRun)
            (event,) = result.market_events
            assert event.t_end_ms <= now
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_failed_event_shift_leaves_neither_the_tick_nor_the_state(
    settings: Settings, database_url: str
) -> None:
    """T12: CAS + gap tick + event shift are one transaction."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)

        def fail_on_event_update(*args: Any) -> None:
            if args[2].startswith("UPDATE market_event"):
                raise Injected(args[2])

        try:
            run_id = await _draft(engine)
            _, drink_ids, state, wall = await _trade(engine, run_id)
            await _event(engine, run_id, start=wall - 5_000, end=wall + 25_000)
            before = await _snapshot(engine), await _event_rows(engine)

            event.listen(engine.sync_engine, "before_cursor_execute", fail_on_event_update)
            try:
                with pytest.raises(Injected):
                    await rehydrate(engine, now_ms=wall + BUDGET + 600_000)
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", fail_on_event_update)

            assert (await _snapshot(engine), await _event_rows(engine)) == before
            assert_states_identical(await _stored(engine, run_id, drink_ids), state)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
