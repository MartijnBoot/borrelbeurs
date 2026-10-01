"""The clock seam (Phase 3 SD32): the one place the runtime reads time.

The ticker, the hub, the login limiter and session expiry all take a `Clock`
instead of calling `time`, so tests drive them on `tests/support/clock.py`'s
`FakeClock` -- a 120 s backpressure test must not take 120 s, and AC18a counts
ticks "on the fake clock". `RealClock` here is the only `import time` under
`app/runtime/` and `app/realtime/`; `tests/meta/test_clock_seam.py` holds that.

Two readings, deliberately separate. `wall_ms` stamps what is persisted and
broadcast; `monotonic` schedules, because wall time can jump (SD13 re-anchors
when the two diverge).
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
        await asyncio.sleep(max(0.0, monotonic_deadline - time.monotonic()))
