# Spec: Phase 2 — Data model and persistence

Status: Approved · Depends on: Phase 0, Phase 1 · Fixes: D-01, D-09, D-10, D-11, D-12, D-16, D-24, D-30, D-35

## Problem

v1 persists only static config. `to_persist()` writes names, bounds, coefficients and params
(`tests/engine/v1_reference/engine.py:139-150`, v1's engine verbatim) and `from_persist`
routes back through `init` (`:153`), so **every restart snaps every price back to `p0`** and
loses `y`, `cum_orders`, `flow_ema`, active jumps and the history deque (`:129`, `:370-383`).

Money is worse:

- Revenue is accumulated as floats in memory (`legacy/v1/backend/api.py:379`) and as floats
  in an xlsx (`legacy/v1/backend/persistence.py:111-120`) — two sources that disagree after
  any restart or drink change (`api.py:326` vs `:317`, zeroed at `:542`).
- The workbook is `load_workbook` → `append` → `save`d **per line item**, unlocked
  (`persistence.py:113-120`), and re-read and re-aggregated on every payload build
  (`persistence.py:126-190` via `api.py:317,324,331`) — synchronous file I/O inside async
  handlers.
- Bar prices live in a name-keyed sidecar (`api.py:167-198`) because the first engine save
  after boot drops the `bar_price` key from `exchange_config.json`
  (`persistence.py:70-71` vs `:76-77`).
- Drink identity is array position. Nothing rejects a duplicate name, which silently corrupts
  every name→index map (`api.py:595-646`, `api.py:180`).
- News levels are written capitalised (`legacy/v1/static/manipulation.html:143-146`,
  `api.py:494-500`) while the display keys its CSS on lowercase.

## Decisions

Settled at the spec interview (2026-10-01); the planner must not reopen them.

- **SD1 — Durability is proven against a harness, not the app.** Phase 2 has no ticker and
  no routes. The durability test drives the pure engine plus the Phase 2 repositories from a
  subprocess, SIGKILLs it mid-stream, and rehydrates in a fresh process. Phase 3 repeats it
  as a `docker kill` of the real app.
- **SD2 — The boot gap rule shifts every wall-clock anchor.** Let `gap = now_ms −
  engine_state.wall_ts_ms` and `budget` = the catch-up budget (30 000 ms default, ADR 0003,
  a parameter — not a literal in the function). If `gap ≤ budget`, rehydrate changes nothing
  and writes nothing; catching up is Phase 3's ticker. If `gap > budget`, every wall-clock
  anchor in `EngineState` — `last_order_ts` (every drink), `last_idle_ms`, `last_bm_ms`, and
  each jump's `t0_ms` and `t1_ms` — moves forward by `gap − budget`. An interrupted jump
  therefore plays out its remaining time after boot. No price moves.
- **SD3 — No access-key import.** v1's keys are leaked (D-42) and argon2 and the key format
  belong to Phase 3, which mints fresh keys.
- **SD4 — Eight tables, not thirteen.** Phase 2 creates only what it exercises: `run`,
  `run_config_revision`, `drink`, `engine_state`, `price_tick`, `order`, `order_line`,
  `news`. `auth_key` and `market_event` come with Phase 3, `theme` and `asset` with the
  phases that design them, each in its own migration.
- **SD5 — No earnings-workbook import.** The import script loads configuration, bar prices
  and news. Past workbooks stay files; bringing historical money into the database, if
  wanted, is Phase 7's decision. No `openpyxl` dependency in this phase.
- **SD6 — At most one live run, enforced by the database** (a partial unique index on
  `run.status = 'live'`). The import creates a **new `draft` run on every invocation**, never
  touches an existing run, and never makes a run live. A repository transition
  `draft → live` writes the initial `engine_state` (`exchange.state.initial_state`) and a
  `reset` price tick in one transaction; ending a run is Phase 7.
- **SD7 — Euro inputs convert exactly or not at all.** A euro value from any v1 file is
  converted via `Decimal(str(value))`; if it is not a whole number of cents the import fails,
  naming the drink and field. A quantised engine price converts as `round(p_q * 100)`, which
  is exact because `step_quant` is a multiple of 0.01 (Phase 1 AC5).
- **SD8 — `engine_state` stores per-drink values as JSON objects keyed by `drink_id`**,
  including `last_order_ts`; jumps are stored with `drink_id`, not index. `last_idle_ms` and
  `last_bm_ms` are persisted too — `docs/design/data-model.md` omits them and is updated in
  this phase. Floats must round-trip bit-exact.
- **SD9 — The `engine_state` write is compare-and-set on `version`.** The UPSERT applies only
  when the stored version equals the one the caller read; otherwise the whole transaction
  rolls back and a typed stale-state error is raised. Defence in depth under Phase 3's lock,
  and the thing that makes concurrent writers safe before that lock exists.
- **SD10 — `price_tick.prices` is `{drink_id: {"p_cont": float, "p_q": float}}`**, one row
  per accepted transition, never deduplicated. The display track and its dedupe (D-28) are
  Phase 3.
- **SD11 — The history ring holds committed ticks only**, spans `params.history_window_minutes`
  of wall time, is loaded from `price_tick` at boot ordered by `version`, and is appended to
  only after the transaction commits.
- **SD12 — The earnings aggregate is per `drink_id`: `qty` and `revenue_cents`.**
  `bar_price_total` and its D-20 correction are Phase 7. Rebuilt by one `GROUP BY` at boot,
  updated in memory after each committed order.
- **SD13 — `news.level` is one of `info`, `success`, `warning`, `danger`**, enforced by a
  CHECK constraint. v2's database has no historical rows to migrate, so D-16's "normalise
  historical values" is met at the only place historical values enter: the import lowercases
  them, and rejects an unknown level.
- **SD14 — Drink names are unique per run among non-removed drinks, compared trimmed and
  case-insensitively** (`Bier` and ` bier` collide). A removed drink's name may be reused.
- **SD15 — The import is one transaction.** Inputs are passed as CLI arguments (`--config`,
  optional `--news`, optional `--bar-prices`), validated with pydantic before anything is
  written, and any failure writes nothing. The DSN comes from `app/core/config.py` like
  everything else. Bar-price precedence is v1's (`api.py:167-190`): the config's `bar_price`
  key, then `bar_prices.json`, else `p0`.
- **SD16 — Integration tests run against the compose `db`**, as Phase 0 settled
  (`tests/conftest.py:5-12`), not testcontainers.

## In scope

- Alembic migrations, forward-only, chained from `0001`, creating the eight tables of SD4 with
  their constraints: integer-cents money columns, `order.idempotency_key` UNIQUE, the
  single-live-run index (SD6), the drink-name index (SD14), the news-level CHECK (SD13).
- SQLAlchemy 2.0 async models and a repository layer over asyncpg:
  run create/go-live; drink add (with the name check) and `set_bar_price`; engine-state load
  and compare-and-set save with its price tick; the atomic order write (order + lines +
  engine state + price tick); news create/list; config-revision append; the earnings
  `GROUP BY`.
- Mapping between `drink_id`-keyed rows and the engine's positional `MarketSpec` /
  `EngineState`, by active drinks ordered by `slot`.
- The pure gap function of SD2, and a `rehydrate` that loads the live run, rebuilds spec and
  state, fills the history ring and the earnings aggregate and the news list, applies the gap
  rule, and writes the `gap` tick — in that order (architecture.md, Boot sequence, minus the
  advisory lock, which is Phase 3 AC18).
- The import CLI of SD15, against `legacy/v1/config/exchange_config.json` and
  `legacy/v1/static/news.json`.
- The durability harness of SD1.
- Updating `docs/design/data-model.md` to match SD4, SD8 and SD10.

## Out of scope

- HTTP routes, the ticker and running catch-up, WebSocket/realtime, any UI.
- The advisory lock and boot-time migration wiring (Phase 3 AC18, ADR 0011).
- The order **behaviour**: quoted-price grace, 409s, idempotent replay of a stored receipt
  (Phase 3). Phase 2 provides only the UNIQUE constraint and the atomic write.
- `auth_key`, `market_event`, `theme`, `asset` (SD4); key import (SD3).
- Earnings-workbook import and xlsx export (SD5, Phase 7).
- Run end, run comparison, `bar_price_total` / D-20 (Phase 7).
- Adding or removing drinks mid-run without a reset (D-02, Phase 6); any admin editing of
  params beyond what the tests need.
- The display price track and history dedupe for rendering (D-28, Phase 3).
- `pg_dump` backups (Phase 8).
- Any change to pricing behaviour. Golden fixtures stay green.

## Acceptance criteria

**Durability**

- **AC1.** When the harness process is SIGKILLed mid-stream and a fresh process rehydrates,
  the system shall restore `y`, `cum_orders`, `flow_ema`, `last_order_ts`, active jumps,
  `last_idle_ms`, `last_bm_ms`, `rng_counter`, `version`, `tick_index` and `t_round` equal to
  the last committed `engine_state`, and the count of `order` rows shall equal the count of
  orders the harness saw committed. *(D-01)*
- **AC2.** When an order transaction fails at any point (injected after each statement), the
  system shall leave no `order`, no `order_line`, no `engine_state` change and no
  `price_tick` from it.
- **AC3.** When engine state is saved and loaded, every float shall round-trip bit-exact, and
  `advance()` from the loaded state shall produce the same result as from the saved one.

**Gap rule**

- **AC4.** When rehydrating with `gap ≤ budget`, the system shall return the state unchanged
  and write nothing.
- **AC5.** When rehydrating with `gap > budget`, the system shall shift every anchor listed in
  SD2 forward by exactly `gap − budget`, leave `y` and every price unchanged, and write one
  `price_tick` with `source = 'gap'` and the next `version`, in the same transaction as the
  `engine_state` update.
- **AC6.** When a jump was in flight at the kill and `gap > budget`, the first `advance()`
  after rehydrate shall produce the price the jump would have had at
  `(kill time − t0) + (now − rehydrate time)` into its duration — no jump completes during the
  gap.
- **AC7.** When there is no live run, rehydrate shall return "no live run", write nothing and
  not raise.
- **AC8.** If the live run's `engine_state` keys do not match its active drinks exactly, then
  rehydrate shall fail with an error naming the mismatched `drink_id`s and write nothing.

**Money**

- **AC9.** While any euro amount is stored, the system shall store it as an integer number of
  cents. A test shall inspect the migrated schema and fail if any money column is not an
  integer type. *(D-09)*
- **AC10.** When the import meets a euro value that is not a whole number of cents, it shall
  fail naming the drink and field, and write nothing. *(D-09)*
- **AC11.** When revenue is queried, the system shall derive it only from `order_line`; a test
  shall assert no other table or column stores revenue, and that the boot `GROUP BY` equals
  the sum of `line_total_cents` per `drink_id`. *(D-10)*
- **AC12.** When `bar_price` is set via `set_bar_price` and engine state is subsequently saved
  any number of times and rehydrated, the system shall return the set bar price. *(D-11)*
- **AC13.** When two order transactions run concurrently, every committed order shall be
  present with all its lines afterwards; a transaction that loses the version race shall roll
  back entirely and raise the stale-state error, never commit partially or overwrite.
  *(D-12)*

**Identity**

- **AC14.** When per-drink state, prices or order lines are persisted, the system shall key
  them by `drink_id`; a test shall reorder drink slots between save and load and assert every
  drink keeps its own values. *(D-24)*
- **AC15.** When a drink is added to a run whose non-removed drinks already have that name
  (trimmed, case-insensitive), the system shall reject it; a removed drink's name shall be
  accepted. *(D-24)*

**News**

- **AC16.** When news is imported or created, the system shall store `level` lowercase; the
  import shall map v1's `Info`/`Success`/`Warning`/`Danger` to lowercase and reject any other
  value; the database shall reject a non-conforming level written directly. *(D-16)*

**No file I/O on the read path**

- **AC17.** When the earnings aggregate, the news list or the history window is read after
  rehydrate, the system shall serve it from memory, performing no file I/O and no database
  query. A test shall assert both. *(D-30)*
- **AC18.** While the repository layer and rehydrate run, the system shall perform no
  synchronous file I/O; a meta test shall fail on `open(`, `openpyxl`, `pathlib` reads or
  `json.load` of a file in those modules. Only the import CLI reads files. *(D-35)*

**Import**

- **AC19.** When the import runs against `legacy/v1/config/exchange_config.json` and
  `legacy/v1/static/news.json`, the system shall create one `draft` run whose drinks, slots,
  bounds, `p0`, `a`/`d`/`s0`/`c`, params, bar prices (SD15 precedence) and news equal the
  inputs, plus `run_config_revision` 1 holding that configuration; and a `MarketSpec` built
  from the database shall equal one built directly from the file.
- **AC20.** When the import is run twice, the system shall create two independent draft runs
  and leave the first unchanged; when any input fails validation, it shall write nothing.

**Ring and lifecycle**

- **AC21.** When rehydrating, the history ring shall contain exactly the committed ticks
  within `history_window_minutes` of the latest, in `version` order; a tick from a
  rolled-back transaction shall never appear in it.
- **AC22.** When a second run is moved to `live` while one is live, the database shall reject
  it.

**Migrations**

- **AC23.** When `alembic upgrade head` then `alembic downgrade base` then `upgrade head` run
  against a scratch database, all three shall succeed, and the gate (`scripts/check.sh`) shall
  run this.

## Verification

- `./scripts/check.sh` green, its output pasted: unit and meta tests, plus `tests/integration`
  against the compose `db` (Postgres 16), including the migration round-trip of AC23.
- **The durability test** (SD1): the harness takes the imported live config live, runs a
  scripted stream of ticks, orders and one price jump, and is SIGKILLed at several points —
  between transactions and mid-transaction. Each time a fresh process rehydrates and the test
  asserts AC1: state equals the last committed row, order count equals committed orders, and
  the next `advance()` continues `rng_counter` from where it stopped. A second pass sets the
  harness clock forward past the budget before rehydrate and asserts AC5 and AC6. Evidence:
  the assertion output.
- Run the import against the real v1 files and diff the resulting `MarketSpec`, bar prices
  and news against the files (AC19).
- Golden fixtures still replay (`uv run pytest tests/engine`).

## Exit condition

Today's live configuration round-trips through Postgres, and a hard kill mid-run restores the
last committed price state exactly, loses zero committed orders, and never moves a price
across a gap.
