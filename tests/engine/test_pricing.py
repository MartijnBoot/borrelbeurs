"""`exchange.pricing` is v1's pure helpers, bit for bit (Phase 1 plan T2).

Every comparison is `np.array_equal` against the v1 reference on the same
inputs -- never `allclose` (D13). A ported expression whose arithmetic was
reordered would show up here, in the task that reordered it.
"""

from __future__ import annotations

import numpy as np
import pytest

from exchange import pricing
from exchange.pricing import FloatArray
from tests.engine.v1_reference import engine as v1

N_CASES = 1000
STEPS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0)


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(20261001)


def _bounds(rng: np.random.Generator, n: int) -> tuple[FloatArray, FloatArray]:
    p_min = rng.uniform(0.0, 10.0, n)
    return p_min, p_min + rng.uniform(0.5, 10.0, n)


def test_the_constants_are_v1s() -> None:
    assert pricing.FRAC_EPS == v1._FRAC_EPS
    assert pricing.FRAC_EPS_LOOSE == v1._FRAC_EPS_LOOSE


def test_sigmoid_matches_v1(rng: np.random.Generator) -> None:
    for _ in range(N_CASES):
        x = rng.uniform(-25.0, 25.0, 6)
        assert np.array_equal(pricing.sigmoid(x), v1._sigmoid(x))


def test_inv_sigmoid_matches_v1_including_clipped_inputs(rng: np.random.Generator) -> None:
    for _ in range(N_CASES):
        p = rng.uniform(-0.2, 1.2, 6)
        p[0], p[1] = 0.0, 1.0
        assert np.array_equal(pricing.inv_sigmoid(p), v1._inv_sigmoid(p))


def test_inv_sigmoid_matches_v1_on_a_scalar() -> None:
    f = np.clip(0.1 / 3.0, v1._FRAC_EPS, 1 - v1._FRAC_EPS)
    assert pricing.inv_sigmoid(f) == v1._inv_sigmoid(f)


def test_quantize_step_matches_v1(rng: np.random.Generator) -> None:
    for _ in range(N_CASES):
        x = rng.uniform(-5.0, 20.0, 6)
        step = float(rng.choice(STEPS))
        assert np.array_equal(pricing.quantize_step(x, step), v1._quantize_step(x, step))
    # The default step is v1's too.
    x = np.array([1.26, 1.24, 0.75])
    assert np.array_equal(pricing.quantize_step(x), v1._quantize_step(x))


def test_prices_from_y_matches_v1(rng: np.random.Generator) -> None:
    for _ in range(N_CASES):
        p_min, p_max = _bounds(rng, 6)
        y = rng.uniform(-8.0, 8.0, 6)
        step = float(rng.choice(STEPS))
        got_cont, got_q = pricing.prices_from_y(y, p_min, p_max, step)
        want_cont, want_q = v1.prices_from_y(y, p_min, p_max, step)
        assert np.array_equal(got_cont, want_cont)
        assert np.array_equal(got_q, want_q)


def test_expected_flow_from_price_matches_v1(rng: np.random.Generator) -> None:
    for _ in range(N_CASES):
        p_q = rng.uniform(0.0, 12.0, 6)
        a, d, s0, c = (rng.uniform(-5.0, 15.0, 6) for _ in range(4))
        p_mean = float(np.mean(p_q))
        got = pricing.expected_flow_from_price(p_q, p_mean, a, d, s0, c)
        assert np.array_equal(got, v1.expected_flow_from_price(p_q, p_mean, a, d, s0, c))


def test_expected_flow_is_identically_zero_under_the_live_config() -> None:
    """Why it is dead code in production (spec, Golden scenarios)."""
    zeros = np.zeros(6)
    p_q = np.array([2.6, 4.5, 6.0, 1.5, 3.6, 9.7])
    flow = pricing.expected_flow_from_price(p_q, float(np.mean(p_q)), zeros, zeros, zeros, zeros)
    assert np.array_equal(flow, zeros)
