"""A market process to kill: imports the live config, goes live, plays a script (T15).

    python -m tests.integration.durability.harness --start-ms <t> --script <name>
        [--hold-in-tx <n> [--hold-statement <m>]] [--pause-after <k>]

The database is whatever `DATABASE_URL` says, read through `get_settings()`.
The clock is fake: step `s` of a script runs at `start_ms + s * 1000`, so the
engine never sees wall-clock time. Each step computes its transition with the
pure engine, commits it with `save_transition` or `write_order`, and only then
updates the in-memory ring and earnings (SD11). Version `v` is step `v`'s
transition; go-live is version 0.

stdout carries one JSON object per line, flushed as written:

- `{"kind": "ready", "run_id", "run_seed", "drink_ids"}` once, before go-live;
- `{"kind": "reset" | "tick" | "jump" | "order", "version", "wall_ts_ms",
  "orders_committed", "state"}` after every commit, `state` being the codec's
  encoded columns;
- `{"kind": "in_tx", "version"}` with `--hold-in-tx n`: printed by a
  harness-only `after_cursor_execute` listener after the first statement of
  version `n`'s transaction (the `m`th with `--hold-statement m`), which then
  sleeps inside it until killed;
- `{"kind": "paused", "version"}` with `--pause-after k`: printed after version
  `k`'s commit line, then the process sleeps outside any transaction;
- `{"kind": "done"}` when the script ends.

`SCRIPTS` and `transition` are shared with the test, which replays the same
script purely to check the rehydrated state's next `advance`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import io
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from sqlalchemy import event, select

from app.cli.import_v1 import main as import_v1
from app.core.config import get_settings
from app.db.codec import encode_state, tick_prices
from app.db.engine_state import save_transition
from app.db.mapping import cents_from_quantised, spec_from_rows
from app.db.models import Run
from app.db.orders import OrderLineInput, write_order
from app.db.runs import active_drinks, go_live
from app.db.session import create_engine
from app.runtime.earnings import EarningsAggregate
from app.runtime.history import HistoryRing, TickEntry
from exchange import EngineState, MarketSpec, Params, advance, schedule_jump

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_CONFIG_PATH = REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json"
STEP_MS = 1_000
JUMP_DRINK = 2
JUMP_MS = 120_000
HOLD_SECONDS = 3_600


@dataclass(frozen=True)
class Step:
    """One scripted transition, at `start_ms + second * STEP_MS`. `qtys` is by slot."""

    second: int
    kind: Literal["tick", "jump", "order"]
    qtys: tuple[tuple[int, int], ...] = ()


def _standard() -> tuple[Step, ...]:
    """Thirty seconds at 1 Hz: an order every fourth second, a 120 s jump at ten."""
    steps = []
    for second in range(1, 31):
        if second == 10:
            steps.append(Step(second, "jump"))
        elif second % 4 == 0:
            slot = (second // 4) % 6
            steps.append(Step(second, "order", ((slot, 2), ((slot + 3) % 6, 1))))
        else:
            steps.append(Step(second, "tick"))
    return tuple(steps)


SCRIPTS: dict[str, tuple[Step, ...]] = {"standard": _standard()}


def transition(
    spec: MarketSpec, state: EngineState, step: Step, *, start_ms: int, run_seed: int
) -> EngineState:
    """The pure engine's next state for `step`; no clock, no I/O."""
    now_ms = start_ms + step.second * STEP_MS
    if step.kind == "jump":
        return schedule_jump(
            spec, state, drink=JUMP_DRINK, p_target=6.5, duration_ms=JUMP_MS, now_ms=now_ms
        )
    orders = None
    if step.kind == "order":
        orders = np.zeros(len(spec.names))
        for slot, qty in step.qtys:
            orders[slot] = qty
    return advance(spec, state, now_ms=now_ms, orders=orders, run_seed=run_seed).state


def _emit(line: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(line) + "\n")
    sys.stdout.flush()


def import_live_config() -> int:
    """Import the live v1 config through the CLI and return the new draft run's id."""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        status = import_v1(["--config", str(LIVE_CONFIG_PATH)])
    if status != 0:
        raise SystemExit(f"import_v1 exited {status}")
    return int(captured.getvalue().strip())


