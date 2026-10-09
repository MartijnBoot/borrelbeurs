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
