"""`FakeClock`: the `Clock` protocol (`app/runtime/clock.py`) on time the test controls.

Nothing moves until the test calls `advance(ms)`, which moves wall and
monotonic time together and wakes every `sleep_until` whose deadline has
passed, in deadline order (ties in the order they went to sleep). A woken
sleeper resumes on the event loop's next turn, not inside `advance`; a test
that wants it to have run yields to the loop first (`await asyncio.sleep(0)`).

`set_wall(ms)` moves wall time alone, which is how a clock change looks to the
ticker (SD13's re-anchor).

Not thread-safe: the futures belong to the loop that awaited them. Under
`TestClient` the app runs on a portal thread, so `advance` goes through
`client.portal.call(...)` (plan R3).
"""

from __future__ import annotations

import asyncio
import heapq
import itertools


class FakeClock:
    def __init__(self, wall_start_ms: int, monotonic_start: float = 0.0) -> None:
        self._wall_ms = wall_start_ms
        self._monotonic = monotonic_start
        self._order = itertools.count()
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []

    def wall_ms(self) -> int:
        return self._wall_ms

    def monotonic(self) -> float:
        return self._monotonic

    async def sleep_until(self, monotonic_deadline: float) -> None:
        if monotonic_deadline <= self._monotonic:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (monotonic_deadline, next(self._order), future))
        await future

    def advance(self, ms: int) -> None:
        """Move both clocks forward by `ms` and wake every sleeper now due."""
        if ms < 0:
            raise ValueError(f"time does not run backwards on a monotonic clock: {ms} ms")
        self._wall_ms += ms
        self._monotonic += ms / 1000
        while self._sleepers and self._sleepers[0][0] <= self._monotonic:
            _, _, future = heapq.heappop(self._sleepers)
            if not future.done():
                future.set_result(None)

    def set_wall(self, ms: int) -> None:
        """Jump wall time to `ms`, leaving monotonic time where it is."""
        self._wall_ms = ms

    @property
    def sleepers(self) -> int:
        """How many `sleep_until` calls are still waiting."""
        return sum(1 for _, _, future in self._sleepers if not future.done())
