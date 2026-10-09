"""The live run is closed inside the running process (Phase 7 SD2; PD3, PD4).

The mirror of `golive.py`. `close_in_process(state, run_id, confirm_name=...,
author=...)`, where `state` is `app.state`:

1. **Refuse early**, from a read, with nothing written: 404 `run_not_found`;
   409 `run_not_live` for a draft, an ended run, or a run this process does
   not hold; 422 `name_mismatch` unless the typed name, trimmed, is the run's
   name exactly (PD3: case-sensitive).
2. **Release**, under the state lock: one transaction ends the run on the app
   clock, ends its open market events and queues the final export
   (`close_run`), then the holder holds no run. A failed commit changes no
   memory (`holder.release`). An order queued behind the lock finds no run
   and is 409 `no_live_run` (SD16).
3. **Then, with no await in between**, so no client sees a half-closed market:
   the hub clears its replay log, the publisher drops the run's candles and
   drinks, and every connected client is sent `run_closed`. The ticker idles
   on its grid; `app.state.tick_interval_ms` is kept.
"""

from __future__ import annotations

from typing import Any

from app.db.runs import NameMismatch, RunNotLive, RunSummary, close_run, get_run
from app.realtime.hub import Hub
from app.realtime.messages import Envelope, RunClosedData
from app.realtime.publish import Publisher
from app.runtime.candles import CandleBook
from app.runtime.clock import Clock
from app.runtime.holder import MarketHolder, MarketView, NoLiveRunError


async def close_in_process(
    state: Any, run_id: int, *, confirm_name: str, author: str
) -> RunSummary:
    """Close live `run_id` and unload it from the running runtime; see the module docstring."""
    holder: MarketHolder = state.holder
    clock: Clock = state.clock

    async with holder.engine.connect() as conn:
        run = await get_run(conn, run_id)
    if run.status != "live" or holder.run_id != run_id:
        raise RunNotLive(f"run {run_id} is {run.status}, and not live in this process")
    if confirm_name.strip() != run.name:
        raise NameMismatch(f"the typed name is not run {run_id}'s name")

    async def step(view: MarketView) -> int:
        if view.run_id != run_id:
            raise RunNotLive(f"run {run_id} is no longer live in this process")
        # Never before the last commit, so every order of the run is at or before it.
        ended_at_ms = max(clock.wall_ms(), view.last_commit_wall_ms or 0)
        async with holder.engine.begin() as conn:
            await close_run(conn, run_id, ended_at_ms=ended_at_ms, requested_by=author)
        return ended_at_ms

    try:
        ended_at_ms = await holder.release(step)
    except NoLiveRunError as error:
        raise RunNotLive(f"run {run_id} is no longer live in this process") from error

    # No await from here on: every client learns of the close in one step.
    hub: Hub = state.hub
    publisher: Publisher = state.publisher
    hub.release_run()
    publisher.adopt(CandleBook(holder.candle_interval_ms), active=())
    hub.broadcast(
        Envelope(
            type="run_closed",
            seq=0,  # the hub stamps the real one
            ts_ms=clock.wall_ms(),
            run_id=run_id,
            version=None,
            data=RunClosedData(run_id=run_id, name=run.name, ended_at_ms=ended_at_ms),
        )
    )
    return RunSummary(run_id=run_id, name=run.name, status="ended")
