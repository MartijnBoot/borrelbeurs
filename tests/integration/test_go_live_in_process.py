"""Go-live inside the running process (Phase 6 T9: SD1, SD3; AC25, AC26, AC27; PD11).

The runtime's parts -- an empty holder, its ticker, a hub with a connected
socket and the publisher -- are built the way boot builds them, then a draft
goes live through `go_live_in_process`. No HTTP: `tests/api/test_go_live.py`
drives the same path through the route and a real WebSocket.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.mapping import spec_from_rows
from app.db.runs import LiveRunExists, active_drinks, add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.realtime.hub import Hub
from app.realtime.publish import Publisher, active_drink_ids, seeded_book
from app.runtime.golive import go_live_in_process
from app.runtime.holder import DomainEvent, MarketHolder
from app.runtime.theme import resolve
from app.runtime.ticker import Ticker
from exchange import Params, anchor_s0_to_current_y, initial_state
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
BOOT_INTERVAL = 1_000


class RecordingSocket:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_text(self, frame: str) -> None:
        self.frames.append(json.loads(frame))

    async def close(self, code: int) -> None:
        pass


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _draft(
    engine: AsyncEngine, params: Params | None = None, *, tick_interval_ms: int = 500
) -> int:
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Vrijmibo", params=params or Params(step_quant=0.1), run_seed=7
        )
        for slot, name in enumerate(("Bier", "Wijn")):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=150,
                p0_cents=260 + 40 * slot,
                p_max_cents=500,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )
        await conn.execute(
            text("UPDATE run SET tick_interval_ms = :t WHERE run_id = :r"),
            {"t": tick_interval_ms, "r": run_id},
        )
    return run_id


class Runtime:
    """What boot puts on `app.state`, with no live run."""

    def __init__(self, engine: AsyncEngine, clock: FakeClock) -> None:
        self.engine = engine
        self.clock = clock
        self.events: list[DomainEvent] = []
        self.diverged = 0
        self.holder = MarketHolder.empty(
            engine=engine, clock=clock, sink=self._sink, on_diverged=self._diverged
        )
        self.hub = Hub(clock=clock, replay_window_ms=60_000)
        self.publisher = Publisher(
            self.hub, seeded_book(self.holder), active=active_drink_ids(self.holder)
        )
        self.ticker = Ticker(self.holder, clock=clock, interval_ms=BOOT_INTERVAL)
        self.tick_interval_ms = BOOT_INTERVAL
        self.theme = resolve("blauw", 0)
        self.socket = RecordingSocket()
        self.hub.connect(self.socket)

    def _sink(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)
        self.publisher(events)

    def _diverged(self) -> None:
        self.diverged += 1

    @property
    def state(self) -> SimpleNamespace:
        return SimpleNamespace(
            engine=self.engine,
            clock=self.clock,
            holder=self.holder,
            ticker=self.ticker,
            hub=self.hub,
            publisher=self.publisher,
            theme=self.theme,
            tick_interval_ms=self.tick_interval_ms,
        )

    async def settle(self) -> None:
        """Wait (in real time) until the ticker is asleep on the fake clock again.

        The hub's writer also sleeps on the clock (its 10 s send deadline), so the
        ticker's sleep is told apart as the one due within a boot interval.
        """
        for _ in range(2_000):
            await asyncio.sleep(0.005)
            now = self.clock.monotonic()
            ticker_asleep = any(
                now < due <= now + BOOT_INTERVAL / 1000 and not future.done()
                for due, _, future in self.clock._sleepers
            )
            if ticker_asleep and not self.ticker.busy:
                return
        raise AssertionError("the ticker did not settle")

    async def advance(self, ms: int) -> None:
        self.clock.advance(ms)
        await self.settle()


@asynccontextmanager
async def _runtime(settings: Settings, url: str) -> AsyncIterator[Runtime]:
    engine = _engine(settings, url)
    try:
        runtime = Runtime(engine, FakeClock(T0))
        runtime.ticker.start()
        await runtime.settle()
        try:
            yield runtime
        finally:
            await runtime.ticker.stop()
            await runtime.hub.close_all(1012)
    finally:
        await engine.dispose()


def test_a_draft_goes_live_in_process_and_clients_get_its_snapshot(
    settings: Settings, database_url: str
) -> None:
    """AC25, AC27: no restart, no reconnect; ticks then run at the run's own interval."""

    async def scenario() -> None:
        async with _runtime(settings, database_url) as rt:
            run_id = await _draft(rt.engine, tick_interval_ms=500)
            seq_before = rt.hub.seq
            state = rt.state

            await go_live_in_process(state, run_id, author="Bestuur")
            await rt.settle()

            assert rt.holder.run_id == run_id and state.tick_interval_ms == 500
            snapshots = [f for f in rt.socket.frames if f["type"] == "snapshot"]
            assert len(snapshots) == 1
            (snap,) = snapshots
            assert (snap["run_id"], snap["version"]) == (run_id, 0)
            assert snap["data"]["run"]["tick_interval_ms"] == 500
            assert [d["name"] for d in snap["data"]["drinks"]] == ["Bier", "Wijn"]
            assert snap["seq"] == seq_before + 1  # PD11: the replay log starts over
            assert rt.hub.replay_after(rt.hub.boot_id, seq_before) is None

            for version in (1, 2, 3):
                await rt.advance(500)
                assert rt.holder.state is not None and rt.holder.state.version == version
            async with rt.engine.connect() as conn:
                stamps: list[int] = list(
                    (
                        await conn.execute(
                            text(
                                "SELECT wall_ts_ms FROM price_tick WHERE source = 'tick'"
                                " ORDER BY version"
                            )
                        )
                    ).scalars()
                )
                assert stamps == [T0 + 500, T0 + 1_000, T0 + 1_500]
            kinds = [f["type"] for f in rt.socket.frames]
            assert kinds == ["snapshot", "theme", "tick", "tick", "tick"]
            assert [f["version"] for f in rt.socket.frames[2:]] == [1, 2, 3]

    asyncio.run(scenario())


