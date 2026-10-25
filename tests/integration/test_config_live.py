"""Live config writes (Phase 6 T11: AC8, AC9, AC10, AC12, AC13, AC28; SD7, SD9, SD10; PD5, PD18).

A live `PATCH config` is one `holder.mutate("config", ...)`: the row changes, the
revision, the `engine_state` compare-and-set and a `price_tick` of source
`config`, in one transaction, at `version + 1`, then one `config` broadcast.

The runtime is assembled the way boot assembles it -- a holder rehydrated from a
committed live run, a hub with a connected socket, the publisher as the sink --
with no HTTP; `tests/api/test_config.py` drives the same path through the route.

B-03 T2 (AC5-AC9, SD2): a live change of one of the six noise params is that
same transition and moves no `y`; it acts at the engine's next step, as the
engine already does. These tests change no source: one failing means the code
does not do what SD2 says.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import save_transition
from app.db.runs import add_drink, append_config_revision, create_draft_run, go_live
from app.db.session import create_engine
from app.realtime.hub import Hub
from app.realtime.publish import Publisher, active_drink_ids, seeded_book, snapshot
from app.runtime.config import ConfigPatch, write_live_config
from app.runtime.history import TickEntry
from app.runtime.holder import DomainEvent, MarketHolder, MarketView, Outcome, TickCommitted
from app.runtime.manipulation import schedule, start_event
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import EngineState, Params, advance, prices_from_y
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
        self.run_seed = run.run_seed
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


# A Brownian draw every 2 s, so a test reaches one without a minute of fake time.
NOISE_PARAMS = Params(step_quant=0.5, bm_dt_minutes=2 / 60)
# One new value for each of the six (B-03 SD3's ranges); `y_clip` 1 is its floor.
NOISE_VALUES: dict[str, Any] = {
    "bm_enabled": False,
    "bm_sigma_y": 0.5,
    "bm_dt_minutes": 0.25,
    "flow_vol_amp": 1.2,
    "flow_beta": 0.6,
    "y_clip": 1.0,
}


async def _tick(
    engine: AsyncEngine, holder: MarketHolder, clock: FakeClock, *, ms: int = 1_000
) -> EngineState:
    """One scheduled tick `ms` after the clock's time, committed as the ticker commits it."""
    clock.advance(ms)
    now_ms = clock.wall_ms()

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id is not None and view.spec is not None and view.state is not None
        candidate = advance(view.spec, view.state, now_ms=now_ms, run_seed=view.run_seed).state
        await save_transition(
            engine,
            run_id=view.run_id,
            expected_version=view.state.version,
            state=candidate,
            spec=view.spec,
            drink_ids=view.drink_ids,
            source="tick",
            wall_ts_ms=now_ms,
        )
        entry = TickEntry(
            candidate.version, now_ms, "tick", tick_prices(view.spec, candidate, view.drink_ids)
        )
        return Outcome(
            result=candidate.version,
            view=dataclasses.replace(view, state=candidate, last_commit_wall_ms=now_ms),
            events=(TickCommitted(run_id=view.run_id, entry=entry),),
            ticks=(entry,),
        )

    await holder.mutate("tick", step)
    assert holder.state is not None
    return holder.state


async def _push_bier_past_one(runtime: Runtime) -> None:
    """Bier jumps to 4,50 and lands there: `y` = ln 6, about 1.79."""
    await schedule(runtime.holder, runtime.holder.drink_ids[0], 450, 1_000, clock=runtime.clock)
    state = await _tick(runtime.engine, runtime.holder, runtime.clock)
    assert not state.jumps
    assert float(state.y[0]) > 1


async def _last_config_prices(runtime: Runtime) -> Any:
    return json.loads(
        await runtime.scalar(
            "SELECT prices::text FROM price_tick WHERE run_id = :r AND source = 'config' "
            "ORDER BY version DESC LIMIT 1",
            r=runtime.run_id,
        )
    )


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


