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
