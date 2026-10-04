"""`WS /ws`: the realtime endpoint (Phase 3 SD27, SD30, SD31, SD16; AC3, AC16, AC21, AC24, AC25).

**Handshake (SD31).** `require_ws_role` checks the `Origin` (SD9: browsers send
cookies on cross-site WebSocket handshakes) and the session -- the same
`authenticate` the HTTP routes use, so a revoked key is refused -- *before*
accept. Any failure closes with 1008 and no frame is sent. The dependency
carries `require_role`'s marker, so the route audit (SD4) sees it.

**Then:** a `hello` (unicast, `run_id` null with no live run), and up to one
tick interval for the client's `hello {boot_id, last_seq}`. With the current
`boot_id` and `last_seq` still in the hub's replay log the client gets exactly
the broadcasts it missed; otherwise one `snapshot` at the current `seq`, or
nothing with no live run (AC21, SD16). Only then is the connection added to
the hub, with no await in between, so no broadcast can overtake the replay.

**The theme (Phase 4 SD9, PD7).** `hello` carries the current theme. Because
`hello` goes out before the connection joins the hub, a `theme` broadcast in
between would reach nobody, and a `snapshot` carries no theme; so the handshake
ends with a `theme` unicast, and so does every `resync_request`'s snapshot. The
client applies a theme only when its revision is higher.

**Client messages (SD30)** are parsed with the closed union: `ping` -> a JSON
`pong` (AC24), `resync_request` -> a `snapshot`, anything else or invalid JSON
-> `error {code}`, and the connection stays open. More than five in a rolling
second closes with 1008. Nothing here calls the engine or `holder.mutate`
(AC16, D-36).

**Expiry (AC25).** A timer on the injected clock closes with 4401 at the
session's `exp`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from typing import Annotated, Final

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, WebSocketException
from pydantic import ValidationError

from app.api.deps import (
    ALL_ROLES,
    REQUIRE_ROLE_MARKER,
    SESSION_COOKIE,
    Principal,
    Unauthenticated,
    authenticate,
)
from app.api.security import same_origin
from app.realtime.hub import Connection, Hub
from app.realtime.messages import (
    PROTOCOL_VERSION,
    ClientHello,
    ClientPing,
    Envelope,
    ErrorData,
    Hello,
    Pong,
    ServerData,
    ServerMessageType,
    parse_client_message,
    theme_data,
)
from app.realtime.publish import snapshot
from app.runtime.clock import Clock
from app.runtime.holder import MarketHolder

router = APIRouter()

CLOSE_POLICY_VIOLATION: Final = 1008
CLOSE_SESSION_EXPIRED: Final = 4401
CLIENT_RATE: Final = 5  # messages per rolling second (SD30)


async def require_ws_role(websocket: WebSocket) -> Principal:
    """Origin and session, before accept; any failure is a 1008 close and no frame."""
    if not same_origin(websocket.headers.get("origin"), websocket.headers.get("host")):
        raise WebSocketException(code=CLOSE_POLICY_VIOLATION, reason="origin")
    state = websocket.app.state
    try:
        return await authenticate(
            token=websocket.cookies.get(SESSION_COOKIE),
            settings=state.settings,
            clock=state.clock,
            engine=state.engine,
        )
    except Unauthenticated:
        raise WebSocketException(code=CLOSE_POLICY_VIOLATION, reason="session") from None


setattr(require_ws_role, REQUIRE_ROLE_MARKER, frozenset(ALL_ROLES))


class _Socket:
    """The hub's `Socket` protocol over a Starlette WebSocket."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def send_text(self, frame: str) -> None:
        await self._ws.send_text(frame)

    async def close(self, code: int) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close(code)


