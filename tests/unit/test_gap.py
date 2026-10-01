"""The boot gap rule, pure (Phase 2 T2: AC4, AC5, AC6; SD2; PD1, PD16).

The live configuration's market, traded for a while so that every per-drink
value is non-trivial, then left alone for a "gap" before a rehydrate at `R`.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS, apply_gap_rule, gap_shift_ms
from exchange import EngineState, MarketSpec, advance, initial_state, prices_from_y, schedule_jump
from exchange.steps import apply_jumps
from tests.engine.golden.replay import spec_from_config
from tests.engine.golden.scenarios import LIVE_CONFIG

BUDGET = DEFAULT_CATCH_UP_BUDGET_MS
START = 1_759_312_800_000
SEED = 42
JUMP_DRINK = 2
JUMP_MS = 120_000


def _traded() -> tuple[MarketSpec, EngineState, int]:
    """A live-config market after 125 s of ticks and orders, with a 120 s jump
    started at 85 s -- 40 s before the last commit. Returns spec, state, last wall ts."""
    spec = spec_from_config(LIVE_CONFIG)
    state = initial_state(spec, now_ms=START)
    n = len(spec.names)
    now = START
    for second in range(1, 126):
        now = START + second * 1_000
        if second == 85:
            state = schedule_jump(
                spec, state, drink=JUMP_DRINK, p_target=6.9, duration_ms=JUMP_MS, now_ms=now
            )
        orders = np.eye(n)[second % n] * 2 if second % 7 == 0 else None
        state = advance(spec, state, now_ms=now, orders=orders, run_seed=SEED).state
    return spec, state, now


def test_the_default_budget_is_adr_0003s_thirty_seconds() -> None:
    assert DEFAULT_CATCH_UP_BUDGET_MS == 30_000


@pytest.mark.parametrize("gap", [BUDGET, 0, -5_000, 1])
def test_a_gap_within_the_budget_changes_nothing(gap: int) -> None:
    """AC4 (pure half): `None`, so the caller writes nothing; a negative gap too."""
    _, state, last_wall = _traded()

    assert (
        apply_gap_rule(state, last_wall_ts_ms=last_wall, now_ms=last_wall + gap, budget_ms=BUDGET)
        is None
    )


@pytest.mark.parametrize("gap", [BUDGET + 1, 10 * 60_000, 5 * 3_600_000])
def test_a_gap_beyond_the_budget_shifts_every_anchor_by_gap_minus_budget(gap: int) -> None:
    """AC5 (pure half), SD2: every wall-clock anchor moves; nothing else does."""
    spec, state, last_wall = _traded()
    shift = gap - BUDGET

    shifted = apply_gap_rule(
        state, last_wall_ts_ms=last_wall, now_ms=last_wall + gap, budget_ms=BUDGET
    )

    assert shifted is not None
    assert np.array_equal(shifted.last_order_ts, state.last_order_ts + shift)
    assert shifted.last_order_ts.dtype == np.int64
    assert shifted.last_idle_ms == state.last_idle_ms + shift
    assert shifted.last_bm_ms == state.last_bm_ms + shift
    assert len(shifted.jumps) == len(state.jumps) == 1
    for before, after in zip(state.jumps, shifted.jumps, strict=True):
        assert (after.i, after.y0, after.y1) == (before.i, before.y0, before.y1)
        assert (after.t0_ms, after.t1_ms) == (before.t0_ms + shift, before.t1_ms + shift)
    # PD16: an accepted transition, not a scheduled tick.
    assert shifted.version == state.version + 1
    assert shifted.tick_index == state.tick_index
    assert shifted.rng_counter == state.rng_counter
    assert shifted.t_round == state.t_round
    for key in ("y", "cum_orders", "flow_ema"):
        assert (
            getattr(shifted, key).view(np.uint64).tobytes()
            == getattr(state, key).view(np.uint64).tobytes()
        ), key
    # No price moves.
    step = spec.params.step_quant
    for price_before, price_after in zip(
        prices_from_y(state.y, spec.p_min, spec.p_max, step),
        prices_from_y(shifted.y, spec.p_min, spec.p_max, step),
        strict=True,
    ):
        assert np.array_equal(price_before, price_after)


def test_the_budget_is_a_parameter_not_a_literal() -> None:
    _, state, last_wall = _traded()

    assert (
        apply_gap_rule(state, last_wall_ts_ms=last_wall, now_ms=last_wall + 10_000, budget_ms=5_000)
        is not None
    )
    assert (
        apply_gap_rule(
            state, last_wall_ts_ms=last_wall, now_ms=last_wall + 10_000, budget_ms=10_000
        )
        is None
    )


def test_an_interrupted_jump_plays_out_its_remaining_time_after_boot() -> None:
    """AC6 per PD1: the first `advance(R + 5 s)` puts the jump at elapsed
    `(last commit - t0) + budget + (now - R)` = 40 s + 30 s + 5 s, and the jump
    (80 s left at the commit, more than the budget) is still running."""
    spec, state, last_wall = _traded()
    rehydrate_at = last_wall + 10 * 60_000
    shifted = apply_gap_rule(
        state, last_wall_ts_ms=last_wall, now_ms=rehydrate_at, budget_ms=BUDGET
    )
    assert shifted is not None
    # Premise: Brownian runs after the jumps in `advance`, so its gate must be shut.
    bm_interval = int(spec.params.bm_dt_minutes * 60_000)
    assert shifted.last_bm_ms + bm_interval > rehydrate_at + 5_000

    after = advance(spec, shifted, now_ms=rehydrate_at + 5_000, run_seed=SEED).state

    (jump,) = state.jumps
    expected = apply_jumps(spec, state, now_ms=jump.t0_ms + 40_000 + BUDGET + 5_000)
    assert after.y[JUMP_DRINK] == expected.y[JUMP_DRINK]
    assert [j.i for j in after.jumps] == [JUMP_DRINK]


# --- gap_shift_ms (Phase 3 T7): the shared arithmetic -------------------------


@pytest.mark.parametrize(
    ("gap", "shift"),
    [
        (BUDGET, None),
        (0, None),
        (-5_000, None),
        (BUDGET + 1, 1),
        (10 * 60_000, 10 * 60_000 - BUDGET),
    ],
)
def test_gap_shift_ms_is_gap_minus_budget_or_none(gap: int, shift: int | None) -> None:
    assert gap_shift_ms(last_wall_ts_ms=START, now_ms=START + gap, budget_ms=BUDGET) == shift


@pytest.mark.parametrize("gap", [BUDGET, BUDGET + 1, 10 * 60_000])
def test_apply_gap_rule_moves_the_anchors_by_exactly_gap_shift_ms(gap: int) -> None:
    _, state, last_wall = _traded()
    kwargs = {"last_wall_ts_ms": last_wall, "now_ms": last_wall + gap, "budget_ms": BUDGET}

    shift = gap_shift_ms(**kwargs)
    shifted = apply_gap_rule(state, **kwargs)

    if shift is None:
        assert shifted is None
    else:
        assert shifted is not None
        assert shifted.last_idle_ms - state.last_idle_ms == shift
