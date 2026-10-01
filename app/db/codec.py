"""The engine-state codec: positional arrays to `drink_id`-keyed JSON and back, pure.

The engine's arrays are positional; what is stored is keyed by `drink_id`
(D-24, AC14), so a reorder or a removed drink can never shift one drink's
state onto another. Jumps carry their `drink_id` instead of the index.

Floats round-trip bit-exactly (AC3): `json.dumps` writes `float.__repr__`,
the shortest text that parses back to the same double, and the columns are
`json`, not `jsonb`, so the text is stored as written and `-0.0` keeps its
sign (PD7). Nothing here rounds, normalises or quantises a value.
`allow_nan=False` makes a non-finite value raise rather than be written
(AC8).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.errors import AppError
from exchange import EngineState, MarketSpec, PriceJump, prices_from_y

_PER_DRINK = ("y", "cum_orders", "flow_ema", "last_order_ts")


class StateDrinkMismatch(AppError):
    """The stored engine state names a different set of drinks than the run has."""

    status_code = 500
    code = "state_drink_mismatch"


@dataclass(frozen=True)
class EncodedState:
    """One `engine_state` row's values: JSON text for the per-drink and jump columns."""

    y: str
    cum_orders: str
    flow_ema: str
    last_order_ts: str
    jumps: str
    last_idle_ms: int
    last_bm_ms: int
    rng_counter: int
    version: int
    tick_index: int
    t_round: int


def _dumps(value: Any) -> str:
    return json.dumps(value, allow_nan=False)


def encode_state(state: EngineState, drink_ids: Sequence[int]) -> EncodedState:
    """`state` with every per-drink value keyed by the `drink_id` at its position."""
    keys = [str(drink_id) for drink_id in drink_ids]
    columns: dict[str, list[Any]] = {
        "y": [float(v) for v in state.y],
        "cum_orders": [float(v) for v in state.cum_orders],
        "flow_ema": [float(v) for v in state.flow_ema],
        "last_order_ts": [int(v) for v in state.last_order_ts],
    }
    return EncodedState(
        **{name: _dumps(dict(zip(keys, values, strict=True))) for name, values in columns.items()},
        jumps=_dumps(
            [
                {
                    "drink_id": drink_ids[jump.i],
                    "y0": float(jump.y0),
                    "y1": float(jump.y1),
                    "t0_ms": int(jump.t0_ms),
                    "t1_ms": int(jump.t1_ms),
                }
                for jump in state.jumps
            ]
        ),
        last_idle_ms=state.last_idle_ms,
        last_bm_ms=state.last_bm_ms,
        rng_counter=state.rng_counter,
        version=state.version,
        tick_index=state.tick_index,
        t_round=state.t_round,
    )


def _mismatch(column: str, stored: set[int], expected: set[int]) -> StateDrinkMismatch:
    parts = []
    if missing := sorted(expected - stored):
        parts.append(f"missing: {', '.join(map(str, missing))}")
    if extra := sorted(stored - expected):
        parts.append(f"extra: {', '.join(map(str, extra))}")
    return StateDrinkMismatch(
        f"engine_state.{column} does not match the run's drinks ({'; '.join(parts)})"
    )


def decode_state(encoded: EncodedState, drink_ids: Sequence[int]) -> EngineState:
    """The positional state, in `drink_ids` order, or `StateDrinkMismatch` naming the ids."""
    expected = set(drink_ids)
    arrays: dict[str, list[Any]] = {}
    for column in _PER_DRINK:
        stored = {int(key): value for key, value in json.loads(getattr(encoded, column)).items()}
        if set(stored) != expected:
            raise _mismatch(column, set(stored), expected)
        arrays[column] = [stored[drink_id] for drink_id in drink_ids]

    position = {drink_id: i for i, drink_id in enumerate(drink_ids)}
    jumps = []
    for jump in json.loads(encoded.jumps):
        if jump["drink_id"] not in position:
            raise StateDrinkMismatch(
                f"engine_state.jumps names drink {jump['drink_id']}, which the run does not have"
            )
        jumps.append(
            PriceJump(
                i=position[jump["drink_id"]],
                y0=float(jump["y0"]),
                y1=float(jump["y1"]),
                t0_ms=int(jump["t0_ms"]),
                t1_ms=int(jump["t1_ms"]),
            )
        )

    return EngineState(
        y=np.array(arrays["y"], dtype=np.float64),
        cum_orders=np.array(arrays["cum_orders"], dtype=np.float64),
        flow_ema=np.array(arrays["flow_ema"], dtype=np.float64),
        last_order_ts=np.array(arrays["last_order_ts"], dtype=np.int64),
        jumps=tuple(jumps),
        last_idle_ms=encoded.last_idle_ms,
        last_bm_ms=encoded.last_bm_ms,
        rng_counter=encoded.rng_counter,
        version=encoded.version,
        tick_index=encoded.tick_index,
        t_round=encoded.t_round,
    )


def tick_prices(
    spec: MarketSpec, state: EngineState, drink_ids: Sequence[int]
) -> dict[int, dict[str, float]]:
    """The SD10 `price_tick.prices` shape: `{drink_id: {"p_cont", "p_q"}}`."""
    p_cont, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
    return {
        drink_id: {"p_cont": float(p_cont[i]), "p_q": float(p_q[i])}
        for i, drink_id in enumerate(drink_ids)
    }
