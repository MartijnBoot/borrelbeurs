"""A draft run goes live inside the running process (Phase 6 SD1, SD3; PD11).

`go_live_in_process(state, run_id, author=...)`, where `state` is `app.state`:

1. **Refuse early** with `LiveRunExists` if the holder already holds a run, so
   nothing is written.
2. **Commit** with `go_live` (the CLI's transaction, `auto_calibrate_s0`
   included). Its refusals -- `run_not_found`, `run_not_draft`,
   `run_not_ready`, `live_run_exists` -- write nothing.
3. **Adopt**, under the state lock: the holder loads the committed run through
   `rehydrate`, the path boot uses, and reads its tick interval. A failure in
   either calls `on_diverged`.
4. **Then, with no await in between**, so no tick and no client can slip into
   the middle: the ticker re-anchors at the run's interval, the hub takes its
   replay window and clears its log, the publisher gets the run's candle book
   and drinks, `app.state.tick_interval_ms` is set, and every connected client
   is sent the run's `snapshot` and the theme catch-up.

The advisory-lock watchdog keeps its boot interval (plan R12).
"""

from __future__ import annotations

from typing import Any

from app.db.runs import LiveRunExists, go_live
from app.realtime.hub import Hub
from app.realtime.messages import Envelope, theme_data
from app.realtime.publish import Publisher, active_drink_ids, seeded_book, snapshot
from app.runtime.boot import run_tick_interval_ms
from app.runtime.clock import Clock
from app.runtime.holder import MarketHolder
from app.runtime.rehydrate import RehydratedRun, rehydrate
from app.runtime.ticker import Ticker


async def go_live_in_process(state: Any, run_id: int, *, author: str) -> None:
    """Make draft `run_id` live and hand it to the running runtime; see the module docstring."""
    holder: MarketHolder = state.holder
    clock: Clock = state.clock
    engine = holder.engine
    if not holder.is_empty:
        raise LiveRunExists(f"run {holder.run_id} is already live")

    await go_live(engine, run_id, now_ms=clock.wall_ms(), author=author)

    intervals: list[int] = []

    async def load() -> RehydratedRun:
        run = await rehydrate(engine, now_ms=clock.wall_ms())
        if not isinstance(run, RehydratedRun) or run.run_id != run_id:
            raise LookupError(f"run {run_id} was committed live but did not rehydrate")
        intervals.append(await run_tick_interval_ms(engine, run_id))
        return run

    await holder.adopt(load)
    interval_ms = intervals[0]

    # No await from here on: the runtime switches over in one step.
    assert holder.spec is not None and holder.state is not None
    ticker: Ticker = state.ticker
    hub: Hub = state.hub
    publisher: Publisher = state.publisher
    ticker.adopt_interval(interval_ms)
    hub.adopt_run(
        run_id, replay_window_ms=round(holder.spec.params.history_window_minutes * 60_000)
    )
    publisher.adopt(seeded_book(holder), active=active_drink_ids(holder))
    state.tick_interval_ms = interval_ms

    data = snapshot(holder, tick_interval_ms=interval_ms)
    assert data is not None
    now_ms = clock.wall_ms()
    hub.unicast_all(
        Envelope(
            type="snapshot",
            seq=0,
            ts_ms=now_ms,
            run_id=run_id,
            version=holder.state.version,
            data=data,
        )
    )
    hub.unicast_all(
        Envelope(
            type="theme",
            seq=0,
            ts_ms=now_ms,
            run_id=run_id,
            version=None,
            data=theme_data(state.theme),
        )
    )
