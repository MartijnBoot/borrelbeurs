# BorrelBeurs v2 — target architecture

Companion documents: [data-model.md](data-model.md),
[realtime-protocol.md](realtime-protocol.md),
[frontend-architecture.md](frontend-architecture.md).
Decisions are recorded in [../adr/](../adr/).

## The root cause this architecture addresses

One defect in v1 explains most of the others: **nothing owns time.**

The engine is its own clock (`exchange/engine.py:171,185,240,296,337,381`), so evolution
only happens when something calls it — which is why evolution got bolted onto the read path
(`backend/api.py:735-738`). Because reads mutate, the version token had to be cheap, so it
became a timestamp that does not track state; because the version does not track state, the
order path cannot be made correct.

Putting one explicit owner of time in place, and making the engine a pure function, is the
spine of the rebuild. Most of the rest follows from it.

## Shape

One Docker image, one Postgres. FastAPI serves the API, the WebSocket, and the built React
SPA from the same origin — no CORS, one artifact to promote, one thing to start on the event
laptop, and half the Render bill.

```
  big screen  ──┐
  bar phones  ──┤──  FastAPI (one container): /api/*  /ws  /  (SPA)  ──  Postgres
  admin       ──┘
```

The way-of-working reference architecture splits web and API into separate services because
Azure Container Apps makes that free. Render plus a party app does not.

**The API moves under `/api/*`.** This makes the SPA catch-all trivially safe instead of
requiring a hand-maintained allowlist against roughly twenty top-level paths. Nothing
external calls these endpoints — only the six pages being deleted.

## Module layout

```
exchange/                 PURE. No I/O, no clock, no logging.
  spec.py                 DrinkSpec, MarketSpec, Params, validation
  state.py                EngineState, PriceJump
  pricing.py              sigmoid/logit, prices_from_y, quantize, to_cents
  steps.py                apply_orders / apply_idle / apply_brownian / apply_jumps
  advance.py              advance(), next_due_ms()

app/
  runtime/                holder.py   single owner of spec + state + version + lock
                          ticker.py   fixed grid, gap detection, bounded catch-up
                          history.py  in-memory ring (a cache over price_tick)
  db/                     models, repositories, Alembic migrations
  realtime/               hub.py      per-connection queues, writer tasks, backpressure
                          messages.py Pydantic models — these ARE the protocol contract
  api/                    orders, config, drinks, news, market, auth, state, theme
  jobs/                   export_xlsx.py — the only blocking worker
  main.py                 boot: migrate, advisory lock, rehydrate, start ticker

web/                      Vite + React + TypeScript (see frontend-architecture.md)
```

## The engine: pure, with a reproducible noise stream

v1's `ExchangeState` holds config, simulation state, money, a chart buffer, scheduling
state, and a live RNG. Four of those five do not belong in a pricing model.

| New type | Contents |
|---|---|
| `MarketSpec` (frozen) | Per-drink bounds and coefficients, plus `Params`. Validated on construction: `p_min < p0 < p_max`, `step_quant` a positive multiple of 0.01 |
| `EngineState` (frozen) | `y`, `cum_orders`, `flow_ema`, `last_order_ts`, `jumps`, `rng_counter`, `version`, `tick_index`, `t_round` |
| — | **Money and history leave the package.** `totals_ordered` / `revenue_per_drink` become projections of `order_line`; `history` becomes the `price_tick` table plus a memory ring |

Steps are **non-mutating**: `advance(spec, state, *, now_ms, orders, rng) -> AdvanceResult`.
This is not stylistic. The order path computes a candidate state, commits it, and only then
publishes it; with v1's in-place `self.y = y_next` (`engine.py:227`) a failed commit leaves
memory and the database divergent with no way back.

