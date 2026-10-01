"""The boot gap rule (SD2): what a long outage does to the engine's clock.

The engine measures every elapsed-time gate from an anchor in `EngineState`. If
the process was down for longer than the catch-up budget, Phase 3's ticker will
replay only `budget` worth of ticks; the rest of the outage is cut out by moving
every anchor forward by `gap - budget`. No price moves, and an interrupted jump
plays out its remaining time after boot instead of having completed in the dark.

The shift is exactly `gap - budget`, not `gap` (PD1, confirmed at the Phase 2
audit): the `budget` ms the ticker catches up are real elapsed time, so a jump
progresses through them.
"""

from __future__ import annotations

import dataclasses

from exchange import EngineState

# ADR 0003: the most wall-clock time the ticker replays after a restart.
DEFAULT_CATCH_UP_BUDGET_MS = 30_000


def gap_shift_ms(*, last_wall_ts_ms: int, now_ms: int, budget_ms: int) -> int | None:
    """How far the gap rule moves every anchor: `gap - budget_ms`, or `None` within the budget.

    The one place that arithmetic lives, so the jump anchors here and an active
    market event's start and end (Phase 3 SD23, AC19a) move by exactly the same
    amount.
    """
    gap = now_ms - last_wall_ts_ms
    if gap <= budget_ms:
        return None
    return gap - budget_ms


def apply_gap_rule(
    state: EngineState, *, last_wall_ts_ms: int, now_ms: int, budget_ms: int
) -> EngineState | None:
    """The state with every anchor moved past the gap, or `None` if there is no gap.

    `None` means "change nothing and write nothing": `now_ms - last_wall_ts_ms`
    is within `budget_ms` (or negative, a clock that went backwards). Otherwise
    `last_order_ts` (every drink), `last_idle_ms`, `last_bm_ms` and each jump's
    `t0_ms` and `t1_ms` move forward by `gap - budget_ms`, and `version` counts
    one accepted transition (PD16). `tick_index`, `rng_counter` and every float
    are left exactly as they were.
    """
    shift = gap_shift_ms(last_wall_ts_ms=last_wall_ts_ms, now_ms=now_ms, budget_ms=budget_ms)
    if shift is None:
        return None
    return dataclasses.replace(
        state,
        last_order_ts=state.last_order_ts + shift,
        last_idle_ms=state.last_idle_ms + shift,
        last_bm_ms=state.last_bm_ms + shift,
        jumps=tuple(
            dataclasses.replace(j, t0_ms=j.t0_ms + shift, t1_ms=j.t1_ms + shift)
            for j in state.jumps
        ),
        version=state.version + 1,
    )
