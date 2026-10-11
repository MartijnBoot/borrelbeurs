# ADR 0003: One process owns time; one writer, enforced by an advisory lock

Date: 2026-09-12 · Status: Accepted

## Context

v1 has no tick thread. All time evolution happens lazily inside the payload builder
(`backend/api.py:735-738`), invoked from the broadcast loop, `GET /state`, `POST /order`,
and six other routes. The engine is its own clock (`exchange/engine.py:171,185,240,296`).

This is the root cause of most of v1's defects. Because evolution is on the read path,
`GET /state` mutates and persists; because reads mutate, the version token had to be cheap
and became a timestamp that does not track state; because the version does not track state,
the order path cannot be made correct. A connected browser can also force an engine advance
by sending the string `"state"` over the WebSocket (`api.py:864`).

## Decision

1. One `asyncio.Task` — the ticker — is the only thing that advances time on a schedule. It
   runs on a fixed grid at **1 Hz**, with pricing effects firing on tick multiples derived
   from the existing minute parameters.
2. The ticker **sleeps on monotonic time and stamps with wall time.**
3. Gaps are caught up to a bounded wall-clock budget (~30 s), then the grid is re-anchored,
   a gap marker is written, and time does **not** evolve across the gap.
4. Horizontal scale is not a goal. Boot takes a Postgres `pg_try_advisory_lock` and fails
   fast and loudly if it cannot acquire it.
5. Advance-on-read is removed entirely. `GET /state` becomes a pure read.

## Why the advisory lock, given a single replica

Single-replica is an *intent*, not a runtime guarantee. **Render starts the new instance
before draining the old one on every deploy.** Without the lock, the first mid-event deploy
runs two tickers against one `engine_state` row, each with its own noise stream.

## Why bounded catch-up rather than replay or a single large step

A closed laptop lid produces a large clock gap. Three options:

| Behaviour | Result | Verdict |
|---|---|---|
| Replay every missed tick | Twenty minutes of random walk lands instantly; a drink can be stranded at `p_max` | Rejected — price movement nobody witnessed |
| One step with `dt` = the whole gap | A single ~4.5σ jump | Rejected — same problem, compressed |
| **Clamp: pause, re-anchor, mark the gap** | Prices resume where they were | **Accepted** |

The justification is domain, not engineering: this is a party game. Time during which
nobody is buying and no screen is showing is time in which the market did not exist.

**Note on the status quo.** v1's Brownian noise is *not* elapsed-time-scaled —
`engine.py:297-301` computes `dt_min` from the configured `bm_dt_minutes`, never from actual
elapsed time — so today a gap makes prices **freeze**, not jump. Moving to real elapsed-`dt`
would therefore make gaps strictly *worse* than v1 unless clamped. This is the main
technical argument for the clamp, beyond the domain one.

**Note on a small backward step (Phase 4 SD30).** A tick is stamped
`max(grid slot, last commit's wall time)`, so stamps never go back and a candle is never
reopened. The flip side: a wall clock that steps back by *less* than the catch-up budget
(30 s) is not treated as a gap. Instead every tick is held at the last commit's time until
the grid passes it again, and prices freeze for up to the budget meanwhile. A step back
beyond the budget is a gap and re-anchors as above. This is a deliberate trade, documented
in `Ticker._tick_step`, and does not change the decision.

## Consequences

- Pricing cadence and display cadence are separated. This is what lets the client stop
  synthesising fake candles (see [ADR 0005](0005-server-side-bucketing-and-theming.md)).
- Brownian timing loses up to 12 s of jitter relative to v1. This is a deliberate,
  tested change, not a silent one.
- A dead ticker means frozen prices and a ruined event, so `/healthz` reports
  `last_tick_age_ms` and goes unhealthy past three intervals.
- The app cannot be scaled out without revisiting this ADR. That is intended.

## Addendum (Phase 6, SD3)

Date: 2026-10-08

The single writer can now adopt a run mid-process. Until Phase 6 the process found its live
run once, at boot; `POST /api/runs/{run_id}/go-live` makes a draft live while the app runs,
without a restart (`app/runtime/golive.py`).

