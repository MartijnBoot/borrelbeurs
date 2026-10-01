"""Drive the pure engine through a fixture's events (Phase 1 plan T7; reused by T9).

The mirror of `capture.py`: the same four event kinds, mapped onto `exchange`'s
public API instead of v1's API code (D3):

- tick  -> `advance(orders=None)`
- order -> `advance(orders=vec)`
- jump  -> `schedule_jump`, then `advance(orders=None)`
- crash -> `schedule_jump` for every drink, then `advance(orders=None)`
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from exchange import (
    EngineState,
    MarketSpec,
    Params,
    advance,
    anchor_s0_to_current_y,
    initial_state,
    prices_from_y,
    schedule_jump,
)
from tests.engine.golden.scenarios import Event

# v1's `from_persist` fallbacks (v1 engine.py:154-163), for a config that omits them.
_V1_DEFAULTS: dict[str, Any] = {
    "names": ["Bier", "Wijn", "Cola", "Koffie", "Gin-tonic", "Mocktail"],
    "p_min": [0.5, 1.5, 0.5, 0.5, 2.0, 1.0],
    "p_max": [3.0, 5.0, 3.0, 3.0, 6.0, 5.0],
    "p0": [1.0, 3.0, 1.5, 1.0, 4.0, 2.0],
}
_V1_COEFF_DEFAULTS = {"a": 10.0, "d": 0.6, "s0": 8.0, "c": 0.4}


def spec_from_config(config: dict[str, Any]) -> MarketSpec:
    """A v1 persisted config (the shape of exchange_config.json) as a `MarketSpec`."""
    names = config.get("names") or _V1_DEFAULTS["names"]
    n = len(names)
    arrays = {k: np.array(config.get(k, _V1_DEFAULTS[k]), float) for k in ("p_min", "p_max", "p0")}
    coeffs = {k: np.array(config.get(k, [v] * n), float) for k, v in _V1_COEFF_DEFAULTS.items()}
    return MarketSpec(
        names=tuple(names),
        **arrays,
        **coeffs,
        params=Params.from_dict(config.get("params", {})),
    )


def start(config: dict[str, Any], start_ms: int) -> tuple[MarketSpec, EngineState]:
    """The spec and state v1's `init` produces, `auto_calibrate_s0` included."""
    spec = spec_from_config(config)
    state = initial_state(spec, now_ms=start_ms)
    if spec.params.auto_calibrate_s0:
        spec = anchor_s0_to_current_y(spec, state.y)
    return spec, state


def step(spec: MarketSpec, state: EngineState, event: Event, run_seed: int) -> EngineState:
    now = int(event["t"])
    kind = event["kind"]
    if kind == "order":
        return advance(
            spec, state, now_ms=now, orders=np.array(event["vec"], float), run_seed=run_seed
        ).state
    if kind == "jump":
        state = schedule_jump(
            spec,
            state,
            drink=int(event["drink"]),
            p_target=float(event["target"]),
            duration_ms=int(event["duration_ms"]),
            now_ms=now,
        )
    elif kind == "crash":
        for i in range(len(spec.names)):
            bound = {"min": spec.p_min, "max": spec.p_max}.get(event["target"], spec.p0)
            state = schedule_jump(
                spec,
                state,
                drink=i,
                p_target=float(bound[i]),
                duration_ms=int(event["duration_ms"]),
                now_ms=now,
            )
    elif kind != "tick":
        raise ValueError(f"unknown event kind {kind!r}")
    return advance(spec, state, now_ms=now, run_seed=run_seed).state


def record(spec: MarketSpec, state: EngineState) -> dict[str, Any]:
    """The same fields, in the same form, as `capture.py` records from v1."""
    p_cont, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
    return {
        "y": state.y.tolist(),
        "p_cont": p_cont.tolist(),
        "p_q": p_q.tolist(),
        "cum_orders": state.cum_orders.tolist(),
        "flow_ema": state.flow_ema.tolist(),
        "t_round": int(state.t_round),
        "rng_counter": int(state.rng_counter),
    }


def replay(
    config: dict[str, Any], run_seed: int, start_ms: int, events: Sequence[Event]
) -> list[dict[str, Any]]:
    """One record per event -- directly comparable with `capture.run_v1`'s."""
    spec, state = start(config, start_ms)
    records = []
    for event in events:
        state = step(spec, state, event, run_seed)
        records.append(record(spec, state))
    return records
