"""The real app for Playwright (Phase 4 T23: SD28, PD14).

    uv run python -m tests.integration.realapp.serve --out <file>

Playwright's global setup runs this; it is not a pytest module. On the server
`DATABASE_URL` names (the compose `db` locally, the service container in CI;
use `127.0.0.1`, not `localhost`, on Windows), it:

1. drops every `borrelbeurs_e2e_*` a killed run left behind, then creates
   `borrelbeurs_e2e_<pid>` and migrates it, in a child process
   (`tests/integration/conftest.py`'s reasons);
2. seeds v1's live run and mints a display, a bar and an admin key, through
   the CLIs (`harness.py`);
3. starts `python -m app.main` on a free port and waits for `/readyz`, with no
   watchdog: step 5 owns its lifetime, however long the suite runs;
4. writes `{base_url, keys, log}` to `--out` -- under the OS temp dir, never in
   the repository (`tests/meta/test_repo_hygiene.py` bans key literals) -- and
   prints `ready`;
5. waits until its stdin closes, then stops the app, deletes `--out` and drops
   the database.

Closing stdin, not a signal, is the stop: on Windows a signal is
`TerminateProcess`, which would skip step 5 and leave the app running on its
advisory lock. A runner that dies closes the pipe too.

Nothing here is `TestClient` or `curl`: the browser drives the real process.
The login rate limit is raised for this server only, since the suite logs in
far more often than 10 times a minute from one address.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from tests.integration.conftest import _admin, _drop, run_alembic, scratch_url
from tests.integration.realapp.harness import mint_key, seed_live_run, start_app

ROLES = ("display", "bar", "admin")
E2E_PREFIX = "borrelbeurs_e2e_"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    out: Path = parser.parse_args(argv).out

    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        print(
            "serve: DATABASE_URL is not set (scripts/check.sh exports .env.local)", file=sys.stderr
        )
        return 2

    leftovers = asyncio.run(
        _admin(base_url, f"SELECT datname FROM pg_database WHERE datname LIKE '{E2E_PREFIX}%'")
    )
    for leftover in leftovers:
        _drop(base_url, leftover)

    database = f"{E2E_PREFIX}{os.getpid()}"
    url = scratch_url(base_url, database)
    drop = f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'
    asyncio.run(_admin(base_url, drop, f'CREATE DATABASE "{database}"'))
    try:
        migrated = run_alembic(url, "upgrade", "head")
        if migrated.returncode != 0:
            print(f"serve: alembic upgrade head failed:\n{migrated.stderr}", file=sys.stderr)
            return 1
        seed_live_run(url)
        keys = {role: mint_key(url, role) for role in ROLES}

        os.environ["LOGIN_RATE_PER_MINUTE"] = "1000"
        log = Path(tempfile.gettempdir()) / f"{database}.log"
        log.unlink(missing_ok=True)
        app = start_app(url, log, watchdog_s=None)
        try:
            out.write_text(
                json.dumps({"base_url": app.base, "keys": keys, "log": str(log)}),
                encoding="utf-8",
            )
            print("ready", flush=True)
            sys.stdin.read()
        finally:
            app.kill()
            out.unlink(missing_ok=True)
    finally:
        asyncio.run(_admin(base_url, drop))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
