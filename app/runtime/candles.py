"""Server-side candles (Phase 3 SD25, ADR 0005), on the chart track (SD24, PD14).

`chart_price_cents` is the 0.01 track the candles are drawn from, the successor
of v1's `prices_disp`: `round(p_cont * 100)`, Python's round-half-even, as
`np.round` was. The charged track, `price_cents`, is `cents_from_quantised`
(`app/db/mapping.py`); this module never buckets on it.

Buckets are aligned to wall-clock multiples of `candle_interval_ms`. Each tick
carries, per drink, the OHLC of the current bucket (`CandleBook.update`); the
snapshot carries the bars for the ring's window (`bars_from_ring`), computed
the same way so the two always agree. A `gap` tick closes the open bucket: the
next update opens a fresh one even inside the same interval, so a candle never
spans an outage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.runtime.history import TickEntry


def chart_cents(p_cont: float) -> int:
    """The chart track: a continuous engine price as integer cents, half-even (PD14)."""
    return round(p_cont * 100)


def bucket_start(ts_ms: int, interval_ms: int) -> int:
    """The start of the wall-clock bucket `ts_ms` falls in."""
    return ts_ms - ts_ms % interval_ms


@dataclass(frozen=True)
class Candle:
    """One bucket of one drink, on the chart track, in integer cents."""

    t_ms: int
    o: int
    h: int
    l: int  # noqa: E741 -- OHLC is the protocol's own naming (SD24, AC23)
    c: int


class CandleBook:
    """The open bucket's candle per drink, updated tick by tick."""

    def __init__(self, interval_ms: int) -> None:
        if interval_ms <= 0:
            raise ValueError(f"candle interval must be positive, got {interval_ms} ms")
        self._interval_ms = interval_ms
        self._bucket: int | None = None
        self._open: dict[int, Candle] = {}
        self._generation = 0

    def update(self, ts_ms: int, source: str, prices: Mapping[int, int]) -> dict[int, Candle]:
        """Fold one committed tick's chart prices in; the current candle of each drink given."""
        start = bucket_start(ts_ms, self._interval_ms)
        if start != self._bucket:
            self._bucket = start
            self._open = {}
            self._generation += 1
        for drink_id, cents in prices.items():
            candle = self._open.get(drink_id)
            self._open[drink_id] = (
                Candle(start, cents, cents, cents, cents)
                if candle is None
                else Candle(
                    candle.t_ms, candle.o, max(candle.h, cents), min(candle.l, cents), cents
                )
            )
        current = {drink_id: self._open[drink_id] for drink_id in prices}
        if source == "gap":
            self._bucket = None
            self._open = {}
        return current


def bars_from_ring(entries: Iterable[TickEntry], interval_ms: int) -> dict[int, list[Candle]]:
    """Every drink's bars over `entries` (version order), oldest first, as `update` built them."""
    book = CandleBook(interval_ms)
    bars: dict[int, list[Candle]] = {}
    generation_of_last: dict[int, int] = {}
    for entry in entries:
        current = book.update(
            entry.wall_ts_ms,
            entry.source,
            {drink_id: chart_cents(p["p_cont"]) for drink_id, p in entry.prices.items()},
        )
        for drink_id, candle in current.items():
            series = bars.setdefault(drink_id, [])
            if generation_of_last.get(drink_id) == book._generation:
                series[-1] = candle
            else:
                series.append(candle)
                generation_of_last[drink_id] = book._generation
    return bars
