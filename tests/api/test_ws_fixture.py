"""The recorded WS fixture matches the server (Phase 4 T12: SD26, PD19)."""

from __future__ import annotations

from app.core.config import Settings
from tests.api.ws_fixture import check


def test_the_recorded_ws_fixture_matches_the_server(settings: Settings) -> None:
    """Re-records every server message from the real app.

    A failure is a server model change: re-record with `python -m tests.api.ws_fixture --write`
    and update the web's Zod schemas to match.
    """
    diff = check(settings)
    assert diff is None, f"ws-messages.json is stale:\n{diff}"
