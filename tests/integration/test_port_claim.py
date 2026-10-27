"""B-11 AC17 — a real app whose port was taken between probe and bind retries elsewhere.

`free_port` is made to hand out, once, a port a squatter already holds, as if the
squatter had bound it just after the probe. The squatter binds `127.0.0.1`, the
address the harness connects to, and records every byte sent to it. The harness's
connect probe finds it listening and moves on (on Windows the app's `0.0.0.0` bind
would succeed beside it): the app must come up on another port, the test must be
green, and the squatter must have been sent no request. The probe itself is a bare
connect, which is not one.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.realapp import harness

# Starts a real app (SD3).
pytestmark = pytest.mark.serial


class Squatter:
    """A listener that is not the harness, noting anyone who connects to it."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.sock.settimeout(0.2)
        self.port = int(self.sock.getsockname()[1])
        self.received = 0  # bytes sent to us; a bare connect sends none
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(0.5)
            with contextlib.suppress(TimeoutError, OSError):
                self.received += len(conn.recv(4096))
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.sock.close()


@pytest.fixture
def squatter() -> Iterator[Squatter]:
    held = Squatter()
    yield held
    held.close()


def test_a_lost_port_is_retried_and_the_squatter_is_never_asked(
    database_url: str, squatter: Squatter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = harness.free_port
    offered: list[int] = []

    def free_port() -> int:
        port = squatter.port if not offered else real()
        offered.append(port)
        return port

    monkeypatch.setattr(harness, "free_port", free_port)
    app = harness.start_app(database_url, tmp_path / "app.log")
    try:
        assert offered[0] == squatter.port and len(offered) >= 2
        assert app.port != squatter.port
        assert app.listening()
    finally:
        app.kill()
    assert squatter.received == 0