def test_a_noise_change_leaves_y_bitwise_and_is_one_transition(
    settings: Settings, database_url: str
) -> None:
    """B-03 AC5: each of the six; `y_clip` lowered below Bier's `y` moves nothing at the save."""

    async def scenario() -> None:
        async with _live(settings, database_url, NOISE_PARAMS) as runtime:
            await _push_bier_past_one(runtime)
            for field, value in NOISE_VALUES.items():
                spec, state = runtime.holder.spec, runtime.holder.state
                assert spec is not None and state is not None
                y, version = state.y.tobytes(), state.version
                quoted = tick_prices(spec, state, runtime.holder.drink_ids)
                ticks = await _ticks(runtime, "config")
                frames = len(await runtime.frames("config"))

                await runtime.patch({"params": {field: value}})

                after = runtime.holder.state
                assert after is not None and runtime.holder.spec is not None
                assert after.y.tobytes() == y, field
                assert after.version == version + 1
                assert getattr(runtime.holder.spec.params, field) == value
                assert await _ticks(runtime, "config") == ticks + 1
                assert await _last_config_prices(runtime) == {str(d): p for d, p in quoted.items()}
                config = await runtime.frames("config")
                assert len(config) == frames + 1
                assert config[-1]["version"] == version + 1
                assert config[-1]["data"]["params"][field] == value
            state = runtime.holder.state
            assert state is not None
            assert float(state.y[0]) > 1  # no clip at the save

    asyncio.run(scenario())


def test_noise_off_draws_nothing_and_on_again_draws_once(
    settings: Settings, database_url: str
) -> None:
    """B-03 AC6, SD2: back on, one draw at the next tick, nothing caught up."""

    async def scenario() -> None:
        async with _live(settings, database_url, NOISE_PARAMS) as runtime:
            await runtime.patch({"params": {"bm_enabled": False}})
            off = runtime.holder.state
            assert off is not None

            quiet = await _tick(runtime.engine, runtime.holder, runtime.clock, ms=3_000)

            assert runtime.clock.wall_ms() - off.last_bm_ms >= 2_000  # past the draw interval
            assert (quiet.rng_counter, quiet.last_bm_ms) == (off.rng_counter, off.last_bm_ms)

            await runtime.patch({"params": {"bm_enabled": True}})
            on = await _tick(runtime.engine, runtime.holder, runtime.clock)

            assert on.rng_counter == off.rng_counter + 1
            assert on.last_bm_ms == runtime.clock.wall_ms()
            after = await _tick(runtime.engine, runtime.holder, runtime.clock)
            assert (after.rng_counter, after.last_bm_ms) == (on.rng_counter, on.last_bm_ms)

    asyncio.run(scenario())


def test_a_lowered_clip_holds_every_y_at_the_next_draw(
    settings: Settings, database_url: str
) -> None:
    """B-03 AC7: Bier, at about 1.79, is cut back to 1 by the next draw."""

    async def scenario() -> None:
        async with _live(settings, database_url, NOISE_PARAMS) as runtime:
            await _push_bier_past_one(runtime)
            await runtime.patch({"params": {"y_clip": 1.0}})
            before = runtime.holder.state
            assert before is not None and runtime.holder.spec is not None

            after = await _tick(runtime.engine, runtime.holder, runtime.clock, ms=2_000)

            assert after.rng_counter == before.rng_counter + 1  # a draw
            active = runtime.holder.spec.active
            assert bool(np.all(np.abs(after.y[active]) <= 1.0)), after.y

    asyncio.run(scenario())


