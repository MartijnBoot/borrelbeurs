"""Engine-state persistence: go-live, compare-and-set save, load (T8).

AC3 (bit-exact through the database), AC13 (compare-and-set half), AC14,
AC22 (repository path); SD6, SD9, SD10; PD14.
"""

from __future__ import annotations

import asyncio
import dataclasses

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.engine_state import StaleState, load_state, load_ticks_in_window, save_transition
from app.db.mapping import spec_from_rows
from app.db.runs import (
    LiveRunExists,
    RunNotDraft,
    RunNotFound,
    RunNotReady,
    active_drinks,
    add_drink,
    create_draft_run,
    go_live,
)
from app.db.session import create_engine
from exchange import EngineState, MarketSpec, Params, advance, schedule_jump
from tests.engine.golden.scenarios import LIVE_CONFIG

SEED = 2024
T0 = 1_700_000_000_000


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


async def _draft(engine: AsyncEngine, params: Params | None = None, *, drinks: bool = True) -> int:
    """A draft run holding the live config's six drinks, in cents."""
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn,
            name="Borrel",
            params=params or Params.from_dict(LIVE_CONFIG["params"]),
            run_seed=SEED,
        )
        for slot, name in enumerate(LIVE_CONFIG["names"] if drinks else ()):
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
    return run_id


async def _spec(engine: AsyncEngine, run_id: int) -> tuple[MarketSpec, tuple[int, ...]]:
    async with engine.connect() as conn:
        drinks = await active_drinks(conn, run_id)
    return spec_from_rows(drinks, Params.from_dict(LIVE_CONFIG["params"]))


async def _count(engine: AsyncEngine, sql: str, run_id: int) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(sql), {"r": run_id})).scalar_one())


async def _trade(
    engine: AsyncEngine, run_id: int, spec: MarketSpec, drink_ids: tuple[int, ...]
) -> tuple[EngineState, int]:
    """Go live, then twenty saved transitions: ticks, one order vector, one jump."""
    state = await go_live(engine, run_id, now_ms=T0)
    now = T0
    for step in range(1, 21):
        now = T0 + step * 1_000
        if step == 7:
            candidate = schedule_jump(
                spec, state, drink=3, p_target=4.4, duration_ms=30_000, now_ms=now
            )
            source = "jump"
        elif step == 12:
            orders = np.array([2.0, 0.0, 1.0, 0.0, 3.0, 0.0])
            candidate = advance(spec, state, now_ms=now, orders=orders, run_seed=SEED).state
            source = "order"
        else:
            candidate = advance(spec, state, now_ms=now, run_seed=SEED).state
            source = "tick"
        await save_transition(
            engine,
            run_id=run_id,
            expected_version=state.version,
            state=candidate,
            spec=spec,
            drink_ids=drink_ids,
            source=source,
            wall_ts_ms=now,
        )
        state = candidate
    return state, now


