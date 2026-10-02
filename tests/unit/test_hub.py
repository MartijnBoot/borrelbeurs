"""The hub (Phase 3 T14: SD27, SD29; AC21, AC22 hub half), on the fake clock."""

from __future__ import annotations

import asyncio
import inspect
import json

from app.realtime.hub import QUEUE_LIMIT, SEND_TIMEOUT_MS, Hub
from app.realtime.messages import Envelope, Pong, Resync, TickData, TickDrink
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
WINDOW_MS = 15 * 60_000


class HealthySocket:
    def __init__(self) -> None:
        self.frames: list[str] = []
        self.closed: int | None = None

    async def send_text(self, frame: str) -> None:
        self.frames.append(frame)

    async def close(self, code: int) -> None:
        self.closed = code


class StuckSocket(HealthySocket):
    """Never finishes a send: a client that stopped reading and filled its TCP window."""

    async def send_text(self, frame: str) -> None:
        await asyncio.get_running_loop().create_future()


class SlowSocket(HealthySocket):
    """Each send takes `delay_ms` of fake time: slower than 1 Hz, quicker than the timeout."""

    def __init__(self, clock: FakeClock, delay_ms: int) -> None:
        super().__init__()
        self._clock = clock
        self._delay_s = delay_ms / 1000

    async def send_text(self, frame: str) -> None:
        await self._clock.sleep_until(self._clock.monotonic() + self._delay_s)
        self.frames.append(frame)


def _tick(clock: FakeClock, version: int) -> Envelope:
    return Envelope(
        type="tick",
        seq=0,
        ts_ms=clock.wall_ms(),
        run_id=1,
        version=version,
        data=TickData(
            candle_t_ms=T0,
            drinks={
                7: TickDrink(price_cents=250, chart_price_cents=250, candle=(250, 250, 250, 250))
            },
        ),
    )


def _pong(clock: FakeClock) -> Envelope:
    return Envelope(
        type="pong", seq=0, ts_ms=clock.wall_ms(), run_id=1, version=None, data=Pong(server_ts_ms=1)
    )


async def _drain() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def _types(frames: list[str]) -> list[str]:
    return [json.loads(f)["type"] for f in frames]


def test_broadcast_and_unicast_never_await() -> None:
    """SD29: enqueueing never awaits, so neither the ticker nor a client waits on a socket."""
    assert not inspect.iscoroutinefunction(Hub.broadcast)
    assert not inspect.iscoroutinefunction(Hub.unicast)


def test_the_limits_are_sd29s() -> None:
    assert (QUEUE_LIMIT, SEND_TIMEOUT_MS) == (64, 10_000)


def test_a_stuck_and_a_slow_client_do_not_delay_a_healthy_one() -> None:
    """AC22: 120 fake seconds of 1 Hz ticks. The healthy client gets all 120 in order;
    the slow one overflows and is sent one `resync`; the stuck one is closed by the 10 s
    send timeout. The broadcaster never waited on any of them."""

    async def scenario() -> tuple[HealthySocket, SlowSocket, StuckSocket, list[int]]:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS)
        healthy, slow, stuck = HealthySocket(), SlowSocket(clock, 5_000), StuckSocket()
        for socket in (healthy, slow, stuck):
            hub.connect(socket)
        seqs = []
        for k in range(1, 121):
            clock.advance(1_000)
            seqs.append(hub.broadcast(_tick(clock, k)))
            await _drain()
        clock.advance(60_000)
        await _drain()
        await hub.close_all(1001)
        return healthy, slow, stuck, seqs

    healthy, slow, stuck, seqs = asyncio.run(scenario())

    assert seqs == list(range(1, 121))
    assert [json.loads(f)["seq"] for f in healthy.frames] == seqs
    assert [json.loads(f)["version"] for f in healthy.frames] == list(range(1, 121))
    assert "resync" in _types(slow.frames)
    assert len(slow.frames) < 120
    assert stuck.closed == 1013
    assert healthy.closed == 1001


def test_overflow_drops_every_queued_tick_and_enqueues_one_resync() -> None:
    async def scenario() -> list[str]:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS)
        slow = SlowSocket(clock, 1_000)
        connection = hub.connect(slow)
        hub.broadcast(_tick(clock, 1))
        await _drain()  # tick 1 is now in flight
        for k in range(2, QUEUE_LIMIT + 3):  # 64 fill the queue, the 65th overflows it
            hub.broadcast(_tick(clock, k))
        hub.unicast(connection, _pong(clock))
        await _drain()
        for _ in range(5):
            clock.advance(1_000)
            await _drain()
        return slow.frames

    frames = asyncio.run(scenario())

    assert _types(frames) == ["tick", "resync", "pong"]


