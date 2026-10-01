"""The history ring: the committed price ticks within the window, in version order (SD11).

Loaded from `price_tick` at boot, then appended to after each committed
transition, so reading history is a pure in-memory read (AC17). Every
committed transition is kept, identical prices included: the display track's
dedupe is D-28 and Phase 3's.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TickEntry:
    """One `price_tick` row: `prices` is `{drink_id: {"p_cont", "p_q"}}` (SD10)."""

    version: int
    wall_ts_ms: int
    source: str
    prices: Mapping[int, Mapping[str, float]]


class HistoryRing:
    """Ticks with `wall_ts_ms >= latest.wall_ts_ms - window_ms`; "latest" is the highest version."""

    def __init__(self, window_ms: int) -> None:
        self._window_ms = window_ms
        self._entries: deque[TickEntry] = deque()

    def load(self, entries: Iterable[TickEntry]) -> None:
        """Replace the contents with `entries`, which must be in strictly ascending version."""
        loaded: deque[TickEntry] = deque()
        for entry in entries:
            if loaded and entry.version <= loaded[-1].version:
                raise ValueError(
                    f"history must load in ascending version: {entry.version} after "
                    f"{loaded[-1].version}"
                )
            loaded.append(entry)
        self._entries = loaded
        self._trim()

    def append(self, entry: TickEntry) -> None:
        """Add the tick of a transition. Call only after its transaction committed (SD11)."""
        if self._entries and entry.version <= self._entries[-1].version:
            raise ValueError(
                f"history appends in ascending version: {entry.version} after "
                f"{self._entries[-1].version}"
            )
        self._entries.append(entry)
        self._trim()

    def window(self) -> tuple[TickEntry, ...]:
        return tuple(self._entries)

    def _trim(self) -> None:
        # Filtered, not popped from the left: wall time need not rise with version.
        if self._entries:
            cutoff = self._entries[-1].wall_ts_ms - self._window_ms
            self._entries = deque(e for e in self._entries if e.wall_ts_ms >= cutoff)
