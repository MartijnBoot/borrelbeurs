"""Live config writes (Phase 6 T11: AC8, AC9, AC10, AC12, AC13, AC28; SD7, SD9, SD10; PD5, PD18).

A live `PATCH config` is one `holder.mutate("config", ...)`: the row changes, the
revision, the `engine_state` compare-and-set and a `price_tick` of source
`config`, in one transaction, at `version + 1`, then one `config` broadcast.

The runtime is assembled the way boot assembles it -- a holder rehydrated from a
committed live run, a hub with a connected socket, the publisher as the sink --
with no HTTP; `tests/api/test_config.py` drives the same path through the route.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.runs import add_drink, append_config_revision, create_draft_run, go_live
from app.db.session import create_engine
from app.realtime.hub import Hub
from app.realtime.publish import Publisher, active_drink_ids, seeded_book, snapshot
from app.runtime.config import ConfigPatch, write_live_config
from app.runtime.holder import DomainEvent, MarketHolder
from app.runtime.manipulation import schedule, start_event
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import Params, prices_from_y
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
REPO_ROOT = Path(__file__).resolve().parents[2]


class RecordingSocket:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_text(self, frame: str) -> None:
        self.frames.append(json.loads(frame))

    async def close(self, code: int) -> None:
        pass


class Runtime:
    def __init__(self, engine: AsyncEngine, run: RehydratedRun, clock: FakeClock) -> None:
        self.engine = engine
        self.clock = clock
        self.run_id = run.run_id
        self.events: list[DomainEvent] = []
        self.holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=self._sink)
        self.hub = Hub(clock=clock, replay_window_ms=15 * 60_000)
        self.publisher = Publisher(
            self.hub,
            seeded_book(self.holder),
            active=active_drink_ids(self.holder),
            ring=lambda: self.holder.ring,
        )
        self.socket = RecordingSocket()
        self.hub.connect(self.socket)

    def _sink(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)
        self.publisher(events)

    async def patch(self, body: dict[str, Any], *, author: str = "Bestuur") -> int:
        return await write_live_config(
            self.holder,
            self.run_id,
            ConfigPatch.model_validate(body),
            author=author,
            clock=self.clock,
        )

    async def frames(self, kind: str) -> list[dict[str, Any]]:
        for _ in range(100):
            await asyncio.sleep(0)
        return [f for f in self.socket.frames if f["type"] == kind]

    async def scalar(self, sql: str, **bind: Any) -> Any:
        async with self.engine.connect() as conn:
            return (await conn.execute(text(sql), bind)).scalar_one()


@asynccontextmanager
async def _live(
    settings: Settings, url: str, params: Params | None = None
) -> AsyncIterator[Runtime]:
    engine = create_engine(settings.model_copy(update={"database_url": url}))
    try:
        async with engine.begin() as conn:
            run_id = await create_draft_run(
                conn, name="Vrijmibo", params=params or Params(step_quant=0.5), run_seed=7
            )
            for slot, name in enumerate(("Bier", "Wijn", "Fris")):
                await add_drink(
                    conn,
                    run_id,
                    name=name,
                    slot=slot,
                    p_min_cents=150,
                    p0_cents=260 + 30 * slot,
                    p_max_cents=500,
                    a=1.0,
                    d=0.1,
                    s0=1.0,
                    c=0.1,
                    bar_price_cents=260,
                )
            # Revision 1, as `create_run` writes it.
            await append_config_revision(conn, run_id, config={}, author="seed")
        await go_live(engine, run_id, now_ms=T0, author="seed")
        clock = FakeClock(T0)
        run = await rehydrate(engine, now_ms=T0)
        assert isinstance(run, RehydratedRun)
        yield Runtime(engine, run, clock)
    finally:
        await engine.dispose()


def _quoted_cents(holder: MarketHolder) -> list[int]:
    spec, state = holder.spec, holder.state
    assert spec is not None and state is not None
    _, p_q = prices_from_y(state.y, spec.p_min, spec.p_max, spec.params.step_quant)
    return [round(float(p) * 100) for p in p_q]


async def _ticks(runtime: Runtime, source: str) -> int:
    return int(
        await runtime.scalar(
            "SELECT count(*) FROM price_tick WHERE run_id = :r AND source = :s",
            r=runtime.run_id,
            s=source,
        )
    )


async def _revisions(runtime: Runtime) -> list[tuple[int, str]]:
    async with runtime.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT revision, author FROM run_config_revision WHERE run_id = :r "
                "ORDER BY revision"
            ),
            {"r": runtime.run_id},
        )
        return [(int(r.revision), str(r.author)) for r in rows]


def test_a_scalar_change_leaves_y_bitwise_and_is_one_transition(
    settings: Settings, database_url: str
) -> None:
    """AC9, AC12: y unchanged; version + 1; one config tick, one revision, one frame."""

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            for body in (
                {"params": {"eta": 0.9}},
                {"params": {"K": 20.0}},
                {"params": {"demand_enabled": False}},
            ):
                state = runtime.holder.state
                assert state is not None
                y, version = state.y.tobytes(), state.version
                revisions = len(await _revisions(runtime))
                ticks = await _ticks(runtime, "config")
                frames = len(await runtime.frames("config"))

                revision = await runtime.patch(body)

                after = runtime.holder.state
                assert after is not None
                assert after.y.tobytes() == y, body
                assert after.version == version + 1
                assert revision == revisions + 1
                assert (await _revisions(runtime))[-1] == (revision, "Bestuur")
                assert await _ticks(runtime, "config") == ticks + 1
                assert (
                    int(
                        await runtime.scalar(
                            "SELECT version FROM engine_state WHERE run_id = :r", r=runtime.run_id
                        )
                    )
                    == version + 1
                )
                config = await runtime.frames("config")
                assert len(config) == frames + 1
                assert config[-1]["version"] == version + 1
                assert config[-1]["data"]["revision"] == revision
            assert runtime.holder.spec is not None
            params = runtime.holder.spec.params
            assert (params.eta, params.K, params.demand_enabled) == (0.9, 20.0, False)

    asyncio.run(scenario())


def test_a_step_quant_change_holds_every_quoted_price_and_cancels_jumps(
    settings: Settings, database_url: str
) -> None:
    """AC8, AC10: 0.5 -> 0.1 holds each quote; a jump and a market event's jumps go."""

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            bier = runtime.holder.drink_ids[0]
            await start_event(runtime.holder, "bubble", 30_000, clock=runtime.clock)
            await schedule(runtime.holder, bier, 400, 60_000, clock=runtime.clock)
            state = runtime.holder.state
            assert state is not None and state.jumps
            before = _quoted_cents(runtime.holder)

            await runtime.patch({"params": {"step_quant": 0.1}})

            state = runtime.holder.state
            assert state is not None and runtime.holder.spec is not None
            assert runtime.holder.spec.params.step_quant == 0.1
            assert state.jumps == ()
            assert _quoted_cents(runtime.holder) == before

    asyncio.run(scenario())