Nothing in the decision changes: there is still one process, holding the advisory lock, and
still one writer. Go-live commits the run's status first, in the same transaction the CLI
uses, and refuses — writing nothing — while another run is live. Only then does the holder
load the committed run, **under the state lock**, through the same rehydrate path boot
uses. The ticker, the hub and the publisher then switch over with no `await` in between, so
no tick and no client can observe a half-adopted run. The hub clears its replay log, so
every client receives the new run's snapshot.

The advisory lock is held from boot and is unchanged. `app.cli.runs go-live` remains for
when the app is down; while the app runs it is refused, because the app holds the lock.

## Addendum (Phase 7, SD2, PD4)

Date: 2026-10-10

The single writer can now release its run mid-process: `POST /api/runs/{run_id}/close`
ends the live run without a restart (`app/runtime/close.py`). It is go-live in reverse.

Nothing in the decision changes. The close is refused, with nothing written, unless this
process holds the run live and the admin typed its name. Then the holder takes the **state
lock** and runs one transaction: the run becomes `ended` at the app clock (never before the
last commit, so no order of the run is stamped after its end), its open market events end,
and its final export is queued. Only after that commit does the holder hold no run. A failed
commit changes no memory. An order waiting on the lock finds no run and is refused with 409
`no_live_run`, so an order either commits before the close or not at all.

With no `await` after the release, the publisher drops the run's candles and drinks, and
the hub clears its replay log and sends every client `run_closed`. The ticker idles on its
grid, as it does at boot with no live run. The export worker is woken for the final export;
it builds in a separate process and writes its result on the main engine, outside the
state lock.

Shutdown is not close: "Sluit app" leaves the run `live`, and the next boot rehydrates it
with the gap rule (SD14).

## Addendum (Phase 8, SD4, SD15)

Date: 2026-10-11

**Decision 4 now reads "waits in standby".** A booting instance that cannot take the advisory
lock no longer exits. It serves `/healthz` (200, `status: standby`) and answers `/readyz` and
`/api/*` with 503 `standby`, closes a WebSocket with 1013, retries the lock every second, and
logs `lock_wait` on entry and every 30 s. Once it holds the lock it boots as before: migrate,
rehydrate, tick. The reason is Render's overlap on a deploy (see "Why the advisory lock"): the
new instance used to exit and be restarted by the platform; now it waits for the old one to go.
`/healthz` could not answer at all while the lifespan retried, because uvicorn binds no socket
until the lifespan yields, so the wait runs in a task after the lifespan has yielded.

Single-writer holds, because **a standby never writes**: it holds no run, runs no ticker, no
export worker and no migration, and the lock is still the only path to any of them. A boot
failure after standby (a failed migration, `schema ahead of image`) is logged `boot_failed` and
exits 3, the code uvicorn uses for a startup failure. A lost lock still exits 70. A database
that is unreachable is not standby: it fails as before, exit 3.

**The app clock.** Every runtime and API caller shares one `AppClock` (`app/runtime/clock.py`)
that wraps the system clock: `wall_ms()` is the system wall time plus an offset, and
`raise_to(t)` only ever raises that offset. Every commit stamps `max(app_now, last_commit)`
(`commit_stamp_ms`), so stamps never go back, whatever the system clock does.

**A backward step beyond the budget is an offset plus a zero-shift gap.** Within the ~30 s
catch-up budget the ticker holds stamps at the last commit, as decision 3 says. When the wall
clock is further behind the last commit than the budget, the ticker raises the offset so its
time continues from the last commit, writes one `gap` tick with the same prices and no anchor
shift (no time evolved), logs `clock_stepped_back`, and re-anchors, so prices keep evolving at
the interval instead of freezing for the size of the step. At boot, a wall clock behind the
stored last commit by any amount raises the offset to it and writes no gap. The offset is not
persisted: each boot recomputes it from the last commit. It never shrinks while the process
runs, so a clock set back by an hour costs that hour of offset until the next restart.
