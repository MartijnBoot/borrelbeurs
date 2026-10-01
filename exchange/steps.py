"""The pricing steps. Each takes a spec and a state and returns a new state.

Ported from v1 (tests/engine/v1_reference/engine.py) with every expression
unchanged; nothing here mutates its arguments.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from exchange.pricing import (
    FRAC_EPS,
    FRAC_EPS_LOOSE,
    FloatArray,
    expected_flow_from_price,
    inv_sigmoid,
    prices_from_y,
)
from exchange.spec import MarketSpec
from exchange.state import EngineState


@dataclass(frozen=True, eq=False)
class OrderDiagnostics:
    """The parts of v1's `single_step` logs that are not prices (v1 engine.py:228-236)."""

    order_pressure: FloatArray
    cross_price_pressure: FloatArray
    cum_orders: FloatArray


def apply_orders(
    spec: MarketSpec, state: EngineState, orders: FloatArray, *, now_ms: int
) -> tuple[EngineState, OrderDiagnostics]:
    """One order batch: v1's `post_order` pricing lines, then `single_step`, then `t_round + 1`.

    `flow_ema` and `last_order_ts` lived in v1's API (legacy/v1/backend/api.py:355-361),
    not its engine; they are pricing state, so they move here. `flow_ema` is
    updated only by orders and never decays (D-23, ADR 0012).
    """
    p = spec.params
    flow_ema = (1.0 - p.flow_beta) * state.flow_ema + p.flow_beta * orders
    last_order_ts = np.array(state.last_order_ts)
    for i, q in enumerate(orders):
        if q > 0:
            last_order_ts[i] = now_ms
    ordered = dataclasses.replace(state, flow_ema=flow_ema, last_order_ts=last_order_ts)
    stepped, diagnostics = _single_step(spec, ordered, orders)
    return dataclasses.replace(stepped, t_round=stepped.t_round + 1), diagnostics


def _single_step(
    spec: MarketSpec, state: EngineState, orders_vec: FloatArray
) -> tuple[EngineState, OrderDiagnostics]:
    """v1's `single_step` (v1 engine.py:190-236): new `y` and `cum_orders`, nothing else.

    Shared by the order path and the idle step, which feeds it a signed vector.
    """
    p = spec.params
    p_cont, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, p.step_quant)
    p_mean = float(np.mean(p_q))
    exp_flow = (
        expected_flow_from_price(p_q, p_mean, spec.a, spec.d, spec.s0, spec.c)
        if p.demand_enabled
        else np.zeros_like(p_q)
    )

    dev = orders_vec - exp_flow
    N = len(spec.names)
    if np.allclose(orders_vec, 0.0):
        order_pressure = np.zeros_like(dev)
    else:
        others_avg_dev = (np.sum(dev) - dev) / max(N - 1, 1)
        order_pressure = dev - p.lambda_orders * others_avg_dev

    cum_orders = p.decay_rho * state.cum_orders + dev
    # The cross-price term: dead under the live config (alpha_price = 0), kept frozen.
    cross = p.alpha_price * (p_mean - p_q) if p.alpha_price else np.zeros_like(p_q)
    E = order_pressure + p.phi_persist * cum_orders + cross

    frac = np.clip(
        (p_cont - spec.p_min) / (spec.p_max - spec.p_min), FRAC_EPS_LOOSE, 1 - FRAC_EPS_LOOSE
    )
    barrier = np.clip(frac * (1.0 - frac) * 4.0, 0.2, 1.0)
    E *= barrier

    y_next = state.y + p.eta * np.tanh(E / max(p.K, 1e-6))
    _, p_q_next = prices_from_y(y_next, spec.p_min, spec.p_max, p.step_quant)

    # The unstick hack (AC6): a quote pinned at a bound that pressure pushes
    # away from, but which would not move by itself, is moved one step.
    step = p.step_quant
    tol = 1e-9
    for i in range(N):
        lo, hi = spec.p_min[i], spec.p_max[i]
        if (
            ((E[i] > 0) or (orders_vec[i] > 0))
            and abs(p_q[i] - lo) <= tol
            and abs(p_q_next[i] - p_q[i]) <= tol
        ):
            target = min(hi, lo + step)
            p_q_next[i] = target
            f = np.clip((target - lo) / (hi - lo), FRAC_EPS, 1 - FRAC_EPS)
            y_next[i] = inv_sigmoid(f)
        if (
            ((E[i] < 0) or (orders_vec[i] < 0))
            and abs(p_q[i] - hi) <= tol
            and abs(p_q_next[i] - p_q[i]) <= tol
        ):
            target = max(lo, hi - step)
            p_q_next[i] = target
            f = np.clip((target - lo) / (hi - lo), FRAC_EPS, 1 - FRAC_EPS)
            y_next[i] = inv_sigmoid(f)

    diagnostics = OrderDiagnostics(
        order_pressure=order_pressure, cross_price_pressure=cross, cum_orders=cum_orders
    )
    return dataclasses.replace(state, y=y_next, cum_orders=cum_orders), diagnostics
