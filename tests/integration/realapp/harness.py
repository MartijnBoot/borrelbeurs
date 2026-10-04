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

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_CONFIG = REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json"
READY_TIMEOUT_S = 60.0
WATCHDOG_S = 300.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


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
    _watchdog: threading.Timer = field(repr=False)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stderr(self) -> str:
        return self.stderr_path.read_text(encoding="utf-8", errors="replace")

    def kill(self) -> int:
        self.proc.kill()
        code = self.proc.wait(timeout=30)
        self._watchdog.cancel()
        return code

    def wait(self, timeout: float) -> int:
        code = self.proc.wait(timeout=timeout)
        self._watchdog.cancel()
        return code


def spawn_app(database_url: str, stderr_path: Path, *, port: int | None = None) -> AppProcess:
    """Start `python -m app.main`; do not wait for it."""
    port = port or free_port()
    stderr = stderr_path.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=REPO_ROOT,
        env=app_env(database_url, port),
        # The app's JSON log goes to stdout; keep it with stderr for the assertions.
        stdout=stderr,
        stderr=stderr,
    )
    stderr.close()
    watchdog = threading.Timer(WATCHDOG_S, proc.kill)
    watchdog.start()
    return AppProcess(proc=proc, port=port, stderr_path=stderr_path, _watchdog=watchdog)


def start_app(database_url: str, stderr_path: Path) -> AppProcess:
    """Start the app and wait until `/readyz` answers 200."""
    app = spawn_app(database_url, stderr_path)
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if app.proc.poll() is not None:
            raise AssertionError(f"the app exited {app.proc.returncode}:\n{app.stderr()}")
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