def test_a_queue_full_of_non_ticks_closes_with_1013() -> None:
    async def scenario() -> int | None:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS)
        stuck = StuckSocket()
        connection = hub.connect(stuck)
        await _drain()
        for _ in range(QUEUE_LIMIT + 2):
            hub.unicast(connection, _pong(clock))
        await _drain()
        return stuck.closed

    assert asyncio.run(scenario()) == 1013


def test_a_send_over_ten_seconds_closes_only_that_connection() -> None:
    async def scenario() -> tuple[int | None, int | None, int]:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS)
        healthy, stuck = HealthySocket(), StuckSocket()
        hub.connect(healthy)
        hub.connect(stuck)
        hub.broadcast(_tick(clock, 1))
        await _drain()
        clock.advance(SEND_TIMEOUT_MS - 1)
        await _drain()
        before = stuck.closed
        clock.advance(1)
        await _drain()
        hub.broadcast(_tick(clock, 2))
        await _drain()
        return before, stuck.closed, len(healthy.frames)

    assert asyncio.run(scenario()) == (None, 1013, 2)


def test_unicast_carries_the_current_seq_without_moving_it() -> None:
    """SD27: a snapshot at seq S means "state as of S"; the next broadcast is S+1."""

    async def scenario() -> list[int]:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS)
        socket = HealthySocket()
        connection = hub.connect(socket)
        hub.unicast(connection, _pong(clock))
        hub.broadcast(_tick(clock, 1))
        hub.unicast(connection, _pong(clock))
        hub.unicast(connection, _pong(clock))
        hub.broadcast(_tick(clock, 2))
        await _drain()
        return [json.loads(f)["seq"] for f in socket.frames]

    assert asyncio.run(scenario()) == [0, 1, 1, 1, 2]


def test_replay_returns_exactly_the_frames_after_last_seq() -> None:
    """AC21 (hub half)."""

    async def scenario() -> None:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS, boot_id="b00t")
        frames = []
        for k in range(1, 6):
            clock.advance(1_000)
            hub.broadcast(_tick(clock, k))
        replay = hub.replay_after("b00t", 2)
        assert replay is not None
        frames = [json.loads(f)["seq"] for f in replay]
        assert frames == [3, 4, 5]
        assert hub.replay_after("b00t", 5) == []
        assert hub.replay_after("b00t", 0) is not None
        assert hub.replay_after("other", 2) is None
        assert hub.replay_after("b00t", 6) is None
        assert hub.seq == 5

    asyncio.run(scenario())


def test_replay_is_none_once_the_seq_is_trimmed_from_the_window() -> None:
    async def scenario() -> tuple[bool, list[int]]:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=10_000, boot_id="b00t")
        for k in range(1, 21):
            clock.advance(1_000)
            hub.broadcast(_tick(clock, k))
        trimmed = hub.replay_after("b00t", 3) is None
        kept = hub.replay_after("b00t", 12)
        assert kept is not None
        return trimmed, [json.loads(f)["seq"] for f in kept]

    trimmed, kept = asyncio.run(scenario())
    assert trimmed
    assert kept == list(range(13, 21))


def test_a_resync_frame_is_a_closed_envelope() -> None:
    async def scenario() -> list[str]:
        clock = FakeClock(T0)
        hub = Hub(clock=clock, replay_window_ms=WINDOW_MS)
        slow = SlowSocket(clock, 1_000)
        hub.connect(slow)
        hub.broadcast(_tick(clock, 1))
        await _drain()
        for k in range(2, QUEUE_LIMIT + 3):
            hub.broadcast(_tick(clock, k))
        for _ in range(3):
            clock.advance(1_000)
            await _drain()
        return slow.frames

    resync = [f for f in asyncio.run(scenario()) if json.loads(f)["type"] == "resync"]
    assert len(resync) == 1
    assert isinstance(Envelope.model_validate_json(resync[0]).data, Resync)


def test_a_new_boot_id_per_hub() -> None:
    clock = FakeClock(T0)

    assert (
        Hub(clock=clock, replay_window_ms=1).boot_id != Hub(clock=clock, replay_window_ms=1).boot_id
    )
