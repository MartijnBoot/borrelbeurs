"""Market events, pure (Phase 3 SD23): kinds, jump targets, v1's news text, the gap shift.

A crash, bubble or correction jumps every active drink to its `p_min`, `p_max`
or `p0`, and posts v1's auto news item: its Dutch text verbatim
(`legacy/v1/backend/api.py:492-500`), its level lowercased to SD13's four.

An active event's `t_start_ms` / `t_end_ms` are wall-clock anchors like a
jump's `t0_ms` / `t1_ms`, so the gap rule moves them by the same amount
(`app/runtime/gap.py`'s `gap_shift_ms`), extending Phase 2 SD2's anchor list.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

from app.db.mapping import DrinkRow

EventKind = Literal["crash", "bubble", "correction"]


@dataclass(frozen=True)
class ActiveEvent:
    event_id: int
    kind: EventKind
    drink_ids: tuple[int, ...]
    t_start_ms: int
    t_end_ms: int


@dataclass(frozen=True)
class EventNews:
    level: str
    text: str


NEWS_FOR_KIND: Final[dict[EventKind, EventNews]] = {
    "crash": EventNews("danger", "MARKTCRASH! Alle prijzen kelderen naar hun minimum!"),
    "bubble": EventNews("warning", "PRIJSBUBBEL! Alle prijzen schieten omhoog naar hun maximum!"),
    "correction": EventNews("info", "Marktcorrectie: Prijzen keren terug naar startpositie."),
}


def target_cents(kind: EventKind, drink: DrinkRow) -> int:
    """Where `kind` jumps `drink`: crash to `p_min`, bubble to `p_max`, correction to `p0`."""
    if kind == "crash":
        return drink.p_min_cents
    if kind == "bubble":
        return drink.p_max_cents
    return drink.p0_cents


def shift_events(events: Iterable[ActiveEvent], shift_ms: int) -> tuple[ActiveEvent, ...]:
    """Every event's start and end moved forward by `shift_ms`, the gap rule's amount."""
    return tuple(
        dataclasses.replace(e, t_start_ms=e.t_start_ms + shift_ms, t_end_ms=e.t_end_ms + shift_ms)
        for e in events
    )
