"""Structured logging — one JSON object per line, carrying a correlation id.

A skeleton, deliberately. Way-of-working §5.3:839 asks for "structured JSON,
one line per event, correlation id propagated from the edge through every
layer"; Phase 0 builds the formatter and the context variable, and Phase 3 adds
the middleware that sets the id at ingress and the request/response fields
worth logging.

Two choices are worth stating because they are easy to undo by accident:

- **stdout, not a file.** The container is the log shipper (ADR 0001:24). A
  process that opens a log file has decided where it runs.
- **The root logger is configured once, at boot.** uvicorn's own loggers
  propagate into it, so its access lines come out in the same shape as the
  application's rather than in uvicorn's default plain text.

Nothing here reads the environment: `configure_logging()` takes the level from
a `Settings` the caller already has (spec AC3).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# The id that ties every line of one request together. `-` is what an event
# outside any request -- boot, shutdown, a background task -- gets. Phase 3
# sets this at ingress from the inbound header or a fresh uuid4.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

# Attributes LogRecord always carries. Anything else a caller attached via
# `extra=` is application data and is merged into the payload below.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a `LogRecord` as one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            # record.created rather than a fresh clock read: the timestamp is
            # when the event happened, not when it was formatted.
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info is not None:
            payload["stack"] = self.formatStack(record.stack_info)

        # `default=str` so an unserialisable extra loses its detail rather than
        # raising inside the logger and taking the event with it.
        return json.dumps(payload, default=str, ensure_ascii=False)


class _DropQueryString(logging.Filter):
    """Log an access line's path without its query.

    A query can hold a player's name (`/api/kassa/wallets?name=`) or the sign-up
    code (`/speler?code=`); a log line would keep the name after its wallet is
    deleted (B-05 SD5, SD15). uvicorn's access line carries the path as its third
    argument.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def configure_logging(level: str) -> None:
    """Send JSON to stdout at `level`. Idempotent: calling it twice is calling it once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    # Replace rather than add: a reload, a second boot in a test, or a
    # framework that configured logging first would otherwise duplicate lines.
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers and does not propagate by default;
    # clearing them sends its lines through the formatter above instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, _DropQueryString) for existing in access.filters):
        access.addFilter(_DropQueryString())
