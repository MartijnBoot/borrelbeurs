"""`exchange.state`: frozen `EngineState` and `PriceJump` (Phase 1 plan T3, D4, D14)."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import numpy as np
import pytest

from exchange.spec import MarketSpec, Params
from exchange.state import (
    EngineState,
    PriceJump,
    initial_state,
    retarget_y_to_hold_quantized_prices,
)
from tests.engine.golden.scenarios import DEFAULT_CONFIG, LIVE_CONFIG
from tests.engine.v1_reference import engine as v1

NOW = 1_759_312_800_000
CONFIGS = [pytest.param(LIVE_CONFIG, id="live"), pytest.param(DEFAULT_CONFIG, id="default")]
STATE_ARRAYS = ("y", "cum_orders", "flow_ema", "last_order_ts")


def _v1_init(config: dict[str, Any], now_ms: int) -> Any:
    original = v1.now_ms
    v1.now_ms = lambda: now_ms
    try:
        return v1.ExchangeState.from_persist(copy.deepcopy(config))
    finally:
        v1.now_ms = original


def _spec(config: dict[str, Any]) -> MarketSpec:
    st = _v1_init(config, NOW)
    return MarketSpec(
        names=tuple(st.names),
        p_min=st.p_min,
        p_max=st.p_max,
        p0=st.p0,
        a=st.a,
        d=st.d,
        s0=st.s0,
        c=st.c,
        params=Params.from_dict(config.get("params", {})),
    )


@pytest.mark.parametrize("config", CONFIGS)
def test_initial_state_reproduces_v1_init(config: dict[str, Any]) -> None:
    st = _v1_init(config, NOW)
    state = initial_state(_spec(config), now_ms=NOW)
    assert np.array_equal(state.y, st.y)
    assert np.array_equal(state.cum_orders, st.cum_orders)
    assert np.array_equal(state.flow_ema, st.flow_ema)
    assert np.array_equal(state.last_order_ts, st.last_order_ts)
    assert state.last_order_ts.dtype == np.int64
    assert (state.last_idle_ms, state.last_bm_ms) == (st.last_idle_apply_ms, st.last_bm_ts_ms)
    assert state.t_round == st.t_round == 0
    assert state.jumps == ()


def test_initial_state_starts_every_counter_at_zero() -> None:
    state = initial_state(_spec(LIVE_CONFIG), now_ms=NOW)
    assert (state.version, state.tick_index, state.rng_counter, state.t_round) == (0, 0, 0, 0)


def test_initial_state_does_not_auto_calibrate() -> None:
    """The caller anchors s0 itself (anchor_s0_to_current_y); state never touches the spec."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["params"] = {"auto_calibrate_s0": True}
    spec = _spec(config)
    before = spec.s0.copy()
    initial_state(spec, now_ms=NOW)
    assert np.array_equal(spec.s0, before)


@pytest.mark.parametrize("config", CONFIGS)
def test_retarget_matches_v1(config: dict[str, Any]) -> None:
    rng = np.random.default_rng(3)
    spec = _spec(config)
    st = _v1_init(config, NOW)
    state = initial_state(spec, now_ms=NOW)
    for _ in range(1000):
        y = rng.uniform(-8.0, 8.0, len(spec.names))
        st.y = y.copy()
        st.retarget_y_to_hold_quantized_prices()
        got = retarget_y_to_hold_quantized_prices(spec, dataclasses.replace(state, y=y))
        assert np.array_equal(got.y, st.y)


def test_retarget_returns_a_new_state_and_leaves_the_old_one_alone() -> None:
    spec = _spec(LIVE_CONFIG)
    state = dataclasses.replace(initial_state(spec, now_ms=NOW), y=np.full(6, 0.37))
    got = retarget_y_to_hold_quantized_prices(spec, state)
    assert got is not state
    assert np.array_equal(state.y, np.full(6, 0.37))


def test_every_state_array_is_read_only() -> None:
    state = initial_state(_spec(LIVE_CONFIG), now_ms=NOW)
    for key in STATE_ARRAYS:
        with pytest.raises(ValueError, match="read-only"):
            getattr(state, key)[0] = 0


def test_state_and_jump_are_frozen() -> None:
    state = initial_state(_spec(LIVE_CONFIG), now_ms=NOW)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.version = 1  # type: ignore[misc]
    jump = PriceJump(i=0, y0=0.0, y1=1.0, t0_ms=0, t1_ms=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        jump.y1 = 2.0  # type: ignore[misc]


def test_the_state_does_not_alias_its_inputs() -> None:
    y = np.zeros(2)
    state = EngineState(
        y=y,
        cum_orders=np.zeros(2),
        flow_ema=np.zeros(2),
        last_order_ts=np.zeros(2, dtype=np.int64),
        jumps=(),
        last_idle_ms=0,
        last_bm_ms=0,
        rng_counter=0,
        version=0,
        tick_index=0,
        t_round=0,
    )
    y[0] = 5.0
    assert state.y[0] == 0.0


def test_jumps_are_held_as_a_tuple() -> None:
    state = initial_state(_spec(LIVE_CONFIG), now_ms=NOW)
    jump = PriceJump(i=2, y0=0.0, y1=1.0, t0_ms=NOW, t1_ms=NOW + 60_000)
    moved = dataclasses.replace(state, jumps=[jump])  # type: ignore[arg-type]
    assert moved.jumps == (jump,)
