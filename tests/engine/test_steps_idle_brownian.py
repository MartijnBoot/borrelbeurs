"""`exchange.steps.apply_idle` and `apply_brownian` (Phase 1 plan T6, D1, D-22, D-23).

The v1 reference is driven with the capture's counter-seeded RNG shim (D1), so
"bitwise vs v1" includes the noise: draw k of both engines comes from
`default_rng(SeedSequence([run_seed, k]))`.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import numpy as np
import pytest

from exchange.pricing import FloatArray
from exchange.spec import MarketSpec, Params
from exchange.state import EngineState, initial_state
from exchange.steps import _normal, apply_brownian, apply_idle, apply_jumps, schedule_jump
from tests.engine.golden.capture import CounterRng
from tests.engine.golden.scenarios import FRIS, LIVE_CONFIG, STELZ
from tests.engine.v1_reference import engine as v1

NOW = 1_759_312_800_000
MINUTE = 60_000


def _live_spec(**params: Any) -> MarketSpec:
    st = v1.ExchangeState.from_persist(copy.deepcopy(LIVE_CONFIG))
    return MarketSpec(
        names=tuple(st.names),
        **{k: getattr(st, k) for k in ("p_min", "p_max", "p0", "a", "d", "s0", "c")},
        params=Params.from_dict({**LIVE_CONFIG["params"], **params}),
    )


# --- matched random cases ------------------------------------------------------------


def _random_case(
    rng: np.random.Generator,
) -> tuple[MarketSpec, EngineState, dict[str, Any], int]:
    n = int(rng.integers(2, 8))
    names = [f"d{i}" for i in range(n)]
    p_min = np.round(rng.uniform(0.5, 8.0, n), 2)
    p_max = p_min + np.round(rng.uniform(1.0, 6.0, n), 2)
    p0 = p_min + (p_max - p_min) * rng.uniform(0.1, 0.9, n)
    coeffs = {k: rng.uniform(0.0, 12.0, n) if rng.random() < 0.5 else np.zeros(n) for k in "adsc"}

    def targets() -> list[str]:
        picked = [nm for nm in names if rng.random() < 0.4]
        return picked + (["ghost"] if rng.random() < 0.1 else [])  # unknown names are skipped

    params = {
        "step_quant": float(rng.choice([0.05, 0.1, 0.5])),
        "lambda_orders": float(rng.uniform(0.0, 2.0)),
        "eta": float(rng.uniform(0.1, 1.5)),
        "K": float(rng.uniform(0.5, 15.0)),
        "phi_persist": float(rng.uniform(0.0, 0.3)),
        "refresh_minutes": float(rng.choice([0.0, 0.2, 1.0])),
        "idle_decay_minutes": float(rng.choice([0.0, 0.1, 2.0])),
        "idle_strength": float(rng.uniform(-2.0, 2.0)),
        "idle_targets": targets(),
        "idle_rise_minutes": float(rng.choice([0.0, 0.1, 2.0])),
        "idle_rise_strength": float(rng.uniform(-2.0, 2.0)),
        "idle_rise_targets": targets(),
        "bm_enabled": bool(rng.random() < 0.85),
        "bm_dt_minutes": float(rng.choice([0.0, 0.5, 1.0])),
        "bm_sigma_y": float(rng.choice([0.0, 0.18, 0.5])) if rng.random() < 0.9 else -0.1,
        "flow_vol_amp": float(rng.uniform(0.0, 1.5)),
        "y_clip": float(rng.choice([3.0, 6.0])),
        "demand_enabled": bool(rng.random() < 0.5),
    }
    spec = MarketSpec(
        names=tuple(names),
        p_min=p_min,
        p_max=p_max,
        p0=p0,
        a=coeffs["a"],
        d=coeffs["d"],
        s0=coeffs["s"],
        c=coeffs["c"],
        params=Params.from_dict(params),
    )
    now = NOW + int(rng.integers(0, 10 * MINUTE))
    state = EngineState(
        y=rng.uniform(-8.0, 8.0, n),
        cum_orders=rng.uniform(-30.0, 60.0, n),
        flow_ema=rng.uniform(0.0, 6.0, n),
        last_order_ts=NOW - rng.integers(0, 5 * MINUTE, n),
        jumps=(),
        last_idle_ms=int(rng.choice([0, now - int(rng.integers(0, 2 * MINUTE))])),
        last_bm_ms=int(rng.choice([0, now - int(rng.integers(0, 2 * MINUTE))])),
        rng_counter=int(rng.integers(0, 50)),
        version=0,
        tick_index=0,
        t_round=int(rng.integers(0, 100)),
    )
    return spec, state, params, now


def _v1_twin(spec: MarketSpec, state: EngineState, params: dict[str, Any], run_seed: int) -> Any:
    st = v1.ExchangeState.init(
        list(spec.names),
        *(np.array(getattr(spec, k)) for k in ("p_min", "p_max", "p0", "a", "d", "s0", "c")),
        v1.Params.from_dict(copy.deepcopy(params)),
    )
    st.y = np.array(state.y)
    st.cum_orders = np.array(state.cum_orders)
    st.flow_ema = np.array(state.flow_ema)
    st.last_order_ts = np.array(state.last_order_ts)
    st.last_idle_apply_ms = state.last_idle_ms
    st.last_bm_ts_ms = state.last_bm_ms
    st.t_round = state.t_round
    st.rng = CounterRng(run_seed)
    st.rng.counter = state.rng_counter
    return st


def _at(now: int) -> Any:
    original = v1.now_ms

    class _Clock:
        def __enter__(self) -> None:
            v1.now_ms = lambda: now

        def __exit__(self, *exc: object) -> None:
            v1.now_ms = original

    return _Clock()


def _assert_same(got: EngineState, st: Any, case: int) -> None:
    assert np.array_equal(got.y, st.y), case
    assert np.array_equal(got.cum_orders, st.cum_orders), case
    assert np.array_equal(got.flow_ema, st.flow_ema), case
    assert got.last_idle_ms == st.last_idle_apply_ms, case
    assert got.last_bm_ms == st.last_bm_ts_ms, case
    assert got.t_round == st.t_round, case
    assert got.rng_counter == st.rng.counter, case


def test_apply_idle_matches_v1_bitwise() -> None:
    rng = np.random.default_rng(66)
    adjusted = 0
    for case in range(600):
        spec, state, params, now = _random_case(rng)
        st = _v1_twin(spec, state, params, run_seed=case)
        with _at(now):
            st.apply_idle_adjust_if_needed()
        got = apply_idle(spec, state, now_ms=now)
        _assert_same(got, st, case)
        adjusted += int(got.t_round > state.t_round)
    assert adjusted >= 100, "the random cases must reach the adjusting branch"


def test_apply_brownian_matches_v1_bitwise() -> None:
    rng = np.random.default_rng(67)
    drawn = 0
    for case in range(600):
        spec, state, params, now = _random_case(rng)
        st = _v1_twin(spec, state, params, run_seed=case)
        with _at(now):
            st.apply_bm_if_needed()
        got = apply_brownian(spec, state, now_ms=now, run_seed=case)
        _assert_same(got, st, case)
        drawn += int(got.rng_counter > state.rng_counter)
    assert drawn >= 100, "the random cases must reach the drawing branch"


# --- D-22: the idle gate is refresh_minutes ------------------------------------------------


def test_d22_idle_fires_on_the_refresh_boundary_not_the_idle_threshold() -> None:
    spec = _live_spec(refresh_minutes=1.0, idle_decay_minutes=0.1, idle_targets=["Stelz"])
    state = dataclasses.replace(initial_state(spec, now_ms=NOW - 10 * MINUTE), last_idle_ms=NOW)
    # Stelz has been idle for 10 minutes, far past idle_decay_minutes (6 s) ...
    early = apply_idle(spec, state, now_ms=NOW + MINUTE - 1)
    assert np.array_equal(early.y, state.y)
    assert early.last_idle_ms == NOW
    # ... but nothing happens until refresh_minutes has elapsed since the last idle step.
    due = apply_idle(spec, state, now_ms=NOW + MINUTE)
    assert due.y[STELZ] < state.y[STELZ]
    assert due.t_round == state.t_round + 1
    assert due.last_idle_ms == NOW + MINUTE


def test_idle_skips_a_drink_ordered_within_its_threshold() -> None:
    spec = _live_spec(idle_targets=["Stelz"], idle_rise_targets=["Fris"])
    state = initial_state(spec, now_ms=NOW)  # everything "last ordered" at NOW
    got = apply_idle(spec, state, now_ms=NOW + 5_999)  # idle_*_minutes = 0.1 = 6 s
    assert np.array_equal(got.y, state.y)
    assert got.t_round == state.t_round
    assert got.last_idle_ms == NOW + 5_999


def test_idle_decay_pushes_down_and_idle_rise_pushes_up() -> None:
    spec = _live_spec(idle_targets=["Stelz"], idle_rise_targets=["Fris"])
    state = initial_state(spec, now_ms=NOW)
    got = apply_idle(spec, state, now_ms=NOW + MINUTE)
    assert got.y[STELZ] < state.y[STELZ]
    assert got.y[FRIS] > state.y[FRIS]


# --- D-23: flow_ema is moved by orders only -------------------------------------------------


def test_d23_flow_ema_is_unchanged_by_idle_and_brownian() -> None:
    spec = _live_spec(idle_targets=["Stelz"], idle_rise_targets=["Fris"])
    flow = np.array([3.0, 0.5, 0.0, 1.0, 2.0, 0.25])
    state = dataclasses.replace(initial_state(spec, now_ms=NOW), flow_ema=flow)
    idled = apply_idle(spec, state, now_ms=NOW + MINUTE)
    noised = apply_brownian(spec, idled, now_ms=NOW + MINUTE, run_seed=1)
    assert idled.t_round == state.t_round + 1 and noised.rng_counter == 1
    assert np.array_equal(noised.flow_ema, flow)


# --- the counter-based RNG -------------------------------------------------------------------


def test_the_same_seed_and_counter_give_the_same_draw() -> None:
    assert np.array_equal(_normal(7, 3, 0.18, 6), _normal(7, 3, 0.18, 6))


def test_a_different_counter_or_seed_gives_a_different_draw() -> None:
    assert not np.array_equal(_normal(7, 3, 0.18, 6), _normal(7, 4, 0.18, 6))
    assert not np.array_equal(_normal(7, 3, 0.18, 6), _normal(8, 3, 0.18, 6))


def test_normal_is_the_d1_derivation_with_v1s_argument_order() -> None:
    expected = np.random.default_rng(np.random.SeedSequence([7, 3])).normal(0.0, 0.18, 6)
    assert np.array_equal(_normal(7, 3, 0.18, 6), expected)


def test_brownian_draws_once_and_bumps_the_counter() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    got = apply_brownian(spec, state, now_ms=NOW, run_seed=5)
    assert got.rng_counter == state.rng_counter + 1
    assert got.last_bm_ms == NOW
    assert not np.array_equal(got.y, state.y)
    again = apply_brownian(spec, got, now_ms=NOW + MINUTE - 1, run_seed=5)
    assert again is got or (again.rng_counter == got.rng_counter and again.last_bm_ms == NOW)


@pytest.mark.parametrize("sigma", [0.0, -0.2])
def test_no_draw_and_no_counter_bump_when_sigma_is_not_positive(sigma: float) -> None:
    spec = _live_spec(bm_sigma_y=sigma)
    state = initial_state(spec, now_ms=NOW)
    got = apply_brownian(spec, state, now_ms=NOW, run_seed=5)
    assert np.array_equal(got.y, state.y)
    assert got.rng_counter == state.rng_counter
    assert got.last_bm_ms == NOW  # v1 still moves its anchor (engine.py:303)


def test_no_draw_and_no_change_at_all_when_brownian_is_disabled() -> None:
    spec = _live_spec(bm_enabled=False)
    state = initial_state(spec, now_ms=NOW)
    got = apply_brownian(spec, state, now_ms=NOW, run_seed=5)
    assert np.array_equal(got.y, state.y)
    assert (got.rng_counter, got.last_bm_ms) == (state.rng_counter, state.last_bm_ms)


def test_brownian_does_not_mutate_its_input() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    before = np.array(state.y)
    apply_brownian(spec, state, now_ms=NOW, run_seed=5)
    assert np.array_equal(state.y, before)


# --- AC7, the Brownian half --------------------------------------------------------------------


def test_ac7_brownian_then_jumps_mid_jump_yield_the_smoothstep_value() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    state = schedule_jump(spec, state, drink=STELZ, p_target=4.0, duration_ms=MINUTE, now_ms=NOW)
    jump = state.jumps[0]
    t = NOW + 20_000
    noised = apply_brownian(spec, state, now_ms=t, run_seed=11)
    assert noised.rng_counter == 1 and noised.y[STELZ] != state.y[STELZ]
    got = apply_jumps(spec, noised, now_ms=t)
    f = np.clip((t - jump.t0_ms) / max(1, jump.t1_ms - jump.t0_ms), 0.0, 1.0)
    expected: FloatArray = jump.y0 + f * f * (3 - 2 * f) * (jump.y1 - jump.y0)
    assert got.y[STELZ] == expected
