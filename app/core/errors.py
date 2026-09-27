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

from typing import ClassVar

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An error this application raises deliberately, with a status and a code.

    Subclasses override the two class attributes and nothing else::

        class StaleSnapshot(AppError):
            status_code = 409
            code = "stale_snapshot"
    """

    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"


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
        content={"error": {"code": exc.code, "message": str(exc)}},
    )
