"""`exchange.advance`: AC4, the D9 counters, the `next_due_ms` contract, D12 (Phase 1 plan T7)."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import numpy as np
import pytest

from exchange import (
    AdvanceResult,
    EngineState,
    MarketSpec,
    advance,
    next_due_ms,
    schedule_jump,
)
from tests.engine.golden import replay
from tests.engine.golden.scenarios import LIVE_CONFIG, STELZ

NOW = 1_759_312_800_000
SECOND = 1_000
SEED = 20261001


def _live(**params: Any) -> tuple[MarketSpec, EngineState]:
    config = copy.deepcopy(LIVE_CONFIG)
    config["params"].update(params)
    return replay.start(config, NOW)


def _fields(obj: Any) -> dict[str, Any]:
    return {f.name: copy.deepcopy(getattr(obj, f.name)) for f in dataclasses.fields(obj)}


def _assert_unchanged(before: dict[str, Any], obj: Any) -> None:
    for name, value in before.items():
        now = getattr(obj, name)
        if isinstance(value, np.ndarray):
            assert now.dtype == value.dtype and np.array_equal(now, value), name
        else:
            assert now == value, name


# --- AC4: advance never mutates its arguments ----------------------------------------------


def _ac4_cases() -> list[Any]:
    spec, state = _live(idle_targets=["Stelz"])
    jumping = schedule_jump(spec, state, drink=STELZ, p_target=4.0, duration_ms=60_000, now_ms=NOW)
    return [
        pytest.param(spec, state, np.array([2.0, 0, 1, 0, 0, 1]), NOW + 500, id="orders"),
        pytest.param(spec, state, None, NOW + 30 * SECOND, id="tick-idle-fires"),
        pytest.param(spec, jumping, np.array([0, 0, 3.0, 0, 0, 0]), NOW + 20 * SECOND, id="jump"),
        pytest.param(spec, state, None, NOW, id="brownian-fires"),
    ]


@pytest.mark.parametrize(("spec", "state", "orders", "now"), _ac4_cases())
def test_ac4_advance_leaves_spec_and_state_unchanged(
    spec: MarketSpec, state: EngineState, orders: Any, now: int
) -> None:
    spec_before, state_before = _fields(spec), _fields(state)
    orders_before = None if orders is None else orders.copy()
    result = advance(spec, state, now_ms=now, orders=orders, run_seed=SEED)
    assert result.state is not state
    _assert_unchanged(spec_before, spec)
    _assert_unchanged(state_before, state)
    if orders_before is not None:
        assert np.array_equal(orders, orders_before)


def test_the_brownian_case_really_draws() -> None:
    """Anti-vacuity for the AC4 case named for it."""
    spec, state = _live()
    assert advance(spec, state, now_ms=NOW, run_seed=SEED).state.rng_counter == 1


# --- D9: three counters -------------------------------------------------------------------


def test_a_tick_bumps_version_and_tick_index() -> None:
    spec, state = _live()
    got = advance(spec, state, now_ms=NOW + 500, run_seed=SEED).state
    assert (got.version, got.tick_index) == (state.version + 1, state.tick_index + 1)


def test_an_order_bumps_version_and_t_round_but_not_tick_index() -> None:
    spec, state = _live()
    result = advance(spec, state, now_ms=NOW + 500, orders=np.ones(6), run_seed=SEED)
    got = result.state
    assert (got.version, got.tick_index, got.t_round) == (1, 0, 1)
    assert result.diagnostics is not None


def test_a_tick_has_no_order_diagnostics() -> None:
    spec, state = _live()
    assert advance(spec, state, now_ms=NOW, run_seed=SEED).diagnostics is None


def test_rng_counter_moves_only_when_brownian_draws() -> None:
    spec, state = _live()
    first = advance(spec, state, now_ms=NOW, run_seed=SEED).state  # anchors start at 0
    assert first.rng_counter == 1
    later = advance(spec, first, now_ms=NOW + 59_999, run_seed=SEED).state
    assert later.rng_counter == 1
    assert advance(spec, later, now_ms=NOW + 60_000, run_seed=SEED).state.rng_counter == 2


def test_advance_returns_an_advance_result() -> None:
    spec, state = _live()
    assert isinstance(advance(spec, state, now_ms=NOW, run_seed=SEED), AdvanceResult)


# --- D12: orders validated at the boundary -------------------------------------------------


@pytest.mark.parametrize(
    "orders",
    [
        pytest.param(np.ones(5), id="too-short"),
        pytest.param(np.ones(7), id="too-long"),
        pytest.param(np.ones((6, 1)), id="two-dimensional"),
        pytest.param(np.array([1.0, -1, 0, 0, 0, 0]), id="negative"),
        pytest.param(np.array([1.0, np.nan, 0, 0, 0, 0]), id="nan"),
        pytest.param(np.array([1.0, np.inf, 0, 0, 0, 0]), id="inf"),
        pytest.param(["a", 0, 0, 0, 0, 0], id="not-numbers"),
    ],
)
def test_invalid_orders_raise(orders: Any) -> None:
    spec, state = _live()
    with pytest.raises(ValueError, match="orders"):
        advance(spec, state, now_ms=NOW, orders=orders, run_seed=SEED)


def test_a_valid_order_list_is_accepted() -> None:
    spec, state = _live()
    advance(spec, state, now_ms=NOW, orders=[1, 0, 0, 0, 0, 2], run_seed=SEED)


# --- next_due_ms ------------------------------------------------------------------------------


def _evolved(rng: np.random.Generator) -> tuple[MarketSpec, EngineState, int]:
    """A random live-like market after a random stretch of real trading."""
    config = copy.deepcopy(LIVE_CONFIG)
    names = config["names"]
    config["params"].update(
        refresh_minutes=float(rng.choice([0.05, 0.2, 1.0])),
        bm_dt_minutes=float(rng.choice([0.1, 0.5, 1.0])),
        bm_enabled=bool(rng.random() < 0.8),
        bm_sigma_y=float(rng.choice([0.0, 0.18])),
        idle_targets=[nm for nm in names if rng.random() < 0.3],
        idle_rise_targets=[nm for nm in names if rng.random() < 0.3],
    )
    spec, state = replay.start(config, NOW)
    t = NOW
    for _ in range(int(rng.integers(1, 25))):
        t += int(rng.integers(0, 20 * SECOND))
        event: dict[str, Any] = {"kind": "tick", "t": t}
        if rng.random() < 0.4:
            event = {"kind": "order", "t": t, "vec": rng.integers(0, 4, 6).astype(float).tolist()}
        elif rng.random() < 0.03:
            event = {
                "kind": "jump",
                "t": t,
                "drink": int(rng.integers(0, 6)),
                "target": float(rng.uniform(0, 12)),
                "duration_ms": int(rng.integers(1, 60 * SECOND)),
            }
        state = replay.step(spec, state, event, SEED)
    return spec, state, t


def _schedule(state: EngineState) -> tuple[Any, ...]:
    return (state.y.tolist(), state.last_idle_ms, state.last_bm_ms, state.rng_counter)


def test_next_due_ms_contract_over_random_markets() -> None:
    """Before `next_due_ms`, a tick changes no price and fires nothing; at it, something fires."""
    rng = np.random.default_rng(77)
    checked = 0
    for case in range(1000):
        spec, state, t = _evolved(rng)
        due = next_due_ms(spec, state)
        if state.jumps:
            assert due == min(j.t0_ms for j in state.jumps) <= t, case
            continue
        assert due > t, case
        for now in {t, t + 1, (t + due) // 2, due - 1}:
            if now < due:
                quiet = advance(spec, state, now_ms=now, run_seed=SEED).state
                assert _schedule(quiet) == _schedule(state), (case, now)
        fired = advance(spec, state, now_ms=due, run_seed=SEED).state
        assert (fired.last_idle_ms, fired.last_bm_ms) != (state.last_idle_ms, state.last_bm_ms)
        checked += 1
    assert checked >= 800


def test_next_due_ms_is_the_earliest_of_idle_and_brownian() -> None:
    spec, state = _live(refresh_minutes=0.2, bm_dt_minutes=1.0)
    state = dataclasses.replace(state, last_idle_ms=NOW, last_bm_ms=NOW)
    assert next_due_ms(spec, state) == NOW + 12 * SECOND
    spec, state = _live(refresh_minutes=2.0, bm_dt_minutes=1.0)
    state = dataclasses.replace(state, last_idle_ms=NOW, last_bm_ms=NOW)
    assert next_due_ms(spec, state) == NOW + 60 * SECOND


def test_next_due_ms_ignores_a_disabled_brownian() -> None:
    spec, state = _live(refresh_minutes=2.0, bm_dt_minutes=1.0, bm_enabled=False)
    state = dataclasses.replace(state, last_idle_ms=NOW, last_bm_ms=NOW)
    assert next_due_ms(spec, state) == NOW + 120 * SECOND


def test_next_due_ms_is_now_while_a_jump_is_running() -> None:
    spec, state = _live()
    state = dataclasses.replace(state, last_idle_ms=NOW, last_bm_ms=NOW)
    jumping = schedule_jump(
        spec, state, drink=STELZ, p_target=4.0, duration_ms=60_000, now_ms=NOW + 5
    )
    assert next_due_ms(spec, jumping) == NOW + 5