**The RNG becomes counter-based.** v1 uses an unseeded, unpersisted `default_rng()`
(`engine.py:114`), so the noise stream is neither reproducible in tests nor continuous across
restart. Replace with `default_rng(SeedSequence([run_seed, rng_counter]))`, both durable.
This makes the whole price trajectory a pure function of
`(spec, initial_state, run_seed, ordered list of (now_ms, orders))` — which is what makes
golden-fixture testing possible at all.

**Wall-clock time enters in exactly one place:** the `now_ms` parameter. Enforced by a test
that walks the package's transitive imports and fails on `time`, `datetime`, `random`, `os`,
`asyncio`, `sqlalchemy`, `fastapi`. Five lines, and it permanently prevents the regression.

**Three counters, three questions.** `version` is state identity, bumped on every accepted
transition. `tick_index` drives the schedule grid. `rng_counter` drives the noise stream.
Conflating them is what produced v1's mess.

## Tick model

See [ADR 0003](../adr/0003-single-writer-owns-time.md). One ticker at 1 Hz on a fixed grid,
sleeping on monotonic time and stamping with wall time, with pricing effects firing on tick
multiples derived from the existing minute parameters. Gaps beyond a bounded budget
re-anchor the grid and write a gap marker rather than evolving.

Orders, jumps, config changes and drink changes advance state immediately and out of band —
they take the same lock and call the same pure functions, and they bump `version` but not
`tick_index`.

## Durability

| Class | Guarantee |
|---|---|
| Money and audit — orders, lines, news, config revisions, drink lifecycle, run lifecycle | Transactional, synchronous, exact, committed before the response |
| Price state — `y`, `cum_orders`, `flow_ema`, jumps, `rng_counter`, counters | At most one tick of loss |

One transaction per tick: UPSERT `engine_state` + INSERT `price_tick`. At 1 Hz a four-hour
borrel is ~14k tick rows, which Postgres does not notice.

One transaction per order, **atomic together**: order + lines + engine state + price tick.
You must not be able to charge a customer and lose the price move it caused, or move the
price and lose the sale.

> Acceptance criterion: *a hard kill loses at most one tick of Brownian drift and zero orders.*

**Boot sequence.** Migrate → acquire advisory lock → load the live run → rebuild spec and
state **keyed by `drink_id`, not positional arrays** → load the history window into the ring
→ recompute earnings with one `GROUP BY` → apply the gap rule → insert a `gap` tick so the
chart draws a break rather than a fake straight line.

This is the fix for v1's worst defect: `to_persist()` (`engine.py:139-150`) stores only
static config and `from_persist` routes through `init`, so every restart recomputes `y` from
`p0` — every price snaps back to its starting value and the history is gone.

**The in-memory history ring stays**, demoted to a derived cache so broadcasts do not hit
Postgres on the hot path. One change: v1's `_append_hist` (`engine.py:370-375`) deduplicates
consecutive identical display prices. Keep that for *rendering*, but write **every** tick to
`price_tick` — the dedupe costs an honest time axis, and it has a live consequence in v1
(`bar.html:356` falls back to `history[last].ts` as its version token, which therefore
freezes during a flat period).

## Order path

Six defects fixed together. See [ADR 0008](../adr/0008-honour-the-quoted-price.md) for the
pricing policy.

| # | Defect in v1 | Fix |
|---|---|---|
| 1 | Stale check runs before the lock (`api.py:312` vs `:320`) | Take the lock first, before reading anything |
| 2 | `snapshot_version` is a timestamp that does not track price | int64 `version`, bumped on every accepted transition |
| 3 | No idempotency — a retry double-charges and double-moves the price | `Idempotency-Key`, unique index, replay returns the stored receipt |
| 4 | Charged price comes from `LAST_SNAPSHOT`, written by the broadcast loop | Delete `LAST_SNAPSHOT`; compute inside the lock, return what was charged |
| 5 | Response reads `t_round` and version *after* the lock is released (`api.py:365-368`) | Build the receipt inside the lock |
| 6 | Money as floats (`api.py:349`, `persistence.py:117`) | Integer cents everywhere past the engine boundary |

