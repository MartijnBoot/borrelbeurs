"""Market-event rules, pure (Phase 3 T7: AC19a pure half; SD23)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.mapping import DrinkRow
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS, apply_gap_rule, gap_shift_ms
from app.runtime.market_events import (
    NEWS_FOR_KIND,
    ActiveEvent,
    EventKind,
    shift_events,
    target_cents,
)
from tests.unit.test_gap import _traded

V1_API = Path(__file__).resolve().parents[2] / "legacy" / "v1" / "backend" / "api.py"

BIER = DrinkRow(
    drink_id=7,
    slot=0,
    name="Bier",
    p_min_cents=150,
    p0_cents=260,
    p_max_cents=500,
    a=0.0,
    d=0.0,
    s0=0.0,
    c=0.0,
    bar_price_cents=260,
)


@pytest.mark.parametrize(("kind", "cents"), [("crash", 150), ("bubble", 500), ("correction", 260)])
def test_each_kind_targets_its_bound(kind: EventKind, cents: int) -> None:
    assert target_cents(kind, BIER) == cents


def test_every_kind_has_news() -> None:
    assert set(NEWS_FOR_KIND) == {"crash", "bubble", "correction"}


# v1's own `target` per kind (api.py:483-488) and the level it used.
V1_TARGET = {
    "crash": ("min", "Danger"),
    "bubble": ("max", "Warning"),
    "correction": ("mid", "Info"),
}


@pytest.mark.parametrize("kind", ["crash", "bubble", "correction"])
def test_the_news_text_is_v1s_verbatim_and_the_level_lowercased(kind: EventKind) -> None:
    """Compared to the v1 source lines (api.py:492-500), not retyped."""
    block = V1_API.read_text(encoding="utf-8").splitlines()[491:500]
    news = NEWS_FOR_KIND[kind]
    _, v1_level = V1_TARGET[kind]

    text_line = next(i for i, line in enumerate(block) if f'news_text = "{news.text}"' in line)
    assert block[text_line + 1].strip() == f'news_level = "{v1_level}"'
    assert news.level == v1_level.lower()
    assert news.level in {"info", "success", "warning", "danger"}


def test_the_v1_block_is_where_the_test_looks() -> None:
    """Anti-vacuity: lines 492-500 are still the three-branch news block."""
    block = V1_API.read_text(encoding="utf-8").splitlines()[491:500]

    assert sum("news_text = " in line for line in block) == 3


EVENTS = (
    ActiveEvent(event_id=1, kind="crash", drink_ids=(7, 8), t_start_ms=1_000, t_end_ms=31_000),
    ActiveEvent(event_id=2, kind="bubble", drink_ids=(7,), t_start_ms=5_000, t_end_ms=6_000),
)


def test_shift_events_moves_start_and_end_only() -> None:
    shifted = shift_events(EVENTS, 120_000)

    assert [(e.t_start_ms, e.t_end_ms) for e in shifted] == [(121_000, 151_000), (125_000, 126_000)]
    assert [(e.event_id, e.kind, e.drink_ids) for e in shifted] == [
        (e.event_id, e.kind, e.drink_ids) for e in EVENTS
    ]


@pytest.mark.parametrize("gap", [DEFAULT_CATCH_UP_BUDGET_MS + 1, 10 * 60_000])
def test_events_and_jump_anchors_move_by_the_same_gap_shift(gap: int) -> None:
    """AC19a (pure half): the event shift is exactly the amount the jump anchors moved."""
    _, state, last_wall = _traded()
    now = last_wall + gap
    budget = DEFAULT_CATCH_UP_BUDGET_MS

    shift = gap_shift_ms(last_wall_ts_ms=last_wall, now_ms=now, budget_ms=budget)
    shifted_state = apply_gap_rule(state, last_wall_ts_ms=last_wall, now_ms=now, budget_ms=budget)

    assert shift is not None and shifted_state is not None
    (jump_before,) = state.jumps
    (jump_after,) = shifted_state.jumps
    jump_moved = jump_after.t0_ms - jump_before.t0_ms
    assert jump_moved == jump_after.t1_ms - jump_before.t1_ms == shift
    (event,) = shift_events(EVENTS[:1], shift)
    assert event.t_start_ms - EVENTS[0].t_start_ms == jump_moved
    assert event.t_end_ms - EVENTS[0].t_end_ms == jump_moved
