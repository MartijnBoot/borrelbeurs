"""`exchange.steps.schedule_jump` and `apply_jumps` (Phase 1 plan T5, AC7, AC8, D5)."""

from __future__ import annotations

import copy
import dataclasses

import numpy as np
import pytest

from exchange.pricing import FloatArray, prices_from_y
from exchange.spec import MarketSpec, Params
from exchange.state import EngineState, initial_state
from exchange.steps import apply_jumps, apply_orders, schedule_jump
from tests.engine.golden import capture
from tests.engine.golden.scenarios import LIVE_CONFIG, STELZ, by_name
from tests.engine.v1_reference import engine as v1

NOW = 1_759_312_800_000


def _live_spec() -> MarketSpec:
    st = v1.ExchangeState.from_persist(copy.deepcopy(LIVE_CONFIG))
    return MarketSpec(
        names=tuple(st.names),
        **{k: getattr(st, k) for k in ("p_min", "p_max", "p0", "a", "d", "s0", "c")},
        params=Params.from_dict(LIVE_CONFIG["params"]),
    )


def _smoothstep(y0: float, y1: float, t0: int, t1: int, now: int) -> float:
    f = np.clip((now - t0) / max(1, t1 - t0), 0.0, 1.0)
    return float(y0 + f * f * (3 - 2 * f) * (y1 - y0))


class _V1Clock:
    def __init__(self) -> None:
        self.now = NOW
        self._original = v1.now_ms

    def __enter__(self) -> _V1Clock:
        v1.now_ms = lambda: self.now
        return self

    def __exit__(self, *exc: object) -> None:
        v1.now_ms = self._original


# --- bitwise against v1 -------------------------------------------------------------


def test_random_jump_timelines_match_v1_bitwise() -> None:
    rng = np.random.default_rng(55)
    spec = _live_spec()
    n = len(spec.names)
    for case in range(300):
        with _V1Clock() as clock:
            st = v1.ExchangeState.from_persist(copy.deepcopy(LIVE_CONFIG))
            y = rng.uniform(-6.0, 6.0, n)
            st.y = y.copy()
            state = dataclasses.replace(initial_state(spec, now_ms=NOW), y=y)
            for _ in range(int(rng.integers(5, 40))):
                clock.now += int(rng.integers(0, 15_000))
                if rng.random() < 0.3:
                    drink = int(rng.integers(0, n))
                    target = float(rng.uniform(spec.p_min[drink] - 2, spec.p_max[drink] + 2))
                    duration = int(rng.choice([0, 1, 500, 10_000, 30_000, 60_000]))
                    st.schedule_price_jump(st.names[drink], target, duration)
                    state = schedule_jump(
                        spec,
                        state,
                        drink=drink,
                        p_target=target,
                        duration_ms=duration,
                        now_ms=clock.now,
                    )
                st.apply_price_jumps_if_needed()
                state = apply_jumps(spec, state, now_ms=clock.now)
                assert np.array_equal(state.y, st.y), case
                v1_jumps = {
                    i: (pj.y0, pj.y1, pj.t0_ms, pj.t1_ms) for i, pj in st.price_jumps.items()
                }
                assert {j.i: (j.y0, j.y1, j.t0_ms, j.t1_ms) for j in state.jumps} == v1_jumps


# --- schedule_jump --------------------------------------------------------------------


def test_schedule_jump_quantises_the_target_and_bumps_version() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    got = schedule_jump(spec, state, drink=STELZ, p_target=4.04, duration_ms=60_000, now_ms=NOW)
    (jump,) = got.jumps
    assert (jump.i, jump.t0_ms, jump.t1_ms) == (STELZ, NOW, NOW + 60_000)
    assert jump.y0 == state.y[STELZ]
    end = apply_jumps(spec, got, now_ms=NOW + 60_000)
    assert prices_from_y(end.y, spec.p_min, spec.p_max, 0.1)[1][STELZ] == pytest.approx(4.0)
    assert got.version == state.version + 1
    assert state.jumps == ()


def test_a_new_jump_on_the_same_drink_replaces_the_old_one() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    state = schedule_jump(spec, state, drink=STELZ, p_target=4.0, duration_ms=60_000, now_ms=NOW)
    state = schedule_jump(spec, state, drink=0, p_target=2.0, duration_ms=60_000, now_ms=NOW)
    state = schedule_jump(
        spec, state, drink=STELZ, p_target=6.5, duration_ms=10_000, now_ms=NOW + 1
    )
    assert [j.i for j in state.jumps] == [STELZ, 0]
    assert state.jumps[0].t1_ms == NOW + 1 + 10_000


@pytest.mark.parametrize("duration", [0, -5_000])
def test_a_non_positive_duration_lasts_one_millisecond(duration: int) -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    got = schedule_jump(spec, state, drink=0, p_target=2.0, duration_ms=duration, now_ms=NOW)
    assert got.jumps[0].t1_ms == NOW + 1


@pytest.mark.parametrize("drink", [-1, 6, 99])
def test_an_unknown_drink_index_raises(drink: int) -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    with pytest.raises(ValueError, match="drink"):
        schedule_jump(spec, state, drink=drink, p_target=2.0, duration_ms=1_000, now_ms=NOW)


# --- AC8: out-of-range targets saturate --------------------------------------------------


