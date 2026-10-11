"""The clock seam (Phase 3 SD32): the one place the runtime reads time.

The ticker, the hub, the login limiter and session expiry all take a `Clock`
instead of calling `time`, so tests drive them on `tests/support/clock.py`'s
`FakeClock` -- a 120 s backpressure test must not take 120 s, and AC18a counts
ticks "on the fake clock". `RealClock` here is the only `import time` under
`app/runtime/` and `app/realtime/`; `tests/meta/test_clock_seam.py` holds that.

Two readings, deliberately separate. `wall_ms` stamps what is persisted and
broadcast; `monotonic` schedules, because wall time can jump (SD13 re-anchors
when the two diverge).

**The app clock (Phase 8 SD15, PD4).** `create_app` wraps whichever clock it is
given in `AppClock`, so every caller -- ticker, orders, jumps, drink and config
edits, news -- reads one wall time: the injected clock's plus an offset that only
ever grows. The ticker raises it when the wall clock steps back past the last
commit (T5), and boot when it rehydrates behind one. Each commit then stamps
`commit_stamp_ms`: never before the last commit, whatever the wall clock did.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def wall_ms(self) -> int:
        """Wall-clock time in integer milliseconds since the epoch."""
        ...

    def monotonic(self) -> float:
        """Monotonic time in seconds, as `time.monotonic`."""
        ...

    async def sleep_until(self, monotonic_deadline: float) -> None:
        """Return once `monotonic()` has reached `monotonic_deadline`."""
        ...


class RealClock:
    """The process's own clocks."""

    def wall_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep_until(self, monotonic_deadline: float) -> None:
        # `asyncio.sleep` may wake early -- on Windows by up to the ~16 ms timer
        # tick -- so sleep again until the deadline has really passed.
        while (remaining := monotonic_deadline - time.monotonic()) > 0:
            await asyncio.sleep(remaining)


class AppClock:
    """`inner`'s clocks, with wall time raised by an offset that never decreases."""

    def __init__(self, inner: Clock) -> None:
        self._inner = inner
        self._offset_ms = 0

    @property
    def offset_ms(self) -> int:
        return self._offset_ms

    def wall_ms(self) -> int:
        return self._inner.wall_ms() + self._offset_ms

    def monotonic(self) -> float:
        return self._inner.monotonic()

    async def sleep_until(self, monotonic_deadline: float) -> None:
        await self._inner.sleep_until(monotonic_deadline)

    def raise_to(self, target_ms: int) -> None:
        """Make `wall_ms()` at least `target_ms` now; a lower target changes nothing."""
        self._offset_ms = max(self._offset_ms, target_ms - self._inner.wall_ms())


class _Committed(Protocol):
    @property
    def last_commit_wall_ms(self) -> int | None: ...


def commit_stamp_ms(clock: Clock, committed: _Committed) -> int:
    """The stamp for a commit: now, or the last commit's stamp if now is before it.

    A wall clock stepping back within the catch-up budget therefore holds stamps
    at the last commit (ADR 0003); beyond it the ticker raises the app clock (T5).
    """
    return max(clock.wall_ms(), committed.last_commit_wall_ms or 0)
