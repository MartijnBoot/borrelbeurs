"""Smoke-test a running BorrelBeurs: is the build the one asked for, and does it work?

    BB_SMOKE_KEY=bb_... python scripts/smoke.py https://borrelbeurs.example --expect-sha <sha>

Phase 8 SD12. Seven steps, one line each, exit 0 when all pass and 1 at the first
that fails:

1. `/healthz` is 200 -- and, with `--expect-sha`, reports that `build_sha`. Polled
   until `--wait-seconds` runs out, so it can follow a deploy that is still rolling;
2. `/readyz` is 200 (polled within the same budget);
3. log in with the admin key, sending the same-origin `Origin` a browser would;
4. `/api/auth/me` is the admin role;
5. `GET /api/runs/current` is 200, or 404 `no_current_run`;
6. the current theme is saved again, unchanged (PD13): its preset is read from
   `/theme.css`'s `ETag` (`"theme-<revision>-<preset>"`) and `PUT` back -- a write
   through the whole stack that changes nothing on any screen;
7. log out.

The key comes from `BB_SMOKE_KEY`, or the first line of stdin when that is unset. It
is never printed. Standard library only, so it runs anywhere Python does: a GitHub
runner, the venue laptop, a developer's shell.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

ETAG = re.compile(r'^"theme-(\d+)-([a-z]+)"$')
TIMEOUT_S = 10


class SmokeFailed(Exception):
    """A step failed; the message says which and why, never with the key in it."""


class Session:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        parts = urlsplit(self.base)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(
        self, method: str, path: str, body: Any = None
    ) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Origin": self.origin, "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=TIMEOUT_S) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def json(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        status, _, raw = self.request(method, path, body)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None


def _poll(session: Session, path: str, deadline: float, accept: Any) -> Any:
    """GET `path` until `accept(status, body)` is truthy or `deadline` passes."""
    last = "no answer"
    while True:
        try:
            status, body = session.json("GET", path)
            if accept(status, body):
                return body
            last = f"{status} {body}"
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            last = type(error).__name__
        if time.monotonic() >= deadline:
            raise SmokeFailed(f"{path}: {last}")
        time.sleep(1)


def run(base: str, key: str, *, expect_sha: str | None, wait_seconds: float) -> None:
    session = Session(base)
    deadline = time.monotonic() + wait_seconds

    def healthy(status: int, body: Any) -> bool:
        return status == 200 and (expect_sha is None or body.get("build_sha") == expect_sha)

    health = _poll(session, "/healthz", deadline, healthy)
    print(f"ok   healthz      status={health['status']} build_sha={health.get('build_sha')}")

    _poll(session, "/readyz", deadline, lambda status, _: status == 200)
    print("ok   readyz")

    status, body = session.json("POST", "/api/auth/login", {"key": key})
    if status != 200:
        raise SmokeFailed(f"login: {status} {_code(body)}")
    print("ok   login")

    status, body = session.json("GET", "/api/auth/me")
    if status != 200 or body.get("role") != "admin":
        raise SmokeFailed(f"me: {status}, role {body.get('role') if body else None}, not admin")
    print(f"ok   me           role=admin label={body.get('label')}")

    status, body = session.json("GET", "/api/runs/current")
    if status == 200:
        print(f"ok   runs/current run_id={body.get('run_id')} status={body.get('status')}")
    elif status == 404 and _code(body) == "no_current_run":
        print("ok   runs/current none")
    else:
        raise SmokeFailed(f"runs/current: {status} {_code(body)}")

    status, headers, _ = session.request("GET", "/theme.css")
    match = ETAG.match(headers.get("ETag", headers.get("etag", "")))
    if status != 200 or match is None:
        raise SmokeFailed(f"theme.css: {status}, ETag {headers.get('ETag')!r}")
    revision, preset = int(match.group(1)), match.group(2)
    status, body = session.json("PUT", "/api/theme", {"preset": preset})
    if status != 200 or body.get("preset") != preset or body.get("revision") != revision + 1:
        raise SmokeFailed(f"theme: {status} {_code(body)}")
    print(f"ok   theme        preset={preset} revision={revision}->{revision + 1}")

    status, _, _ = session.request("POST", "/api/auth/logout")
    if status != 204:
        raise SmokeFailed(f"logout: {status}")
    print("ok   logout")


def _code(body: Any) -> str | None:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("code"))
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("base_url", help="e.g. https://borrelbeurs.onrender.com")
    parser.add_argument("--expect-sha", help="the build_sha /healthz must report")
    parser.add_argument(
        "--wait-seconds", type=float, default=0, help="how long to wait for health and the SHA"
    )
    args = parser.parse_args(argv)
    key = os.environ.get("BB_SMOKE_KEY") or sys.stdin.readline().strip()
    if not key:
        print("FAIL no key: set BB_SMOKE_KEY or pass it on stdin", file=sys.stderr)
        return 1
    try:
        run(args.base_url, key, expect_sha=args.expect_sha, wait_seconds=args.wait_seconds)
    except SmokeFailed as failure:
        print(f"FAIL {str(failure).replace(key, '<key>')}")
        return 1
    print("smoke: all steps passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
