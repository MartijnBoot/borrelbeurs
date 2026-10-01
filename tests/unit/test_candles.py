"""Candles, pure (Phase 3 T6: SD25; AC20 candle half; PD14)."""

from __future__ import annotations

import pytest

from app.runtime.candles import Candle, CandleBook, bars_from_ring, bucket_start, chart_cents
from app.runtime.history import TickEntry

MINUTE = 60_000
T0 = 1_759_312_800_000  # a whole minute
assert T0 % MINUTE == 0


@pytest.mark.parametrize(
    ("ts_ms", "start"),
    [(T0, T0), (T0 + 1, T0), (T0 + MINUTE - 1, T0), (T0 + MINUTE, T0 + MINUTE)],
)
def test_buckets_align_to_wall_clock_multiples(ts_ms: int, start: int) -> None:
    assert bucket_start(ts_ms, MINUTE) == start


def test_buckets_align_for_any_interval() -> None:
    assert bucket_start(T0 + 7_500, 5_000) == T0 + 5_000


@pytest.mark.parametrize(
    ("p_cont", "cents"),
    [(2.125, 212), (2.375, 238), (2.6, 260), (2.604, 260), (2.606, 261), (1.5, 150)],
)
def test_the_chart_track_rounds_half_even(p_cont: float, cents: int) -> None:
    """PD14: x.xx5 exactly representable rounds to even, as `np.round` did for v1."""
    assert chart_cents(p_cont) == cents
    assert isinstance(chart_cents(p_cont), int)


def test_ohlc_within_a_bucket_and_a_fresh_candle_across_the_boundary() -> None:
    book = CandleBook(MINUTE)

    for second, cents in enumerate((100, 120, 90, 110)):
        current = book.update(T0 + second * 1_000, "tick", {7: cents})

    assert current == {7: Candle(T0, o=100, h=120, l=90, c=110)}
    assert book.update(T0 + MINUTE, "tick", {7: 105}) == {
        7: Candle(T0 + MINUTE, o=105, h=105, l=105, c=105)
    }


def test_drinks_are_independent_and_only_given_drinks_are_returned() -> None:
    book = CandleBook(MINUTE)
    book.update(T0, "tick", {7: 100, 8: 200})

    current = book.update(T0 + 1_000, "order", {7: 130})

    assert current == {7: Candle(T0, o=100, h=130, l=100, c=130)}
    assert book.update(T0 + 2_000, "tick", {8: 190}) == {8: Candle(T0, o=200, h=200, l=190, c=190)}


def test_a_gap_closes_the_open_bucket_mid_interval() -> None:
    """SD25: the next update after a `gap` opens a fresh candle in the same interval."""
    book = CandleBook(MINUTE)
    book.update(T0, "tick", {7: 100})
    book.update(T0 + 1_000, "tick", {7: 140})

    assert book.update(T0 + 2_000, "gap", {7: 140}) == {7: Candle(T0, o=100, h=140, l=100, c=140)}
    assert book.update(T0 + 3_000, "tick", {7: 120}) == {7: Candle(T0, o=120, h=120, l=120, c=120)}


def test_a_non_positive_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        CandleBook(0)


def _entry(version: int, ts_ms: int, source: str, p_conts: dict[int, float]) -> TickEntry:
    return TickEntry(
        version=version,
        wall_ts_ms=ts_ms,
        source=source,
        prices={d: {"p_cont": p, "p_q": round(p, 1)} for d, p in p_conts.items()},
    )


RING = [
    _entry(1, T0 + 5_000, "tick", {7: 2.60, 8: 1.50}),
    _entry(2, T0 + 20_000, "order", {7: 2.81, 8: 1.49}),
    _entry(3, T0 + 59_999, "tick", {7: 2.55, 8: 1.52}),
    _entry(4, T0 + MINUTE, "tick", {7: 2.70, 8: 1.52}),
    _entry(5, T0 + MINUTE + 10_000, "gap", {7: 2.70, 8: 1.52}),
    _entry(6, T0 + MINUTE + 11_000, "tick", {7: 2.75, 8: 1.40}),
    _entry(7, T0 + 3 * MINUTE + 1, "tick", {7: 2.40, 8: 1.45}),
]


def test_bars_from_ring_agree_with_incremental_updates() -> None:
    """The snapshot's bars are exactly the candles the ticks carried, bucket by bucket."""
    book = CandleBook(MINUTE)
    last_in_bucket: dict[int, list[Candle]] = {7: [], 8: []}
    for entry in RING:
        current = book.update(
            entry.wall_ts_ms,
            entry.source,
            {d: chart_cents(p["p_cont"]) for d, p in entry.prices.items()},
        )
        for drink_id, candle in current.items():
            series = last_in_bucket[drink_id]
            if series and series[-1].t_ms == candle.t_ms and series[-1].o == candle.o:
                series[-1] = candle
            else:
                series.append(candle)

    assert bars_from_ring(RING, MINUTE) == last_in_bucket


def test_bars_from_ring_written_out() -> None:
    """Independently of `CandleBook`: four bars for drink 7, the gap splitting minute two."""
    assert bars_from_ring(RING, MINUTE)[7] == [
        Candle(T0, o=260, h=281, l=255, c=255),
        Candle(T0 + MINUTE, o=270, h=270, l=270, c=270),
        Candle(T0 + MINUTE, o=275, h=275, l=275, c=275),
        Candle(T0 + 3 * MINUTE, o=240, h=240, l=240, c=240),
    ]


def test_bars_from_an_empty_ring_are_empty() -> None:
    assert bars_from_ring([], MINUTE) == {}
