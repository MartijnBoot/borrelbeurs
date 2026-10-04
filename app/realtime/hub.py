"""The hub: fan-out to WebSocket clients with per-connection backpressure (Phase 3 SD27, SD29).

**`seq` (SD27).** Every `broadcast` takes the next `seq`; a `unicast` (`hello`,
`snapshot`, `pong`, `error`) carries the current one without moving it, so a
snapshot at `seq = S` means "state as of S" and the next broadcast is `S+1`.
Each hub draws a random `boot_id`; with the replay log of broadcasts covering
`replay_window_ms`, a reconnecting client's `(boot_id, last_seq)` either gets
exactly the frames it missed or `None`, meaning "send a snapshot" (AC21). A
replay longer than `QUEUE_LIMIT` is `None` too: it is enqueued before the
writer can drain anything, so it would overflow into a `resync` mid-replay.

**Backpressure (SD29, D-34).** Each connection has a bounded queue of
`QUEUE_LIMIT` frames and one writer task. `broadcast` and `unicast` are plain
functions: they serialise once and enqueue, and never await, so neither the
ticker nor another client ever waits on a slow socket. On overflow every queued
`tick` is dropped and one `resync` is enqueued; if the queue is still full of
other frames the connection is closed with 1013. A single send taking longer
than `SEND_TIMEOUT_MS` on the injected clock also closes it with 1013.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections import deque
from typing import Final, Protocol

from app.realtime.messages import Envelope, Resync
from app.runtime.clock import Clock

QUEUE_LIMIT: Final = 64
SEND_TIMEOUT_MS: Final = 10_000
# "Try again later": the client is too far behind to be served from its queue.
CLOSE_TRY_AGAIN_LATER: Final = 1013


class Socket(Protocol):
    async def send_text(self, frame: str) -> None: ...

    async def close(self, code: int) -> None: ...


class Connection:
    """One client: a bounded queue of serialised frames, drained by its own writer task."""

    def __init__(self, hub: Hub, socket: Socket) -> None:
        self._hub = hub
        self.socket = socket
        self._queue: deque[tuple[str, str]] = deque()  # (type, frame)
        self._wake = asyncio.Event()
        self.closed = False
        self._writer = asyncio.get_running_loop().create_task(self._write())

    def enqueue(self, kind: str, frame: str) -> None:
        """Queue one frame without awaiting; overflow per SD29."""
        if self.closed:
            return
        if len(self._queue) >= QUEUE_LIMIT:
            self._queue = deque(item for item in self._queue if item[0] != "tick")
            if len(self._queue) >= QUEUE_LIMIT:
                self.close(CLOSE_TRY_AGAIN_LATER)
                return
            self._queue.append(("resync", self._hub.resync_frame()))
            if kind == "tick":
                return  # the resync supersedes it
            if len(self._queue) >= QUEUE_LIMIT:
                self.close(CLOSE_TRY_AGAIN_LATER)
                return
        self._queue.append((kind, frame))
        self._wake.set()

    def close(self, code: int) -> None:
        """Stop the writer and close the socket; idempotent, never awaits."""
        if self.closed:
            return
        self.closed = True
        self._queue.clear()
        self._writer.cancel()
        self._hub.forget(self)
        asyncio.get_running_loop().create_task(self._close_socket(code))

    async def _close_socket(self, code: int) -> None:
        with contextlib.suppress(Exception):
            await self.socket.close(code)

    async def _write(self) -> None:
        clock = self._hub.clock
        while True:
            while not self._queue:
                self._wake.clear()
                await self._wake.wait()
            _, frame = self._queue.popleft()
            send = asyncio.ensure_future(self.socket.send_text(frame))
            deadline = asyncio.ensure_future(
                clock.sleep_until(clock.monotonic() + SEND_TIMEOUT_MS / 1000)
            )
            try:
                await asyncio.wait({send, deadline}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                deadline.cancel()
            if not send.done():
                send.cancel()
                self.close(CLOSE_TRY_AGAIN_LATER)
                return
            if send.exception() is not None:
                self.close(CLOSE_TRY_AGAIN_LATER)
                return


class Hub:
    def __init__(self, *, clock: Clock, replay_window_ms: int, boot_id: str | None = None) -> None:
        self.clock = clock
        self.boot_id = boot_id if boot_id is not None else secrets.token_hex(8)
        self._replay_window_ms = replay_window_ms
        self._seq = 0
        self._log: deque[tuple[int, int, str]] = deque()  # (seq, ts_ms, frame)
        self._connections: set[Connection] = set()
        self._run_id: int | None = None
        self._version: int | None = None

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def connections(self) -> frozenset[Connection]:
        return frozenset(self._connections)

    def connect(self, socket: Socket) -> Connection:
        connection = Connection(self, socket)
        self._connections.add(connection)
        return connection

    def forget(self, connection: Connection) -> None:
        self._connections.discard(connection)

    def broadcast(self, envelope: Envelope) -> int:
        """Stamp the next `seq`, serialise once, log it, enqueue it everywhere; the `seq`."""
        self._seq += 1
        frame = envelope.model_copy(update={"seq": self._seq}).model_dump_json()
        self._run_id, self._version = envelope.run_id, envelope.version
        self._log.append((self._seq, envelope.ts_ms, frame))
        self._trim(envelope.ts_ms)
        for connection in tuple(self._connections):
            connection.enqueue(envelope.type, frame)
        return self._seq

    def unicast(self, connection: Connection, envelope: Envelope) -> None:
        """Send one frame to one client, stamped with the current `seq`, which does not move."""
        frame = envelope.model_copy(update={"seq": self._seq}).model_dump_json()
        connection.enqueue(envelope.type, frame)

    def resync_frame(self) -> str:
        return Envelope(
            type="resync",
            seq=self._seq,
            ts_ms=self.clock.wall_ms(),
            run_id=self._run_id,
            version=self._version,
            data=Resync(),
        ).model_dump_json()

    def replay_after(self, boot_id: str, last_seq: int) -> list[str] | None:
        """The broadcasts after `last_seq`, or `None` if they cannot all be replayed."""
        if boot_id != self.boot_id or last_seq > self._seq:
            return None
        if last_seq == self._seq:
            return []
        if not self._log or self._log[0][0] > last_seq + 1:
            return None
        if self._seq - last_seq > QUEUE_LIMIT:
            return None  # enqueued in one go, it would overflow into a resync
        return [frame for seq, _, frame in self._log if seq > last_seq]

    async def close_all(self, code: int) -> None:
        connections = tuple(self._connections)
        for connection in connections:
            connection.close(code)
        await asyncio.sleep(0)

    def _trim(self, newest_ts_ms: int) -> None:
        while self._log and self._log[0][1] < newest_ts_ms - self._replay_window_ms:
            self._log.popleft()
