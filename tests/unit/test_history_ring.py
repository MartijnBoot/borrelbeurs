"""The in-memory history ring: committed ticks within the window, by version (T7).

AC21 (window logic), AC17 (pure in-memory reads); SD11.
"""

from __future__ import annotations

import pytest

from app.runtime.history import HistoryRing, TickEntry

WINDOW_MS = 15 * 60_000


def tick(version: int, wall_ts_ms: int, source: str = "tick") -> TickEntry:
    return TickEntry(
        version=version,
        wall_ts_ms=wall_ts_ms,
        source=source,
        prices={7: {"p_cont": 2.61, "p_q": 2.6}},
    )


def versions(ring: HistoryRing) -> list[int]:
    return [entry.version for entry in ring.window()]


def test_the_boundary_is_inclusive_at_exactly_the_window() -> None:
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(1, 1_000), tick(2, 1_000 + WINDOW_MS)])

    assert versions(ring) == [1, 2]


def test_one_millisecond_past_the_window_is_dropped() -> None:
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(1, 1_000), tick(2, 1_001), tick(3, 1_001 + WINDOW_MS)])

    assert versions(ring) == [2, 3]


def test_append_trims() -> None:
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(1, 0), tick(2, 60_000), tick(3, 120_000)])

    ring.append(tick(4, 60_000 + WINDOW_MS))

    assert versions(ring) == [2, 3, 4]


def test_the_window_is_measured_from_the_highest_version() -> None:
    """Not from the greatest wall time: a clock that stepped back keeps its own window."""
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(1, 0), tick(2, 2 * WINDOW_MS), tick(3, WINDOW_MS - 10)])

    assert versions(ring) == [1, 2, 3]


def test_the_order_is_by_version() -> None:
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(v, 1_000 * v) for v in range(1, 6)])
    ring.append(tick(9, 9_000, source="order"))

    assert versions(ring) == [1, 2, 3, 4, 5, 9]
    assert ring.window()[-1].source == "order"


@pytest.mark.parametrize("load", [[tick(2, 0), tick(1, 0)], [tick(1, 0), tick(1, 5)]])
def test_an_out_of_order_load_raises(load: list[TickEntry]) -> None:
    with pytest.raises(ValueError, match="version"):
        HistoryRing(WINDOW_MS).load(load)


@pytest.mark.parametrize("version", [3, 2])
def test_an_out_of_order_append_raises(version: int) -> None:
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(2, 0), tick(3, 0)])

    with pytest.raises(ValueError, match="version"):
        ring.append(tick(version, 10))
    assert versions(ring) == [2, 3]


def test_an_out_of_order_append_raises_even_after_its_predecessor_was_trimmed() -> None:
    ring = HistoryRing(1_000)
    ring.load([tick(1, 0), tick(5, 10_000)])

    with pytest.raises(ValueError, match="version"):
        ring.append(tick(4, 10_500))


def test_identical_consecutive_prices_are_kept() -> None:
    """Dedupe is D-28 and Phase 3's; every committed transition stays."""
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(1, 0), tick(2, 1)])
    ring.append(tick(3, 2))

    assert versions(ring) == [1, 2, 3]


def test_load_replaces_the_contents_and_an_empty_ring_is_empty() -> None:
    ring = HistoryRing(WINDOW_MS)
    assert ring.window() == ()

    ring.load([tick(1, 0)])
    ring.load([tick(5, 0)])

    assert versions(ring) == [5]


def test_window_returns_a_tuple() -> None:
    ring = HistoryRing(WINDOW_MS)
    ring.load([tick(1, 0)])

    assert isinstance(ring.window(), tuple)