def test_go_live_with_a_run_already_held_is_refused_and_writes_nothing(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        async with _runtime(settings, database_url) as rt:
            first = await _draft(rt.engine)
            await go_live_in_process(rt.state, first, author="a")
            async with rt.engine.begin() as conn:
                second = await create_draft_run(conn, name="Twee", params=Params(), run_seed=1)

            with pytest.raises(LiveRunExists):
                await go_live_in_process(rt.state, second, author="a")

            async with rt.engine.connect() as conn:
                status: str = (
                    await conn.execute(
                        text("SELECT status FROM run WHERE run_id = :r"), {"r": second}
                    )
                ).scalar_one()
            assert status == "draft"
            assert rt.holder.run_id == first

    asyncio.run(scenario())


def test_a_failed_adopt_after_the_commit_calls_on_diverged(
    settings: Settings, database_url: str
) -> None:
    """SD3: the run is live in the database but not in memory; boot must rehydrate it."""

    async def scenario() -> None:
        async with _runtime(settings, database_url) as rt:
            run_id = await _draft(rt.engine)

            async def failing() -> Any:
                raise OSError("the database went away")

            with pytest.raises(OSError):
                await rt.holder.adopt(failing)

            assert rt.diverged == 1
            assert rt.holder.is_empty
            assert run_id

    asyncio.run(scenario())


def test_a_failed_interval_read_after_the_commit_calls_on_diverged(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SD3: every read after the commit is part of the swap, so its failure is a divergence."""

    async def scenario() -> None:
        async with _runtime(settings, database_url) as rt:
            run_id = await _draft(rt.engine)

            async def failing(engine: AsyncEngine, run_id: int) -> int:
                raise OSError("the database went away")

            monkeypatch.setattr("app.runtime.golive.run_tick_interval_ms", failing)

            with pytest.raises(OSError):
                await go_live_in_process(rt.state, run_id, author="a")

            assert rt.diverged == 1
            assert rt.holder.is_empty

    asyncio.run(scenario())


def test_go_live_with_auto_calibrate_anchors_s0_and_adds_one_revision(
    settings: Settings, database_url: str
) -> None:
    """SD3: `anchor_s0_to_current_y` on the initial prices, written to every `drink.s0`."""

    async def scenario() -> tuple[NDArray[np.float64], NDArray[np.float64], list[tuple[Any, ...]]]:
        engine = _engine(settings, database_url)
        try:
            params = Params(step_quant=0.1, auto_calibrate_s0=True)
            run_id = await _draft(engine, params)
            async with engine.connect() as conn:
                spec, _ = spec_from_rows(await active_drinks(conn, run_id), params)
            expected = anchor_s0_to_current_y(spec, initial_state(spec, now_ms=T0).y).s0

            await go_live(engine, run_id, now_ms=T0, author="Bestuur")

            async with engine.connect() as conn:
                stored = np.array(
                    [d.s0 for d in await active_drinks(conn, run_id)], dtype=np.float64
                )
                revisions = (
                    await conn.execute(
                        text("SELECT revision, author FROM run_config_revision WHERE run_id = :r"),
                        {"r": run_id},
                    )
                ).all()
            return expected, stored, [tuple(r) for r in revisions]
        finally:
            await engine.dispose()

    expected, stored, revisions = asyncio.run(scenario())

    assert stored.tobytes() == expected.tobytes()
    assert not np.array_equal(stored, np.ones(2))
    assert revisions == [(1, "Bestuur")]
