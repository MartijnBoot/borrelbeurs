"""Kill the market process, rehydrate in a fresh one, lose nothing (T15).

AC1; AC5 and AC6 across a real kill; SD1. The harness
(`tests/integration/durability/harness.py`) runs as a subprocess on the
scratch database and is `Popen.kill()`ed at the plan's five points: after the
commit of version k, for three k, and inside version k's transaction, for two
k, one of them an order. A sixth kills that order after its last statement, so
a write split across two transactions cannot hide behind the first one. This
process then rehydrates and compares against what the harness printed as
committed, and against a pure replay of the same script.

The assertion output of this module is the phase's durability evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import EncodedState, decode_state, tick_prices
from app.db.session import create_engine
from app.runtime.gap import DEFAULT_CATCH_UP_BUDGET_MS
from app.runtime.rehydrate import RehydratedRun, rehydrate
from exchange import EngineState, MarketSpec, advance, initial_state
from exchange.steps import apply_jumps
from tests.integration.durability.harness import JUMP_DRINK, SCRIPTS, transition

REPO_ROOT = Path(__file__).resolve().parents[2]
START_MS = 1_759_312_800_000
SCRIPT = "standard"
BUDGET = DEFAULT_CATCH_UP_BUDGET_MS
TIMEOUT_S = 180
STEPS = {step.second: step for step in SCRIPTS[SCRIPT]}
# UPDATE engine_state, INSERT "order", INSERT order_line, INSERT price_tick (T12).
WRITE_ORDER_STATEMENTS = 4


@dataclass(frozen=True)
class Killed:
    """What the harness printed before it was killed."""

    run_id: int
    run_seed: int
    drink_ids: tuple[int, ...]
    last_commit: dict[str, Any]
    stderr: str


def _kill_harness(url: str, tmp_path: Path, *flags: str, until: str, version: int) -> Killed:
    """Run the harness until it prints `{"kind": until, "version": version}`, then kill it."""
    stderr_path = tmp_path / "harness.stderr"
    command = [
        sys.executable,
        "-m",
        "tests.integration.durability.harness",
        "--start-ms",
        str(START_MS),
        "--script",
        SCRIPT,
        *flags,
    ]
    with stderr_path.open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env={**os.environ, "DATABASE_URL": url},
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
        )
        watchdog = threading.Timer(TIMEOUT_S, proc.kill)
        watchdog.start()
        ready: dict[str, Any] = {}
        last_commit: dict[str, Any] = {}
        reached = False
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = json.loads(raw)
                if line["kind"] == "ready":
                    ready = line
                elif line["kind"] == until and line["version"] == version:
                    reached = True
                    break
                elif "state" in line:
                    last_commit = line
                if line["kind"] == "done":
                    break
        finally:
            proc.kill()
            proc.wait()
            watchdog.cancel()
    captured = stderr_path.read_text(encoding="utf-8")
    assert reached, f"the harness never printed {until} {version}; stderr:\n{captured}"
    if until == "paused":
        assert last_commit["version"] == version
    return Killed(
        run_id=ready["run_id"],
        run_seed=ready["run_seed"],
        drink_ids=tuple(ready["drink_ids"]),
        last_commit=last_commit,
        stderr=captured,
    )


def assert_states_identical(left: EngineState, right: EngineState) -> None:
    """All eleven `EngineState` fields, floats by their bits (AC1)."""
    for key in ("y", "cum_orders", "flow_ema"):
        assert getattr(left, key).tobytes() == getattr(right, key).tobytes(), key
    assert left.last_order_ts.tobytes() == right.last_order_ts.tobytes(), "last_order_ts"
    assert [(j.i, j.t0_ms, j.t1_ms) for j in left.jumps] == [
        (j.i, j.t0_ms, j.t1_ms) for j in right.jumps
    ], "jumps"
    assert np.array([[j.y0, j.y1] for j in left.jumps]).tobytes() == (
        np.array([[j.y0, j.y1] for j in right.jumps]).tobytes()
    ), "jumps"
    for key in ("last_idle_ms", "last_bm_ms", "rng_counter", "version", "tick_index", "t_round"):
        assert getattr(left, key) == getattr(right, key), key


def _replay(spec: MarketSpec, run_seed: int, upto: int) -> EngineState:
    """The script, purely, from go-live to version `upto`."""
    state = initial_state(spec, now_ms=START_MS)
    for second in range(1, upto + 1):
        state = transition(spec, state, STEPS[second], start_ms=START_MS, run_seed=run_seed)
    return state


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _rows(engine: AsyncEngine, run_id: int) -> tuple[int, int, list[tuple[int, str]]]:
    async with engine.connect() as conn:
        orders: int = (
            await conn.execute(
                text('SELECT count(*) FROM "order" WHERE run_id = :r'), {"r": run_id}
            )
        ).scalar_one()
        lines: int = (
            await conn.execute(
                text(
                    'SELECT count(*) FROM order_line l JOIN "order" o USING (order_id)'
                    " WHERE o.run_id = :r"
                ),
                {"r": run_id},
            )
        ).scalar_one()
        ticks: list[tuple[int, str]] = [
            (row.version, row.source)
            for row in await conn.execute(
                text("SELECT version, source FROM price_tick WHERE run_id = :r ORDER BY version"),
                {"r": run_id},
            )
        ]
    return orders, lines, ticks


KILL_POINTS = [
    pytest.param(("--pause-after", "3"), "paused", 3, id="after-commit-3"),
    pytest.param(("--pause-after", "9"), "paused", 9, id="after-commit-9"),
    pytest.param(("--pause-after", "15"), "paused", 15, id="after-commit-15"),
    pytest.param(("--hold-in-tx", "7"), "in_tx", 7, id="inside-tick-7"),
    pytest.param(("--hold-in-tx", "12"), "in_tx", 12, id="inside-order-12"),
    # After the order's last statement, the tick insert, just short of its commit.
    pytest.param(
        ("--hold-in-tx", "12", "--hold-statement", str(WRITE_ORDER_STATEMENTS)),
        "in_tx",
        12,
        id="inside-order-12-before-commit",
    ),
]


@pytest.mark.parametrize(("flags", "until", "version"), KILL_POINTS)
def test_a_killed_market_rehydrates_to_its_last_commit(
    settings: Settings,
    database_url: str,
    tmp_path: Path,
    flags: tuple[str, ...],
    until: str,
    version: int,
) -> None:
    """AC1: state bitwise, order count, and the next `advance`, at each kill point."""
    assert STEPS[12].kind == "order" and STEPS[7].kind == "tick"
    killed = _kill_harness(database_url, tmp_path, *flags, until=until, version=version)
    committed_version = version if until == "paused" else version - 1
    last = killed.last_commit
    assert last["version"] == committed_version

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            result = await rehydrate(engine, now_ms=last["wall_ts_ms"])
            assert isinstance(result, RehydratedRun)
            assert (result.run_id, result.run_seed) == (killed.run_id, killed.run_seed)
            assert result.drink_ids == killed.drink_ids

            printed = decode_state(EncodedState(**last["state"]), killed.drink_ids)
            assert_states_identical(result.state, printed)

            orders, lines, ticks = await _rows(engine, killed.run_id)
            assert orders == last["orders_committed"]
            assert lines == 2 * orders
            # Nothing of a killed transaction survives: one tick per committed version.
            assert [v for v, _ in ticks] == list(range(committed_version + 1))

            replayed = _replay(result.spec, killed.run_seed, committed_version)
            assert_states_identical(replayed, result.state)
            following = STEPS[committed_version + 1]
            assert_states_identical(
                transition(
                    result.spec,
                    result.state,
                    following,
                    start_ms=START_MS,
                    run_seed=result.run_seed,
                ),
                transition(
                    result.spec, replayed, following, start_ms=START_MS, run_seed=killed.run_seed
                ),
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_kill_mid_jump_then_a_long_outage_shifts_and_plays_the_jump_out(
    settings: Settings, database_url: str, tmp_path: Path
) -> None:
    """AC5 and AC6 (per PD1) across a real kill, with the jump still in flight."""
    killed = _kill_harness(
        database_url, tmp_path, "--pause-after", "15", until="paused", version=15
    )
    last = killed.last_commit
    wall = last["wall_ts_ms"]
    rehydrate_at = wall + BUDGET + 10 * 60_000
    shift = rehydrate_at - wall - BUDGET

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            result = await rehydrate(engine, now_ms=rehydrate_at)
            assert isinstance(result, RehydratedRun)
            spec, drink_ids = result.spec, result.drink_ids
            before = decode_state(EncodedState(**last["state"]), killed.drink_ids)

            # AC5: every anchor moved by exactly gap - budget; y and prices did not.
            (jump_before,) = before.jumps
            (jump_after,) = result.state.jumps
            assert (jump_after.t0_ms, jump_after.t1_ms) == (
                jump_before.t0_ms + shift,
                jump_before.t1_ms + shift,
            )
            assert np.array_equal(result.state.last_order_ts, before.last_order_ts + shift)
            assert result.state.last_idle_ms == before.last_idle_ms + shift
            assert result.state.last_bm_ms == before.last_bm_ms + shift
            assert result.state.y.tobytes() == before.y.tobytes()
            assert tick_prices(spec, result.state, drink_ids) == tick_prices(
                spec, before, drink_ids
            )
            assert result.state.version == before.version + 1
            _, _, ticks = await _rows(engine, killed.run_id)
            assert ticks[-1] == (before.version + 1, "gap")
            assert [v for v, _ in ticks] == list(range(before.version + 2))

            # AC6 per PD1: the first advance puts the jump at
            # (last commit - t0) + budget + (now - R), and it is still running.
            bm_interval = int(spec.params.bm_dt_minutes * 60_000)
            assert result.state.last_bm_ms + bm_interval > rehydrate_at + 5_000
            after = advance(
                spec, result.state, now_ms=rehydrate_at + 5_000, run_seed=result.run_seed
            ).state
            elapsed = (wall - jump_before.t0_ms) + BUDGET + 5_000
            assert elapsed < jump_before.t1_ms - jump_before.t0_ms
            expected = apply_jumps(spec, before, now_ms=jump_before.t0_ms + elapsed)
            assert after.y[JUMP_DRINK] == expected.y[JUMP_DRINK]
            assert [j.i for j in after.jumps] == [JUMP_DRINK]
        finally:
            await engine.dispose()

    asyncio.run(scenario())
