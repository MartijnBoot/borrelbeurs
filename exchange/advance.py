"""`advance`: one accepted transition of the market, and `next_due_ms`: when the next one is.

Wall-clock time enters the engine here and only here, as `now_ms`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import numpy as np

from exchange.pricing import FloatArray
from exchange.spec import MarketSpec
from exchange.state import EngineState
from exchange.steps import (
    OrderDiagnostics,
    apply_brownian,
    apply_idle,
    apply_jumps,
    apply_orders,
)


@dataclass(frozen=True, eq=False)
class AdvanceResult:
    state: EngineState
    diagnostics: OrderDiagnostics | None  # None for a tick


def advance(
    spec: MarketSpec,
    state: EngineState,
    *,
    now_ms: int,
    orders: Any = None,
    run_seed: int,
) -> AdvanceResult:
    """The next state: an order batch if `orders` is given, a scheduled tick if not.

    The step order is v1's API call sequence (plan D3). A tick is
    `_snapshot_payload_unlocked` (legacy/v1/backend/api.py:775-777): idle,
    jumps, Brownian. An order is `post_order` (api.py:352-392): the order step,
    jumps, then that same tick sequence -- so jumps run twice (plan R10).

    `version` moves on every call; `tick_index` only on a tick (D9).
    `orders` must be N finite, non-negative numbers (D12); mapping drink names
    to that vector is the caller's job.
    """
    diagnostics = None
    if orders is not None:
        vec = _validated_orders(spec, orders)
        state, diagnostics = apply_orders(spec, state, vec, now_ms=now_ms)
        state = apply_jumps(spec, state, now_ms=now_ms)
    state = apply_idle(spec, state, now_ms=now_ms)
    state = apply_jumps(spec, state, now_ms=now_ms)
    state = apply_brownian(spec, state, now_ms=now_ms, run_seed=run_seed)
    state = dataclasses.replace(
        state,
        version=state.version + 1,
        tick_index=state.tick_index + (1 if orders is None else 0),
    )
    return AdvanceResult(state=state, diagnostics=diagnostics)


def _validated_orders(spec: MarketSpec, orders: Any) -> FloatArray:
    try:
        vec = np.array(orders, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"orders must be numbers, got {orders!r}") from exc
    n = len(spec.names)
    if vec.shape != (n,):
        raise ValueError(f"orders must have shape ({n},), got {vec.shape}")
    if not np.all(np.isfinite(vec)):
        raise ValueError("orders must be finite")
    if np.any(vec < 0):
        raise ValueError("orders must be non-negative")
    return vec


def next_due_ms(spec: MarketSpec, state: EngineState) -> int:
    """The earliest `now_ms` at which `advance(orders=None)` does anything but count.

    Before it, a tick changes no price and moves no anchor; at it, the idle or
    Brownian gate opens (v1's elapsed-time gates, measured from the D4
    anchors). While a jump is running every tick moves its drink, so the
    answer is the earliest running jump's start -- already past.
    """
    if state.jumps:
        return min(j.t0_ms for j in state.jumps)
    p = spec.params
    due = state.last_idle_ms + max(1, int(p.refresh_minutes * 60_000))
    if p.bm_enabled:
        due = min(due, state.last_bm_ms + max(1, int(p.bm_dt_minutes * 60_000)))
    return due
