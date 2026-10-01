"""The pricing steps. Each takes a spec and a state and returns a new state.

Ported from v1 (tests/engine/v1_reference/engine.py) with every expression
unchanged; nothing here mutates its arguments.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import numpy as np

from exchange.pricing import (
    FRAC_EPS,
    FRAC_EPS_LOOSE,
    FloatArray,
    expected_flow_from_price,
    inv_sigmoid,
    prices_from_y,
    quantize_step,
)
from exchange.spec import MarketSpec
from exchange.state import EngineState, PriceJump


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


def schedule_jump(
    spec: MarketSpec,
    state: EngineState,
    *,
    drink: int,
    p_target: float,
    duration_ms: int,
    now_ms: int,
) -> EngineState:
    """Start easing `drink` to `p_target` over `duration_ms` (v1 engine.py:318-332).

    The target is quantised to `step_quant` and its fraction clipped into
    (0, 1), so a target outside `[p_min, p_max]` saturates at the bound rather
    than raising (AC8). A jump already running on that drink is replaced.
    """
    if not 0 <= drink < len(spec.names):
        raise ValueError(f"unknown drink index {drink} (market has {len(spec.names)} drinks)")
    step = float(spec.params.step_quant)
    p_target_q = float(quantize_step(p_target, step))
    lo, hi = spec.p_min[drink], spec.p_max[drink]
    f = np.clip((p_target_q - lo) / (hi - lo), FRAC_EPS, 1 - FRAC_EPS)
    y1 = float(inv_sigmoid(f))
    jump = PriceJump(
        i=drink,
        y0=float(state.y[drink]),
        y1=y1,
        t0_ms=now_ms,
        t1_ms=now_ms + max(1, int(duration_ms)),
    )
    # Replace in place, as v1's dict assignment keeps the key's position.
    jumps = [jump if j.i == drink else j for j in state.jumps]
    if not any(j.i == drink for j in state.jumps):
        jumps.append(jump)
    return dataclasses.replace(state, jumps=tuple(jumps), version=state.version + 1)


def apply_jumps(spec: MarketSpec, state: EngineState, *, now_ms: int) -> EngineState:
    """Put every jumping drink on its smoothstep path; land and drop finished jumps.

    v1 engine.py:334-358. While a jump is active this overwrites whatever
    orders or noise did to that drink's `y` (AC7) -- but only when it runs: in
    v1's tick Brownian runs after it, so a jumping drink can be published with
    one draw of noise on top until the next application (plan D5).
    """
    if not state.jumps:
        return state
    y = np.array(state.y)
    remaining = []
    for pj in state.jumps:
        if now_ms >= pj.t1_ms:
            y[pj.i] = pj.y1
        else:
            # smoothstep easing
            f = (now_ms - pj.t0_ms) / max(1, pj.t1_ms - pj.t0_ms)
            f = np.clip(f, 0.0, 1.0)
            f = f * f * (3 - 2 * f)
            y[pj.i] = pj.y0 + f * (pj.y1 - pj.y0)
            remaining.append(pj)
    return dataclasses.replace(state, y=y, jumps=tuple(remaining))


def apply_idle(spec: MarketSpec, state: EngineState, *, now_ms: int) -> EngineState:
    """Push idle drinks down and "rise" drinks up, once per `refresh_minutes`.

    v1 engine.py:239-291.

    D-22: the gate is `refresh_minutes`, measured from `last_idle_ms`.
    `idle_decay_minutes` and `idle_rise_minutes` are only the per-drink "time
    since last order" thresholds checked once the gate is open, so an idle
    drink is not touched before the next refresh boundary however long it has
    gone unordered.
    """
    p = spec.params
    interval_ms = max(1, int(p.refresh_minutes * 60_000))
    if now_ms - state.last_idle_ms < interval_ms:
        return state

    # Nothing to do?
    if not (p.idle_targets or p.idle_rise_targets):
        return dataclasses.replace(state, last_idle_ms=now_ms)

    _, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, p.step_quant)
    p_mean = float(np.mean(p_q))
    exp_flow = (
        expected_flow_from_price(p_q, p_mean, spec.a, spec.d, spec.s0, spec.c)
        if p.demand_enabled
        else np.zeros_like(p_q)
    )

    name_to_idx = {nm: i for i, nm in enumerate(spec.names)}
    f = np.zeros(len(spec.names), float)
    any_adj = False

    # decay (push down)
    if p.idle_targets:
        idle_ms = int(p.idle_decay_minutes * 60_000)
        for nm in p.idle_targets:
            j = name_to_idx.get(nm)
            if j is None:
                continue
            if now_ms - int(state.last_order_ts[j]) >= idle_ms:
                base = exp_flow[j] if p.demand_enabled else 0.0
                pop_weight = 1.0 + np.log1p(base)
                f[j] -= abs(float(p.idle_strength)) * pop_weight
                any_adj = True

    # rise (push up)
    if p.idle_rise_targets:
        rise_ms = int(p.idle_rise_minutes * 60_000)
        for nm in p.idle_rise_targets:
            j = name_to_idx.get(nm)
            if j is None:
                continue
            if now_ms - int(state.last_order_ts[j]) >= rise_ms:
                base = exp_flow[j] if p.demand_enabled else 0.0
                pop_weight = 1.0 + np.log1p(base)
                f[j] += abs(float(p.idle_rise_strength)) * pop_weight
                any_adj = True

    if not any_adj:
        return dataclasses.replace(state, last_idle_ms=now_ms)

    stepped, _ = _single_step(spec, state, f)
    return dataclasses.replace(stepped, t_round=stepped.t_round + 1, last_idle_ms=now_ms)


def apply_brownian(
    spec: MarketSpec, state: EngineState, *, now_ms: int, run_seed: int
) -> EngineState:
    """One draw of noise in `y`, once per `bm_dt_minutes` (v1 engine.py:293-315).

    The draw is `_normal(run_seed, state.rng_counter, ...)`, then the counter
    moves on (D1). No draw and no counter bump when Brownian is disabled or
    `bm_sigma_y <= 0`. Its volatility scales with `flow_ema`, which only orders
    move and which never decays (D-23, ADR 0012).
    """
    p = spec.params
    if not p.bm_enabled:
        return state
    dt_ms = max(1, int(p.bm_dt_minutes * 60_000))
    if now_ms - state.last_bm_ms < dt_ms:
        return state

    dt_min = dt_ms / 60_000.0
    sigma_y = float(p.bm_sigma_y)
    if sigma_y <= 0:
        return dataclasses.replace(state, last_bm_ms=now_ms)

    ranges = spec.p_max - spec.p_min
    mean_range = float(np.mean(ranges)) if float(np.mean(ranges)) > 0 else 1.0
    range_scale = ranges / mean_range
    scale = range_scale * (1.0 + p.flow_vol_amp * np.log1p(state.flow_ema))
    draw = _normal(run_seed, state.rng_counter, sigma_y * np.sqrt(dt_min), len(spec.names))
    dy = draw * scale
    y = np.clip(state.y + dy, -p.y_clip, p.y_clip)
    return dataclasses.replace(state, y=y, last_bm_ms=now_ms, rng_counter=state.rng_counter + 1)


def _normal(run_seed: int, rng_counter: int, scale: Any, size: int) -> FloatArray:
    """Draw `rng_counter` of the run's noise stream (D1, architecture.md "The engine").

    `loc`, `scale` and `size` are passed exactly as v1 passes them
    (v1 engine.py:311); scaling a unit normal afterwards would not give the
    same floats.
    """
    rng = np.random.default_rng(np.random.SeedSequence([run_seed, rng_counter]))
    out: FloatArray = rng.normal(0.0, scale, size)
    return out
