# Plan: Phase 7 — Run lifecycle, export and analytics

Spec: [docs/specs/phase-7-analytics.md](../specs/phase-7-analytics.md) (`Status: Approved`, committed `98cd039`) · Status: Audited — PASS (2026-10-09)
Design: [architecture.md](../design/architecture.md) ("Durability", "Authorization"), [data-model.md](../design/data-model.md), [realtime-protocol.md](../design/realtime-protocol.md), [frontend-architecture.md](../design/frontend-architecture.md) ("State", "Forms")
ADRs honoured: 0003 (one writer; the close addendum is written in T24), 0004 (Postgres only; exports are `bytea`), 0005 (series and price curves bucketed in SQL), 0006 (no new frontend dependency; charts use the bundled `lightweight-charts`), 0008 (the charged price is untouched), 0009/0010 (hard stops: new dependency, `docs/design/`, ADR text), 0011 (the migration runs at boot)
Fixes: D-20, D-31

---

## Approach

**Close is go-live in reverse, and everything else reads.** Phase 6 gave the holder exactly one
way in (`adopt`, `app/runtime/holder.py:368-382`) and `app/runtime/golive.py` the orchestration
around it. This phase adds the one way out:
- `holder.release(step)` takes the lock, runs one transaction, and swaps in the empty view (T5);
- `app/runtime/close.py` mirrors `golive.py` (T6). After the release, with no `await` in
  between, the hub clears its replay log and broadcasts `run_closed`.

The ticker already idles on an empty holder (`ticker.py:157-159`). A ticker that was *waiting*
on the lock when the close landed would get `NoLiveRunError` from `mutate`, which `_guarded`
does not catch (`ticker.py:178-186`), so T5 makes that an idle slot.

The money and identity fixes are additive columns written on the existing write paths:
- `order_line.bar_price_cents` is set by a scalar subquery inside `write_order`'s insert (T2, D-20);
- `drink.product_id` is resolved inside `add_drink`, so the v1 import, a draft add and a live add
  all get it without touching their callers (T3).

Exports are rows built by one worker task (`app/jobs/export_xlsx.py`). It reads a
`REPEATABLE READ` snapshot on a separate heavy-read engine (T4) and builds the workbook in
`asyncio.to_thread` (T10, T11). Analytics are four GET routes over the same heavy-read engine,
bucketed in SQL like `earnings_series` (`app/db/orders.py:170-200`) (T13, T14). The web adds:
- a typed-name variant of the existing `ConfirmDialog` (T16);
- the closed-run states (T17) and the Borrel section's close and copy-from (T18);
- one `/analytics` page split into components that are built in parallel (T19–T22).

Rejected:
- **A new holder method per lifecycle step.** One `release` mirrors `adopt`. Close-specific
  writes live in the step passed to it.
- **Reading the bar price from `MarketView.bar_price_cents` in Python.** The spec says "read
  inside the order transaction". A scalar subquery in the existing multi-row insert does that
  with no extra round trip (PD6).
- **Resolving products in each caller** (`runtime/drinks.py`, `cli/import_v1.py`). That makes
  three copies of one rule. `add_drink` is already the single insert point.
- **Raising the 5 s timeout, or `SET LOCAL statement_timeout` on a pooled connection.** asyncpg's
  client-side `command_timeout` (`app/db/session.py:20`) still cancels at 5 s, and SD6/SD11 ask
  for a connection outside the order path's pool (PD2).
- **A WebSocket push for export status.** The spec rules it out (SD12: poll every 2 s).
- **One migration per feature.** Every migration mirrors into `app/db/models.py` and
  `tests/integration/test_migrations.py`. A single additive migration (T1) lets T2–T5 start at
  once, as Phase 6 T1 did.
- **Parallel server route tasks.** Every task that adds or changes a route regenerates
  `web/src/api/generated/schema.d.ts` (the `check.sh` drift step) and adds rows to
  `tests/api/test_authorization_matrix.py`, whose completeness check rejects a missing row. So
  T6 → T7 → T8 → T9 → T13 → T14 → T12 is a chain by construction. The engine-free server work
  (T2–T5, T10, T11) and all web work run beside it.

---

## Decisions this plan makes

