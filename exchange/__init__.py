"""The pricing engine: pure. No clock, no I/O, no framework.

`advance(spec, state, now_ms=..., orders=..., run_seed=...)` is the one entry
point that moves prices; everything it needs is in its arguments.
"""

from exchange.advance import AdvanceResult, advance, next_due_ms
from exchange.pricing import prices_from_y
from exchange.spec import DrinkSpec, MarketSpec, Params, anchor_s0_to_current_y
from exchange.state import (
    EngineState,
    PriceJump,
    append_slot,
    cancel_jumps,
    hold_quoted_prices,
    initial_state,
    retarget_y_to_hold_quantized_prices,
)
from exchange.steps import OrderDiagnostics, schedule_jump

__all__ = [
    "AdvanceResult",
    "DrinkSpec",
    "EngineState",
    "MarketSpec",
    "OrderDiagnostics",
    "Params",
    "PriceJump",
    "advance",
    "anchor_s0_to_current_y",
    "append_slot",
    "cancel_jumps",
    "hold_quoted_prices",
    "initial_state",
    "next_due_ms",
    "prices_from_y",
    "retarget_y_to_hold_quantized_prices",
    "schedule_jump",
]
