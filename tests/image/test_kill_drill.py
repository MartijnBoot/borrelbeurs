"""The kill drill (Phase 8 T14: AC17, AC18) against a built image.

The image runs as the venue runs it: `--restart on-failure`, its own Postgres beside
it (`conftest.py`). A live run is seeded through the image's own CLIs.

- **AC17, a power cut:** orders stream from a thread, recording each acknowledged
  `order_id`; mid-stream the app **and** Postgres are `docker kill -s KILL`ed. The
  outage outlasts the catch-up budget (30 s), as a power cut does, so the restarted
  app's first row is the gap rule's. Postgres is started, then the app. Every
  acknowledged order is stored, `price_tick` versions are contiguous, the gap row
  carries the last pre-kill tick's prices unchanged (the gap rule moves anchors, not
  prices) and `/api/state` serves the persisted chain, and ticking resumes.
- **AC18, Postgres restarts alone:** the app loses its lock connection and exits 70;
  docker restarts it, and with Postgres back it is ready within 60 s with no command
  issued to it. No acknowledged order is lost.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.db.mapping import cents_from_quantised
from tests.image.conftest import REPO_ROOT, App, Stack, docker
from tests.integration.realapp.harness import Client, order_until_acked

LIVE_CONFIG = REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json"
CATCH_UP_BUDGET_S = 30.0  # app/runtime/gap.py DEFAULT_CATCH_UP_BUDGET_MS
READY_AFTER_DB_S = 60.0  # AC18


def _seed_live_run(stack: Stack) -> None:
    """v1's live config as a draft run, made live, through the image's CLIs."""
    _check(stack.run_cli("alembic", "-c", "db/alembic.ini", "upgrade", "head"))
    imported = _check(
        stack.run_cli(
            "python",
            "-m",
            "app.cli.import_v1",
            "--config",
            "/seed/exchange_config.json",
            mounts=(f"{LIVE_CONFIG}:/seed/exchange_config.json:ro",),
        )
    )
    _check(stack.run_cli("python", "-m", "app.cli.runs", "go-live", imported.strip()))


def _bar_key(stack: Stack) -> str:
    return _check(
        stack.run_cli("python", "-m", "app.cli.keys", "create", "--role", "bar", "--label", "drill")
    ).strip()


def _check(done: Any) -> str:
    assert done.returncode == 0, done.stdout + done.stderr
    out: str = done.stdout
    return out


class _Stream:
    """Orders one after another on a thread until the app stops answering."""

    def __init__(self, base: str, key: str) -> None:
        self.client = Client(base)
        self.client.login(key)
        self.acked: list[dict[str, Any]] = []
        self.thread = threading.Thread(target=self._run)

    def _run(self) -> None:
        for k in range(10_000):
            try:
                receipt = order_until_acked(self.client, f"kill-drill-{k:05d}")
            except Exception:
                return  # the kill: whatever was in flight was never acknowledged
            if receipt is not None:
                self.acked.append(receipt)


def _stored_orders(stack: Stack) -> set[int]:
    out = stack.psql('SELECT order_id FROM "order"')
    return {int(line) for line in out.splitlines() if line}


def _versions(stack: Stack) -> list[int]:
    out = stack.psql("SELECT version FROM price_tick ORDER BY version")
    return [int(line) for line in out.splitlines()]


def _row(stack: Stack, version: int) -> tuple[str, dict[str, Any]]:
    out = stack.psql(
        f"SELECT source || '|' || prices::text FROM price_tick WHERE version = {version}"
    )
    source, prices = out.split("|", 1)
    parsed: dict[str, Any] = json.loads(prices)
    return source, parsed


def _wait_db(stack: Stack, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while docker(
        "exec",
        stack.db,
        "psql",
        "-U",
        "borrelbeurs",
        "-d",
        "borrelbeurs",
        "-tAc",
        "SELECT 1",
        check=False,
    ).returncode:
        assert time.monotonic() < deadline, "the drill Postgres never came back"
        time.sleep(0.5)


def test_a_power_cut_loses_no_acknowledged_order_and_keeps_the_prices(stack: Stack) -> None:
    """AC17."""
    _seed_live_run(stack)
    key = _bar_key(stack)
    app = stack.start_app(restart="on-failure")
    app.wait_ready()
    stream = _Stream(app.base, key)
    stream.thread.start()
    time.sleep(3.0)

    docker("kill", "--signal", "KILL", app.container, stack.db)
    killed = time.monotonic()
    stream.thread.join(timeout=60)
    assert not stream.thread.is_alive()
    assert stream.acked, "no order was acknowledged before the kill; the drill proves nothing"

    # A power cut longer than the catch-up budget, so the restart is the gap rule's.
    time.sleep(max(0.0, CATCH_UP_BUDGET_S + 2 - (time.monotonic() - killed)))
    docker("start", stack.db)
    _wait_db(stack)
    last_before = max(_versions(stack))
    _, prices_before = _row(stack, last_before)
    docker("start", app.container, check=False)  # unless docker already restarted it
    app.wait_ready()

    client = Client(app.base)
    client.login(key)
    state = client.state()
    _wait_for_tick_after(stack, last_before + 1)

    stored = _stored_orders(stack)
    missing = [r["order_id"] for r in stream.acked if r["order_id"] not in stored]
    assert not missing, f"acknowledged but not stored: {missing}"
    versions = _versions(stack)
    assert versions == list(range(len(versions))), "a version is missing or duplicated"
    # The restarted app's first row is the gap rule's, at the pre-kill prices.
    assert _row(stack, last_before + 1) == ("gap", prices_before)
    # What /api/state serves is the persisted chain from there.
    assert state["version"] > last_before
    _, at_state = _row(stack, state["version"])
    assert {int(d): p["price_cents"] for d, p in state["prices"].items()} == {
        int(d): cents_from_quantised(p["p_q"]) for d, p in at_state.items()
    }


def _wait_for_tick_after(stack: Stack, version: int, seconds: float = 15) -> None:
    """Ticking resumed: a `tick` row newer than `version`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        newest = stack.psql(
            f"SELECT max(version) FROM price_tick WHERE source = 'tick' AND version > {version}"
        )
        if newest:
            return
        time.sleep(0.5)
    raise AssertionError(f"no tick after version {version} within {seconds} s")