Rows marked **Confirm** change user-visible behaviour, the API surface, or a CLAUDE.md reading.
The audit confirms or overrules them. **PD1 is a hard stop that only the human can answer.**

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | **xlsx library (SD17), pending the human's approval** | Recommendation: runtime `xlsxwriter`, dev-only `openpyxl` (the cent gate reads the file back). T10 adds both to `pyproject.toml`/`uv.lock`. **T10, and everything after it in the export path (T11, T12, T15, T21, T23), may not start until the human answers.** The approval note is under Data changes | CLAUDE.md: "A new dependency … ask first". The spec forbids the planner from adding either before the answer |
| PD2 | The heavy-read connection (SD11) | `app/db/session.py` gains `create_heavy_read_engine(settings)`. It is a second `AsyncEngine` on the **same** validated DSN, with `poolclass=NullPool` (a fresh connection per use, never the order path's pool) and `command_timeout = heavy_read_timeout_seconds`. `app/core/config.py` gains `heavy_read_timeout_seconds: float = 60.0` (`HEAVY_READ_TIMEOUT_SECONDS` in `.env.example`). Boot stores it as `app.state.heavy_engine` and disposes it at shutdown. `app/api/deps.py` gains `heavy_engine(request)`. **Confirm** | CLAUDE.md's "never introduce a second database engine" is read as a second database *technology* (ADR 0004). This is the same Postgres on the same DSN, built in the same one place. If the human reads it as "a second SQLAlchemy engine object", the only alternative is raw `asyncpg.connect` in the same module |
| PD3 | Matching `confirm_name` | `body.confirm_name.strip() == run.name` (stored stripped, `runs.py:381`). Case-sensitive, no casefold. **Confirm** | "Type the run's name". A case-insensitive match would accept a name the admin never typed exactly |
| PD4 | Close orchestration | `close_in_process(state, run_id, confirm_name, author)` in `app/runtime/close.py`: (1) refuse with 404, 409 `run_not_live` or 422 `name_mismatch` from a read, with nothing written; (2) `holder.release(step)`, which under the lock checks `holder.run_id == run_id` (else 409 `run_not_live`) and runs **one** transaction: `UPDATE run SET status='ended', ended_at=<app clock>` guarded by `WHERE status='live'`, end every open `market_event`, and insert the `export` row (`kind='final'`, `status='queued'`); then swaps in the empty view, ring and earnings; (3) with no `await` after the release: `hub.release_run()`, `publisher.adopt(empty book)`, `state.tick_interval_ms` kept, broadcast `run_closed`, and set the export worker's wake-up (T11). A failed commit changes no memory (the `mutate` contract). A failure *after* the commit calls `on_diverged`, as `adopt` does | The mirror of `golive.py`. Releasing an `asyncio.Lock` does not let a waiter run before the current task yields, so "no await" is equivalent to "under the lock" for the fan-out |
| PD5 | `run_closed` on the client | `applyMessage` applies `run_closed` **outside the seq rule**, like `theme`: with no live run the server has no snapshot to end a resync. It sets `empty: true`, clears live state as a new boot does, clears `awaitingResync`, and records `closedRun {run_id, name, endedAtMs}`. A `snapshot` or a `hello` with a new `boot_id` clears `closedRun`. A same-boot `hello` with `run_id: null` keeps it. Koers shows "Borrel afgelopen" while `closedRun` is set, else "Geen actieve borrel". The bar and home show "Geen actieve borrel" (their existing empty states, `BarPage.tsx:25`, `HomePage.tsx:169`) | SD2 "No reload". A client connecting later gets `hello` with `run_id: null`, as today |
| PD6 | Where the bar price is read (SD5) | `write_order` inserts `bar_price_cents = (SELECT bar_price_cents FROM drink WHERE drink_id = :id)` per line, in its existing multi-row insert. `OrderLineInput` is unchanged | Inside the order transaction, as the spec says. Live bar-price edits commit under the same holder lock (`runtime/drinks.py` `edit_live_drink`), so the row and memory agree anyway |
| PD7 | Where product resolution lives (SD1) | New `app/db/products.py`: `resolve_product(conn, run_id, name_key, name) -> int`. It takes the newest product with that `name_key` that has no active drink in `run_id`, else inserts one. `add_drink` gains `product_id: int \| None = None` and resolves when it is `None`. `update_drink` never writes `product_id`, so a rename keeps it. Copy-from passes `product_id` explicitly | One insert path covers import, draft add and live add (`runtime/drinks.py:153-167`, `cli/import_v1.py:53`) |
| PD8 | The export queue rule (SD6) | In one transaction under `LOCK TABLE export IN SHARE ROW EXCLUSIVE MODE` (the `create_run` pattern, `runs.py:385`): **manual** requests go (a) if the run has a `queued` or `running` export, return it (202); (b) else, if the other runs have ≥ 2 exports `queued` or `running` (one running, one in the slot), 409 `export_busy`; (c) else insert `queued`. A **final** export is always inserted, by the close transaction. The worker takes the oldest `queued` by `export_id` | Exactly "one runs, one waits" for manual requests. A final export may exceed that, as SD6 allows |
| PD9 | The worker's lifecycle | One asyncio task, started by boot after rehydrate. It is woken by an `asyncio.Event` (`app.state.export_wakeup`) that a request and a close set, and it scans once at start. Per export: `status='running'`; read the snapshot on the heavy engine (`REPEATABLE READ`, `READ ONLY`); `build_workbook` in `asyncio.to_thread`; write `data`, `sha256`, `bytes`, `line_count`, `total_cents`, `status='done'` on the main engine in one short transaction; then prune (SD6 retention). An exception sets `failed` with `error`. A result `UPDATE` that matches 0 rows (the run was deleted meanwhile) is logged and dropped. Before the task starts, boot sets every `queued`/`running` row to `failed`, `error='onderbroken'`. Shutdown cancels the task and does not wait | SD6. SD11 makes the heavy engine read-only, so the result write uses the main engine |
| PD10 | The download filename (SD12) | `borrel-<slug>-<yyyymmdd-hhmm>.xlsx`. `slug` is the run name NFKD-folded to ASCII, lowercased, with runs of `[^a-z0-9]` turned into `-`, trimmed, at most 40 characters, falling back to `run-<id>`. The stamp is the export's `created_at` in UTC (SD15). **Confirm** | Distinguishes a final export from manual ones of the same run. UTC per SD15 |
| PD11 | Money field names | API: `qty`, `revenue_cents`, `bar_price_total_cents`, `avg_price_cents`; the run detail's per-product list is `bar_price_per_drink`-style rows under `per_product`. Workbook: euro columns named `revenue`, `bar_price_total`, `bar_price`. `p0_*` appears nowhere (AC13; T13's meta test) | The repo's `*_cents` convention (`models.py:7`). AC13's names stay readable as prefixes |
| PD12 | Run list times (AC26) | `t0_ms`: the run's first `price_tick.wall_ts_ms` (by `version`, the PK order), `null` for a draft. `ended_at_ms`. `duration_ms = ended_at_ms − t0_ms` for an ended run, else `null`; the UI shows "loopt" (live) or "—" (draft). **Confirm** | SD2 and AC26 define duration only up to `ended_at` |
| PD13 | Price-curve buckets (SD10, AC29) | The product's drink in each run is the one added most recently (`max(drink_id)`). Bucket `k = floor((wall_ts_ms − t0) / bucket_ms)`, with `x = k × bucket_s / 60` minutes. The value is the `p_q` of the bucket's highest-`version` tick that carries that drink, turned into cents in Python by the existing `cents_from_quantised` (the one `runtime/orders.py` uses). It is `null` when any tick in the bucket has `source='gap'`. Only buckets holding a tick are returned | The "close" of a bucket, like candles. A count bounded by duration over `bucket_s` |
| PD14 | Compare matching (AC28, SD13) | Rows join on `product_id`. A `NULL`-product drink, written only by a rolled-back image, keys as `name:<name_key>` and matches only a `NULL`-product key in the other run. Each row is named after the most recently added drink across both runs (B before A) | AC11: never a name join for normal rows. SD13: never an error on a rolled-back row |
| PD15 | Series reads (SD9) | The live run is read on the main engine, as today (bounded by duration over bucket size). Any other run is read on the heavy engine. A bar asking for a `run_id` other than the live one gets 403 `forbidden`. With no `run_id` and no live run, the answer stays 409 `no_live_run` (`earnings.py:36-37`; the bar's client maps it to `[]`) | Keeps the bar's existing contract (`web/src/features/bar/api/earningsSeries.ts:17-21`) |
| PD16 | Where the copy-from select gets its runs | `GET /api/analytics/runs` (admin, T13), listing ended and live runs. `/settings` is admin-only too. `features/settings` calls the route with its own small Zod schema, not by importing `features/analytics` (eslint boundaries) | No `GET /api/runs` list exists, and SD12 names none |
| PD17 | Orphan products on delete | `delete_run` ends with `DELETE FROM product WHERE NOT EXISTS (SELECT 1 FROM drink WHERE drink.product_id = product.product_id)`. This is global, so it also removes products orphaned earlier by a draft's hard delete (`runs.py` `delete_drink`) | AC8: "every `product` no drink references any more" |
| PD18 | The typed-name `ConfirmDialog` | A new optional prop `confirmText?: string`. When it is set the dialog renders a labelled input, "Typ de naam '{confirmText}' om te bevestigen". Confirm is disabled until `value.trim() === confirmText`. Focus starts on the input, and the focus trap cycles through input, confirm and cancel. Without the prop, behaviour is unchanged | AC32. Reuses the one dialog (Phase 5 SD9) |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `db/migrations/versions/0010_phase_7_lifecycle.py` | Create | `product`; `drink.product_id` + backfill; partial unique `drink_product_live`; `order_line.bar_price_cents` + backfill; `export`; `order_run_wall_ts` index | T1 |
| `app/db/models.py` | Modify | Mirror 0010 | T1 |
| `tests/integration/test_migrations.py` | Modify | 0010 backfill, constraints and round-trip tests | T1 |
| `app/db/orders.py` | Modify | `bar_price_cents` subquery in `write_order` | T2 |
| `app/db/products.py` | Create | `resolve_product` | T3 |
| `app/db/runs.py` | Modify | `add_drink(product_id=)` (T3); `close_run` (T6); `delete_run` (T7); `create_run(copy_from_run_id=)` (T8) | T3, T6, T7, T8 |
| `app/core/config.py`, `.env.example` | Modify | `heavy_read_timeout_seconds` | T4 |
| `app/db/session.py` | Modify | `create_heavy_read_engine` | T4 |
| `app/api/deps.py` | Modify | `heavy_engine(request)` | T4 |
| `app/runtime/boot.py` | Modify | Heavy engine lifecycle (T4); interrupted exports, worker start/cancel (T11) | T4, T11 |
| `app/runtime/holder.py` | Modify | `release(step)` | T5 |
| `app/runtime/ticker.py` | Modify | `NoLiveRunError` in `_guarded` is an idle slot | T5 |
| `app/realtime/hub.py` | Modify | `release_run()` | T5 |
| `app/realtime/publish.py` | Modify | Empty book on release (if `adopt` alone does not suffice) | T5 |
| `app/realtime/messages.py` | Modify | `RunClosedData`, `run_closed` type | T5 |
| `tests/api/ws_fixture.py`, `web/src/features/exchange/model/__fixtures__/ws-messages.json` | Modify | `run_closed` fixture | T5 |
| `web/src/features/exchange/model/{schemas,applyMessage,selectors}.ts`, `exchange/index.ts` | Modify | Zod `run_closed`; reducer (PD5); `selectClosedRun` | T5 |
| `app/db/market_events.py` | Modify | `end_open_events(conn, run_id)` | T6 |
| `app/runtime/close.py` | Create | `close_in_process` (PD4) (T6); worker wake-up (T11) | T6, T11 |
| `app/api/runs.py` | Modify | `POST …/close` (T6), `DELETE /api/runs/{run_id}` (T7), `copy_from_run_id` (T8) | T6, T7, T8 |
| `tests/api/test_authorization_matrix.py`, `tests/api/test_draining.py`, `web/src/api/generated/schema.d.ts` | Modify | Rows for every new route; regenerated types | T6, T7, T8, T9, T12, T13, T14 |
| `app/api/earnings.py` | Modify | `run_id`, `bucket_s` (SD9) | T9 |
| `app/jobs/__init__.py`, `app/jobs/export_xlsx.py` | Create | `build_workbook` (T10); worker loop (T11) | T10, T11 |
| `app/db/exports.py` | Create | Snapshot read (T10); claim, finish, fail, prune, interrupt (T11); request with coalescing (T12) | T10, T11, T12 |
| `pyproject.toml`, `uv.lock` | Modify | `xlsxwriter`, dev `openpyxl` (PD1) | T10 |
| `tests/meta/test_no_file_io.py` | Modify | Add `app/jobs` to `SCANNED_ROOTS` | T10 |
| `app/api/exports.py` | Create | Four export routes | T12 |
| `app/main.py` | Modify | Include the analytics and exports routers | T13, T12 |
| `app/db/analytics.py` | Create | Run list and run detail (T13); compare and price curve (T14) | T13, T14 |
| `app/api/analytics.py` | Create | Analytics routes | T13, T14 |
| `app/api/security.py` | Modify | `/analytics` in admin `ROLE_ROUTES` | T13 |
| `tests/meta/test_no_p0_totals.py` | Create | AC13 scan | T13 |
| `web/src/components/ui/ConfirmDialog{,.test}.tsx` | Modify | `confirmText` (PD18) | T16 |
| `web/src/features/koers/KoersPage{,.test}.tsx` | Modify | "Borrel afgelopen" | T17 |
| `web/src/features/bar/BarPage.test.tsx`, `web/src/features/home/HomePage.test.tsx` | Modify | Closed-run tests (the pages already render the empty state) | T17 |
| `web/src/features/settings/BorrelSection{,.test}.tsx` | Modify | "Borrel afsluiten", copy-from select | T18 |
| `web/src/features/analytics/**` | Create | Page, run list, stubs (T19); detail (T20); export panel (T21); compare (T22) | T19–T22 |
| `web/src/app/routes.tsx`, `web/src/components/ui/NavMenu.tsx` | Modify | `/analytics` route and label "Analyse" | T19 |
| `web/e2e/analytics.spec.ts` | Create | The spec's Playwright flow | T23 |
| `docs/adr/0003-*.md`, `docs/design/{data-model,realtime-protocol,architecture}.md`, `docs/specs/defect-register.md`, `docs/specs/phase-6-admin.md`, `docs/plans/manual-checklist.md` | Modify | Documents (spec "In scope: Documents") | T24 |

---

## Tasks

### T1 — Migration 0010: product, bar price per line, export, indexes

- **Implements:** AC10 (backfill), AC12 (column), AC15 (index); SD1, SD5, SD6, SD9, SD13
- **Expected output:**
  - `0010_phase_7_lifecycle.py` (revises `0009`), every step additive (table under Data changes):
    - `product(product_id identity PK, name_key text NOT NULL, name text NOT NULL, created_at timestamptz default now())`. `name_key` is **not** unique.
    - `drink.product_id bigint NULL REFERENCES product`, backfilled: one product per distinct
      `name_key`, named after that key's earliest drink by `(added_at, drink_id)`, with that
      drink's `added_at` as `created_at`; every drink then points at its key's product.
    - `drink_product_live`: unique on `drink(run_id, product_id) WHERE removed_at IS NULL`.
    - `order_line.bar_price_cents integer NULL CHECK (bar_price_cents >= 0)`, backfilled from
      the line's drink.
    - `export` with the columns of SD6. CHECKs: `kind IN ('manual','final')`;
      `status IN ('queued','running','done','failed')`; `bytes = octet_length(data)` when `data`
      is not null; `status <> 'done' OR data IS NOT NULL`. `run_id` references `run` (no
      cascade: `delete_run` deletes explicitly).
    - `order_run_wall_ts` on `"order"(run_id, wall_ts_ms)`.
  - `app/db/models.py` mirrors it: `Product`, `Export`, `Drink.product_id`,
    `OrderLine.bar_price_cents`, and both indexes in `__table_args__`.
- **Verification:** `uv run pytest tests/integration/test_migrations.py tests/integration/test_schema.py -v`:
  - models match the migrated schema (the existing test);
  - upgrade → downgrade → upgrade round-trips;
  - on a database seeded at 0009 with two runs that share "Bier", plus a removed and re-added
    "Wijn" in one run, upgrading gives every drink a `product_id`, both "Bier" drinks share
    one, and every `order_line.bar_price_cents` equals its drink's;
  - a second active drink with the same `product_id` in one run is an `IntegrityError`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** constraint names, the backfill SQL's shape, test seeding helpers.
  - **Must stop and ask if:** any backfill would need `NOT NULL`, or an existing migration
    would need editing (the `guard_migrations` hook refuses it anyway).

### T2 — The bar price is stored per sale (D-20 gate)

- **Implements:** AC12, AC14; SD5; PD6
- **Expected output:**
  - **The gate test, first and failing:** `tests/integration/test_bar_price_snapshot.py`.
    Place orders on a live run through `place_order`, change the drink's bar price with
    `edit_live_drink`, and place more. Earlier lines' `bar_price_cents` are unchanged, the new
    lines carry the new price, and `Σ qty × bar_price_cents` over the run equals the per-line
    sum computed in Python from the two prices.
  - `write_order` (`app/db/orders.py:101-114`) sets `bar_price_cents` with a scalar subquery on
    `drink`, per line, in the same insert. Charged columns are untouched.
  - A test that no `order_line` written by the app has `bar_price_cents IS NULL` (SD13).
- **Verification:**
  - `uv run pytest tests/integration/test_bar_price_snapshot.py tests/integration/test_place_order.py tests/integration/test_orders.py tests/integration/test_order_concurrency.py -v`. The gate is red before the change and green after; the builder pastes both.
  - `pnpm --dir web exec vitest run src/features/bar/model/money.property.test.ts`: Phase 5's
    money property test stays green (AC14).
- **Depends on:** T1
- **Autonomy note:**
  - **May decide alone:** test names, whether the subquery is built with `select(...).scalar_subquery()` or `literal_column`.
  - **Must stop and ask if:** the change would alter `unit_price_cents`, `line_total_cents`, or
    the order receipt. That is ADR 0008 territory.

### T3 — Products: resolved on add, kept on rename

- **Implements:** AC10; SD1; PD7
- **Expected output:**
  - `app/db/products.py: resolve_product(conn, run_id, name_key, name)` implements SD1's rule:
    the newest product with that key and no **active** drink in `run_id`, else a new product.
  - `add_drink` gains `product_id: int | None = None` and resolves when it is `None`. It is
    still the one insert, so `cli/import_v1.py`, `add_draft_drink` and `add_live_drink` are
    unchanged.
  - `update_drink` does not write `product_id`.
- **Verification:** `uv run pytest tests/integration/test_products.py tests/integration/test_drink_lifecycle.py tests/integration/test_import_v1.py tests/integration/test_runs.py -v`:
  - two runs, each adding "Bier", share a `product_id`;
  - " bier " in a third run resolves to the same product (trimmed, casefold);
  - renaming "Bier" → "Pils" keeps the `product_id`;
  - removing then re-adding "Wijn" in a live run gives a new `drink_id` and the same product;
  - an import gives every drink a product.
- **Depends on:** T1
- **Autonomy note:**
  - **May decide alone:** helper names; whether `resolve_product` locks (the run row lock
    taken by its callers already serialises adds within one run).
  - **Must stop and ask if:** SD1's rule cannot be met with the existing `drink_name_live`
    index plus T1's index (for example, a rename onto a removed drink's name breaking
    `drink_product_live`).

