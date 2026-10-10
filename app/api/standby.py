"""The standby gate (Phase 8 SD4, SD5; plan PD1).

An instance that boots while another holds the advisory lock serves in standby: it
binds, `/healthz` says `standby`, and it takes over once the lock frees. Until then
it has no holder, hub or theme, so nothing that needs them may run:

- every `http` request under `/api` is 503 with the one error envelope, code
  `standby` -- ahead of authentication and the origin check, so every client is
  told the same thing;
- `/ws` is accepted and closed at once with 1013, "try again later", before
  `require_ws_role`: a phone reconnects, rather than being told its session is bad.

A pure ASGI middleware, because it must also see the WebSocket handshake. Outside
standby it passes everything through untouched.
"""

from __future__ import annotations

from typing import Final

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import AppError, handle_app_error

CLOSE_TRY_AGAIN_LATER: Final = 1013


class Standby(AppError):
    """Another instance holds the lock; this one takes over when it frees (SD4)."""

    status_code = 503
    code = "standby"


class StandbyGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and getattr(scope["app"].state, "standby", False):
            if scope["type"] == "websocket" and scope["path"] == "/ws":
                await receive()  # websocket.connect
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": CLOSE_TRY_AGAIN_LATER})
                return
            if scope["type"] == "http" and (
                scope["path"] == "/api" or scope["path"].startswith("/api/")
            ):
                response = await handle_app_error(
                    Request(scope), Standby("this instance is waiting to take over")
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