**The database transaction sits inside the state lock.** This deliberately violates the usual
"never hold a lock across I/O" rule. If the transaction were outside, two orders could commit
out of order relative to their version numbers and `price_tick` would stop being a coherent
sequence. The rule becomes: *inside the lock, pure numpy plus exactly one short database
transaction, nothing else, ever* — instrumented with a warning above 50 ms hold time, and
that warning treated as a bug.

**Two quantisation tracks.** The tradeable price sits on the `step_quant` grid (0.1 live);
display is quantised to 0.01 for the candle chart. Charging must use the `step_quant` track.
This is an assertion in code, not a convention.

## Non-destructive drink add and remove

v1's `POST /drinks` (`api.py:599-643`) rebuilds the entire `ExchangeState`, resetting every
price to `p0` and wiping history, totals, revenue and active jumps for *all* drinks
mid-event. It also rotates the earnings workbook, splitting one event's revenue across two
files.

**Add** appends a slot; only the new drink's `y` is initialised and every existing value is
bitwise unchanged. **Remove** is a soft delete — the slot stays, masked via
`DrinkSpec.active` — so its order lines and revenue stay in the ledger, which is what you
want, because people already bought them. Re-adding creates a new `drink_id`.

**One consequence must be explicit.** `single_step` computes `others_avg_dev` over `N-1`
(`engine.py:199`) and `p_mean` over all drinks (`engine.py:168`). Removed slots must be
excluded from both, so `N` ranges over *active* slots only. That is technically a change to
the maths — but only in the presence of a removal, which is impossible in v1 without a full
reset, so there is no existing behaviour to preserve. Under the live config the blast radius
is only the `N-1` denominator, because `p_mean` feeds terms that are currently zero.

## Authorization

`auth_key` rows with argon2 hashes replace plaintext `keys.json`. Two practical consequences
that "hash the keys" hides:

- Argon2 blocks for 50–100 ms by design, which stalls the event loop. `verify` runs in a
  thread.
- You can no longer look a key up by value. A naive implementation iterates every key at
  100 ms each per login attempt. Keys are issued as `bb_<key_id>_<secret>`: look up by
  `key_id`, verify once.
- Rate-limit login **before** hashing, or the hash cost is itself the denial-of-service.

**Every route carries an explicit authorization dependency, and the WebSocket handshake
carries a role check.** This is task one, not a later hardening pass: with an SPA there are
no per-page HTML routes left to gate, so v1's page-level RBAC would become literally nothing.
`ROLE_PAGES` stops being duplicated in `auth.py:25-29` and in four page scripts — `/auth/me`
returns the allowed routes and the client reads that one list.

`JWT_SECRET` becomes required, failing fast at boot. The cookie gains `Secure`. The separate
`ADMIN_TOKEN` mechanism folds into the JWT session, so there is one auth system rather than
two.

## Where blocking I/O goes

v1 runs every file operation synchronously inside async handlers, mostly under the lock:
`load_workbook` + `save` **per line item**, a full xlsx re-parse and re-aggregate on **every
payload build**, `atomic_write_json` with `fsync` per mutation, and a `news.json` re-read per
broadcast.

1. **asyncpg** (via SQLAlchemy 2.0 async). Awaitable; no thread pool on the main path.
2. **Nothing on the hot path touches the filesystem.** Earnings are an in-memory aggregate
   rehydrated by one `GROUP BY` at boot; news is an in-memory list; history is the ring.
3. **Genuinely blocking work goes to one background worker** — and that means the xlsx
   export, and only the xlsx export. Modelled as a job with a coalescing depth-1 queue, run
   inside `asyncio.to_thread`, so at most one runs at a time and the caller returns
   immediately with a spinner instead of a frozen server.
4. Static SPA assets are served with hashed filenames and `immutable` cache headers;
   `index.html` is `no-store`. This removes v1's per-request `sha1` and logo `listdir`.