def test_a_saved_state_loads_back_bit_identical(settings: Settings, database_url: str) -> None:
    """AC3: twenty transitions through the database, and the next step agrees."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids = await _spec(engine, run_id)
            in_memory, last_wall = await _trade(engine, run_id, spec, drink_ids)

            async with engine.connect() as conn:
                loaded = await load_state(conn, run_id, drink_ids)
            assert loaded is not None
            state, wall_ts_ms = loaded

            assert wall_ts_ms == last_wall
            assert state.version == 20 and len(state.jumps) == 1
            assert_states_identical(state, in_memory)
            nxt = [
                advance(spec, s, now_ms=last_wall + 1_000, run_seed=SEED).state
                for s in (state, in_memory)
            ]
            assert_states_identical(nxt[0], nxt[1])
            assert (
                await _count(engine, "SELECT count(*) FROM price_tick WHERE run_id = :r", run_id)
                == 21
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_swapping_slots_keeps_every_drinks_own_state(settings: Settings, database_url: str) -> None:
    """AC14: a slot swap between save and load moves no value onto another drink."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids = await _spec(engine, run_id)
            saved, _ = await _trade(engine, run_id, spec, drink_ids)
            first, last = drink_ids[0], drink_ids[4]

            async with engine.begin() as conn:
                for drink_id, slot in ((first, 1000), (last, 0), (first, 4)):
                    await conn.execute(
                        text("UPDATE drink SET slot = :s WHERE drink_id = :d"),
                        {"s": slot, "d": drink_id},
                    )

            new_spec, new_ids = await _spec(engine, run_id)
            assert new_ids[0] == last and new_ids[4] == first
            async with engine.connect() as conn:
                loaded = await load_state(conn, run_id, new_ids)
            assert loaded is not None
            state, _ = loaded

            for new_position, drink_id in enumerate(new_ids):
                old_position = drink_ids.index(drink_id)
                for key in ("y", "cum_orders", "flow_ema"):
                    assert (
                        getattr(state, key)[new_position].tobytes()
                        == getattr(saved, key)[old_position].tobytes()
                    ), (key, drink_id)
                assert state.last_order_ts[new_position] == saved.last_order_ts[old_position]
            for jump, saved_jump in zip(state.jumps, saved.jumps, strict=True):
                assert new_ids[jump.i] == drink_ids[saved_jump.i]
            assert new_spec.names[0] == spec.names[4]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_second_live_run_is_rejected_and_the_first_stays_live(
    settings: Settings, database_url: str
) -> None:
    """AC22 (repository path), SD6."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            first = await _draft(engine)
            second = await _draft(engine)
            await go_live(engine, first, now_ms=T0)

            with pytest.raises(LiveRunExists) as raised:
                await go_live(engine, second, now_ms=T0)
            assert raised.value.status_code == 409

            async with engine.connect() as conn:
                statuses: dict[int, str] = dict(
                    (await conn.execute(text("SELECT run_id, status FROM run"))).all()
                )
            assert statuses == {first: "live", second: "draft"}
            assert (
                await _count(engine, "SELECT count(*) FROM engine_state WHERE run_id = :r", second)
                == 0
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_go_live_writes_the_initial_state_and_a_reset_tick(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, drink_ids = await _spec(engine, run_id)
            state = await go_live(engine, run_id, now_ms=T0)

            async with engine.connect() as conn:
                loaded = await load_state(conn, run_id, drink_ids)
                ticks = await load_ticks_in_window(conn, run_id, 15 * 60_000)
                started: bool = (
                    await conn.execute(
                        text("SELECT started_at IS NOT NULL FROM run WHERE run_id = :r"),
                        {"r": run_id},
                    )
                ).scalar_one()
            assert loaded is not None
            assert_states_identical(loaded[0], state)
            assert loaded[1] == T0 and state.version == 0
            assert started is True
            assert [(t.version, t.source, t.wall_ts_ms) for t in ticks] == [(0, "reset", T0)]
            assert set(ticks[0].prices) == set(drink_ids)
            assert ticks[0].prices[drink_ids[0]]["p_q"] == LIVE_CONFIG["p0"][0]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_racing_saves_commit_exactly_one(settings: Settings, database_url: str) -> None:
    """SD9 under READ COMMITTED: one wins, the other raises `StaleState`, one new tick."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids = await _spec(engine, run_id)
            state = await go_live(engine, run_id, now_ms=T0)
            candidates = [
                advance(spec, state, now_ms=T0 + 1_000, run_seed=SEED).state,
                advance(spec, state, now_ms=T0 + 1_000, orders=np.ones(6), run_seed=SEED).state,
            ]

            results = await asyncio.gather(
                *(
                    save_transition(
                        engine,
                        run_id=run_id,
                        expected_version=0,
                        state=candidate,
                        spec=spec,
                        drink_ids=drink_ids,
                        source=source,
                        wall_ts_ms=T0 + 1_000,
                    )
                    for candidate, source in zip(candidates, ("tick", "order"), strict=True)
                ),
                return_exceptions=True,
            )

            assert sorted(type(r).__name__ for r in results) == ["NoneType", "StaleState"]
            winner = candidates[results.index(None)]
            async with engine.connect() as conn:
                loaded = await load_state(conn, run_id, drink_ids)
                ticks = await load_ticks_in_window(conn, run_id, 60_000)
            assert loaded is not None
            assert_states_identical(loaded[0], winner)
            assert [t.version for t in ticks] == [0, 1]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_stale_expected_version_writes_nothing(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            spec, drink_ids = await _spec(engine, run_id)
            state = await go_live(engine, run_id, now_ms=T0)
            candidate = advance(spec, state, now_ms=T0 + 1_000, run_seed=SEED).state

            with pytest.raises(StaleState, match="version 5") as raised:
                await save_transition(
                    engine,
                    run_id=run_id,
                    expected_version=5,
                    state=dataclasses.replace(candidate, version=6),
                    spec=spec,
                    drink_ids=drink_ids,
                    source="tick",
                    wall_ts_ms=T0 + 1_000,
                )
            assert raised.value.status_code == 409

            async with engine.connect() as conn:
                loaded = await load_state(conn, run_id, drink_ids)
            assert loaded is not None
            assert_states_identical(loaded[0], state)
            assert (
                await _count(engine, "SELECT count(*) FROM price_tick WHERE run_id = :r", run_id)
                == 1
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_load_ticks_in_window_keeps_the_window_and_orders_by_version(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            await go_live(engine, run_id, now_ms=T0)
            async with engine.begin() as conn:
                for version, offset_min in ((3, 20), (1, 4), (2, 5)):
                    await conn.execute(
                        text(
                            "INSERT INTO price_tick (run_id, version, source, prices, wall_ts_ms)"
                            " VALUES (:r, :v, 'tick', '{}', :w)"
                        ),
                        {"r": run_id, "v": version, "w": T0 + offset_min * 60_000},
                    )
            async with engine.connect() as conn:
                ticks = await load_ticks_in_window(conn, run_id, 15 * 60_000)
                empty = await load_ticks_in_window(conn, run_id + 1, 15 * 60_000)

            assert [t.version for t in ticks] == [2, 3]
            assert empty == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_load_state_of_a_draft_run_is_none(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine)
            _, drink_ids = await _spec(engine, run_id)
            async with engine.connect() as conn:
                assert await load_state(conn, run_id, drink_ids) is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["live", "no_drinks", "ended"])
def test_go_live_rejections_write_nothing(settings: Settings, database_url: str, case: str) -> None:
    """A live or ended run, or zero drinks, raise. `auto_calibrate_s0` goes live (Phase 6 SD3)."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id = await _draft(engine, None, drinks=case != "no_drinks")
            expected_ticks = 0
            if case == "live":
                await go_live(engine, run_id, now_ms=T0)
                expected_ticks = 1
            if case == "ended":
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE run SET status = 'ended' WHERE run_id = :r"), {"r": run_id}
                    )

            expected: dict[str, tuple[type[Exception], str]] = {
                "live": (RunNotDraft, "live"),
                "ended": (RunNotDraft, "ended"),
                "no_drinks": (RunNotReady, "drink"),
            }
            error, named = expected[case]
            with pytest.raises(error, match=named):
                await go_live(engine, run_id, now_ms=T0 + 5_000)

            ticks = await _count(
                engine, "SELECT count(*) FROM price_tick WHERE run_id = :r", run_id
            )
            assert ticks == expected_ticks
            if case == "no_drinks":
                assert (
                    await _count(
                        engine,
                        "SELECT count(*) FROM run WHERE run_id = :r AND status = 'draft' "
                        "AND started_at IS NULL",
                        run_id,
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_go_live_on_an_unknown_run_raises(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            with pytest.raises(RunNotFound, match="424242"):
                await go_live(engine, 424242, now_ms=T0)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
