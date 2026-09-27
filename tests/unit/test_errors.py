"""T5 — the error skeleton: one typed base, one global handler (§5.3:837).

Phase 3 adds the error types that carry real meaning. Phase 0 proves the seam
exists and that an `AppError` reaching the edge becomes a JSON response with
the status the type declares, rather than a stack trace.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.core.errors import AppError, handle_app_error


class Unavailable(AppError):
    status_code = 503
    code = "unavailable"


def _handle(error: Exception) -> tuple[int, Any]:
    response = asyncio.run(handle_app_error(None, error))  # type: ignore[arg-type]
    return response.status_code, json.loads(bytes(response.body))


def test_the_base_error_carries_a_status_and_a_code() -> None:
    error = AppError("something went wrong")

    assert error.status_code == 500
    assert error.code == "internal_error"
    assert str(error) == "something went wrong"


def test_a_subclass_sets_the_status_the_handler_uses() -> None:
    status, payload = _handle(Unavailable("not booted yet"))

    assert status == 503
    assert payload == {"error": {"code": "unavailable", "message": "not booted yet"}}


def test_an_unrelated_exception_is_not_swallowed() -> None:
    """Never swallow (§5.3:837): the handler owns AppError and nothing else."""
    with pytest.raises(ValueError):
        _handle(ValueError("not mine"))