def test_a_shorter_rhythm_draws_once_sized_for_the_new_value(
    settings: Settings, database_url: str
) -> None:
    """B-03 AC8, PD7: 1 min -> 0.05 min ten seconds after the last draw.

    The draw is `rng_counter`'s normal, so the same pre-state advanced with
    `bm_dt_minutes = 1` (its gate moved back) draws the same number: the noise
    part of `y` is exactly sqrt(0.05 / 1) of that one's.
    """

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:  # bm_dt_minutes = 1
            # A new run's `last_bm_ms` is 0, so its first tick draws; count from that draw.
            start = await _tick(runtime.engine, runtime.holder, runtime.clock)
            assert start.last_bm_ms == runtime.clock.wall_ms()
            for _ in range(10):
                state = await _tick(runtime.engine, runtime.holder, runtime.clock)
            assert state.rng_counter == start.rng_counter  # no draw in ten seconds
            assert runtime.clock.wall_ms() - state.last_bm_ms == 10_000

            await runtime.patch({"params": {"bm_dt_minutes": 0.05}})
            spec, pre = runtime.holder.spec, runtime.holder.state
            assert spec is not None and pre is not None
            after = await _tick(runtime.engine, runtime.holder, runtime.clock)
            now_ms = runtime.clock.wall_ms()

            assert after.rng_counter == pre.rng_counter + 1
            assert after.last_bm_ms == now_ms

            def y_with(minutes: float, enabled: bool, last_bm_ms: int) -> Any:
                params = dataclasses.replace(spec.params, bm_dt_minutes=minutes, bm_enabled=enabled)
                return advance(
                    dataclasses.replace(spec, params=params),
                    dataclasses.replace(pre, last_bm_ms=last_bm_ms),
                    now_ms=now_ms,
                    run_seed=runtime.run_seed,
                ).state.y

            assert after.y.tobytes() == y_with(0.05, True, pre.last_bm_ms).tobytes()
            quiet = y_with(0.05, False, pre.last_bm_ms)
            sized_for_one = y_with(1.0, True, now_ms - 60_000)
            assert not np.allclose(after.y, quiet)  # a real draw
            np.testing.assert_allclose(
                after.y - quiet, np.sqrt(0.05 / 1) * (sized_for_one - quiet), rtol=1e-9, atol=1e-12
            )

            nothing = await _tick(runtime.engine, runtime.holder, runtime.clock)
            assert (nothing.rng_counter, nothing.last_bm_ms) == (after.rng_counter, now_ms)

    asyncio.run(scenario())


def test_a_restart_runs_on_the_changed_values(settings: Settings, database_url: str) -> None:
    """B-03 AC9, PD6: a fresh rehydrate of the committed run, as boot does, then a tick."""

    async def scenario() -> None:
        async with _live(settings, database_url, NOISE_PARAMS) as runtime:
            await runtime.patch({"params": NOISE_VALUES})

            run = await rehydrate(runtime.engine, now_ms=runtime.clock.wall_ms())

            assert isinstance(run, RehydratedRun)
            assert {name: getattr(run.spec.params, name) for name in NOISE_VALUES} == NOISE_VALUES
            holder = MarketHolder.from_rehydrated(
                run, engine=runtime.engine, clock=runtime.clock, sink=lambda events: None
            )
            before = holder.state
            assert before is not None
            after = await _tick(runtime.engine, holder, runtime.clock, ms=60_000)
            assert runtime.clock.wall_ms() - before.last_bm_ms >= 15_000  # past Ritme ruis
            assert (after.rng_counter, after.last_bm_ms) == (before.rng_counter, before.last_bm_ms)

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


def test_a_live_switch_or_limit_change_is_one_transition_into_the_view(
    settings: Settings, database_url: str
) -> None:
    """B-06 PD4, SD1, SD17: version + 1, one config frame carrying both, `y` unchanged, and
    the holder's view holds the new values, so the next order is judged by them."""

    async def scenario() -> None:
        async with _live(settings, database_url) as runtime:
            state = runtime.holder.state
            assert state is not None
            y, version = state.y.tobytes(), state.version
            assert runtime.holder.view.wallet_required is False
            frames = len(await runtime.frames("config"))

            await runtime.patch({"wallet_required": True, "credit_limit_cents": 250})

            after = runtime.holder.state
            assert after is not None
            assert after.version == version + 1
            assert after.y.tobytes() == y
            view = runtime.holder.view
            assert (view.wallet_required, view.credit_limit_cents) == (True, 250)
            config = await runtime.frames("config")
            assert len(config) == frames + 1
            assert config[-1]["data"]["run"]["wallet_required"] is True
            assert config[-1]["data"]["run"]["credit_limit_cents"] == 250
            data = snapshot(runtime.holder, tick_interval_ms=1_000)
            assert data is not None
            assert (data.run.wallet_required, data.run.credit_limit_cents) == (True, 250)

    asyncio.run(scenario())
