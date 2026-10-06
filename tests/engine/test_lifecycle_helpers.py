"""`hold_quoted_prices`, `append_slot`, `cancel_jumps` (Phase 6 T3, SD9, SD12).

The pure halves of a live config change: hold a quote across a bounds or
`step_quant` change, add a drink to a running market, and drop jumps whose
targets no longer mean anything.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from exchange import (
    EngineState,
    MarketSpec,
    Params,
    PriceJump,
    append_slot,
    cancel_jumps,
    hold_quoted_prices,
    initial_state,
    prices_from_y,
)
from exchange.pricing import FloatArray, quantize_step

NOW = 1_759_312_800_000
STEPS = (0.01, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0)


def _cents(rng: np.random.Generator, lo: float, hi: float, n: int) -> FloatArray:
    """Whole cents, the only bounds the database can hold: often off the step grid."""
    cents: FloatArray = np.round(rng.uniform(lo, hi, n) * 100) / 100
    return cents


def _spec(rng: np.random.Generator, n: int, step: float) -> MarketSpec:
    p_min = _cents(rng, 0.0, 5.0, n)
    p_max = p_min + _cents(rng, 0.5, 6.0, n)
    p0 = np.round((p_min + (p_max - p_min) * rng.uniform(0.2, 0.8, n)) * 100) / 100
    p0 = np.clip(p0, p_min + 0.01, p_max - 0.01)
    return MarketSpec(
        names=tuple(f"d{i}" for i in range(n)),
        p_min=p_min,
        p_max=p_max,
        p0=p0,
        a=np.zeros(n),
        d=np.zeros(n),
        s0=np.zeros(n),
        c=np.zeros(n),
        params=Params(step_quant=step),
    )


def _state(rng: np.random.Generator, spec: MarketSpec) -> EngineState:
    n = len(spec.names)
    return dataclasses.replace(
        initial_state(spec, now_ms=NOW),
        y=rng.uniform(-8.0, 8.0, n),
        cum_orders=rng.uniform(-5.0, 5.0, n),
        flow_ema=rng.uniform(0.0, 3.0, n),
        jumps=tuple(
            PriceJump(i, 0.0, 1.0, NOW, NOW + 5_000) for i in range(n) if rng.random() < 0.5
        ),
        rng_counter=int(rng.integers(0, 100)),
        version=int(rng.integers(0, 100)),
    )


def _quotes(spec: MarketSpec, state: EngineState) -> FloatArray:
    return prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)[1]


def _same_bytes(left: FloatArray, right: FloatArray) -> bool:
    return left.dtype == right.dtype and left.tobytes() == right.tobytes()


# --- hold_quoted_prices -----------------------------------------------------------------


TOL = 1e-9


def _expected(price: float, lo: float, hi: float, step: float) -> float:
    """R6, as the human decided (2026-10-06): clamp, re-quantise, and if that grid point
    lies outside `[lo, hi]`, take the neighbouring one inside instead."""
    k = float(np.round(np.clip(price, lo, hi) / step))
    if k * step > hi + TOL and (k - 1) * step >= lo - TOL:
        k -= 1
    elif k * step < lo - TOL and (k + 1) * step <= hi + TOL:
        k += 1
    return k * step


def _grid_point_within(lo: float, hi: float, step: float) -> bool:
    return bool(np.floor(hi / step + TOL) * step >= lo - TOL)


def test_a_held_quote_is_the_nearest_quote_within_the_new_bounds() -> None:
    """AC8/AC10 (engine half), R6: over random cent bounds, most off the new grid, the held
    quote is the clamped, re-quantised old quote -- stepped back inside the bounds when a
    half-step bound rounds it out -- and lies within the bounds whenever a grid point does."""
    rng = np.random.default_rng(6301)
    misses: list[tuple[float, float, float, float, float]] = []
    outside = 0
    stepped_in = 0
    for _ in range(3000):
        n = int(rng.integers(1, 6))
        old = _spec(rng, n, float(rng.choice(STEPS)))
        state = _state(rng, old)
        if rng.random() < 0.5:
            new = dataclasses.replace(old, params=Params(step_quant=float(rng.choice(STEPS))))
        else:
            moved = _spec(rng, n, old.params.step_quant)
            new = dataclasses.replace(old, p_min=moved.p_min, p_max=moved.p_max, p0=moved.p0)
        slots = [i for i in range(n) if rng.random() < 0.7]

        held = hold_quoted_prices(old, new, state, slots)

        before = _quotes(old, state)
        after = _quotes(new, held)
        step = new.params.step_quant
        for i in slots:
            lo, hi = float(new.p_min[i]), float(new.p_max[i])
            target = _expected(float(before[i]), lo, hi, step)
            rounded = float(quantize_step(np.clip(before[i], lo, hi), step))
            stepped_in += int(target != rounded)
            if after[i] != target:
                misses.append((target, float(after[i]), lo, hi, step))
            if _grid_point_within(lo, hi, step) and not lo - TOL <= after[i] <= hi + TOL:
                outside += 1
    assert misses == [], f"{len(misses)} held quotes differ from their target: {misses[:10]}"
    assert outside == 0
    assert stepped_in >= 10, "the random bounds must reach the half-step case R6 is about"


def test_the_half_step_bound_cases_found_by_the_property_test() -> None:
    """The cases that stopped T3 (2026-10-06): each now holds the nearest in-bounds quote."""
    for price, lo, hi, step, want in (
        (4.8, 2.23, 4.75, 0.1, 4.7),
        (5.0, 2.25, 4.95, 0.1, 4.9),
        (5.0, 3.66, 4.75, 0.5, 4.5),
        (2.2, 2.25, 6.14, 0.1, 2.3),
        (0.4, 0.5, 5.28, 0.2, 0.6),
    ):
        old = MarketSpec(
            names=("x",),
            p_min=np.array([0.0]),
            p_max=np.array([20.0]),
            p0=np.array([1.0]),
            a=np.zeros(1),
            d=np.zeros(1),
            s0=np.zeros(1),
            c=np.zeros(1),
            params=Params(step_quant=0.01),
        )
        y = np.log(price / 20.0 / (1 - price / 20.0))
        state = dataclasses.replace(initial_state(old, now_ms=NOW), y=np.array([y]))
        assert _quotes(old, state)[0] == price
        new = dataclasses.replace(
            old,
            p_min=np.array([lo]),
            p_max=np.array([hi]),
            p0=np.array([(lo + hi) / 2]),
            params=Params(step_quant=step),
        )
        held = hold_quoted_prices(old, new, state, [0])
        assert abs(_quotes(new, held)[0] - want) < TOL, (price, lo, hi, step)


def test_unheld_slots_keep_their_y_bitwise_and_held_slots_lose_their_jumps() -> None:
    rng = np.random.default_rng(6302)
    for _ in range(500):
        n = int(rng.integers(2, 6))
        old = _spec(rng, n, 0.5)
        new = dataclasses.replace(old, params=Params(step_quant=0.1))
        state = _state(rng, old)
        slots = {int(rng.integers(0, n))}

        held = hold_quoted_prices(old, new, state, slots)

        for i in range(n):
            if i not in slots:
                assert _same_bytes(held.y[i : i + 1], state.y[i : i + 1])
        assert held.jumps == tuple(j for j in state.jumps if j.i not in slots)
        for key in ("cum_orders", "flow_ema", "last_order_ts"):
            assert _same_bytes(getattr(held, key), getattr(state, key)), key
        assert (held.rng_counter, held.version) == (state.rng_counter, state.version)


# --- append_slot ------------------------------------------------------------------------


def test_an_appended_slot_quotes_p0_and_leaves_every_prefix_bitwise() -> None:
    """AC14 (engine half), SD12."""
    rng = np.random.default_rng(6303)
    for _ in range(500):
        n = int(rng.integers(1, 6))
        grown = _spec(rng, n + 1, float(rng.choice(STEPS)))
        old = MarketSpec(
            names=grown.names[:n],
            **{k: getattr(grown, k)[:n] for k in ("p_min", "p_max", "p0", "a", "d", "s0", "c")},
            params=grown.params,
        )
        state = _state(rng, old)

        appended = append_slot(grown, state, now_ms=NOW + 42)

        alone = initial_state(grown, now_ms=NOW + 42)
        assert _same_bytes(appended.y[n:], alone.y[n:])
        assert _quotes(grown, appended)[n] == float(
            quantize_step(grown.p0[n], grown.params.step_quant)
        )
        assert (appended.cum_orders[n], appended.flow_ema[n]) == (0.0, 0.0)
        assert appended.last_order_ts[n] == NOW + 42
        for key in ("y", "cum_orders", "flow_ema", "last_order_ts"):
            assert _same_bytes(getattr(appended, key)[:n], getattr(state, key)), key
        assert appended.jumps == state.jumps
        for counter in ("rng_counter", "version", "tick_index", "t_round", "last_idle_ms"):
            assert getattr(appended, counter) == getattr(state, counter), counter


def test_the_noise_draw_is_prefix_stable() -> None:
    """SD12: one more drink does not change the existing drinks' raw draws."""
    for seed in (0, 7, 2**62 + 3):
        for counter in (0, 1, 999):
            for n in (1, 5, 12):
                short = np.random.default_rng(np.random.SeedSequence([seed, counter]))
                long = np.random.default_rng(np.random.SeedSequence([seed, counter]))
                assert _same_bytes(long.normal(0.0, 0.18, n + 1)[:n], short.normal(0.0, 0.18, n))


# --- cancel_jumps -----------------------------------------------------------------------


def test_cancel_jumps_drops_only_the_named_slots_in_order() -> None:
    jumps = tuple(PriceJump(i, 0.0, 1.0, NOW, NOW + 1) for i in (3, 0, 2, 1))
    state = dataclasses.replace(
        initial_state(_spec(np.random.default_rng(1), 4, 0.1), now_ms=NOW), jumps=jumps
    )
    assert [j.i for j in cancel_jumps(state, [0, 2]).jumps] == [3, 1]
    assert cancel_jumps(state, []).jumps == jumps
