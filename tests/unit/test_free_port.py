"""`tests/integration/realapp/harness.py`'s `free_port` under Linux's bind rules.

Linux refuses a `127.0.0.1:p` bind while a socket of the same process still holds
`0.0.0.0:p` (EADDRINUSE); Windows allows it. `free_port` once held both at once,
so on Linux every probe failed and it looped forever, without a word: in CI the
e2e launcher never printed `ready` and Playwright gave up after 120 s. This fake
socket applies Linux's rule on any OS, and gives up after a bounded number of binds
so a regression fails here rather than hanging.
"""

from __future__ import annotations

import errno
import socket
from types import TracebackType

import pytest

from tests.integration.realapp import harness

WILDCARD = "0.0.0.0"
MAX_BINDS = 100


class LinuxSockets:
    """A stand-in for `socket.socket` with Linux's wildcard/specific bind conflict."""

    def __init__(self) -> None:
        self.bound: set[tuple[str, int]] = set()
        self.binds = 0
        self.next_port = 40000

    def __call__(self) -> FakeSocket:
        return FakeSocket(self)


class FakeSocket:
    def __init__(self, sockets: LinuxSockets) -> None:
        self.sockets = sockets
        self.address: tuple[str, int] | None = None

    def bind(self, address: tuple[str, int]) -> None:
        self.sockets.binds += 1
        if self.sockets.binds > MAX_BINDS:
            raise AssertionError(f"free_port made more than {MAX_BINDS} binds")
        host, port = address
        if port == 0:  # the OS picks a port nothing is bound to
            while any(p == self.sockets.next_port for _, p in self.sockets.bound):
                self.sockets.next_port += 1
            port = self.sockets.next_port
            self.sockets.next_port += 1
        holders = {h for h, p in self.sockets.bound if p == port}
        if host in holders or (holders and (host == WILDCARD or WILDCARD in holders)):
            raise OSError(errno.EADDRINUSE, "Address already in use")
        self.address = (host, port)
        self.sockets.bound.add(self.address)

    def getsockname(self) -> tuple[str, int]:
        assert self.address is not None
        return self.address

    def close(self) -> None:
        if self.address is not None:
            self.sockets.bound.discard(self.address)
            self.address = None

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def test_free_port_returns_a_port_under_linux_bind_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    sockets = LinuxSockets()
    monkeypatch.setattr(socket, "socket", sockets)

    port = harness.free_port()

    assert port >= 40000
    assert sockets.bound == set()  # every probe socket closed again