async def play(
    *,
    run_id: int,
    start_ms: int,
    script: str,
    hold_in_tx: int | None,
    hold_statement: int,
    pause_after: int | None,
) -> None:
    engine = create_engine(get_settings())
    current = {"version": 0, "statements": 0}

    def hold(*_: Any) -> None:
        if current["version"] != hold_in_tx:
            return
        current["statements"] += 1
        if current["statements"] == hold_statement:
            _emit({"kind": "in_tx", "version": hold_in_tx})
            time.sleep(HOLD_SECONDS)

    if hold_in_tx is not None:
        event.listen(engine.sync_engine, "after_cursor_execute", hold)

    async with engine.connect() as conn:
        drinks = await active_drinks(conn, run_id)
        run = (
            await conn.execute(select(Run.run_seed, Run.params).where(Run.run_id == run_id))
        ).one()
    run_seed, params = int(run.run_seed), Params.from_dict(run.params)
    spec, drink_ids = spec_from_rows(drinks, params)
    _emit({"kind": "ready", "run_id": run_id, "run_seed": run_seed, "drink_ids": drink_ids})

    ring = HistoryRing(round(params.history_window_minutes * 60_000))
    earnings = EarningsAggregate()
    orders_committed = 0

    def committed(kind: str, state: EngineState, wall_ts_ms: int) -> None:
        ring.append(TickEntry(state.version, wall_ts_ms, kind, tick_prices(spec, state, drink_ids)))
        _emit(
            {
                "kind": kind,
                "version": state.version,
                "wall_ts_ms": wall_ts_ms,
                "orders_committed": orders_committed,
                "state": dataclasses.asdict(encode_state(state, drink_ids)),
            }
        )
        if state.version == pause_after:
            _emit({"kind": "paused", "version": pause_after})
            time.sleep(HOLD_SECONDS)

    state = await go_live(engine, run_id, now_ms=start_ms)
    committed("reset", state, start_ms)

    for step in SCRIPTS[script]:
        wall_ts_ms = start_ms + step.second * STEP_MS
        candidate = transition(spec, state, step, start_ms=start_ms, run_seed=run_seed)
        current["version"] = candidate.version
        if step.kind == "order":
            prices = tick_prices(spec, state, drink_ids)
            lines = [
                OrderLineInput(
                    drink_id=drink_ids[slot],
                    qty=qty,
                    unit_price_cents=cents_from_quantised(prices[drink_ids[slot]]["p_q"]),
                    p_cont=prices[drink_ids[slot]]["p_cont"],
                )
                for slot, qty in step.qtys
            ]
            await write_order(
                engine,
                run_id=run_id,
                idempotency_key=f"harness-{run_id}-{candidate.version}",
                expected_version=state.version,
                state=candidate,
                spec=spec,
                drink_ids=drink_ids,
                lines=lines,
                wall_ts_ms=wall_ts_ms,
            )
            orders_committed += 1
            earnings.add_lines((ln.drink_id, ln.qty, ln.qty * ln.unit_price_cents) for ln in lines)
        else:
            await save_transition(
                engine,
                run_id=run_id,
                expected_version=state.version,
                state=candidate,
                spec=spec,
                drink_ids=drink_ids,
                source=step.kind,
                wall_ts_ms=wall_ts_ms,
            )
        state = candidate
        committed(step.kind, state, wall_ts_ms)

    await engine.dispose()
    _emit({"kind": "done"})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.integration.durability.harness")
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--script", choices=sorted(SCRIPTS), required=True)
    parser.add_argument("--hold-in-tx", type=int, help="sleep inside version N's transaction")
    parser.add_argument(
        "--hold-statement", type=int, default=1, help="... after its Mth statement (default 1)"
    )
    parser.add_argument("--pause-after", type=int, help="sleep after version K's commit")
    args = parser.parse_args(argv)
    run_id = import_live_config()  # before the loop: the CLI runs its own
    asyncio.run(
        play(
            run_id=run_id,
            start_ms=args.start_ms,
            script=args.script,
            hold_in_tx=args.hold_in_tx,
            hold_statement=args.hold_statement,
            pause_after=args.pause_after,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
