"""The pure price helpers: logit space to quoted price, and back.

Ported from v1 (tests/engine/v1_reference/engine.py:13-36) with every
expression unchanged -- the same operations in the same order, so the same
floats. `tests/engine/test_pricing.py` holds each one bitwise to v1.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

# Keeps fractions strictly inside (0, 1) for log/sigmoid stability.
FRAC_EPS = 1e-9
# The looser bound used in the barrier computation.
FRAC_EPS_LOOSE = 1e-6


def sigmoid(x: Any) -> Any:
    return 1.0 / (1.0 + np.exp(-x))


def inv_sigmoid(p: Any) -> Any:
    p = np.clip(p, FRAC_EPS, 1 - FRAC_EPS)
    return np.log(p / (1 - p))


def quantize_step(x: Any, step: float = 0.5) -> Any:
    return np.round(x / step) * step


def prices_from_y(
    y: FloatArray, p_min: FloatArray, p_max: FloatArray, step: float
) -> tuple[FloatArray, FloatArray]:
    """The continuous price and the tradeable price quantised to `step`."""
    p_cont: FloatArray = p_min + (p_max - p_min) * sigmoid(y)
    p_q: FloatArray = quantize_step(p_cont, step=step)
    return p_cont, p_q


def expected_flow_from_price(
    p_q: FloatArray,
    p_mean: float,
    a: FloatArray,
    d: FloatArray,
    s0: FloatArray,
    c: FloatArray,
) -> FloatArray:
    """v1's linear demand model.

    Identically zero under the live config, where `a = d = s0 = c = 0`: dead in
    production, kept with its maths frozen (Phase 1 spec, Out of scope) because
    the default config's `demand_enabled: true` still runs it.
    """
    lam = a - d * p_q + s0 + c * (p_mean - p_q)
    flow: FloatArray = np.maximum(0.0, lam)
    return flow