def _exit_codes(app: App, since: float) -> list[int]:
    """Every exit of the app container since `since` (unix time), oldest first."""
    out = docker(
        "events",
        "--since",
        f"{since:.0f}",
        "--until",
        f"{time.time():.0f}",
        "--filter",
        f"container={app.container}",
        "--filter",
        "event=die",
        "--format",
        '{{index .Actor.Attributes "exitCode"}}',
    )
    return [int(line) for line in out.stdout.split()]


def _ready(app: App) -> bool:
    return app.get("/readyz")[0] == 200


def test_a_postgres_restart_is_recovered_by_the_restart_policy_alone(stack: Stack) -> None:
    """AC18."""
    _seed_live_run(stack)
    key = _bar_key(stack)
    app = stack.start_app(restart="on-failure")
    app.wait_ready()
    client = Client(app.base)
    client.login(key)
    acked = [order_until_acked(client, f"restart-drill-{k}") for k in range(3)]
    assert all(r is not None for r in acked)

    since = time.time() - 2
    docker("kill", "--signal", "KILL", stack.db)
    deadline = time.monotonic() + 30
    while not (codes := _exit_codes(app, since)):
        assert time.monotonic() < deadline, f"the app never exited:\n{app.logs()}"
        time.sleep(0.5)
    assert codes[0] == 70, (codes, app.logs())

    docker("start", stack.db)
    started = time.monotonic()
    while not _ready(app):
        assert time.monotonic() - started < READY_AFTER_DB_S, (
            f"not ready {READY_AFTER_DB_S:.0f} s after Postgres came back:\n{app.logs()}"
        )
        time.sleep(0.5)
    print(f"ready {time.monotonic() - started:.1f} s after Postgres came back")

    restarts = docker("inspect", "--format", "{{.RestartCount}}", app.container).stdout.strip()
    assert int(restarts) >= 1, restarts
    stored = _stored_orders(stack)
    assert {r["order_id"] for r in acked if r is not None} <= stored
