"""The real app as a process, driven over stdlib `urllib` (Phase 3 T29: SD34).

`start_app` runs the production entrypoint, `python -m app.main`, against the
scratch database on a free port and waits for `/readyz`. `Client` logs in with
a key minted by `app.cli.keys` and places orders with a session cookie and a
same-origin `Origin`, as a browser would. Seeding uses the CLIs too
(`app.cli.import_v1`, then `app.cli.runs go-live`). Nothing here uses
`TestClient` or `curl`: it must be the real process over real HTTP (T29).

The spawn/kill shape is `tests/integration/test_durability.py`'s: `Popen`, a
watchdog timer, `kill()` then `wait()`. On Windows `kill()` is
`TerminateProcess`, as close to SIGKILL as the platform has (Phase 2 R6).
`SESSION_COOKIE_SECURE=false` with `APP_ENV=ci`: the cookie travels over plain
http to localhost, which is allowed outside production (SD8).

**Ports (B-11 SD14).** `claim_free_port` hands out a port no other run of this
harness holds (`pg_gate.claim_port`, released when the app is killed or waited
for) and that nothing already listens on (a connect probe: on Windows the app's
`0.0.0.0` bind succeeds beside a `127.0.0.1` squatter, so a bind error cannot be
relied on). A process that takes the number between that check and the bind makes
the child log the bind error and exit 3, and `start_app` retries on another port.
It does not poll `/readyz` until the child's own "Uvicorn running on ..." line for
its port appears, so a foreign process on the port is never sent a request.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.support import pg_gate

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_CONFIG = REPO_ROOT / "tests" / "fixtures" / "v1" / "config" / "exchange_config.json"
READY_TIMEOUT_S = 60.0
WATCHDOG_S = 300.0


BIND_FAILED_EXIT = 3  # uvicorn's exit code for any startup failure, a lost port included
PORT_RETRIES = 5


def free_port() -> int:
    """A port free on `0.0.0.0`, the address the app binds, and on `127.0.0.1`, the one we use."""
    while True:
        with socket.socket() as wide, socket.socket() as narrow:
            wide.bind(("0.0.0.0", 0))
            port = int(wide.getsockname()[1])
            try:
                narrow.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port


def _something_listens(port: int) -> bool:
    """Whether a connection to `127.0.0.1:port` is accepted. A connect sends nothing."""
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def claim_free_port() -> int:
    """`free_port`, claimed against other runs of this harness and checked for squatters.

    Two guards, because neither alone is unambiguous. The claim lock keeps two runs
    of this harness apart; it needs the maintenance connection every scratch
    database's owner has, and a caller with none gets only the probe. The connect
    probe catches a process outside the harness that already holds the port on
    `127.0.0.1`: on Windows the app's `0.0.0.0` bind succeeds beside it, so no
    bind error would ever say so, and `/readyz` would reach the squatter.
    """
    for _ in range(50):
        port = free_port()
        if pg_gate.has_connection() and not pg_gate.claim_port(port):
            continue
        if _something_listens(port):
            if pg_gate.has_connection():
                pg_gate.release_port(port)
            continue
        return port
    raise RuntimeError("no unclaimed, unoccupied port after 50 probes")


def app_env(database_url: str, port: int) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": database_url,
        "PORT": str(port),
        "APP_ENV": "ci",
        "SESSION_COOKIE_SECURE": "false",
        "LOG_LEVEL": "INFO",
    }


def cli(database_url: str, module: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one of the app's CLIs as its own process."""
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def seed_live_run(database_url: str) -> int:
    """Import v1's live config as a draft run and make it live, through the CLIs."""
    imported = cli(database_url, "app.cli.import_v1", "--config", str(LIVE_CONFIG))
    assert imported.returncode == 0, imported.stderr
    run_id = int(imported.stdout.strip())
    live = cli(database_url, "app.cli.runs", "go-live", str(run_id))
    assert live.returncode == 0, live.stderr
    return run_id


def mint_key(database_url: str, role: str) -> str:
    created = cli(
        database_url, "app.cli.keys", "create", "--role", role, "--label", f"realapp {role}"
    )
    assert created.returncode == 0, created.stderr
    return created.stdout.strip()


@dataclass
class AppProcess:
    proc: subprocess.Popen[bytes]
    port: int
    stderr_path: Path
    _watchdog: threading.Timer | None = field(repr=False)
    log_offset: int = 0  # where this child's output starts in the shared, append-mode log
    claimed: bool = False  # whether `kill`/`wait` release the port claim

    def own_log(self) -> str:
        """The log from this child's start, not an earlier run's."""
        data = self.stderr_path.read_bytes()[self.log_offset :]
        return data.decode("utf-8", errors="replace")

    def listening(self) -> bool:
        """Whether the child has said it serves on its own port."""
        return f"Uvicorn running on http://0.0.0.0:{self.port}" in self.own_log()

    def lost_port(self) -> bool:
        """Whether the child exited because something else took its port first."""
        return (
            self.proc.poll() == BIND_FAILED_EXIT
            and f"error while attempting to bind on address ('0.0.0.0', {self.port})"
            in self.own_log()
        )

    def _release_port(self) -> None:
        if self.claimed:
            self.claimed = False
            pg_gate.release_port(self.port)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stderr(self) -> str:
        return self.stderr_path.read_text(encoding="utf-8", errors="replace")

    def kill(self) -> int:
        self.proc.kill()
        code = self.proc.wait(timeout=30)
        if self._watchdog is not None:
            self._watchdog.cancel()
        self._release_port()
        return code

    def wait(self, timeout: float) -> int:
        code = self.proc.wait(timeout=timeout)
        if self._watchdog is not None:
            self._watchdog.cancel()
        self._release_port()
        return code


