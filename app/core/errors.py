"""Typed errors and the one handler that turns them into responses (§5.3:837).

A skeleton. The rule it establishes is the one worth establishing early:
**an error the application raises on purpose carries its own status and its own
stable code**, so the edge never has to guess and a client never has to parse
prose. Phase 3 adds the concrete subclasses (a stale snapshot, a rejected
order) and the error contract the web client codegens against.

The envelope is `{"error": {"code": ..., "message": ...}}`. No document
specifies a shape for Phase 0; this one is chosen because it leaves room for
fields Phase 3 will want (a correlation id, per-field detail) without changing
what is already there. FastAPI's own `HTTPException` keeps its `{"detail": ...}`
shape and is untouched.

`message` is written for a human reading a log or a toast. It must never carry a
secret or a credential -- the same rule `app/core/config.py` follows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import JsonValue


class AppError(Exception):
    """An error this application raises deliberately, with a status and a code.

    Subclasses override the two class attributes and nothing else::

        class StaleSnapshot(AppError):
            status_code = 409
            code = "stale_snapshot"
    """

    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"

    def __init__(
        self,
        message: str = "",
        *,
        extra: Mapping[str, JsonValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """`extra` adds fields inside the `error` object beside `code` and `message`
        (Phase 3 PD8: `price_changed` carries `version` and `prices`); `headers` are
        set on the response (`Retry-After` on 429)."""
        super().__init__(message)
        self.extra: Mapping[str, JsonValue] = extra or {}
        self.headers: Mapping[str, str] = headers or {}


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """Render an `AppError` as JSON. Anything else is re-raised, never swallowed.

    The signature takes `Exception` because that is what Starlette's handler
    protocol passes; the narrowing below is the type guard, and the `raise` is
    what keeps a mis-registration loud instead of turning every unrelated bug
    into a 500 with a misleading code.
    """
    if not isinstance(exc, AppError):
        raise exc

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {**exc.extra, "code": exc.code, "message": str(exc)}},
        headers=dict(exc.headers),
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's request-validation 422, in the same envelope, code `invalid_request` (PD9).

    Each fault is its location and message only. pydantic's `input` is dropped:
    a login body's rejected value is an access key, and this lands in a log.
    """
    if not isinstance(exc, RequestValidationError):
        raise exc

    faults: list[JsonValue] = [
        {"loc": [str(part) for part in error["loc"]], "msg": str(error["msg"])}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "the request is not valid",
                "faults": faults,
            }
        },
    )
