"""Record one frame of every server message from the real app, for the web's schemas (PD19).

    uv run python -m tests.api.ws_fixture --write   # (re)write the fixture
    uv run python -m tests.api.ws_fixture --check   # re-record, diff, exit 1 on change

The fixture, `web/src/features/exchange/model/__fixtures__/ws-messages.json`, is
what the web's Zod schemas are tested against (Phase 4 SD26). `--check` runs in
the gate through `tests/api/test_ws_fixture.py`, so a server model changed
without re-recording is red here, and a Zod schema that stops matching the
recorded shapes is red in Vitest: either side drifting fails.

**Deterministic by construction.** The app runs on a `FakeClock`, so every
`ts_ms` is scenario time, and on a scratch database created for this recording
alone, so every id a sequence hands out is the same on every run, whatever else
the session's tests did first. Only `hello.data.boot_id` is random (the hub
draws it); it is replaced by `BOOT_ID`. Each step reads its frame before the
next one starts, so no two broadcasts race for a `seq`.

**`resync`** is sent only when a connection's queue overflows, which a scripted
session cannot provoke without racing its own writer. It is recorded from
`hub.resync_frame()` -- the frame the overflow path enqueues, built by the same
code -- at the end of the session.

**`config`** has no route to provoke it until Phase 6's config writes exist. It
is recorded by handing a `ConfigChanged` -- the run as booted, with `Fris`
marked removed -- to a `Publisher` on the app's own hub, on the app's loop:
the frame the holder's sink would broadcast, built by the same code.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.security import format_key, hash_secret, mint_secret
from app.core.config import Settings, get_settings
from app.db.keys import create_key, set_secret_hash
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.main import create_app
from app.realtime.publish import Publisher, active_drink_ids, seeded_book
from app.runtime.holder import ConfigChanged
from exchange import Params
from tests.integration.conftest import _create, _drop, run_alembic
from tests.support.clock import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "web/src/features/exchange/model/__fixtures__/ws-messages.json"
BASE_URL = "https://testserver"
T0 = 1_759_312_800_000
BOOT_ID = "BOOT"
# Long enough that the resync snapshot still carries the event, then it ends.
EVENT_MS = 3_000
MAX_FRAMES = 20

Frame = dict[str, Any]


@contextmanager
def _database_env(url: str) -> Iterator[None]:
    """Point the app's settings at `url` for the recording, then restore them."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@contextmanager
def _scratch_database(settings: Settings) -> Iterator[str]:
    """A freshly migrated database of its own, dropped afterwards."""
    database, url = _create(settings.database_url)
    try:
        migrated = run_alembic(url, "upgrade", "head")
        if migrated.returncode != 0:
            raise RuntimeError(f"alembic upgrade head failed:\n{migrated.stderr}")
        yield url
    finally:
        _drop(settings.database_url, database)


def _seed(settings: Settings, url: str) -> str:
    """The `tests/api/conftest.py` live run of three drinks, plus an admin key; the raw key."""

    async def scenario() -> str:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(
                    conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
                )
                for slot, name in enumerate(("Bier", "Wijn", "Fris")):
                    await add_drink(
                        conn,
                        run_id,
                        name=name,
                        slot=slot,
                        p_min_cents=150,
                        p0_cents=260,
                        p_max_cents=500,
                        a=1.0,
                        d=0.1,
                        s0=1.0,
                        c=0.1,
                        bar_price_cents=260,
                    )
                key_id = await create_key(conn, label="fixture", role="admin", secret_hash="-")
                secret = mint_secret()
                await set_secret_hash(conn, key_id, hash_secret(secret))
            await go_live(engine, run_id, now_ms=T0)
            return format_key(key_id, secret)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


class _Session:
    def __init__(self, client: TestClient, clock: FakeClock, ws: Any) -> None:
        self.client = client
        self.clock = clock
        self.ws = ws

    def send(self, message: Any) -> None:
        self.ws.send_text(message if isinstance(message, str) else json.dumps(message))

    def until(self, kind: str, **data: Any) -> Frame:
        """The next frame of type `kind` whose data has `data`'s items; others are skipped."""
        for _ in range(MAX_FRAMES):
            frame: Frame = json.loads(self.ws.receive_text())
            if frame["type"] == kind and data.items() <= frame["data"].items():
                return frame
        raise AssertionError(f"no {kind} {data} within {MAX_FRAMES} frames")

    def advance(self, ms: int) -> None:
        self.client.portal.call(self.clock.advance, ms)  # type: ignore[union-attr]