def spawn_app(
    database_url: str,
    stderr_path: Path,
    *,
    port: int | None = None,
    watchdog_s: float | None = WATCHDOG_S,
) -> AppProcess:
    """Start `python -m app.main`; do not wait for it.

    The watchdog kills a test's app that outlives it; `None` arms none, for a
    caller that owns the app's lifetime itself (`serve.py`). A `port` the caller
    passes is the caller's to have claimed; one chosen here is claimed and released
    with the process.
    """
    claimed = port is None
    port = port or claim_free_port()
    claimed = claimed and pg_gate.has_connection()
    offset = stderr_path.stat().st_size if stderr_path.exists() else 0
    stderr = stderr_path.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=REPO_ROOT,
        env=app_env(database_url, port),
        # Never `serve.py`'s stdin: it blocks reading it, and on Windows the export's
        # build process (Phase 7 T11) would stall at startup on that same pipe.
        stdin=subprocess.DEVNULL,
        # The app's JSON log goes to stdout; keep it with stderr for the assertions.
        stdout=stderr,
        stderr=stderr,
    )
    stderr.close()
    watchdog = None
    if watchdog_s is not None:
        watchdog = threading.Timer(watchdog_s, proc.kill)
        watchdog.start()
    return AppProcess(
        proc=proc,
        port=port,
        stderr_path=stderr_path,
        _watchdog=watchdog,
        log_offset=offset,
        claimed=claimed,
    )


def start_app(
    database_url: str, stderr_path: Path, *, watchdog_s: float | None = WATCHDOG_S
) -> AppProcess:
    """Start the app and wait until `/readyz` answers 200.

    A port lost to a process outside this harness is retried on a new one; and
    `/readyz` is first asked only after this child has logged that it listens on
    its own port, so nothing else on that port is ever sent a request.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    for _ in range(PORT_RETRIES):
        app = spawn_app(database_url, stderr_path, watchdog_s=watchdog_s)
        while not app.listening() and time.monotonic() < deadline:
            if app.proc.poll() is not None:
                break
            time.sleep(0.05)
        if app.proc.poll() is not None:
            app.wait(timeout=5)
            if app.lost_port():
                continue
        break
    while time.monotonic() < deadline:
        if app.proc.poll() is not None:
            raise AssertionError(f"the app exited {app.proc.returncode}:\n{app.stderr()}")
        if not app.listening():
            time.sleep(0.05)
            continue
        try:
            with urllib.request.urlopen(f"{app.base}/readyz", timeout=2) as response:
                if response.status == 200:
                    return app
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.1)
    app.kill()
    raise AssertionError(f"the app never became ready:\n{app.stderr()}")


class Client:
    """A browser stand-in: a cookie jar, a same-origin `Origin`, JSON in and out."""

    def __init__(self, base: str) -> None:
        self.base = base
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={"Origin": self.base, "Content-Type": "application/json", **(headers or {})},
        )
        try:
            with self._opener.open(request, timeout=10) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def login(self, key: str) -> None:
        status, body = self.request("POST", "/api/auth/login", {"key": key})
        assert status == 200, body

    def state(self) -> dict[str, Any]:
        status, body = self.request("GET", "/api/state")
        assert status == 200, body
        result: dict[str, Any] = body
        return result

    def order(self, key: str, quote_version: int, lines: list[dict[str, int]]) -> tuple[int, Any]:
        return self.request(
            "POST",
            "/api/orders",
            {"quote_version": quote_version, "lines": lines},
            headers={"Idempotency-Key": key},
        )


def order_until_acked(client: Client, key: str) -> dict[str, Any] | None:
    """One order of drink one at its live price; on a 409, once more with the returned prices.

    `/api/state` carries no version, so the quote is version 0 at the live price:
    charged under SD18's equal-price rule whatever its age, or 409 with the
    current version and prices to retry with.
    """
    state = client.state()
    drink = int(next(iter(state["prices"])))
    price = state["prices"][str(drink)]["price_cents"]
    quote = 0
    for _ in range(3):
        status, body = client.order(
            key, quote, [{"drink_id": drink, "qty": 1, "unit_price_cents": price}]
        )
        if status in (200, 201):
            receipt: dict[str, Any] = body
            return receipt
        if status != 409:
            raise AssertionError((status, body))
        quote = body["error"]["version"]
        price = next(p["price_cents"] for p in body["error"]["prices"] if p["drink_id"] == drink)
    return None


def stop_gracefully(app: AppProcess, admin_key: str, timeout: float = 30.0) -> int:
    """`POST /api/admin/shutdown` (Phase 3 PD17): uvicorn's own graceful path -- the
    lifespan's exit releases the lock -- on every OS, Windows included, where there is
    no SIGTERM to send. Returns the exit code."""
    admin = Client(app.base)
    admin.login(admin_key)
    status, body = admin.request("POST", "/api/admin/shutdown")
    assert status == 202, body
    return app.wait(timeout=timeout)
