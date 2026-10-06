"""The active mask, `MarketSpec.active` (Phase 6 T2, SD14, PD17).

Two claims. With every slot active, every step is bitwise v1's: the random
cases of `test_steps_orders.py` and `test_steps_idle_brownian.py` are rerun
with the mask given explicitly, against the v1 reference. With a slot
inactive, that slot is frozen and the market behaves as if the drink were not
there -- each mean, sum and count equals a hand computation over the active
slots, and every other drink's raw noise draw is untouched.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from exchange import (
    DrinkSpec,
    EngineState,
    MarketSpec,
    Params,
    advance,
    anchor_s0_to_current_y,
    initial_state,
    schedule_jump,
)
from exchange.pricing import expected_flow_from_price, prices_from_y
from exchange.steps import _normal, _single_step, apply_brownian, apply_idle, apply_orders
from tests.engine.test_steps_idle_brownian import _assert_same, _at
from tests.engine.test_steps_idle_brownian import _random_case as _tick_case
from tests.engine.test_steps_idle_brownian import _v1_twin as _tick_twin
from tests.engine.test_steps_orders import _random_case as _order_case
from tests.engine.test_steps_orders import _random_orders, _v1_post_order
from tests.engine.test_steps_orders import _v1_twin as _order_twin
from tests.engine.v1_reference import engine as v1

NOW = 1_759_312_800_000
MINUTE = 60_000
PER_SLOT = ("y", "cum_orders", "flow_ema", "last_order_ts")


def _all_active(spec: MarketSpec) -> MarketSpec:
    return dataclasses.replace(spec, active=np.ones(len(spec.names), dtype=bool))


def _same_bytes(left: Any, right: Any) -> bool:
    a, b = np.asarray(left), np.asarray(right)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


# --- every slot active: bitwise v1 ---------------------------------------------------


def test_an_all_true_mask_gives_v1s_order_step_bitwise() -> None:
    rng = np.random.default_rng(6201)
    for case in range(400):
        spec, state, params = _order_case(rng)
        st = _order_twin(spec, state, params)
        vec = _random_orders(rng, len(spec.names))
        logs = _v1_post_order(st, vec, NOW)
        got, diag = apply_orders(_all_active(spec), state, vec, now_ms=NOW)
        for key in PER_SLOT:
            assert _same_bytes(getattr(got, key), np.asarray(getattr(st, key))), (case, key)
        assert _same_bytes(diag.order_pressure, logs["order_pressure"]), case
        assert _same_bytes(diag.cum_orders, logs["cum_orders"]), case


def test_an_all_true_mask_gives_v1s_signed_single_step_bitwise() -> None:
    rng = np.random.default_rng(6202)
    for case in range(400):
        spec, state, params = _order_case(rng)
        st = _order_twin(spec, state, params)
        vec = _random_orders(rng, len(spec.names), signed=True)
        st.single_step(vec)
        got, _ = _single_step(_all_active(spec), state, vec)
        assert _same_bytes(got.y, st.y), case
        assert _same_bytes(got.cum_orders, st.cum_orders), case


@pytest.mark.parametrize("step", ["idle", "brownian"])
def test_an_all_true_mask_gives_v1s_idle_and_brownian_bitwise(step: str) -> None:
    rng = np.random.default_rng(6203 if step == "idle" else 6204)
    for case in range(400):
        spec, state, params, now = _tick_case(rng)
        st = _tick_twin(spec, state, params, run_seed=case)
        with _at(now):
            if step == "idle":
                st.apply_idle_adjust_if_needed()
            else:
                st.apply_bm_if_needed()
        if step == "idle":
            got = apply_idle(_all_active(spec), state, now_ms=now)
        else:
            got = apply_brownian(_all_active(spec), state, now_ms=now, run_seed=case)
        _assert_same(got, st, case)
        assert _same_bytes(got.y, st.y), case


def test_an_all_true_mask_gives_v1s_anchor_bitwise() -> None:
    rng = np.random.default_rng(6205)
    for case in range(200):
        spec, state, params = _order_case(rng)
        st = _order_twin(spec, state, params)
        st.y = np.array(state.y)
        v1.calibrate_s0_to_p0(st)
        anchored = anchor_s0_to_current_y(_all_active(spec), state.y)
        assert _same_bytes(anchored.s0, st.s0), case


def test_the_default_mask_is_all_true_and_read_only() -> None:
    spec = _market(4)
    assert spec.active.dtype == np.bool_
    assert spec.active.tolist() == [True] * 4
    with pytest.raises(ValueError):
        spec.active[0] = False


# --- one slot inactive ---------------------------------------------------------------


def _market(n: int, *, inactive: tuple[int, ...] = (), **params: Any) -> MarketSpec:
    p_min = np.array([1.0 + 0.5 * i for i in range(n)])
    return MarketSpec(
        names=tuple(f"d{i}" for i in range(n)),
        p_min=p_min,
        p_max=p_min + np.array([3.0 + 0.7 * i for i in range(n)]),
        p0=p_min + 1.0,
        a=np.full(n, 10.0),
        d=np.full(n, 0.6),
        s0=np.full(n, 8.0),
        c=np.full(n, 0.4),
        params=Params(step_quant=0.1, **params),
        active=np.array([i not in inactive for i in range(n)]),
    )


def _drop(spec: MarketSpec, i: int) -> MarketSpec:
    """The same market with slot `i` deleted outright."""
    keep = [j for j in range(len(spec.names)) if j != i]
    return MarketSpec(
        names=tuple(spec.names[j] for j in keep),
        **{k: getattr(spec, k)[keep] for k in ("p_min", "p_max", "p0", "a", "d", "s0", "c")},
        params=spec.params,
    )


def _drop_state(state: EngineState, i: int) -> EngineState:
    keep = [j for j in range(len(state.y)) if j != i]
    return dataclasses.replace(state, **{k: getattr(state, k)[keep] for k in PER_SLOT})


def _scrambled(spec: MarketSpec, seed: int) -> EngineState:
    rng = np.random.default_rng(seed)
    n = len(spec.names)
    return dataclasses.replace(
        initial_state(spec, now_ms=NOW),
        y=rng.uniform(-3.0, 3.0, n),
        cum_orders=rng.uniform(-20.0, 20.0, n),
        flow_ema=rng.uniform(0.0, 4.0, n),
        last_order_ts=NOW - rng.integers(0, 10 * MINUTE, n),
    )


def test_an_inactive_slot_is_frozen_across_200_advances() -> None:
    """PD17: `y`, `cum_orders`, `flow_ema` and `last_order_ts` of an inactive slot never move."""
    spec = _market(
        5,
        inactive=(2,),
        refresh_minutes=0.5,
        idle_decay_minutes=0.5,
        idle_targets=("d2", "d3"),
        idle_rise_minutes=0.5,
        idle_rise_targets=("d2", "d0"),
        bm_dt_minutes=0.5,
    )
    state = _scrambled(spec, 7)
    frozen = {k: getattr(state, k)[2] for k in PER_SLOT}
    rng = np.random.default_rng(8)
    moved = 0
    now = NOW
    for _ in range(200):
        now += int(rng.integers(1_000, 40_000))
        orders = None
        if rng.random() < 0.5:
            orders = np.where(rng.random(5) < 0.5, rng.integers(0, 4, 5), 0).astype(float)
            orders[2] = 0.0
        before = np.array(state.y)
        state = advance(spec, state, now_ms=now, orders=orders, run_seed=99).state
        moved += int(not np.array_equal(before, state.y))
        for key, value in frozen.items():
            assert getattr(state, key)[2] == value, key
    assert moved > 100, "the other drinks must actually trade"


def test_the_order_step_over_active_slots_is_the_market_without_the_drink() -> None:
    """`p_mean`, `N` and `others_avg_dev` range over active slots: the masked step equals
    the step of the market with that drink deleted, bitwise, on every active slot."""
    rng = np.random.default_rng(6206)
    for case in range(200):
        spec = _market(5, inactive=(1,), lambda_orders=float(rng.uniform(0.2, 2.0)))
        state = _scrambled(spec, case)
        vec = np.where(rng.random(5) < 0.6, rng.integers(1, 6, 5), 0).astype(float)
        vec[1] = 0.0
        got, diag = apply_orders(spec, state, vec, now_ms=NOW + 1)
        want, want_diag = apply_orders(
            _drop(spec, 1), _drop_state(state, 1), np.delete(vec, 1), now_ms=NOW + 1
        )
        for key in PER_SLOT:
            assert _same_bytes(np.delete(getattr(got, key), 1), getattr(want, key)), (case, key)
        assert _same_bytes(np.delete(diag.order_pressure, 1), want_diag.order_pressure), case


def test_p_mean_in_the_order_step_is_the_active_mean() -> None:
    """By hand: with demand on, `exp_flow` uses the mean quote of the active drinks."""
    spec = _market(4, inactive=(3,), lambda_orders=0.0, phi_persist=0.0)
    state = _scrambled(spec, 3)
    _, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, 0.1)
    p_mean = float(np.mean(p_q[:3]))
    assert p_mean != float(np.mean(p_q)), "the inactive quote must pull the full mean away"
    exp_flow = expected_flow_from_price(p_q, p_mean, spec.a, spec.d, spec.s0, spec.c)
    _, diag = _single_step(spec, state, np.array([1.0, 0.0, 0.0, 0.0]))
    dev = np.array([1.0, 0.0, 0.0, 0.0]) - exp_flow
    assert np.array_equal(
        diag.cum_orders[:3], spec.params.decay_rho * state.cum_orders[:3] + dev[:3]
    )


def test_others_avg_dev_divides_by_the_active_count() -> None:
    spec = _market(4, inactive=(0,), demand_enabled=False, lambda_orders=1.0)
    state = _scrambled(spec, 4)
    vec = np.array([0.0, 3.0, 0.0, 1.0])
    _, diag = _single_step(spec, state, vec)
    # dev = vec (no demand); over active slots 1..3 the sum is 4 and N - 1 = 2.
    expected = vec[1:] - (4.0 - vec[1:]) / 2
    assert np.array_equal(diag.order_pressure[1:], expected)


def test_mean_range_is_over_active_slots() -> None:
    spec = _market(4, inactive=(3,), bm_dt_minutes=1.0, flow_vol_amp=0.0)
    state = dataclasses.replace(_scrambled(spec, 5), last_bm_ms=0)
    got = apply_brownian(spec, state, now_ms=NOW, run_seed=11)
    ranges = spec.p_max - spec.p_min
    mean_range = float(np.mean(ranges[:3]))
    draw = _normal(11, state.rng_counter, spec.params.bm_sigma_y * np.sqrt(1.0), 4)
    expected = np.clip(state.y + draw * (ranges / mean_range), -6.0, 6.0)
    assert np.array_equal(got.y[:3], expected[:3])
    assert got.y[3] == state.y[3]


def test_other_drinks_brownian_draws_do_not_change_when_a_slot_is_deactivated() -> None:
    """SD14: the draw keeps `len(names)` values. With equal ranges `mean_range` is the
    same either way, so every active drink moves exactly as before."""
    base = _market(4, bm_dt_minutes=1.0)
    equal = dataclasses.replace(base, p_max=base.p_min + 3.0)
    state = dataclasses.replace(_scrambled(equal, 6), last_bm_ms=0)
    everyone = apply_brownian(equal, state, now_ms=NOW, run_seed=12)
    masked = apply_brownian(
        dataclasses.replace(equal, active=np.array([True, False, True, True])),
        state,
        now_ms=NOW,
        run_seed=12,
    )
    assert _same_bytes(np.delete(masked.y, 1), np.delete(everyone.y, 1))
    assert masked.y[1] == state.y[1]
    assert masked.rng_counter == everyone.rng_counter


def test_the_idle_step_over_active_slots_is_the_market_without_the_drink() -> None:
    spec = _market(
        4,
        inactive=(2,),
        refresh_minutes=1.0,
        idle_decay_minutes=1.0,
        idle_targets=("d0", "d2"),
        idle_rise_minutes=1.0,
        idle_rise_targets=("d3",),
    )
    state = dataclasses.replace(
        _scrambled(spec, 9), last_order_ts=np.full(4, NOW - 10 * MINUTE), last_idle_ms=0
    )
    got = apply_idle(spec, state, now_ms=NOW)
    want = apply_idle(_drop(spec, 2), _drop_state(state, 2), now_ms=NOW)
    assert got.t_round == want.t_round == state.t_round + 1
    for key in PER_SLOT:
        assert _same_bytes(np.delete(getattr(got, key), 2), getattr(want, key)), key
        assert getattr(got, key)[2] == getattr(state, key)[2], key


@pytest.mark.parametrize("removed", [0, 1], ids=["removed-first", "removed-last"])
def test_a_duplicate_name_idle_target_hits_only_the_active_slot(removed: int) -> None:
    """PD17: a removed "Bier" and a re-added "Bier"; the idle push reaches only the live one."""
    live = 1 - removed
    drinks = [
        DrinkSpec("Bier", 1.0, 5.0, 2.0, 0.0, 0.0, 0.0, 0.0, active=(i != removed))
        for i in range(2)
    ] + [DrinkSpec("Wijn", 2.0, 6.0, 3.0, 0.0, 0.0, 0.0, 0.0)]
    spec = MarketSpec.from_drinks(
        drinks,
        Params(
            step_quant=0.1,
            refresh_minutes=1.0,
            idle_decay_minutes=1.0,
            idle_targets=("Bier",),
            demand_enabled=False,
        ),
    )
    state = dataclasses.replace(initial_state(spec, now_ms=NOW - 10 * MINUTE), last_idle_ms=0)
    got = apply_idle(spec, state, now_ms=NOW)
    assert got.y[live] < state.y[live]
    assert got.y[removed] == state.y[removed]


def test_the_anchor_mean_is_over_active_slots_and_keeps_an_inactive_s0() -> None:
    spec = _market(4, inactive=(1,))
    y = np.array([0.3, 2.5, -0.4, 1.1])
    anchored = anchor_s0_to_current_y(spec, y)
    _, p_q = prices_from_y(y, spec.p_min, spec.p_max, 0.1)
    p_mean = float(np.mean(p_q[[0, 2, 3]]))
    for i in (0, 2, 3):
        assert anchored.s0[i] == spec.d[i] * p_q[i] - spec.a[i] - spec.c[i] * (p_mean - p_q[i])
    assert anchored.s0[1] == spec.s0[1]
    assert anchored.active.tolist() == spec.active.tolist()


# --- refusals --------------------------------------------------------------------------


def test_an_inactive_drink_takes_no_jump() -> None:
    spec = _market(3, inactive=(1,))
    state = initial_state(spec, now_ms=NOW)
    with pytest.raises(ValueError, match="inactive"):
        schedule_jump(spec, state, drink=1, p_target=3.0, duration_ms=1_000, now_ms=NOW)
    schedule_jump(spec, state, drink=2, p_target=3.0, duration_ms=1_000, now_ms=NOW)


def test_an_order_on_an_inactive_drink_is_refused_and_a_zero_is_not() -> None:
    spec = _market(3, inactive=(1,))
    state = initial_state(spec, now_ms=NOW)
    with pytest.raises(ValueError, match="inactive"):
        advance(spec, state, now_ms=NOW, orders=[0, 1, 0], run_seed=1)
    advance(spec, state, now_ms=NOW, orders=[1, 0, 0], run_seed=1)


def test_a_market_needs_an_active_drink() -> None:
    with pytest.raises(ValueError, match="at least one active"):
        _market(2, inactive=(0, 1))


def test_a_mask_of_the_wrong_length_is_refused() -> None:
    spec = _market(3)
    with pytest.raises(ValueError, match="active has length"):
        dataclasses.replace(spec, active=np.array([True, True]))


def test_from_drinks_carries_each_drinks_active_flag() -> None:
    spec = MarketSpec.from_drinks(
        [
            DrinkSpec("A", 1.0, 3.0, 2.0, 0.0, 0.0, 0.0, 0.0),
            DrinkSpec("B", 1.0, 3.0, 2.0, 0.0, 0.0, 0.0, 0.0, active=False),
        ],
        Params(),
    )
    assert spec.active.tolist() == [True, False]