def test_a_candle_change_re_buckets_the_snapshot(settings: Settings, database_url: str) -> None:
    """AC28, SD10: the snapshot's bars are 30 s buckets after the change."""

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            bier = runtime.holder.drink_ids[0]
            for offset_ms in (10_000, 40_000, 70_000):
                runtime.clock.set_wall(T0 + offset_ms)
                await schedule(runtime.holder, bier, 400, 60_000, clock=runtime.clock)

            await runtime.patch({"candle_interval_s": 30})

            assert runtime.holder.candle_interval_ms == 30_000
            data = snapshot(runtime.holder, tick_interval_ms=1_000)
            assert data is not None
            starts = [bar.t_ms for bar in data.bars[bier]]
            assert all(t % 30_000 == 0 for t in starts)
            assert len(starts) == len(set(starts)) >= 3
            assert (
                int(
                    await runtime.scalar(
                        "SELECT candle_interval_ms FROM run WHERE run_id = :r", r=runtime.run_id
                    )
                )
                == 30_000
            )

    asyncio.run(scenario())


def test_a_history_window_change_resizes_the_ring_and_replay_window(
    settings: Settings, database_url: str
) -> None:
    """PD18: shrinking trims the ring and the hub's replay window at once."""

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            bier = runtime.holder.drink_ids[0]
            runtime.clock.set_wall(T0 + 5 * 60_000)
            await schedule(runtime.holder, bier, 400, 60_000, clock=runtime.clock)
            assert runtime.holder.ring[0].wall_ts_ms == T0

            await runtime.patch({"params": {"history_window_minutes": 2}})

            assert all(e.wall_ts_ms >= T0 + 3 * 60_000 for e in runtime.holder.ring)
            assert runtime.hub.replay_window_ms == 2 * 60_000

    asyncio.run(scenario())


def test_an_empty_patch_takes_no_transition(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            state = runtime.holder.state
            assert state is not None
            revisions = await _revisions(runtime)

            bodies: list[dict[str, Any]] = [{}, {"params": {}}, {"params": {"eta": 0.6}}]
            for body in bodies:
                assert await runtime.patch(body) == revisions[-1][0]

            assert runtime.holder.state is state
            assert await _revisions(runtime) == revisions
            assert await _ticks(runtime, "config") == 0
            assert await runtime.frames("config") == []

    asyncio.run(scenario())


def test_two_concurrent_live_patches_get_consecutive_revisions(
    settings: Settings, database_url: str
) -> None:
    """AC13 (live)."""

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            first = (await _revisions(runtime))[-1][0]

            written = await asyncio.gather(
                runtime.patch({"params": {"eta": 0.9}}, author="a"),
                runtime.patch({"params": {"K": 20.0}}, author="b"),
            )

            assert sorted(written) == [first + 1, first + 2]
            assert [r for r, _ in await _revisions(runtime)][-2:] == [first + 1, first + 2]
            assert runtime.holder.spec is not None
            assert (runtime.holder.spec.params.eta, runtime.holder.spec.params.K) == (0.9, 20.0)

    asyncio.run(scenario())


def test_no_golden_scenario_saves_config() -> None:
    """R15: SD9 differs from v1 on purpose; no fixture's events include a config save."""
    fixtures = sorted((REPO_ROOT / "tests/engine/golden/fixtures").glob("*.json"))
    kinds = {
        event["kind"]
        for path in fixtures
        for event in json.loads(path.read_text(encoding="utf-8"))["events"]
    }

    assert len(fixtures) == 6
    assert kinds == {"tick", "order", "jump", "crash"}


def test_y_is_an_array_the_bitwise_check_can_see() -> None:
    """Anti-vacuity: `tobytes` differs when any element does."""
    a = np.array([0.1, 0.2])
    assert a.tobytes() != np.array([0.1, 0.2000000000000001]).tobytes()
