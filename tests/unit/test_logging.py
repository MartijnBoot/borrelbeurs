"""T5 — the logging skeleton: one JSON line per event, carrying a correlation id.

Phase 3 propagates the id from the edge through every layer (way-of-working
§5.3:839). What is asserted here is only what Phase 0 promises: the formatter
emits parseable JSON, the id is in it, and configuring twice does not stack
handlers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from app.core.logging import JsonFormatter, configure_logging, correlation_id


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """`configure_logging()` owns the root logger; give pytest its own back."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _format(record: logging.LogRecord) -> dict[str, Any]:
    formatted = JsonFormatter().format(record)
    assert "\n" not in formatted, "one event is one line, or log aggregation splits it"
    parsed: dict[str, Any] = json.loads(formatted)
    return parsed


def _record(message: str = "hello %s", *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )


def test_a_record_becomes_one_json_object() -> None:
    payload = _format(_record("hello %s", "world"))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "hello world"
    assert payload["timestamp"].startswith("20")


def test_the_correlation_id_is_present_and_follows_the_context() -> None:
    assert _format(_record("no context"))["correlation_id"] == "-"

    token = correlation_id.set("abc-123")
    try:
        assert _format(_record("in context"))["correlation_id"] == "abc-123"
    finally:
        correlation_id.reset(token)


def test_an_exception_is_carried_on_the_same_line() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record("failed")
        record.exc_info = __import__("sys").exc_info()

    payload = _format(record)

    assert "ValueError: boom" in payload["exception"]


def test_configuring_twice_leaves_one_handler() -> None:
    """Re-entrant boots (a reload, a test) must not double every log line."""
    configure_logging("DEBUG")
    configure_logging("WARNING")

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert root.level == logging.WARNING