def _drive(client: TestClient, clock: FakeClock, key: str) -> dict[str, Frame]:
    response = client.post("/api/auth/login", json={"key": key})
    assert response.status_code == 200, response.text
    frames: dict[str, Frame] = {}
    with client.websocket_connect("wss://testserver/ws") as ws:
        s = _Session(client, clock, ws)
        frames["hello"] = s.until("hello")
        frames["hello"]["data"]["boot_id"] = BOOT_ID
        s.send({"type": "hello", "boot_id": "not-this-boot", "last_seq": 0})
        s.until("snapshot")
        frames["theme"] = s.until("theme")
        s.send({"type": "ping"})
        frames["pong"] = s.until("pong")
        s.send("state")
        frames["error"] = s.until("error")

        s.advance(1_000)
        frames["tick"] = s.until("tick")

        version = client.app.state.holder.state.version  # type: ignore[attr-defined]
        drink_id = client.app.state.holder.drink_ids[0]  # type: ignore[attr-defined]
        price = frames["tick"]["data"]["drinks"][str(drink_id)]["price_cents"]
        line = {"drink_id": drink_id, "qty": 2, "unit_price_cents": price}
        response = client.post(
            "/api/orders",
            json={"quote_version": version, "lines": [line]},
            headers={"Idempotency-Key": "fixture-order-1"},
        )
        assert response.status_code == 201, response.text
        frames["order"] = s.until("order")

        response = client.post("/api/news", json={"level": "warning", "text": "Happy hour!"})
        assert response.status_code == 201, response.text
        frames["news"] = s.until("news")

        response = client.post(
            "/api/market/events", json={"kind": "correction", "duration_ms": EVENT_MS}
        )
        assert response.status_code == 201, response.text
        frames["market_event_start"] = s.until("market_event", op="start")

        # A snapshot with news, an event, bars and earnings in it.
        s.send({"type": "resync_request"})
        frames["snapshot"] = s.until("snapshot")
        s.until("theme")

        for _ in range(EVENT_MS // 1_000):
            s.advance(1_000)
            s.until("tick")
        frames["market_event_end"] = s.until("market_event", op="end")

        client.portal.call(_publish_config, client)  # type: ignore[union-attr]
        frames["config"] = s.until("config")

        frames["resync"] = json.loads(client.app.state.hub.resync_frame())  # type: ignore[attr-defined]
    return frames


async def _publish_config(client: TestClient) -> None:
    """One `config` broadcast, as a live config write that removed `Fris` would send."""
    state = client.app.state  # type: ignore[attr-defined]
    holder = state.holder
    event = ConfigChanged(
        run_id=holder.run_id,
        version=holder.state.version,
        revision=2,
        name="Borrel",
        tick_interval_ms=state.tick_interval_ms,
        candle_interval_ms=holder.candle_interval_ms,
        quote_grace_versions=holder.quote_grace_versions,
        drinks=tuple(
            (d, name, name != "Fris")
            for d, name in zip(holder.drink_ids, holder.spec.names, strict=True)
        ),
        params=holder.spec.params,
    )
    Publisher(state.hub, seeded_book(holder), active=active_drink_ids(holder))([event])


def record(settings: Settings) -> dict[str, Frame]:
    """One frame per server message type, from a fresh database and a fake clock."""
    with _scratch_database(settings) as url, _database_env(url):
        key = _seed(settings, url)
        clock = FakeClock(T0)
        app = create_app(clock=clock, run_migrations=False)
        with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
            return _drive(client, clock, key)


def render(frames: dict[str, Frame]) -> str:
    return json.dumps(frames, indent=2, ensure_ascii=False) + "\n"


def check(settings: Settings) -> str | None:
    """The diff between a fresh recording and the committed fixture, or `None` if equal."""
    fresh = render(record(settings))
    committed = FIXTURE.read_text(encoding="utf-8") if FIXTURE.exists() else ""
    if fresh == committed:
        return None
    diff = difflib.unified_diff(
        committed.splitlines(keepends=True),
        fresh.splitlines(keepends=True),
        fromfile=f"{FIXTURE.name} (committed)",
        tofile=f"{FIXTURE.name} (recorded)",
    )
    return "".join(diff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.api.ws_fixture")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="re-record and diff; exit 1 on change")
    mode.add_argument("--write", action="store_true", help="re-record and write the fixture")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.write:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(render(record(settings)), encoding="utf-8", newline="\n")
        print(f"wrote {FIXTURE.relative_to(REPO_ROOT)}")
        return 0
    diff = check(settings)
    if diff is None:
        print(f"{FIXTURE.relative_to(REPO_ROOT)}: unchanged")
        return 0
    sys.stdout.write(diff)
    return 1


if __name__ == "__main__":
    sys.exit(main())