@pytest.mark.parametrize(
    ("target", "bound"), [(-50.0, "p_min"), (0.0, "p_min"), (8.0, "p_max"), (1e6, "p_max")]
)
def test_ac8_a_target_outside_the_bounds_saturates_at_the_bound(target: float, bound: str) -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    got = schedule_jump(spec, state, drink=STELZ, p_target=target, duration_ms=1_000, now_ms=NOW)
    end = apply_jumps(spec, got, now_ms=NOW + 1_000)
    quote = prices_from_y(end.y, spec.p_min, spec.p_max, spec.params.step_quant)[1][STELZ]
    assert quote == pytest.approx(getattr(spec, bound)[STELZ], abs=1e-9)
    assert np.isfinite(end.y[STELZ])


# --- apply_jumps ----------------------------------------------------------------------------


def test_apply_jumps_eases_by_smoothstep_then_lands_exactly_and_drops_the_jump() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    state = schedule_jump(spec, state, drink=STELZ, p_target=4.0, duration_ms=60_000, now_ms=NOW)
    jump = state.jumps[0]
    for t in (NOW, NOW + 15_000, NOW + 30_000, NOW + 59_999):
        mid = apply_jumps(spec, state, now_ms=t)
        assert mid.y[STELZ] == _smoothstep(jump.y0, jump.y1, jump.t0_ms, jump.t1_ms, t)
        assert len(mid.jumps) == 1
    end = apply_jumps(spec, state, now_ms=NOW + 60_000)
    assert end.y[STELZ] == jump.y1
    assert end.jumps == ()


def test_apply_jumps_without_jumps_changes_nothing() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    got = apply_jumps(spec, state, now_ms=NOW + 1)
    assert np.array_equal(got.y, state.y)
    assert got.version == state.version


def test_apply_jumps_does_not_mutate_its_input() -> None:
    spec = _live_spec()
    state = initial_state(spec, now_ms=NOW)
    state = schedule_jump(spec, state, drink=STELZ, p_target=4.0, duration_ms=60_000, now_ms=NOW)
    before = np.array(state.y)
    apply_jumps(spec, state, now_ms=NOW + 30_000)
    assert np.array_equal(state.y, before)
    assert len(state.jumps) == 1


# --- AC7: a jump overrides order-driven and Brownian movement -------------------------------


def _mid_jump_state(spec: MarketSpec) -> EngineState:
    state = initial_state(spec, now_ms=NOW)
    return schedule_jump(spec, state, drink=STELZ, p_target=4.0, duration_ms=60_000, now_ms=NOW)


@pytest.mark.parametrize(
    "orders",
    [np.zeros(6), np.full(6, 3.0), np.array([0, 0, 9.0, 0, 0, 0]), np.array([9.0, 9, 0, 9, 9, 9])],
    ids=["none", "equal", "stelz-heavy", "everything-else"],
)
def test_ac7_orders_then_jumps_mid_jump_yield_the_smoothstep_value(orders: FloatArray) -> None:
    spec = _live_spec()
    state = _mid_jump_state(spec)
    jump = state.jumps[0]
    t = NOW + 20_000
    ordered, _ = apply_orders(spec, state, orders, now_ms=t)
    got = apply_jumps(spec, ordered, now_ms=t)
    assert got.y[STELZ] == _smoothstep(jump.y0, jump.y1, jump.t0_ms, jump.t1_ms, t)


def test_ac7_a_perturbed_y_is_overridden_by_the_next_jump_application() -> None:
    """Stands in for Brownian noise until T6 adds `apply_brownian`."""
    spec = _live_spec()
    state = _mid_jump_state(spec)
    jump = state.jumps[0]
    y = np.array(state.y)
    y[STELZ] += 0.37
    got = apply_jumps(spec, dataclasses.replace(state, y=y), now_ms=NOW + 45_000)
    assert got.y[STELZ] == _smoothstep(jump.y0, jump.y1, jump.t0_ms, jump.t1_ms, NOW + 45_000)


def test_d5_residual_v1_publishes_one_draw_of_noise_on_a_jumping_drink() -> None:
    """Plan D5, pinned from v1's own fixture: in v1's tick, Brownian runs *after*
    jumps, so on a tick where it fires a jumping drink is published off its
    smoothstep path; the next jump application puts it back.
    """
    scenario = by_name("s2_jump")
    doc = capture.load_fixture(scenario.name)
    events, records = doc["events"], doc["records"]
    spec = _live_spec()
    k_jump = next(k for k, e in enumerate(events) if e["kind"] == "jump")
    jump_event = events[k_jump]
    before = dataclasses.replace(
        initial_state(spec, now_ms=NOW), y=np.array(records[k_jump - 1]["y"])
    )
    jumped = schedule_jump(
        spec,
        before,
        drink=jump_event["drink"],
        p_target=jump_event["target"],
        duration_ms=jump_event["duration_ms"],
        now_ms=jump_event["t"],
    )
    end = jumped.jumps[0].t1_ms
    # The tick, mid-jump, on which Brownian drew noise.
    k_bm = next(
        k
        for k in range(k_jump + 1, len(events))
        if events[k]["t"] < end and records[k]["rng_counter"] > records[k - 1]["rng_counter"]
    )
    path = apply_jumps(spec, jumped, now_ms=events[k_bm]["t"]).y[STELZ]
    assert records[k_bm]["y"][STELZ] != path
    after = apply_jumps(spec, jumped, now_ms=events[k_bm + 1]["t"]).y[STELZ]
    assert records[k_bm + 1]["y"][STELZ] == after