class _Session:
    def __init__(self, websocket: WebSocket, principal: Principal) -> None:
        state = websocket.app.state
        self.ws = websocket
        self.principal = principal
        self.hub: Hub = state.hub
        self.holder: MarketHolder = state.holder
        self.clock: Clock = state.clock
        self.tick_interval_ms: int = state.tick_interval_ms
        self.app_state = state
        self.connection: Connection | None = None
        self._arrivals: deque[float] = deque()

    def envelope(self, kind: ServerMessageType, data: ServerData) -> Envelope:
        state = self.holder.state
        return Envelope(
            type=kind,
            seq=self.hub.seq,
            ts_ms=self.clock.wall_ms(),
            run_id=self.holder.run_id,
            version=None if state is None else state.version,
            data=data,
        )

    def send(self, kind: ServerMessageType, data: ServerData) -> None:
        assert self.connection is not None
        self.hub.unicast(self.connection, self.envelope(kind, data))

    def send_snapshot(self) -> None:
        data = snapshot(self.holder, tick_interval_ms=self.tick_interval_ms)
        if data is not None:
            self.send("snapshot", data)

    def send_theme(self) -> None:
        """The current theme, as a unicast that does not move `seq` (PD7)."""
        assert self.connection is not None
        envelope = self.envelope("theme", theme_data(self.app_state.theme))
        self.hub.unicast(self.connection, envelope.model_copy(update={"version": None}))

    def too_fast(self) -> bool:
        now = self.clock.monotonic()
        self._arrivals.append(now)
        while self._arrivals and self._arrivals[0] <= now - 1.0:
            self._arrivals.popleft()
        return len(self._arrivals) > CLIENT_RATE

    async def next_frame(self) -> str:
        """The next client frame; a binary one is `""`, which parses as no message (SD30)."""
        message = await self.ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000), message.get("reason"))
        text = message.get("text")
        return text if isinstance(text, str) else ""

    async def receive(self, *, until: float | None = None) -> str | None:
        """The next frame, or `None` if `until` (monotonic) passes first."""
        receiving = asyncio.ensure_future(self.next_frame())
        if until is None:
            return await receiving
        waiting = asyncio.ensure_future(self.clock.sleep_until(until))
        try:
            await asyncio.wait({receiving, waiting}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiting.cancel()
        if receiving.done():
            return receiving.result()
        receiving.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receiving
        return None

    def handle(self, raw: str) -> None:
        """Answer one client frame after the handshake; never mutates the market."""
        try:
            message = parse_client_message(raw)
        except ValidationError:
            self.send("error", ErrorData(code="invalid_message"))
            return
        if isinstance(message, ClientPing):
            self.send("pong", Pong(server_ts_ms=self.clock.wall_ms()))
        elif isinstance(message, ClientHello):
            self.send("error", ErrorData(code="unexpected_hello"))
        else:
            self.send_snapshot()
            self.send_theme()

    async def run(self) -> None:
        hello = self.envelope(
            "hello",
            Hello(
                boot_id=self.hub.boot_id,
                run_id=self.holder.run_id,
                tick_interval_ms=self.tick_interval_ms,
                protocol=PROTOCOL_VERSION,
                role=self.principal.role,
                theme=theme_data(self.app_state.theme),
            ),
        )
        await self.ws.send_text(hello.model_dump_json())

        first = await self.receive(until=self.clock.monotonic() + self.tick_interval_ms / 1000)
        if first is not None and self.too_fast():
            await self.ws.close(CLOSE_POLICY_VIOLATION)
            return
        parsed = None
        if first is not None:
            with contextlib.suppress(ValidationError):
                parsed = parse_client_message(first)

        # No await from here until the replay or snapshot is queued.
        self.connection = self.hub.connect(_Socket(self.ws))
        replay = (
            self.hub.replay_after(parsed.boot_id, parsed.last_seq)
            if isinstance(parsed, ClientHello)
            else None
        )
        if replay is not None:
            for frame in replay:
                self.connection.enqueue(json.loads(frame)["type"], frame)
        else:
            self.send_snapshot()
        self.send_theme()
        if first is not None and not isinstance(parsed, ClientHello):
            self.handle(first)

        while True:
            raw = await self.receive()
            assert raw is not None
            if self.too_fast():
                self.connection.close(CLOSE_POLICY_VIOLATION)
                return
            self.handle(raw)

    async def expire(self) -> None:
        remaining_s = (self.principal.exp_ms - self.clock.wall_ms()) / 1000
        await self.clock.sleep_until(self.clock.monotonic() + remaining_s)
        if self.connection is not None:
            self.connection.close(CLOSE_SESSION_EXPIRED)
        else:
            await self.ws.close(CLOSE_SESSION_EXPIRED)


@router.websocket("/ws")
async def ws(
    websocket: WebSocket, principal: Annotated[Principal, Depends(require_ws_role)]
) -> None:
    await websocket.accept()
    session = _Session(websocket, principal)
    talking = asyncio.ensure_future(session.run())
    expiring = asyncio.ensure_future(session.expire())
    try:
        await asyncio.wait({talking, expiring}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        talking.cancel()
        expiring.cancel()
        # `wait`, not `gather`: if this task is cancelled meanwhile, a cancelled `gather`
        # raises a child's `CancelledError` instead of the one cancelling us, and an
        # enclosing anyio scope only swallows its own.
        await asyncio.wait({talking, expiring})
        for task in (talking, expiring):
            # Whatever either task raised is retrieved, so asyncio does not log it.
            if not task.cancelled():
                task.exception()
        if session.connection is not None:
            session.connection.close(1000)
        # Let the hub's close task send its frame before the handler returns.
        for _ in range(3):
            await asyncio.sleep(0)
