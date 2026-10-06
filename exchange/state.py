"""What changes as a market trades: `EngineState`, and the `PriceJump`s within it.

Frozen, with every array a read-only copy (plan D14): a step returns a new
state rather than editing the one it was given, so a caller can compute a
candidate, commit it, and only then publish it.

Money and history are not here (Phase 1 spec, In scope 3). Of v1's scheduling
state only the two elapsed-time anchors stay -- `last_idle_ms` and `last_bm_ms`,
v1's `last_idle_apply_ms` and `last_bm_ts_ms` (D4) -- because v1's idle and
Brownian gates are measured from them.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from exchange.pricing import FRAC_EPS, FloatArray, inv_sigmoid, prices_from_y
from exchange.spec import MarketSpec

_FLOAT_ARRAYS = ("y", "cum_orders", "flow_ema")


@dataclass(frozen=True)
class PriceJump:
    """A scheduled smoothstep from `y0` to `y1` for drink `i` (v1 engine.py:84-90).

    v1's mutable `done` flag is gone: a finished jump is simply dropped from
    `EngineState.jumps`.
    """

    i: int
    y0: float
    y1: float
    t0_ms: int
    t1_ms: int


@dataclass(frozen=True, eq=False)
class EngineState:
    y: FloatArray
    cum_orders: FloatArray
    flow_ema: FloatArray
    last_order_ts: NDArray[np.int64]
    jumps: tuple[PriceJump, ...]
    last_idle_ms: int
    last_bm_ms: int
    # Three counters, three questions (architecture.md, "Three counters").
    rng_counter: int  # which noise draw comes next
    version: int  # state identity: +1 on every accepted transition
    tick_index: int  # +1 per scheduled tick only
    t_round: int  # v1's round counter: +1 per order and per idle step that adjusts

    def __post_init__(self) -> None:
        for key in _FLOAT_ARRAYS:
            arr = np.array(getattr(self, key), dtype=np.float64)
            arr.setflags(write=False)
            object.__setattr__(self, key, arr)
        ts = np.array(self.last_order_ts, dtype=np.int64)
        ts.setflags(write=False)
        object.__setattr__(self, "last_order_ts", ts)
        object.__setattr__(self, "jumps", tuple(self.jumps))


def initial_state(spec: MarketSpec, *, now_ms: int) -> EngineState:
    """The state v1's `ExchangeState.init` starts from (v1 engine.py:120-137).

    Every drink at `p0`, nothing ordered, every drink "last ordered" at
    `now_ms`, both anchors at 0 so the first tick runs idle and Brownian.
    Unlike v1 it does not apply `auto_calibrate_s0`: that changes the *spec*,
    so the caller does it with `anchor_s0_to_current_y(spec, state.y)`.
    """
    n = len(spec.names)
    return EngineState(
        y=inv_sigmoid((spec.p0 - spec.p_min) / (spec.p_max - spec.p_min)),
        cum_orders=np.zeros(n),
        flow_ema=np.zeros(n, dtype=float),
        last_order_ts=np.full(n, now_ms, dtype=np.int64),
        jumps=(),
        last_idle_ms=0,
        last_bm_ms=0,
        rng_counter=0,
        version=0,
        tick_index=0,
        t_round=0,
    )


def retarget_y_to_hold_quantized_prices(spec: MarketSpec, state: EngineState) -> EngineState:
    """Move `y` onto the quoted prices, so a spec change keeps every quote.

    v1 engine.py:176-180.
    """
    _, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
    frac = (np.array(p_q) - spec.p_min) / (spec.p_max - spec.p_min)
    frac = np.clip(frac, FRAC_EPS, 1 - FRAC_EPS)
    return dataclasses.replace(state, y=np.log(frac / (1 - frac)))


def hold_quoted_prices(
    old_spec: MarketSpec, new_spec: MarketSpec, state: EngineState, slots: Iterable[int]
) -> EngineState:
    """Keep each slot in `slots` at its quoted price across a spec change (Phase 6 SD9, D-45).

    For each such slot: the quote under `old_spec`, clamped into `new_spec`'s
    bounds, re-quantised on `new_spec`'s grid, then `y` refitted to it under
    `new_spec` with `retarget_y_to_hold_quantized_prices`' `FRAC_EPS` clip.
    Every other slot's `y` is the same value, bitwise. A jump on a held slot
    is dropped: its target was computed against the old spec.

    A bound half a step off the grid can round the clamped price to a grid
    point outside the bounds (`p_max` 4.75 on a 0.1 grid gives 4.8), which no
    `y` can quote. The target then steps one grid point back inside: the
    nearest quote within `[p_min, p_max]` (decided by the human, 2026-10-06,
    plan R6). Only when no grid point lies inside the bounds at all is the
    rounded value kept.
    """
    held = sorted(set(slots))
    _, p_q = prices_from_y(state.y, old_spec.p_min, old_spec.p_max, old_spec.params.step_quant)
    y = np.array(state.y)
    for i in held:
        lo, hi = new_spec.p_min[i], new_spec.p_max[i]
        target = _nearest_quote_within(float(np.clip(p_q[i], lo, hi)), lo, hi, new_spec)
        frac = np.clip((target - lo) / (hi - lo), FRAC_EPS, 1 - FRAC_EPS)
        y[i] = np.log(frac / (1 - frac))
    return cancel_jumps(dataclasses.replace(state, y=y), held)


# The bound tolerance `_single_step`'s unstick check uses: a grid point an ulp
# past a bound is on it.
_BOUND_TOL = 1e-9


def _nearest_quote_within(price: float, lo: float, hi: float, spec: MarketSpec) -> float:
    """`quantize_step(price)`, moved one grid point inward if that lands outside `[lo, hi]`.

    Computed as `k * step`, the same expression `quantize_step` evaluates, so
    the target is exactly a value the engine can quote.
    """
    step = spec.params.step_quant
    k = float(np.round(price / step))
    if k * step > hi + _BOUND_TOL and (k - 1) * step >= lo - _BOUND_TOL:
        k -= 1
    elif k * step < lo - _BOUND_TOL and (k + 1) * step <= hi + _BOUND_TOL:
        k += 1
    return k * step


def append_slot(new_spec: MarketSpec, state: EngineState, *, now_ms: int) -> EngineState:
    """Add `new_spec`'s last slot to `state` (Phase 6 SD12, D-02).

    The new slot starts as `initial_state` starts a drink: `y` from `p0`,
    nothing ordered, "last ordered" at `now_ms`. Every existing slot's values,
    the jumps and every counter are unchanged.
    """
    n = len(state.y)
    if len(new_spec.names) != n + 1:
        raise ValueError(f"the new spec has {len(new_spec.names)} drinks, expected {n + 1}")
    fresh = initial_state(new_spec, now_ms=now_ms)
    return dataclasses.replace(
        state,
        y=np.append(state.y, fresh.y[n]),
        cum_orders=np.append(state.cum_orders, fresh.cum_orders[n]),
        flow_ema=np.append(state.flow_ema, fresh.flow_ema[n]),
        last_order_ts=np.append(state.last_order_ts, fresh.last_order_ts[n]),
    )


def cancel_jumps(state: EngineState, slots: Iterable[int]) -> EngineState:
    """Drop every jump on a slot in `slots`; the others keep their order."""
    gone = set(slots)
    return dataclasses.replace(state, jumps=tuple(j for j in state.jumps if j.i not in gone))
