"""`exchange.steps.apply_orders`: v1's order path, bit for bit (Phase 1 plan T4).

The order half of D3 is the `flow_ema` and `last_order_ts` updates from v1's
`post_order` (legacy/v1/backend/api.py:355-361), then `single_step`
(v1 engine.py:190-236), then `t_round + 1`. Every comparison with v1 is exact.

**AC10, as measured here.** The plan's original AC10 check -- over 30 rounds of
equal orders, a spread of per-drink moves under 25 % of a lone favoured
drink's move -- does not hold on v1's own maths (ratios 0.7-4.6 on the live
config): `phi_persist * cum_orders` accumulates for every drink alike, so
after a few dozen rounds equal demand lifts every price together, unevenly
because each sits at a different point of its barrier. The plan says not to
tune that number; the human chose instead (2026-10-01) to measure AC10 as:

1. under equal orders, the pre-barrier pressure is *exactly* uniform across
   drinks, every round -- the model treats them identically; and
2. over a short horizon (1 and 5 rounds), a drink ordered alone rises and
   every other drink falls or stays put. Direction only, by a second human
   decision (2026-10-01): "and moves most" fails for Fris, which starts at
   87 % of its range, where the barrier damps its rise (+0.017 after one
   round) below the full-strength fall of Vodka Red Bull (-0.024).

The 30-round common drift is pinned as v1 behaviour, not fixed (a pricing
change is out of scope for Phase 1).
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from exchange.pricing import FloatArray, expected_flow_from_price, prices_from_y
from exchange.spec import MarketSpec, Params
from exchange.state import EngineState, initial_state
from exchange.steps import _single_step, apply_orders
from tests.engine.golden.scenarios import FRIS, LIVE_CONFIG, WIJN
from tests.engine.v1_reference import engine as v1

NOW = 1_759_312_800_000
STEPS = (0.05, 0.1, 0.2, 0.5)


# --- building matched v1 and v2 states ------------------------------------------


def _random_case(rng: np.random.Generator) -> tuple[MarketSpec, EngineState, dict[str, Any]]:
    n = int(rng.integers(2, 8))
    p_min = np.round(rng.uniform(0.5, 8.0, n), 2)
    p_max = p_min + np.round(rng.uniform(1.0, 6.0, n), 2)
    p0 = p_min + (p_max - p_min) * rng.uniform(0.1, 0.9, n)
    coeffs = {k: rng.uniform(-2.0, 12.0, n) if rng.random() < 0.5 else np.zeros(n) for k in "adsc"}
    params = {
        "alpha_price": float(rng.uniform(-1.0, 1.0)) if rng.random() < 0.3 else 0.0,
        "lambda_orders": float(rng.uniform(0.0, 2.0)),
        "eta": float(rng.uniform(0.1, 1.5)),
        "K": float(rng.uniform(0.5, 15.0)),
        "step_quant": float(rng.choice(STEPS)),
        "phi_persist": float(rng.uniform(0.0, 0.3)),
        "decay_rho": float(rng.uniform(0.8, 1.0)),
        "flow_beta": float(rng.uniform(0.0, 1.0)),
        "demand_enabled": bool(rng.random() < 0.5),
    }
    spec = MarketSpec(
        names=tuple(f"d{i}" for i in range(n)),
        p_min=p_min,
        p_max=p_max,
        p0=p0,
        a=coeffs["a"],
        d=coeffs["d"],
        s0=coeffs["s"],
        c=coeffs["c"],
        params=Params.from_dict(params),
    )
    # Half the drinks pinned far past a bound, so the unstick branches run.
    y = rng.uniform(-6.0, 6.0, n)
    pinned = rng.random(n) < 0.5
    y[pinned] = rng.choice([-1.0, 1.0], pinned.sum()) * rng.uniform(7.0, 25.0, pinned.sum())
    state = EngineState(
        y=y,
        cum_orders=rng.uniform(-30.0, 60.0, n),
        flow_ema=rng.uniform(0.0, 5.0, n),
        last_order_ts=NOW - rng.integers(0, 600_000, n),
        jumps=(),
        last_idle_ms=0,
        last_bm_ms=0,
        rng_counter=0,
        version=0,
        tick_index=0,
        t_round=int(rng.integers(0, 1000)),
    )
    return spec, state, params


def _v1_twin(spec: MarketSpec, state: EngineState, params: dict[str, Any]) -> Any:
    st = v1.ExchangeState.init(
        list(spec.names),
        *(np.array(getattr(spec, k)) for k in ("p_min", "p_max", "p0", "a", "d", "s0", "c")),
        v1.Params.from_dict(params),
    )
    st.y = np.array(state.y)
    st.cum_orders = np.array(state.cum_orders)
    st.flow_ema = np.array(state.flow_ema)
    st.last_order_ts = np.array(state.last_order_ts)
    st.t_round = state.t_round
    return st


def _v1_post_order(st: Any, vec: FloatArray, now_ms: int) -> dict[str, Any]:
    """legacy/v1/backend/api.py:355-367, the lines that touch pricing state."""
    st.flow_ema = (1.0 - st.params.flow_beta) * st.flow_ema + st.params.flow_beta * vec
    for i, q in enumerate(vec):
        if q > 0:
            st.last_order_ts[i] = now_ms
    logs: dict[str, Any] = st.single_step(vec)
    st.t_round += 1
    return logs


def _random_orders(rng: np.random.Generator, n: int, *, signed: bool = False) -> FloatArray:
    if rng.random() < 0.1:
        return np.zeros(n)
    vec: FloatArray = np.where(rng.random(n) < 0.6, rng.integers(0, 8, n), 0).astype(np.float64)
    if signed:
        vec = vec - np.where(rng.random(n) < 0.4, rng.integers(0, 4, n), 0)
    return vec


# --- bitwise against v1 -----------------------------------------------------------


def test_apply_orders_matches_v1_post_order_bitwise() -> None:
    rng = np.random.default_rng(404)
    at_a_bound = 0
    for case in range(600):
        spec, state, params = _random_case(rng)
        st = _v1_twin(spec, state, params)
        vec = _random_orders(rng, len(spec.names))
        _, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
        # v1's own bound tolerance (engine.py:214): a quantised quote can sit an ulp off.
        pinned = (np.abs(p_q - spec.p_min) <= 1e-9) | (np.abs(p_q - spec.p_max) <= 1e-9)
        at_a_bound += int(np.any(pinned))

        logs = _v1_post_order(st, vec, NOW)
        got, diag = apply_orders(spec, state, vec, now_ms=NOW)

        for key in ("y", "cum_orders", "flow_ema", "last_order_ts"):
            assert np.array_equal(getattr(got, key), getattr(st, key)), (case, key)
        assert got.t_round == st.t_round
        assert np.array_equal(diag.order_pressure, logs["order_pressure"]), case
        assert np.array_equal(diag.cross_price_pressure, logs["cross_price_pressure"]), case
        assert np.array_equal(diag.cum_orders, logs["cum_orders"]), case
    assert at_a_bound >= 100, "the random states must exercise the unstick branches"


def test_single_step_matches_v1_on_signed_vectors() -> None:
    """The idle step feeds `_single_step` negative vectors (v1 engine.py:256-287)."""
    rng = np.random.default_rng(405)
    for case in range(600):
        spec, state, params = _random_case(rng)
        st = _v1_twin(spec, state, params)
        vec = _random_orders(rng, len(spec.names), signed=True)
        st.single_step(vec)
        got, _ = _single_step(spec, state, vec)
        assert np.array_equal(got.y, st.y), case
        assert np.array_equal(got.cum_orders, st.cum_orders), case
        assert got.t_round == state.t_round, "the caller bumps t_round, not _single_step"


def test_apply_orders_does_not_mutate_its_inputs() -> None:
    rng = np.random.default_rng(406)
    spec, state, _ = _random_case(rng)
    vec = _random_orders(rng, len(spec.names))
    before = {k: np.array(getattr(state, k)) for k in ("y", "cum_orders", "flow_ema")}
    vec_before = vec.copy()
    apply_orders(spec, state, vec, now_ms=NOW)
    for key, value in before.items():
        assert np.array_equal(getattr(state, key), value)
    assert np.array_equal(vec, vec_before)


def test_last_order_ts_moves_only_for_ordered_drinks() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    got, _ = apply_orders(spec, state, _only(FRIS, 2.0), now_ms=NOW + 5_000)
    assert got.last_order_ts[FRIS] == NOW + 5_000
    assert np.all(np.delete(got.last_order_ts, FRIS) == NOW)


# --- live-config helpers ----------------------------------------------------------


def _live_spec(**params: Any) -> MarketSpec:
    st = v1.ExchangeState.from_persist(copy.deepcopy(LIVE_CONFIG))
    return MarketSpec(
        names=tuple(st.names),
        p_min=st.p_min,
        p_max=st.p_max,
        p0=st.p0,
        a=st.a,
        d=st.d,
        s0=st.s0,
        c=st.c,
        params=Params.from_dict({**LIVE_CONFIG["params"], **params}),
    )


def _only(drink: int, qty: float, n: int = 6) -> FloatArray:
    vec = np.zeros(n)
    vec[drink] = qty
    return vec


def _quotes(spec: MarketSpec, state: EngineState) -> FloatArray:
    return prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)[1]


# --- AC6: the unstick hack ----------------------------------------------------------


def test_ac6_an_order_at_p_min_lifts_the_quote_by_at_least_one_step() -> None:
    spec = _live_spec()
    y = np.array(initial_state(spec, now_ms=NOW).y)
    y[FRIS] = -12.0  # deep below p_min: a plain step would leave the quote at p_min
    state = EngineState(**{**_fields(initial_state(spec, now_ms=NOW)), "y": y})
    assert _quotes(spec, state)[FRIS] == spec.p_min[FRIS]

    got, _ = apply_orders(spec, state, _only(FRIS, 1.0), now_ms=NOW)

    assert _quotes(spec, got)[FRIS] >= spec.p_min[FRIS] + spec.params.step_quant - 1e-9


def test_ac6_negative_pressure_at_p_max_drops_the_quote_by_at_least_one_step() -> None:
    spec = _live_spec()
    y = np.array(initial_state(spec, now_ms=NOW).y)
    y[WIJN] = 12.0
    state = EngineState(**{**_fields(initial_state(spec, now_ms=NOW)), "y": y})
    assert _quotes(spec, state)[WIJN] == spec.p_max[WIJN]

    # Orders on every other drink: Wijn's relative pressure is negative.
    vec = np.full(6, 5.0)
    vec[WIJN] = 0.0
    got, diag = apply_orders(spec, state, vec, now_ms=NOW)

    assert diag.order_pressure[WIJN] < 0
    assert _quotes(spec, got)[WIJN] <= spec.p_max[WIJN] - spec.params.step_quant + 1e-9


def _fields(state: EngineState) -> dict[str, Any]:
    return {k: getattr(state, k) for k in EngineState.__dataclass_fields__}


# --- AC9: demand off means raw orders ------------------------------------------------


def test_ac9_with_demand_off_the_demand_coefficients_change_nothing() -> None:
    rng = np.random.default_rng(9)
    n = 6
    base = _live_spec(demand_enabled=False)
    coeffs = {k: rng.uniform(1.0, 10.0, n) for k in ("a", "d", "s0", "c")}
    loaded = MarketSpec(
        **{**{k: getattr(base, k) for k in MarketSpec.__dataclass_fields__}, **coeffs}
    )
    state = initial_state(base, now_ms=NOW)
    vec = np.array([3.0, 0.0, 1.0, 2.0, 0.0, 1.0])

    got_base, diag_base = apply_orders(base, state, vec, now_ms=NOW)
    got_loaded, diag_loaded = apply_orders(loaded, state, vec, now_ms=NOW)

    assert np.array_equal(got_loaded.y, got_base.y)
    others_avg = (np.sum(vec) - vec) / (n - 1)
    raw = vec - base.params.lambda_orders * others_avg
    assert np.array_equal(diag_loaded.order_pressure, raw)
    assert np.array_equal(diag_loaded.order_pressure, diag_base.order_pressure)


def test_ac9_with_demand_on_the_coefficients_do_matter() -> None:
    """Anti-vacuity: the same loaded spec with demand on must price differently."""
    rng = np.random.default_rng(9)
    base = _live_spec(demand_enabled=True)
    coeffs = {k: rng.uniform(1.0, 10.0, 6) for k in ("a", "d", "s0", "c")}
    loaded = MarketSpec(
        **{**{k: getattr(base, k) for k in MarketSpec.__dataclass_fields__}, **coeffs}
    )
    state = initial_state(base, now_ms=NOW)
    _, p_q = prices_from_y(state.y, loaded.p_min, loaded.p_max, loaded.params.step_quant)
    flow = expected_flow_from_price(
        p_q, float(np.mean(p_q)), loaded.a, loaded.d, loaded.s0, loaded.c
    )
    assert np.any(flow > 0)
    vec = np.array([3.0, 0.0, 1.0, 2.0, 0.0, 1.0])
    got_base, _ = apply_orders(base, state, vec, now_ms=NOW)
    got_loaded, _ = apply_orders(loaded, state, vec, now_ms=NOW)
    assert not np.array_equal(got_loaded.y, got_base.y)


# --- AC10: relative demand ---------------------------------------------------------


def _fractional_moves(spec: MarketSpec, vec: FloatArray, rounds: int) -> FloatArray:
    state = initial_state(spec, now_ms=NOW)
    start, _ = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
    for _ in range(rounds):
        state, _ = apply_orders(spec, state, vec, now_ms=NOW)
    end, _ = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
    moves: FloatArray = (end - start) / (spec.p_max - spec.p_min)
    return moves


@pytest.mark.parametrize("qty", [1.0, 2.0, 4.0])
def test_ac10_equal_orders_give_exactly_uniform_pre_barrier_pressure(qty: float) -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    for round_ in range(30):
        state, diag = apply_orders(spec, state, np.full(6, qty), now_ms=NOW)
        pressure = diag.order_pressure + spec.params.phi_persist * diag.cum_orders
        assert np.all(pressure == pressure[0]), round_


@pytest.mark.parametrize("rounds", [1, 5])
@pytest.mark.parametrize("drink", range(6))
def test_ac10_a_drink_ordered_alone_rises_and_every_other_falls(drink: int, rounds: int) -> None:
    moves = _fractional_moves(_live_spec(), _only(drink, 2.0), rounds)
    assert moves[drink] > 0
    assert np.all(np.delete(moves, drink) <= 0)


def test_ac10_pinned_v1_behaviour_equal_orders_drift_together_over_time() -> None:
    """v1, not a target: persistence lifts every price under sustained equal demand."""
    moves = _fractional_moves(_live_spec(), np.full(6, 2.0), 30)
    assert np.all(moves > 0)
