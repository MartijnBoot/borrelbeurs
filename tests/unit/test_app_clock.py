"""`AppClock` and `commit_stamp_ms` (Phase 8 T4: SD15, PD4).

The app clock is the injected clock plus an offset that only ever grows. T5 raises
it when the wall clock steps back past the last commit; until then it is the inner
clock exactly. Every commit stamps `max(app now, last commit)`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.runtime.clock import AppClock, commit_stamp_ms
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
HOUR = 3_600_000


def test_without_an_offset_it_is_the_inner_clock() -> None:
    inner = FakeClock(T0, monotonic_start=5.0)
    clock = AppClock(inner)

    inner.advance(1_500)

    assert clock.wall_ms() == T0 + 1_500
    assert clock.monotonic() == 6.5
    assert clock.offset_ms == 0


def test_raise_to_lifts_wall_time_to_the_target_and_keeps_it_moving() -> None:
    inner = FakeClock(T0)
    clock = AppClock(inner)
    inner.set_wall(T0 - HOUR)

    clock.raise_to(T0)

    assert clock.offset_ms == HOUR
    assert clock.wall_ms() == T0
    inner.advance(1_000)
    assert clock.wall_ms() == T0 + 1_000


def test_the_offset_never_decreases() -> None:
    inner = FakeClock(T0)
    clock = AppClock(inner)
    inner.set_wall(T0 - HOUR)
    clock.raise_to(T0)

    clock.raise_to(T0 - 2 * HOUR)  # already past it
    inner.set_wall(T0 + HOUR)  # the wall clock comes back on its own

    assert clock.offset_ms == HOUR
    assert clock.wall_ms() == T0 + 2 * HOUR


def test_raise_to_a_time_already_reached_changes_nothing() -> None:
    inner = FakeClock(T0)
    clock = AppClock(inner)

    clock.raise_to(T0 - 1)

    assert clock.offset_ms == 0
    assert clock.wall_ms() == T0


def test_sleep_until_is_the_inner_clocks() -> None:
    inner = FakeClock(T0)
    clock = AppClock(inner)

    async def scenario() -> bool:
        sleeper = asyncio.create_task(clock.sleep_until(2.0))
        await asyncio.sleep(0)
        assert inner.sleepers == 1
        inner.advance(2_000)
        await sleeper
        return sleeper.done()

    assert asyncio.run(scenario())


@dataclass
class _View:
    last_commit_wall_ms: int | None


def test_a_commit_is_stamped_now_when_now_is_after_the_last_commit() -> None:
    assert commit_stamp_ms(FakeClock(T0), _View(T0 - 1)) == T0


def test_a_commit_is_never_stamped_before_the_last_commit() -> None:
    assert commit_stamp_ms(FakeClock(T0), _View(T0 + 5_000)) == T0 + 5_000


def test_with_no_commit_yet_the_stamp_is_now() -> None:
    assert commit_stamp_ms(FakeClock(T0), _View(None)) == T0