### T4 — The heavy-read engine and its timeout

- **Implements:** AC31 (connection half); SD11; PD2
- **Expected output:**
  - `Settings.heavy_read_timeout_seconds: float = Field(default=60.0, gt=0)`;
    `HEAVY_READ_TIMEOUT_SECONDS=60` in `.env.example`.
  - `create_heavy_read_engine(settings)` in `app/db/session.py`: `NullPool`, the same DSN,
    `command_timeout` and connect `timeout` set from the new setting.
  - `start_runtime` builds it as `app.state.heavy_engine` and disposes it in `finally`.
  - `deps.heavy_engine(request)`, beside `db_engine`.
- **Verification:** `uv run pytest tests/unit/test_config.py tests/integration/test_boot.py tests/meta -v`:
  - the setting defaults to 60 and rejects 0;
  - after boot, `app.state.heavy_engine` is a distinct engine whose pool is `NullPool`;
  - a `SELECT pg_sleep(6)` succeeds on it and times out on `app.state.engine`;
  - `tests/meta/test_config_boundary.py` stays green (no `os.environ` read).
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** names, test layout.
  - **Must stop and ask if:** the audit or the human overrules PD2's reading of "second
    database engine", or `test_compose_matches_env_example.py` needs a compose change.

### T5 — Unload the holder, and the `run_closed` message

- **Implements:** AC1 (unload half), AC3 (protocol and store); SD2; PD4, PD5
- **Expected output:**
  - `MarketHolder.release(step)`, the mirror of `adopt`. Under the lock it refuses an empty
    holder (`NoLiveRunError`), runs `step(view)` through `_run` (so a database failure is 503
    and memory is unchanged), and then installs the empty view, `HistoryRing(0)` and an empty
    `EarningsAggregate`. A failure after the step committed calls `on_diverged`.
  - `Ticker._guarded` treats `NoLiveRunError` as an idle slot. A ticker that was waiting on
    the lock during a release neither crashes nor logs a commit failure.
  - `Hub.release_run()`: the replay log is cleared and `run_id`/`version` become `None`.
    `Publisher` can adopt an empty book.
  - `RunClosedData {run_id, name, ended_at_ms}` and the `run_closed` type in
    `app/realtime/messages.py`. The JSON fixture and `ws_fixture.py` gain it.
  - Zod `run_closed` in `schemas.ts`. `applyMessage` per PD5, plus `selectClosedRun`.
