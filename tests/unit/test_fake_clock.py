"""`FakeClock` (tests/support/clock.py): the fake every Phase 3 timing test runs on.

If the fake woke sleepers early, late or out of order, the ticker and hub tests
built on it would prove nothing, so it gets tests of its own.
"""

from __future__ import annotations

import asyncio

import pytest

from app.runtime.clock import Clock, RealClock
from tests.support.clock import FakeClock

START_MS = 1_759_312_800_000


def test_both_implement_the_clock_protocol() -> None:
    clocks: list[Clock] = [RealClock(), FakeClock(START_MS)]

    assert all(isinstance(clock.wall_ms(), int) for clock in clocks)


def test_time_stands_still_until_advanced() -> None:
    clock = FakeClock(START_MS, monotonic_start=5.0)

    assert (clock.wall_ms(), clock.monotonic()) == (START_MS, 5.0)

    clock.advance(1_500)

    assert (clock.wall_ms(), clock.monotonic()) == (START_MS + 1_500, 6.5)


def test_time_does_not_run_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        FakeClock(START_MS).advance(-1)


def test_set_wall_moves_wall_time_only() -> None:
    clock = FakeClock(START_MS)

    clock.set_wall(START_MS - 60_000)

    assert (clock.wall_ms(), clock.monotonic()) == (START_MS - 60_000, 0.0)


def test_a_sleeper_wakes_only_once_its_deadline_has_passed() -> None:
    async def scenario() -> list[str]:
        clock = FakeClock(START_MS)
        events: list[str] = []

        async def sleeper() -> None:
            await clock.sleep_until(2.0)
            events.append(f"woke at {clock.monotonic()}")

        task = asyncio.create_task(sleeper())
        await asyncio.sleep(0)
        clock.advance(1_999)
        await asyncio.sleep(0)
        events.append("woke early" if task.done() else "still asleep")
        clock.advance(1)
        await task
        return events

    assert asyncio.run(scenario()) == ["still asleep", "woke at 2.0"]


def test_sleepers_wake_in_deadline_order_whatever_order_they_slept_in() -> None:
    async def scenario() -> tuple[list[float], list[int]]:
        clock = FakeClock(START_MS)
        woken: list[float] = []
        waiting: list[int] = []

        async def sleeper(deadline: float) -> None:
            await clock.sleep_until(deadline)
            woken.append(deadline)

        tasks = [asyncio.create_task(sleeper(d)) for d in (3.0, 1.0, 2.0, 1.0)]
        await asyncio.sleep(0)
        waiting.append(clock.sleepers)
        clock.advance(2_500)
        await asyncio.sleep(0)
        waiting.append(clock.sleepers)
        clock.advance(500)
        await asyncio.gather(*tasks)
        return woken, waiting

    assert asyncio.run(scenario()) == ([1.0, 1.0, 2.0, 3.0], [4, 1])


def test_a_deadline_already_passed_returns_without_advancing() -> None:
    async def scenario() -> float:
        clock = FakeClock(START_MS, monotonic_start=10.0)
        await asyncio.wait_for(clock.sleep_until(9.0), timeout=1)
        await asyncio.wait_for(clock.sleep_until(10.0), timeout=1)
        return clock.monotonic()

    assert asyncio.run(scenario()) == 10.0


def test_a_cancelled_sleeper_is_skipped() -> None:
    async def scenario() -> int:
        clock = FakeClock(START_MS)
        task = asyncio.create_task(clock.sleep_until(1.0))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        clock.advance(2_000)
        return clock.sleepers

    assert asyncio.run(scenario()) == 0


def test_the_real_clock_sleeps_until_a_monotonic_deadline() -> None:
    async def scenario() -> tuple[float, float]:
        clock = RealClock()
        deadline = clock.monotonic() + 0.02
        await clock.sleep_until(deadline)
        return clock.monotonic(), deadline

    after, deadline = asyncio.run(scenario())
    assert after >= deadline - 0.005  # the event loop's timer resolution
