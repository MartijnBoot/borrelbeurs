"""A TCP proxy in front of Postgres that can go silent: the network partition a refused
connection does not reproduce.

`blackhole()` keeps every socket open and stops moving bytes in both directions, so
a client sees neither an answer nor an error -- only its own timeout ends the wait.
`close()` drops every connection, which a client sees at once.
"""

from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy.engine import make_url


class BlackholeProxy:
    def __init__(self, upstream_host: str, upstream_port: int) -> None:
        self._upstream = (upstream_host, upstream_port)
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._pumps: set[asyncio.Task[None]] = set()
        self.silent = False

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> BlackholeProxy:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self

    def blackhole(self) -> None:
        self.silent = True

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
        for writer in self._writers:
            writer.transport.abort()
        for pump in tuple(self._pumps):
            pump.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*self._pumps, return_exceptions=True)

    async def _serve(self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        if self.silent:
            self._writers.append(client_w)  # accept, then say nothing
            return
        upstream_r, upstream_w = await asyncio.open_connection(*self._upstream)
        self._writers += [client_w, upstream_w]
        for source, sink in ((client_r, upstream_w), (upstream_r, client_w)):
            pump = asyncio.get_running_loop().create_task(self._pump(source, sink))
            self._pumps.add(pump)
            pump.add_done_callback(self._pumps.discard)

    async def _pump(self, source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
        with contextlib.suppress(ConnectionError, OSError):
            while data := await source.read(65_536):
                if self.silent:
                    continue  # swallowed: no answer, no error
                sink.write(data)
                await sink.drain()


async def proxied(database_url: str) -> tuple[BlackholeProxy, str]:
    """A started proxy in front of `database_url`'s server, and the URL through it."""
    upstream = make_url(database_url)
    host = upstream.host or "localhost"
    # Not "localhost": on Windows that tries ::1 first, slower than a short timeout.
    if host == "localhost":
        host = "127.0.0.1"
    proxy = await BlackholeProxy(host, upstream.port or 5432).start()
    url = upstream.set(host="127.0.0.1", port=proxy.port)
    return proxy, url.render_as_string(hide_password=False)