- **Verification:**
  - `uv run pytest tests/integration/test_holder.py tests/integration/test_ticker.py tests/unit/test_hub.py tests/unit/test_messages.py tests/api/test_ws_fixture.py -v`:
    - `release` leaves `is_empty` true, and a failing step leaves the view unchanged;
    - a fake-clock ticker blocked on the lock during a release keeps iterating idle, with
      `version` unchanged;
    - after `release_run`, `replay_after(old boot, old seq)` returns `None`.
  - `pnpm --dir web exec vitest run src/features/exchange`:
    - the fixture validates against Zod;
    - `run_closed` applies with a seq gap and clears `awaitingResync`;
    - a following same-boot `hello` with `run_id: null` keeps `closedRun`;
    - a `snapshot` clears it.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** method names; whether the empty-book swap is a new `Publisher`
    method or `adopt(CandleBook…, active=())`.
  - **Must stop and ask if:** `release` needs a second lock or a change to `mutate`'s
    contract, or the Phase 3 WebSocket flake (memory note) appears. Report it; do not retry
    to green.

### T6 — Close a run

- **Implements:** AC1, AC2, AC4, AC5, AC6 (no live run after restart), AC34, AC35, AC37 (regression); SD2, SD14, SD16; PD3, PD4
- **Expected output:**
  - `POST /api/runs/{run_id}/close` (admin, draining dependency) with body
    `{confirm_name}` (`extra="forbid"`). It returns `RunSummaryData` with `status: "ended"`.
    Refusals:
    - 404 `run_not_found`;
    - 409 `run_not_live` (draft, ended, or not the holder's run);
    - 422 `name_mismatch` (a new `AppError`);
    - 503 `shutting_down`.
  - `app/db/runs.py: close_run(conn, run_id, *, ended_at_ms, requested_by)` sets
    `status='ended'` and `ended_at` **from the app clock**, `WHERE status='live'`. It calls
    `market_events.end_open_events` and inserts the final `export` row with `models.Export`
    directly; `app/db/exports.py` is T10's.
  - `app/runtime/close.py: close_in_process` per PD4.
  - Matrix and draining rows; `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_close.py tests/integration/test_close_in_process.py tests/integration/test_boot.py tests/api/test_runs.py tests/api/test_authorization_matrix.py tests/api/test_draining.py -v`:
  - **AC1:** after a close, `run.status='ended'`, `ended_at` is the fake clock's time, no
    `market_event` has `ended_at IS NULL`, one `export` row has `kind='final'` and
    `status='queued'`, and advancing the fake clock writes no `price_tick` for the run;
  - **AC2:** each refusal leaves status, `ended_at`, the event and export counts, and the holder
    unchanged;
  - **AC3 server half:** a connected `ws_fixture` client receives `run_closed` with the run's
    name;
  - **AC4:** 50 concurrent orders racing one close. Each order is 201 or 409 `no_live_run`;
    every committed order has `wall_ts_ms ≤ ended_at`; the final export row's run has exactly
    the committed orders;
  - **AC5:** after the close, `POST /api/runs` is 201, and the closed run's order, tick, news
    and line counts are unchanged;
  - **AC6:** a restart boots an empty holder and the ended run is unchanged;
  - **AC37:** a shutdown without a close leaves the run `live` and rehydrates it.
- **Depends on:** T1, T3 (`db/runs.py`), T5
- **Autonomy note:**
  - **May decide alone:** error class placement (`app/db/runs.py` beside `RunNotLive`), test
    split.
  - **Must stop and ask if:** AC4's race cannot be made deterministic without sleeping, or
    the close needs anything but the holder lock to serialise against orders.

### T7 — Delete a run

- **Implements:** AC8, AC34, AC35; SD3; PD17
- **Expected output:**
  - `DELETE /api/runs/{run_id}` (admin, draining) with body `{confirm_name}`, answering 204.
    Refusals: 409 `run_live` (a new error), 422 `name_mismatch`, 404 `run_not_found`.
  - `app/db/runs.py: delete_run(engine, run_id)`, in one transaction under the `run` row lock.
    It deletes in FK order: `order_line` (cascade from `order`), `order`, `price_tick`, `news`,
    `market_event`, `run_config_revision`, `engine_state`, `export`, `drink`, `run`. Then it
    deletes orphan products (PD17).
  - Matrix and draining rows; `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_delete_run.py tests/integration/test_delete_run.py tests/api/test_authorization_matrix.py tests/api/test_draining.py -v`:
  - seed two complete runs that share a product, and delete one: every table's row count for
    the other run, and a hash of its rows, is unchanged;
  - the shared product stays, and a product only the deleted run used is gone;
  - a draft with no orders deletes;
  - a live run is 409 with nothing removed.
- **Depends on:** T6 (`api/runs.py`, `db/runs.py`, matrix, `schema.d.ts`)
- **Autonomy note:**
  - **May decide alone:** whether the body is a pydantic model on `DELETE` (FastAPI allows it).
  - **Must stop and ask if:** a table referencing `run` exists beyond the seven in
    `models.py` plus `export`, or the delete of a 30 000-order run exceeds the 5 s timeout
    (R7).

### T8 — Copy a past run's drinks into a new draft

- **Implements:** AC9, AC35 (unchanged route stays covered); SD4
- **Expected output:**
  - `CreateRunRequest.copy_from_run_id: int | None`.
  - `create_run`, in its existing transaction: with a source it copies the source's `params`
    instead of `latest_params`, and each **active** drink in slot order (bounds, `p0`,
    `a/d/s0/c`, `bar_price_cents`, and the same `product_id` through T3's parameter) into new
    `drink_id`s with slots 0..n-1. Revision 1 then holds those drinks.
  - An unknown source is 404 `run_not_found`. `live_run_exists` and `draft_exists` still apply.
  - `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_runs.py tests/integration/test_runs.py -v`:
  - copy from a closed run with one removed drink: the new draft has the active drinks only,
    with equal columns and `product_id`s, new `drink_id`s, and equal `params`;
  - it has no order, tick, news or event;
  - an unknown source is 404 with no run created.
- **Depends on:** T7 (`api/runs.py`, `db/runs.py`, `schema.d.ts`), T3
- **Autonomy note:**
  - **May decide alone:** whether copied slots keep the source's gaps or compact (SD4 says
    "in slot order").
  - **Must stop and ask if:** copying `s0` conflicts with `auto_calibrate_s0` at go-live (it
    should not: go-live re-anchors).

### T9 — The earnings series takes a run and a bucket size (D-31)

- **Implements:** AC15, AC16, AC31 (series on the heavy engine); SD9; PD15
- **Expected output:**
  - `GET /api/earnings/series?run_id=&bucket_s=`. `bucket_s` is `Literal[60, 300, 900]`,
    default 60, so anything else is 422. `run_id` defaults to the live run.
  - Roles: bar gets 403 for a non-live `run_id`; an unknown run is 404 `run_not_found`; a run
    with no orders is `[]`. The live run reads on the main engine, any other on the heavy
    engine. Reuses `earnings_series(conn, run_id, bucket_ms=)` unchanged.
  - `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_earnings_series.py tests/integration/test_earnings_series.py tests/api/test_authorization_matrix.py -v`:
  - **AC15:** 5 000 orders bulk-inserted inside 10 minutes give ≤ 10 points at 60 s and ≤ 2
    at 300 s;
  - **AC16:** each refusal code; a draft returns `[]`;
  - the bar's no-parameter call is unchanged.
- **Depends on:** T8 (`schema.d.ts`), T1 (index), T2 (`db/orders.py`), T4
- **Autonomy note:**
  - **May decide alone:** query-parameter declaration style.
  - **Must stop and ask if:** `earnings_series` itself must change shape.

### T10 — The workbook builder and its snapshot (needs PD1)

- **Implements:** AC13 (workbook), AC18, AC19, AC22, AC23; SD6 (snapshot), SD8, SD15
- **Expected output:**
  - **Hard stop:** not started until the human approves PD1. Then it adds `xlsxwriter` and dev
    `openpyxl` to `pyproject.toml` and `uv.lock`.
  - `app/db/exports.py: read_snapshot(conn, run_id) -> ExportSnapshot`. It runs on a heavy-engine
    connection set to `REPEATABLE READ` and `postgresql_readonly=True`, and reads:
    - the run's name, `t0_ms` and `ended_at`;
    - every order line joined to its order and drink, with SD13's fallbacks
      (`COALESCE(order_line.bar_price_cents, drink.bar_price_cents)`; product `NULL` →
      `name_key` group);
    - `line_count` and `total_cents` computed in the same snapshot.
  - `app/jobs/export_xlsx.py: build_workbook(snapshot, *, generated_at_ms) -> bytes`. It is pure,
    and uses `xlsxwriter` in `in_memory` mode on a `BytesIO`. It writes:
    - **`Sales`**, SD8's column order: `ts_iso` in UTC, `ts_ms`, `drink` (name at export),
      `qty`, `unit_price`, `total_price`, `p_cont`, `p_min`, `p_max` (at export), `order_id`,
      `drink_id`, `bar_price`, `version`;
    - **`Per drink`**, per product;
    - **`Summary`**.

    Euros come from `Decimal(cents) / 100`, written with format `0.00`.
  - `tests/meta/test_no_file_io.py` adds `app/jobs` to `SCANNED_ROOTS` and `MUST_SEE`.
- **Verification:** `uv run pytest tests/integration/test_export_workbook.py tests/meta/test_no_file_io.py -v`. Each case reads the bytes back with `openpyxl`:
  - **AC18:** `Summary.total_revenue`, `Σ Sales.total_price` and `snapshot.total_cents` each
    equal `SELECT sum(line_total_cents)`, compared as `Decimal(str(v)) * 100`;
    `bar_price_total` equals `Σ qty × bar_price_cents`;
  - **AC19:** a run with a mid-run add and remove is one workbook, and the removed drink's
    lines are present;
  - **AC22:** a run with no orders has headers on every sheet and zero totals;
  - **AC23:** an order committed in a second connection after the snapshot opened is absent;
  - **AC13:** no cell contains `p0_`.
- **Depends on:** T1, T2, T4; **PD1 answered by the human**
- **Autonomy note:**
  - **May decide alone:** sheet styling, column widths, the dataclass layout of
    `ExportSnapshot`.
  - **Must stop and ask if:** PD1 is unanswered or answered otherwise (then follow the
    answer); or the library cannot write without touching the filesystem.

### T11 — The export worker: queue, failure, restart, retention, no stall

- **Implements:** AC1 (final export built), AC6 (interrupted → failed), AC7 (server), AC21, AC24; SD6; PD9
- **Expected output:**
  - The worker loop in `app/jobs/export_xlsx.py` per PD9.
  - `app/db/exports.py` gains `claim_next`, `finish`, `fail`, `prune_manual(run_id, keep=3)` (completed manual exports beyond the three newest; finals never), and `interrupt_unfinished` (boot).
  - `boot.py`: `interrupt_unfinished` before the worker starts; the worker task is started and
    cancelled without waiting at shutdown; `app.state.export_wakeup`.
  - `close.py` sets the wake-up after the release.
- **Verification:** `uv run pytest tests/integration/test_export_worker.py tests/integration/test_export_timing.py tests/integration/test_boot.py -v`:
  - **AC1:** closing a seeded run produces a `done` final export whose `total_cents` equals
    the database;
  - **AC7:** a build forced to raise (monkeypatched `build_workbook`) leaves the export
    `failed` with `error`, the run `ended`, and the next request builds;
  - **AC6:** booting over a `queued` and a `running` row marks both `failed`, `error='onderbroken'`;
  - **AC24:** a fourth manual export's completion deletes the oldest completed manual export,
    and two finals survive;
  - **AC21:** a timing test on the real clock. With a 20 000-line run exporting while 20
    orders/s are placed on a live run, the maximum gap between tick `wall_ts_ms` is ≤ 1.5 ×
    the interval, and p95 order latency is ≤ 2 × the same load's baseline without an export.
- **Depends on:** T10, T6 (`close.py`), T4 (`boot.py`)
- **Autonomy note:**
  - **May decide alone:** the wake-up mechanism's shape, log event names.
  - **Must stop and ask if:** AC21's thresholds fail because `to_thread` holds the GIL (R16).
    Report the measured numbers and the options (a process pool, a chunked build); do not
    loosen the thresholds alone.

### T12 — Export routes

- **Implements:** AC7 (request again), AC17, AC20, AC25 (export half), AC34, AC35; SD6, SD7, SD12; PD8, PD10
- **Expected output:**
  - `app/api/exports.py`, all admin:
    - `POST /api/runs/{run_id}/exports`: 202 `ExportData`, coalescing per PD8, 409
      `export_busy`, 404 for an unknown run, 503 while draining;
    - `GET /api/runs/{run_id}/exports`: newest first, without `data`;
    - `GET /api/exports/{export_id}`;
    - `GET /api/exports/{export_id}/file`: 409 `export_not_ready` unless `done`. Otherwise the
      `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` body, with
      `Content-Disposition: attachment; filename="…"` (PD10) and
      `X-Content-Type-Options: nosniff`.
  - `app/db/exports.py: request_export` (PD8).
  - `main.py` router; matrix rows (bar and display 403); draining rows (POST only);
    `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_exports.py tests/integration/test_export_queue.py tests/api/test_authorization_matrix.py tests/api/test_draining.py tests/meta/test_route_authorization.py -v`:
  - **AC17:** the POST returns 202 `queued` before the build finishes (the worker is paused in
    the test);
  - **AC20:** the same run twice returns one `export_id`; a second run queues; a third is 409;
  - **AC20:** a close while the slot is full still creates its final export;
  - **AC25:** the file's headers, and 403 for bar and display;
  - **AC35:** the GET routes answer while draining.
- **Depends on:** T11, T14 (`main.py`, matrix, `schema.d.ts`; last in the route chain so PD1
  blocks nothing else)
- **Autonomy note:**
  - **May decide alone:** response model names, `export_not_ready`'s status (409 vs 404).
  - **Must stop and ask if:** coalescing cannot be made race-free with the table lock.

### T13 — Analytics: run list and run detail

- **Implements:** AC13 (API and web scan), AC25 (analytics half), AC26, AC27, AC30 (server), AC31 (on the heavy engine), AC33 (route list), AC34; SD10, SD12, SD13; PD11, PD12
- **Expected output:**
  - `app/db/analytics.py`:
    - `run_list(conn)`: per run, `run_id`, name, status, `t0_ms`, `ended_at_ms`, `duration_ms`,
      `qty`, `revenue_cents` and `bar_price_total_cents`, in one grouped query (no N+1);
    - `run_detail(conn, run_id)`: per product, removed drinks included, the name of the newest
      drink, `qty`, `revenue_cents`, `bar_price_total_cents` and `avg_price_cents`
      (`round(revenue / qty)`), plus totals.

    Both apply SD13's NULL fallbacks.
  - `app/api/analytics.py`: `GET /api/analytics/runs` and `GET /api/analytics/runs/{run_id}`
    (404 `run_not_found`), both admin, both on `heavy_engine`.
  - `ROLE_ROUTES["admin"]` gains `/analytics`.
  - `tests/meta/test_no_p0_totals.py` fails if `p0_total` or `p0_per_drink` appears in the
    served OpenAPI document, under `web/src/`, or under `app/jobs/`.
  - `main.py`; matrix rows; `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_analytics.py tests/integration/test_analytics_runs.py tests/meta/test_no_p0_totals.py tests/api/test_auth.py tests/api/test_authorization_matrix.py -v`:
  - **AC26 and AC27:** seed two synthetic runs, one with a removed drink that sold. The list
    shows correct revenue, bar-price revenue, quantity and duration (first tick → `ended_at`).
    Detail includes the removed drink, and its totals equal `SELECT sum(line_total_cents)`;
  - **AC30:** a draft with no orders gives zero totals and empty rows, not an error;
  - **SD13:** a drink with `product_id NULL` and a line with `bar_price_cents NULL` are counted;
  - **AC33:** `/api/auth/me` for an admin lists `/analytics`, and bar and display do not.
- **Depends on:** T9 (matrix, `schema.d.ts`), T2, T3, T4
- **Autonomy note:**
  - **May decide alone:** query shape (CTEs or subqueries), response model names.
  - **Must stop and ask if:** a field the spec lists for the run list (SD10) cannot be computed
    in one query without N+1.

### T14 — Analytics: compare and price curve

- **Implements:** AC11, AC28, AC29, AC30 (server), AC34; SD10, SD12; PD13, PD14
- **Expected output:**
  - `GET /api/analytics/compare?a=&b=` (admin, heavy engine). Its rows are
    `{product_key, product_id, name, a: {qty, revenue_cents, bar_price_total_cents} | null, b: … | null}`
    per PD14, and 404 names the unknown side.
  - `GET /api/analytics/price-curve?product_id=&a=&b=&bucket_s=`, with `bucket_s` in {60, 300, 900}.
    It returns `{a: [{minute, price_cents | null}], b: […]}` per PD13. A product absent from a
    run gives `[]` for that side.
  - Repository functions in `app/db/analytics.py`. Matrix rows; `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_analytics_compare.py tests/integration/test_analytics_compare.py tests/api/test_authorization_matrix.py -v`:
  - **AC11:** "Bier" renamed to "Pils" in run B joins run A's "Bier" in one row. A test
    replaces the join key with the name and asserts it then fails (a mutation check written as
    a parametrised test over the key function);
  - **AC28:** a product only in A has `b: null`;
  - **AC29:** a seeded run with a `gap` tick in minute 3 has `price_cents: null` there, and
    point count ≤ ⌈duration / bucket_s⌉;
  - **AC30:** two runs with no orders give `[]` rows and `[]` curves.
- **Depends on:** T13
- **Autonomy note:**
  - **May decide alone:** how the mutation check is expressed.
  - **Must stop and ask if:** reading `price_tick.prices` JSONB per bucket cannot meet AC31 on
    T15's seeded volume without a new index. That would be a new migration.

### T15 — Heavy reads under volume

- **Implements:** AC31
- **Expected output:** `tests/integration/test_heavy_reads.py`, tests only:
  - It bulk-seeds a run with 30 000 orders (about 60 000 lines) and 18 000 ticks over five hours.
  - It runs `read_snapshot` + `build_workbook`, `run_list`, `run_detail`, `compare` and
    `price_curve` against it.
  - An SQLAlchemy `before_cursor_execute` listener on `app.state.engine` counts statements
    that touch `order_line` or `price_tick` during those calls.
- **Verification:** `uv run pytest tests/integration/test_heavy_reads.py -v`:
  - every call completes with the heavy timeout at its default;
  - the listener counts zero statements on the live engine;
  - the test pastes its timings.
- **Depends on:** T11, T14
- **Autonomy note:**
  - **May decide alone:** seeding method (`COPY` or `INSERT … SELECT generate_series`).
  - **Must stop and ask if:** any call needs more than 10 s, or the seed itself exceeds a
    minute in `check.sh` (then propose marking it slow).

### T16 — `ConfirmDialog` with a typed name

- **Implements:** AC32; PD18
- **Expected output:** `confirmText` per PD18. Existing callers and tests are unchanged.
- **Verification:** `pnpm --dir web exec vitest run src/components/ui/ConfirmDialog.test.tsx src/lint-rules.test.ts`:
  - with `confirmText="Vrijdag"`, confirm is disabled for "" and "vrijdag" and enabled for
    " Vrijdag ";
  - the label reads exactly "Typ de naam 'Vrijdag' om te bevestigen";
  - Tab cycles input → confirm → cancel, and Escape cancels;
  - the existing rule that bans `confirm`/`alert` stays green.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** CSS, whether the input uses `Field`.
  - **Must stop and ask if:** the focus-trap change breaks an existing caller's test.

### T17 — Closed-run states on koers, bar and home

- **Implements:** AC3 (web); SD2; PD5
- **Expected output:**
  - Koers renders "Borrel afgelopen" (calm, no tiles, no marquee) while `selectClosedRun` is
    set, and "Geen actieve borrel" otherwise when empty.
  - The bar and home keep their existing empty states. Tests prove that `run_closed` reaches
    them without a remount.
- **Verification:** `pnpm --dir web exec vitest run src/features/koers src/features/bar/BarPage.test.tsx src/features/home`:
  - dispatching a `run_closed` fixture after a snapshot shows "Borrel afgelopen" on koers;
  - the bar shows "Geen actieve borrel" with no pad buttons;
  - home shows "Geen actieve borrel";
  - a later snapshot restores the live views.
- **Depends on:** T5
- **Autonomy note:**
  - **May decide alone:** the closed screen's layout and copy beyond the fixed strings.
  - **Must stop and ask if:** a bar order pending when `run_closed` arrives would be retried
    forever (`orderIntents.ts` handles 5xx retries; 409 `no_live_run` should be terminal).
    Report rather than add new intent behaviour silently.

### T18 — Borrel section: close, and copy from a past run

- **Implements:** AC2 (Dutch refusal texts), AC9 (UI), AC32; SD2, SD4; PD16
- **Expected output:**
  - With a live run, BorrelSection shows a "Borrel afsluiten" button. It opens `ConfirmDialog`
    with `confirmText={run.name}` and posts `/close`. On success the section shows
    "Geen borrel" and the new-borrel form. Refusals map to Dutch texts:
    - `name_mismatch`: "Naam komt niet overeen.";
    - `run_not_live`: "Deze borrel is niet live.".
  - The "Nieuwe borrel" form gains a "Kopieer drankjes uit" `Select`: an empty option plus
    the runs from `GET /api/analytics/runs`, excluding drafts. A choice sends
    `copy_from_run_id`.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/BorrelSection.test.tsx`:
  - the close posts only after the typed name matches;
  - a 422 shows the Dutch text;
  - the copy select's value reaches the POST body;
  - a failed run-list fetch leaves the form usable with only the empty option.
- **Depends on:** T16, T8, T13, T6
- **Autonomy note:**
  - **May decide alone:** the run-list schema's location inside `features/settings`.
  - **Must stop and ask if:** a component would have to be imported from `features/analytics`
    (a boundaries violation).

### T19 — `/analytics`: page, run list, delete

- **Implements:** AC8 (UI), AC32, AC33 (route, nav, list); SD10
- **Expected output:**
  - `features/analytics/`:
    - `AnalyticsPage` composes `RunList` with `RunDetail`, `ExportPanel` and `CompareView`.
      Those three are stubs with final props interfaces (`runId`, or `a`/`b`), filled by
      T20–T22;
    - `api/runs.ts` holds the Zod schema and fetch for the run list;
    - `RunList` shows the table of SD10 (name, status, start, end, duration, revenue,
      bar-price revenue, quantity), with row actions: detail, pick A and B for compare, delete;
    - delete uses `ConfirmDialog` with `confirmText` and calls `DELETE`, then refreshes.
  - `routes.tsx` gains `/analytics`, and `NavMenu` the label "Analyse".
- **Verification:** `pnpm --dir web exec vitest run src/features/analytics src/components/ui/NavMenu.test.tsx src/app`:
  - the list renders seeded rows in euros, with "loopt" for a live run;
  - an empty list shows "Nog geen borrels";
  - delete is guarded by the typed name and refreshes;
  - a bar session's `allowed_routes` hide the nav entry, and the route renders "Geen toegang".
- **Depends on:** T16, T7, T13
- **Autonomy note:**
  - **May decide alone:** layout, how the selection is held (`useState` in the page).
  - **Must stop and ask if:** the stubs' props cannot be fixed now without knowing T20–T22's
    needs.

### T20 — Run detail and its earnings series

- **Implements:** AC27 (UI), AC30 (UI), AC33 (detail); SD9, SD10
- **Expected output:**
  - `RunDetail` shows the per-product table (removed drinks included, with a "verwijderd"
    marker) and totals.
  - `SeriesChart` is a `lightweight-charts` line, following `bar/RevenueChart.tsx`. Its 1 / 5 /
    15 minute picker calls `GET /api/earnings/series?run_id=&bucket_s=`.
  - Empty states: "Geen verkopen" for both the table and the chart.
- **Verification:** `pnpm --dir web exec vitest run src/features/analytics/RunDetail.test.tsx src/features/analytics/SeriesChart.test.tsx`:
  - the picker refetches with 300;
  - an empty run renders the empty state with no chart constructed;
  - a fetch error shows "Verbindingsfout".
- **Depends on:** T19, T9, T13
- **Autonomy note:**
  - **May decide alone:** chart options (reuse `lib/chartTheme.ts`).
  - **Must stop and ask if:** the chart needs a new dependency.

### T21 — Export panel: request, poll, download

- **Implements:** AC7 (UI), AC17 (UI), AC20 (UI), AC33 (export state); SD12
- **Expected output:**
  - `ExportPanel` lists the run's exports (kind, status, time, size), with an
    "Exporteer (xlsx)" button. It polls `GET /api/exports/{id}` every 2 s while any export is
    `queued` or `running`, and stops on unmount.
  - A `done` export is a plain `<a href="/api/exports/{id}/file" download>`. A `failed` one
    shows its `error` (`onderbroken` → "Onderbroken") and an "Opnieuw" button.
  - `export_busy` → "Er loopt al een export. Probeer het zo opnieuw."
- **Verification:** `pnpm --dir web exec vitest run src/features/analytics/ExportPanel.test.tsx` with fake timers:
  - a poll every 2 s while `queued`, and none after `done`;
  - the download link's href;
  - "Opnieuw" re-posts;
  - the 409 text shows.
- **Depends on:** T19, T12
- **Autonomy note:**
  - **May decide alone:** the poll hook's shape.
  - **Must stop and ask if:** the download needs authentication beyond the session cookie.

### T22 — Compare view and price-curve overlay

- **Implements:** AC11 (UI), AC28 (UI), AC29 (UI), AC30 (UI), AC33 (compare); SD10
- **Expected output:**
  - `CompareView(a, b)` shows per-product revenue and quantity side by side, with "—" for an
    absent side.
  - A product select and a 1 / 5 / 15 picker drive `PriceCurveChart`: two `lightweight-charts`
    line series on a minutes axis. A `null` point is a whitespace data point, so the line
    breaks.
  - Empty states: "Kies twee borrels" and "Geen data voor dit drankje".
- **Verification:** `pnpm --dir web exec vitest run src/features/analytics/CompareView.test.tsx src/features/analytics/PriceCurveChart.test.tsx`:
  - a product only in A renders "—" on B;
  - a `null` bucket becomes a whitespace point;
  - with fewer than two runs selected, no request is sent.
- **Depends on:** T19, T14
- **Autonomy note:**
  - **May decide alone:** the x-axis representation (minutes as a numeric time scale).
  - **Must stop and ask if:** `lightweight-charts` cannot draw a non-time x axis without a
    plugin. Report the workaround first.

### T23 — Playwright: two borrels, close, compare, export, delete

- **Implements:** AC3 (end to end), AC33, AC36; spec "Playwright (in the gate)"
- **Expected output:** `web/e2e/analytics.spec.ts`, on its own `serve.py --empty` instance as
  `admin.spec.ts` does (Phase 6 PD15). The flow:
  1. Create a borrel, add three drinks, and go live.
  2. Take orders from a bar context, change a bar price, and add a drink.
  3. A display context sees "Borrel afgelopen" after the admin closes with the typed name.
  4. Create a new borrel copying the first's drinks, take orders, and close it.
  5. Open `/analytics`, compare the two runs, download an export (assert the `.xlsx`
     filename and a non-empty body), and delete one run.

  `page.route('**/*')` fails the test on any request whose origin is not the app's (AC36).
- **Verification:** `./scripts/check.sh`. The e2e step passes, and the builder reports this
  spec's run time.
- **Depends on:** T17, T18, T20, T21, T22
- **Autonomy note:**
  - **May decide alone:** selectors, helper factoring with `admin.spec.ts`.
  - **Must stop and ask if:** the spec adds more than 3 minutes to the gate (Phase 4 R6), or
    needs a server-side test hook.

### T24 — Documents

- **Implements:** spec "In scope: Documents"; closes D-20 and D-31 with evidence
- **Expected output:**
  - an ADR 0003 addendum (close releases the run in-process; PD4);
  - `data-model.md`: `product`, `export`, `order_line.bar_price_cents`, `ended` semantics, the
    new indexes, and line 90's identity claim corrected;
  - `realtime-protocol.md`: `run_closed` and PD5's seq exception;
  - `architecture.md`: `app/jobs/` and the heavy-read engine (PD2);
  - the defect register's Phase 7 evidence table, with D-20 → T2 and D-31 → T9;
  - the Phase 6 spec's out-of-scope list and SD26: reset is gone, not deferred;
  - `manual-checklist.md`'s Phase 7 exit check.
- **Verification:** `./scripts/check.sh` (the repo-hygiene and link checks), plus the human's
  approval before commit.
- **Depends on:** T5, T6, T12, T14
- **Autonomy note:**
  - **Must stop for approval before committing.** `docs/design/` and ADR text are hard stops
    (ADR 0009/0010).
  - **May decide alone:** wording inside the register table.

---

## Acceptance criteria → tasks

| AC | Tasks | AC | Tasks | AC | Tasks |
|---|---|---|---|---|---|
| AC1 | T5, T6, T11 | AC14 | T2 | AC27 | T13, T20 |
| AC2 | T6, T18 | AC15 | T1, T9 | AC28 | T14, T22 |
| AC3 | T5, T6, T17, T23 | AC16 | T9 | AC29 | T14, T22 |
| AC4 | T6 | AC17 | T12, T21 | AC30 | T13, T14, T20, T22 |
| AC5 | T6 | AC18 | T10 | AC31 | T4, T9, T13, T15 |
| AC6 | T6, T11 | AC19 | T10 | AC32 | T16, T18, T19 |
| AC7 | T11, T12, T21 | AC20 | T12, T21 | AC33 | T13, T19–T23 |
| AC8 | T7, T19 | AC21 | T11 | AC34 | T6, T7, T9, T12, T13, T14 |
| AC9 | T8, T18 | AC22 | T10 | AC35 | T6, T7, T8, T12 |
| AC10 | T1, T3 | AC23 | T10 | AC36 | T23 (+ `check.sh`'s built-output step) |
| AC11 | T14, T22 | AC24 | T11 | AC37 | T6 |
| AC12 | T1, T2 | AC25 | T12, T13 | | |
| AC13 | T10, T13 | AC26 | T13 | | |

Every task names at least one AC, except T24, which implements the spec's "In scope: Documents".

---

## Task graph

```
T1 ─┬─ T2 ──────────────┐
    ├─ T3 ─┐            │
T5 ─┼──────┴─ T6 ─ T7 ─ T8 ─ T9 ─ T13 ─ T14 ─ T12 ─ T21 (also T19)
    │          │                   │     │     │
T4 ─┴──────────┼── T10 ─ T11 ──────┼─────┼─────┘ (T11 also feeds T15 with T14)
  (PD1) ───────┘                   │     ├── T22 (also T19)
                                   ├── T18 (also T16, T8, T6)
T5 ── T17                          └── T19 (also T16, T7) ── T20 (also T9)
T17, T18, T20, T21, T22 ── T23          T5, T6, T12, T14 ── T24
```

Edges, exactly:
`T2←T1` · `T3←T1` · `T6←T1,T3,T5` · `T7←T6` · `T8←T7,T3` · `T9←T8,T1,T2,T4` ·
`T10←T1,T2,T4,PD1` · `T11←T10,T6,T4` · `T13←T9,T2,T3,T4` · `T14←T13` · `T12←T11,T14` ·
`T15←T11,T14` · `T17←T5` · `T18←T16,T8,T13,T6` · `T19←T16,T7,T13` · `T20←T19,T9,T13` ·
`T21←T19,T12` · `T22←T19,T14` · `T23←T17,T18,T20,T21,T22` · `T24←T5,T6,T12,T14`.
`T1`, `T4`, `T5` and `T16` depend on nothing.

**The server route chain is forced, not cautious.** T6 → T7 → T8 → T9 → T13 → T14 → T12 each
regenerate `schema.d.ts` and edit the authorization matrix, and T6–T8 also share `api/runs.py`
and `db/runs.py`. Builders run one at a time anyway (ADR 0010 §1), so the groups give the merge
order. **The export routes (T12) come last on purpose:** they wait on PD1 through T10 and T11,
so placing them after analytics keeps the unanswered dependency from blocking T13, T14, T18,
T19, T20 and T22.

Shared files, ordered by dependency:
- `app/db/runs.py`: T3 → T6 → T7 → T8.
- `app/db/orders.py`: T2 → T9 (T9 is not expected to edit it; ordered in case).
- `app/runtime/boot.py`: T4 → T11.
- `app/runtime/close.py`: T6 → T11.
- `app/db/exports.py`: T10 → T11 → T12.
- `app/main.py`: T13 → T12.
- `app/db/analytics.py`, `app/api/analytics.py`: T13 → T14.
- `features/analytics/**`: T19 creates every file, including stubs; T20, T21 and T22 each
  write only their own component, its chart, its `api/*.ts` and its tests.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T4, T5, T16 | T1: 0010, `models.py`, `test_migrations.py`, `test_schema.py` · T4: `core/config.py`, `.env.example`, `db/session.py`, `api/deps.py`, `runtime/boot.py`, config/boot tests · T5: `runtime/{holder,ticker}.py`, `realtime/{hub,publish,messages}.py`, `ws_fixture.py`, fixture JSON, `exchange/model/{schemas,applyMessage,selectors}.ts`, `exchange/index.ts`, their tests · T16: `components/ui/ConfirmDialog*` |
| 2 | T2, T3, T17 | T2: `db/orders.py`, `test_bar_price_snapshot.py` · T3: `db/{products,runs}.py`, `test_products.py`, drink/import/runs tests · T17: `koers/KoersPage*`, `bar/BarPage.test.tsx`, `home/HomePage.test.tsx` |
| 3 | T6, T10 | T6: `db/{runs,market_events}.py`, `runtime/close.py`, `api/runs.py`, matrix, draining, `schema.d.ts`, close tests · T10: `jobs/{__init__,export_xlsx}.py`, `db/exports.py`, `pyproject.toml`, `uv.lock`, `test_no_file_io.py`, `test_export_workbook.py` |
| 4 | T7, T11 | T7: `db/runs.py`, `api/runs.py`, matrix, draining, `schema.d.ts`, delete tests · T11: `jobs/export_xlsx.py`, `db/exports.py`, `runtime/{boot,close}.py`, worker/timing tests |
| 5 | T8 | `db/runs.py`, `api/runs.py`, `schema.d.ts`, runs tests |
| 6 | T9 | `api/earnings.py`, matrix, `schema.d.ts`, earnings tests |
| 7 | T13 | `db/analytics.py`, `api/analytics.py`, `api/security.py`, `main.py`, matrix, `schema.d.ts`, `test_no_p0_totals.py`, analytics tests |
| 8 | T14, T18, T19 | T14: `db/analytics.py`, `api/analytics.py`, matrix, `schema.d.ts`, compare tests · T18: `settings/BorrelSection*` · T19: `features/analytics/**` (create), `app/routes.tsx`, `components/ui/NavMenu*` |
| 9 | T12, T15, T20, T22 | T12: `api/exports.py`, `db/exports.py`, `main.py`, matrix, draining, `schema.d.ts`, export route tests · T15: `test_heavy_reads.py` · T20: `analytics/{RunDetail,SeriesChart}*`, `analytics/api/runDetail.ts` · T22: `analytics/{CompareView,PriceCurveChart}*`, `analytics/api/compare.ts` |
| 10 | T21 | `analytics/ExportPanel*`, `analytics/api/exports.ts` |
| 11 | T23, T24 | T23: `e2e/analytics.spec.ts` (and `serverProcess.ts` only if a helper is needed) · T24: the documents listed in Files |

No two tasks in one group write the same file. In group 1, T4 alone writes `boot.py` and T5
alone writes `holder.py`/`ticker.py`. In group 4, T11 writes `close.py` and T7 does not. In
group 8, only T14 writes server files. In group 9, only T12 writes server source; T15 adds one
test file.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main`, with the output pasted.
- T2's gate test history (red, then green).
- T11's timing numbers; T15's timings; T23's run time.
- D-20 and D-31 closed with their evidence tasks (T24).
- The spec's manual exit check (two short borrels compared in `/analytics`, the xlsx totals
  checked against the database) is the user's step, per the memory notes.

---

## Data changes

One migration, `0010_phase_7_lifecycle.py` (T1). It is forward-only and expand-only (SD13).
Nothing in 0001–0009 is edited.

| Change | Columns / constraint | Backfill | Expand/contract |
|---|---|---|---|
| `product` | `product_id` identity PK, `name_key text NOT NULL` (not unique), `name text NOT NULL`, `created_at timestamptz DEFAULT now()` | One row per distinct `drink.name_key`, from that key's earliest drink | New table |
| `drink.product_id` | `bigint NULL REFERENCES product` | Every drink → its key's product | Expand only: nullable at the database, and the app always sets it (SD13). A rolled-back Phase 6 image inserts `NULL`, which analytics groups by `name_key` |
| `drink_product_live` | `UNIQUE (run_id, product_id) WHERE removed_at IS NULL` | holds after backfill: active `name_key`s are unique per run (`drink_name_live`) | Additive; `NULL`s are distinct, so an old image's inserts never conflict |
| `order_line.bar_price_cents` | `integer NULL CHECK (>= 0)` | From the line's drink's current value (SD5) | Expand only: an old image writes `NULL`, which falls back to the drink's value |
| `export` | SD6's columns; CHECKs on `kind`, `status`, `bytes = octet_length(data)`, `done ⇒ data` | none | New table |
| `order_run_wall_ts` | `"order"(run_id, wall_ts_ms)` | — | Additive |

`downgrade()` drops them in reverse. Product identity is lost, which is correct: going back past
live data is a restore, not a migration (Phase 6's stance). The round-trip test runs on an empty
database.

**Approval note: PD1, pending the human (SD17). T10 adds these only after the answer.**

| | `xlsxwriter` (runtime) | `openpyxl` (dev only) |
|---|---|---|
| What | Writes `.xlsx` workbooks, with an `in_memory` mode onto a `BytesIO` | Reads `.xlsx`; used only by the tests that read exports back |
| Why not stdlib | The stdlib has no xlsx writer. Hand-rolling OOXML with `zipfile` and XML means hundreds of lines of format code to maintain | Same, for reading |
| Licence | BSD-2-Clause | MIT |
| Maintenance | One long-standing maintainer (John McNamara), regular releases, pure Python, no dependencies | Long-lived, slower release cadence; what v1 used (`legacy/v1`) |
| Scope | Under `app/jobs/` only. `tests/meta/test_no_file_io.py` keeps `openpyxl` out of `app/db`, `app/runtime` and (after T10) `app/jobs` | `[dependency-groups] dev` only |

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **PD1 is unanswered.** T10 cannot start, and T11, T12, T15, T21 and T23 wait behind it | T12 sits last in the route chain, so T1–T9, T13, T14 and T16–T20, T22 all proceed without it. T24 waits only for its T12 reference. The human answers SD17 at the audit |
| R2 | **CLAUDE.md "never introduce a second database engine" vs SD11's own connection** | PD2 reads it as a second database technology (ADR 0004). Marked Confirm. If it is overruled, T4 uses raw `asyncpg.connect` in `session.py` instead |
| R3 | **A ticker waiting on the lock during a close** would get `NoLiveRunError`, which `_guarded` does not catch, and the ticker task would die | T5 makes it an idle slot, with a test that blocks the ticker on the lock during a release |
| R4 | **The Phase 3 WebSocket flake** (memory note: `CancelledError` on ws exit) may hit T5's and T6's socket tests | Report and stop; do not retry to green |
| R5 | **AC21's timing test on Windows** could flake | Thresholds are fixed in T11 (≤ 1.5 × interval, p95 ≤ 2 × baseline). A failure is reported with numbers, not loosened |
| R6 | **xlsx stores doubles.** `Decimal(cents) / 100` written as a number becomes the nearest double | The cent gate compares `Decimal(str(cell)) * 100` to integer cents. Two-decimal values round-trip exactly through `repr`. `Summary.total_revenue` is computed from integer cents, never summed from floats |
| R7 | **Deleting a large run on the 5 s engine** | Every table it deletes from is indexed on `run_id` or the parent key (`price_tick` PK, `order_run_wall_ts`, `order_line(order_id, …)`). T7 stops if a 30 000-order delete exceeds 5 s. The heavy engine is read-only by SD11 |
| R8 | **Export rows hold `bytea`** | Bounded: per run, its finals plus three manual exports (AC24). A 60 000-line workbook is a few MB |
| R9 | **The server chain** (T6 → T7 → T8 → T9 → T13 → T14 → T12, 7 links) is the critical path | Forced by `schema.d.ts` and the matrix. T2–T5, T10, T11 and all web primitives run beside it |
| R10 | **Windows:** CRLF from text-mode Python edits; the `localhost` DSN crawls | Builders edit with the Edit tool; `.env.local` uses `127.0.0.1`; never pipe `check.sh` through `tail` (memory notes) |
| R11 | **`docs/design/` and ADR text are hard stops** (T24) | T24 stops for approval. Nothing depends on it |
| R12 | **`run.started_at` uses the database clock** while `ended_at` uses the app clock | The spec settles it: durations and alignment use the first tick's `wall_ts_ms` as `t0` (PD12, PD13). `started_at` is not read for analytics |
| R13 | **A run deleted while its export builds** | The worker's result `UPDATE` matches 0 rows and is logged (PD9). The snapshot read is unaffected (`REPEATABLE READ`) |
| R14 | **Rows from a rolled-back image** (`NULL` product, `NULL` bar price) | T10, T13 and T14 each seed such rows and assert no error (SD13) |
| R15 | **A bar order in flight when `run_closed` lands** | The server answers 409 `no_live_run` (AC4). T17 verifies the intent is terminal, not retried, and stops if it is not |
| R16 | **`asyncio.to_thread` does not release the GIL for pure-Python xlsx writing** | The event loop still gets GIL slices (5 ms switch interval), but jitter is possible on a big run. T11's timing test measures it. Options if it fails: a `ProcessPoolExecutor` (still in-memory) or a chunked build. Stop and ask |
| R17 | **PD2, PD3, PD10 and PD12 are user-visible or API-surface choices** the spec did not make | Marked Confirm; each is small to change |
| R18 | **Size.** T5, T6, T10 and T11 may each approach 400 source lines | The standard stop-and-ask above about 400 source lines, tests excluded (memory note), applies. T5 splits most naturally into server unload and the web store |
| R19 | **Working tree:** `docs/specs/phase-7-analytics.md` and `docs/plans/manual-checklist.md` show as modified with no content diff (line endings or stat only) | Nothing to commit for content. The human may `git checkout` them or commit them with this plan |

---

## Out of scope for this plan

Everything in the spec's "Out of scope", and also:
- a `GET /api/runs` list route (PD16 uses the analytics list);
- removing orphan products at the moment a draft drink is hard-deleted (PD17 sweeps them at run
  delete);
- updating the stale "Phase 7" comments in `SystemSection.tsx:11` and `FinancialPanel.tsx:6-7`,
  except where a task already edits the file (none does);
- moving the bar's revenue chart onto `bucket_s` (the bar keeps the default 60 s);
- a process-pool export build, unless T11's timing test forces it (R16);
- any change to `exchange/`, the grace rule, or what `POST /api/orders` charges.

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file
- [x] PD1 (SD17 dependency) answered by the human
- [x] PD2, PD3, PD10, PD12 confirmed or overruled

Decisions at the audit:
- **PD1 approved:** `xlsxwriter` as a runtime dependency, `openpyxl` as dev-only, per the
  approval note under Data changes. T10 may add both.
- **PD2, PD3, PD10, PD12 confirmed as written.** PD2's reading of "second database engine" (a
  second database technology, not a second `AsyncEngine` on the same DSN) stands.
- Accepted as written, despite the audit's notes:
  - AC3's 2 s bound, AC36 and the live-series half of AC31 have thin test coverage.
  - T5 (13+ files) and T19 may exceed the size limit. The standard stop-and-ask at about 400
    source lines (R18) still applies.
  - T19's stub props and T12's `export_not_ready` status are left to the builder.

Audited by: MartijnBoot (human audit, `/audit 7`)  Date: 2026-10-09
