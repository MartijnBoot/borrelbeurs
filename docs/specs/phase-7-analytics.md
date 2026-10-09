# Spec: Phase 7 — Run lifecycle, export and analytics

Status: Approved · Depends on: Phase 6 · Fixes: D-20, D-31

## Problem

v1 has no concept of an event. The earnings workbook is the de facto run boundary, and it is
rotated by accident: on reset (`legacy/v1/backend/api.py:530,534`) and on every drink add or
remove (`:644-647`, `:667-670`), so one borrel's revenue can be split across several files.
Filenames have one-second resolution (`persistence.py:82-83`), so two rotations in one second
overwrite a finalized file. There is no listing of past files and nothing can be compared across
nights.

The money reporting also carries a lie (D-20). `p0_total` and `p0_per_drink` are computed from
`BAR_PRICE`, not from `p0` (`persistence.py:145,156,189`; every caller passes `BAR_PRICE`, e.g.
`api.py:810`; the register's `api.py:770` has drifted). Worse, the bar price is not stored per
row: the *current* bar price is applied retroactively to every historical row on every read.
The earnings series has one point per sale and is rebroadcast in full (D-31,
`persistence.py:160-161`).

**What v2 has today.**

- **A run can never end.** Nothing writes `status='ended'` or `ended_at`: the only status
  writes are `app/db/runs.py:148-152` (draft) and `:457-461` (live). `create_run` refuses while
  a run is live (`app/db/runs.py:389-391`), so after the first go-live `POST /api/runs` is 409
  forever, and a restart reloads the same live run (`app/runtime/rehydrate.py:80`).
- **The holder cannot unload.** `adopt` is the only way in (`app/runtime/holder.py:368-382`);
  nothing returns it to empty. The ticker stops only at shutdown (`app/runtime/ticker.py:104-113`).
  There is no WebSocket message for "run ended" (`app/realtime/messages.py:254-266`).
- **No bar price per sale.** `order_line` holds `unit_price_cents`, `line_total_cents` and
  `p_cont` only (`app/db/models.py:193-212`). `drink.bar_price_cents` is editable mid-run
  (`app/runtime/drinks.py:115`, `app/db/runs.py:209-230`); the only history is
  `run_config_revision`, in four different JSON shapes. Any `bar_price_total` joined to `drink`
  today would repeat v1's retroactive lie. `MarketView.bar_price_cents` is maintained but read by
  nothing.
- **No drink identity across runs.** `drink_id` is per run, and `create_run` copies no drinks.
  The only link between "Bier" in two runs is `name_key` (`app/db/runs.py:140-142`), which a
  rename breaks. `docs/design/data-model.md:90` claims cross-event analytics works "because
  `drink` carries identity", which holds only inside one run.
- **No export.** No export code, no xlsx dependency (`pyproject.toml:18-47`), no worker; the web
  names the gap (`web/src/features/settings/SystemSection.tsx:11`,
  `web/src/features/bar/FinancialPanel.tsx:6-7`). `tests/meta/test_no_file_io.py:37` bans file
  I/O and `openpyxl` under `app/db` and `app/runtime`.
- **The series endpoint serves the live run only.** `GET /api/earnings/series` has no
  parameters (`app/api/earnings.py:30-40`; query `app/db/orders.py:170-200`, 60 s buckets).
  `order.run_id` and `order.wall_ts_ms` are unindexed; the schema's only secondary indexes are
  `run_one_live`, `drink_name_live` and `market_event_active`.
- **Every statement dies after 5 s** (`database_timeout_seconds`, `app/db/session.py:16-21`). An
  export or analytics query over a whole run on the shared engine would be killed.
- **No analytics UI.** `ROLE_ROUTES` (`app/api/security.py:125-129`) has no analytics route, and
  no run list or comparison component exists.
- **Deferred to this phase by earlier specs:** run close and reset semantics (Phase 6 SD1,
  SD26), the export and the earnings download (Phase 5, Phase 6 SD26), the bar-price aggregate
  and D-20 (Phase 2 SD12), run list, switching and deleting (Phase 6 out of scope), copying a
  past run's drinks into a new one (Phase 6 out of scope).

## Decisions

**Settled at the spec interview (2026-10-09).** The human chose each option below.

- **SD1 — Drinks gain a persistent identity: `product`.**
  - New table `product(product_id, name_key, name, created_at)`. `drink.product_id` references it.
    `name_key` is the `name_key` of the name the product was created with; it is **not** unique.
  - Adding a drink resolves its `name_key` to the most recently created product with that key
    that has no *active* drink in this run; otherwise it creates a product. Re-adding a removed
    drink's name therefore lands on the same product; two active drinks of one run never share a
    product (partial unique index `(run_id, product_id) WHERE removed_at IS NULL`).
  - **A rename keeps the drink's product.** History stays joined.
  - Analytics key on `product_id`, never on a name. A product with several drinks in one run
    (removed, then re-added) is summed in revenue tables.
  - The admin never sees "product"; it is an analytics key.
  - A migration backfills existing drinks by `name_key`. It is expand-only (see SD13).
- **SD2 — Closing a run unloads it in-process.**
  - `POST /api/runs/{run_id}/close` (admin) body `{confirm_name}`. In one transaction, under the
    state lock: `status = 'ended'`, `ended_at` from the **app clock** (not `now()`; `started_at`'s
    database clock is a known mismatch, so durations and alignment in this phase use the run's
    first `price_tick` `wall_ts_ms` as `t0` and `ended_at` as the end), every open market event
    ended, and the final export row created (SD6).
  - After the commit, still under the lock, the holder returns to empty, the ticker idles, the
    hub clears its replay log, and every client is sent a new broadcast `run_closed
    {run_id, name, ended_at_ms}`. The engine state and running jumps stay in the database as they
    were; an ended run is never rehydrated.
  - **Clients:** koers shows a calm "Borrel afgelopen" screen; the bar disables its pad
    ("Geen actieve borrel"); home shows "Geen actieve borrel". No reload. A client connecting
    later gets `hello` with `run_id: null`, as today.
  - **Confirmation:** a `ConfirmDialog` where the admin must type the run's name. The server
    checks `confirm_name` too, so a stray API call cannot close a borrel.
  - **Refuses:** 422 `name_mismatch`; 409 `run_not_live` for a draft or ended run; 503
    `shutting_down` while draining.
  - Closing is irreversible. There is no reopen.
  - An ADR 0003 addendum records the mirror of Phase 6's go-live: the single writer can now
    release its run mid-process.
- **SD3 — Ended runs are permanent unless deleted.** They can be viewed, compared and exported,
  never reopened.
  - `DELETE /api/runs/{run_id}` (admin) body `{confirm_name}`, for an `ended` or `draft` run. A
    live run is 409 `run_live`.
  - One transaction removes every row of the run (orders, lines, ticks, news, events, revisions,
    drinks, engine state, exports) and any `product` left with no drinks. It touches nothing of
    another run.
  - The UI asks the admin to type the run's name.
- **SD4 — No in-run reset. "Reset spel" does not return.**
  - A fresh start is close, then "Nieuwe borrel". Price-only returns to `p0` stay the
    "Terug naar start" market event (Phase 6 SD22).
  - `POST /api/runs` gains optional `copy_from_run_id`. The new draft gets the source run's
    **active** drinks with new `drink_id`s and the **same `product_id`s**, in slot order, with
    bounds, `p0`, `a/d/s0/c` and bar price, and its `params` (instead of the latest run's).
    No orders, ticks, news or events are copied. The "Nieuwe borrel" form gets a select "kopieer
    drankjes uit".
  - This supersedes Phase 6 SD2's "No drinks" for the copy case only. `live_run_exists` and
    `draft_exists` still apply.
- **SD5 — The bar price is snapshotted per sale (D-20).**
  - `order_line.bar_price_cents`: the drink's `bar_price_cents` read inside the order transaction.
    A migration backfills existing rows from the drink's current value.
  - `bar_price_total` = Σ `qty × bar_price_cents`; `bar_price_per_drink` likewise. They mean
    "what these sales would have earned at the bar price in force when each sold".
  - The charged price is untouched. Phase 5's property test (price displayed = price charged)
    stays green.
  - `p0_total`, `p0_per_drink` and `p0_*` appear nowhere in the API, export or UI.
- **SD6 — Exports are rows in Postgres, built by one worker.**
  - `export(export_id, run_id, kind manual|final, status queued|running|done|failed, requested_by,
    data bytea, sha256, bytes, line_count, total_cents, error, created_at, started_at,
    finished_at)`. Same spirit as Phase 6's `asset`: no filesystem, so it works offline and on
    Render.
  - The worker lives in `app/jobs/export_xlsx.py`. It reads on its **own connection**, never the
    pool the order path uses, in a `REPEATABLE READ` read-only transaction (one consistent
    snapshot) with a longer statement timeout (SD11). It builds the workbook in memory inside
    `asyncio.to_thread`.
  - **Concurrency:** at most one export runs. A manual request for a run that already has a
    queued or running export returns *that* row. A manual request for another run takes the one
    queue slot. Beyond that: 409 `export_busy`. **A final export (SD2) is never refused**: its
    row is created in the close transaction and queued behind whatever runs.
  - **Failure and restart:** a failed build records `error` and leaves the run as it is. At boot,
    rows left `queued` or `running` become `failed` ("onderbroken"); an admin requests again.
    Shutdown does not wait for a running export.
  - **Retention:** every export is kept until its run is deleted, except that a completed
    *manual* export beyond the three newest of its run is deleted when a new one completes. Final
    exports are never pruned.
  - The host-directory copy and `pg_dump` belong to Phase 8, which owns the bind mount.
  - Allowed on a live run, in which case it covers the orders committed at the snapshot.
- **SD7 — Exports and analytics are admin-only.** Bar and display get none of it. The bar's
  financial panel gets no download link. The only bar-visible earnings surface stays the live
  run's `GET /api/earnings/series` (SD9).
- **SD8 — The workbook is v1-shaped and extended.**
  - **`Sales`:** one row per order line. v1's headers and order where v2 can fill them:
    `ts_iso, ts_ms, drink, qty, unit_price, total_price, p_cont, p_min, p_max`, then
    `order_id, drink_id, bar_price, version`. Euros are numbers with exactly two decimals,
    converted from integer cents by `Decimal`, never float arithmetic.
  - **`Per drink`:** per product — name, `qty`, `revenue`, `bar_price_total`, average price.
  - **`Summary`:** run name, started, ended, `total_revenue`, `total_qty`, `bar_price_total`,
    line count, generated-at.
  - `Summary.total_revenue` equals `Σ line_total_cents / 100` exactly.
  - **Where v1's columns cannot be filled faithfully** (see "Decided without asking"): v1's
    `round` (`t_round`) is not stored per order and is replaced by `version`; `drink`, `p_min`
    and `p_max` carry the drink's value **at export time**.
- **SD9 — The earnings series takes a run and a bucket size (D-31).**
  - `GET /api/earnings/series?run_id=&bucket_s=` — `run_id` defaults to the live run; `bucket_s`
    is one of 60, 300, 900 (default 60). Bucketed in SQL as today (bucket end, cumulative), so
    the size is bounded by run duration over bucket size, not by order count.
  - Bar and admin may read the live run's series. Any other `run_id` is admin-only (bar gets
    403). An unknown run is 404. A run without orders returns `[]`.
  - Migration adds an index on `order(run_id, wall_ts_ms)`.
- **SD10 — `/analytics` is one admin page that compares exactly two runs.**
  - **Run list:** per run — name, status, start, end, duration, revenue, bar-price revenue,
    quantity. Rows select for detail, compare, export and delete.
  - **Run detail:** the per-product table (quantity, revenue, bar-price revenue, average price,
    removed drinks included), the earnings series with a 1 / 5 / 15 minute picker, and the export
    button with its status.
  - **Compare (A and B):** per-product revenue and quantity side by side, matched on
    `product_id` (a product in one run only shows an empty other side), plus a **price-curve
    overlay** for one chosen product, aligned to minutes since each run's `t0`, bucketed in SQL
    (60 / 300 / 900 s). A bucket containing a `gap` tick has no price, so the line breaks.
  - A product with several drinks in a run uses its most recently added drink for the curve;
    earlier drinks' sales still count in the tables.
  - Charts use the bundled `lightweight-charts`. No new frontend dependency.

**Decided without asking.** These follow from the answers above or from existing decisions. The
human may overrule any of them at spec approval.

- **SD11 — Heavy reads use their own connection and timeout.** One setting in
  `app/core/config.py`, default 60 s, applies to export and analytics queries. The 5 s timeout
  stays for the live path. Both are read-only.
- **SD12 — Analytics routes, all admin and GET:** `/api/analytics/runs`,
  `/api/analytics/runs/{run_id}`, `/api/analytics/compare?a=&b=`,
  `/api/analytics/price-curve?product_id=&a=&b=&bucket_s=`. Export routes:
  `POST /api/runs/{run_id}/exports` (202), `GET /api/runs/{run_id}/exports`,
  `GET /api/exports/{export_id}`, `GET /api/exports/{export_id}/file`. The file response sends the
  xlsx content type, `Content-Disposition` with `borrel-<slug>-<yyyymmdd-hhmm>.xlsx`, and
  `X-Content-Type-Options: nosniff`. The export page polls status every 2 s while an export is
  queued or running; no WebSocket message. `POST` routes answer 503 `shutting_down` while
  draining; `GET` routes still work. `/analytics` is added to the admin entry of `ROLE_ROUTES`
  and to the nav.
- **SD13 — Migrations are expand-only** so Phase 8 AC8 (rollback to the previous image) holds:
  `product_id` and `order_line.bar_price_cents` are nullable at the database, the application
  always sets them, and analytics must not error on a row written by a rolled-back image (a
  NULL-product drink groups by its `name_key`; a NULL bar price falls back to the drink's
  current value). Indexes and the `export` table are additive.
- **SD14 — Shutdown is not close.** "Sluit app" leaves the run `live`, as in Phase 3 and
  Phase 6; the next boot rehydrates it with the gap rule. Only the explicit close ends a borrel.
- **SD15 — `ts_iso` is UTC.** The app has no timezone setting; a naive local stamp (v1) is wrong
  on a laptop whose clock zone was never set. `ts_ms` carries the exact instant.
- **SD16 — A close and an order serialise on the state lock.** An order commits before the close
  (and is in the final export) or finds the holder empty and gets 409 `no_live_run`. No order of
  a run has a `wall_ts_ms` after its `ended_at`.
- **SD17 — Dependency.** Writing xlsx needs a library, and CLAUDE.md requires asking first.
  Candidates: `xlsxwriter` (BSD, write-only, in-memory mode, fast) or `openpyxl` (MIT, what v1
  used, read/write). **Recommendation: `xlsxwriter`**, since the export only writes and the
  verification test reads the file back with `openpyxl` as a dev dependency. *Pending the
  human's approval; the planner must not add either until this is answered.*

## In scope

- **Server:**
  - close, delete and copy-from on runs (SD2–SD4);
  - the `run_closed` message and the holder's unload (SD2);
  - the order path's `bar_price_cents` write (SD5);
  - `product` and its resolution on add, copy and rename (SD1);
  - the export table, worker and routes (SD6, SD8, SD12);
  - the series endpoint's parameters (SD9);
  - analytics routes (SD10, SD12);
  - the heavy-read connection and setting (SD11);
  - regenerated OpenAPI types and Zod fixtures for `run_closed`.
- **Persistence (expand-only migrations, SD13):** `product` and `drink.product_id` with its
  backfill; `order_line.bar_price_cents` with its backfill; `export`; the `order(run_id,
  wall_ts_ms)` index; the partial unique index on `drink(run_id, product_id)`.
- **Web:**
  - `features/analytics` and the `/analytics` route;
  - "Borrel afsluiten" and the copy-from select in the Borrel section;
  - the closed-run states on koers, bar and home;
  - the typed-name `ConfirmDialog` variant.
- **Documents:**
  - an ADR 0003 addendum (close);
  - `data-model.md` (`product`, `export`, `order_line.bar_price_cents`, the `ended` semantics, the
    new indexes, a corrected "identity" claim at line 90);
  - `realtime-protocol.md` (`run_closed`);
  - `architecture.md` (`app/jobs/`, the heavy-read connection);
  - the defect register (a Phase 7 evidence table, as Phase 6 has);
  - the Phase 6 spec's out-of-scope list and SD26 (reset is gone, not deferred);
  - `docs/plans/manual-checklist.md` (the exit check).

## Out of scope

- An importer for v1 workbooks. Comparison starts with the first v2 borrel; old workbooks stay
  files.
- Reopening an ended run, a reset or void inside a run, per-order voiding or refunds, switching
  runs other than close then new.
- Comparing more than two runs, bar or display access to analytics or exports, scheduled or
  emailed exports, CSV or PDF, a BI tool or dashboard framework.
- The `pg_dump` timer, the host-directory copy of an export, the offline bundle (Phase 8).
- Any change to pricing, or to what the order path charges.
- Pruning `price_tick`, the never-written `idle` source, and the unwritten
  `run.tick_interval_ms` / `quote_grace_versions` (found in the audit, not this phase's).
- A WebSocket push of export status or analytics.
- Editing an ended run's config (still 409 `run_ended`).
- Fixing v1 in `legacy/v1/`.

## Acceptance criteria

**Closing a run**

- **AC1.** When an admin closes a live run with a matching `confirm_name`, the system shall in
  one transaction set `status = 'ended'` and `ended_at` from the app clock, end its open market
  events and create its final export, then unload the holder so the ticker writes no further tick
  for that run.
- **AC2.** When `confirm_name` does not match the run's name, the system shall return 422
  `name_mismatch`; when the run is a draft or ended, 409 `run_not_live`; while draining, 503
  `shutting_down`. Each shall change nothing.
- **AC3.** When a run is closed, every connected client shall receive `run_closed` within 2 s
  and, without a reload, koers shall show "Borrel afgelopen", the bar pad shall be disabled, and
  home shall show "Geen actieve borrel".
- **AC4.** When orders race with a close, every order shall either commit with `wall_ts_ms` ≤ the
  run's `ended_at` and appear in the final export, or return 409 `no_live_run`. No order shall
  commit after the close.
- **AC5.** When a run is closed and a new one created, the previous run's orders, ticks, news and
  order lines shall remain queryable and unchanged. `POST /api/runs` shall succeed where it was
  409 `live_run_exists` before.
- **AC6.** When the app restarts after a close, it shall boot with no live run and the ended run
  unchanged; any export left `queued` or `running` shall become `failed`.
- **AC7.** When the final export cannot be built, the run shall stay `ended` and the failure
  shall show on the run, with a way to request again.

**Delete and copy**

- **AC8.** When an admin deletes an ended or draft run with a matching `confirm_name`, the system
  shall remove every row of that run, and every `product` no drink references any more, and shall
  change nothing of any other run. A live run shall be 409 `run_live`; a mismatch 422
  `name_mismatch`.
- **AC9.** When a draft is created with `copy_from_run_id`, it shall hold the source run's active
  drinks with new `drink_id`s and the same `product_id`s, with their bounds, `p0`, coefficients
  and bar prices, and the source's `params`; it shall hold no order, tick, news or event. An
  unknown source shall be 404.

**Identity — old AC9**

- **AC10.** When two runs contain a drink of the same name, their drinks shall share a
  `product_id`; when a drink is renamed, it shall keep its `product_id`; no run shall have two
  active drinks with one `product_id`; and the migration shall give every existing drink a
  product by `name_key`.
- **AC11.** When two runs are compared and a drink was renamed in one, the comparison shall still
  show it as one product row. A test shall fail if the join falls back to a name string.

**Bar price — D-20**

- **AC12.** When an order line is written, the system shall store the drink's current
  `bar_price_cents` on it. When the drink's bar price is changed afterwards, no earlier line's
  `bar_price_cents` and no earlier `bar_price_total` shall change. *(D-20)*
- **AC13.** When revenue at the fixed bar price is reported, in any API response, the workbook or
  the UI, the system shall name it `bar_price_total` / `bar_price_per_drink`. The strings
  `p0_total` and `p0_per_drink` shall appear in no served schema, export or web source. *(D-20)*
- **AC14.** When orders are placed, the charged price shall be unchanged by this phase: Phase 5's
  money property test shall stay green with the new column written.

**Earnings series — D-31**

- **AC15.** When the earnings series is requested, the system shall bucket it in SQL and return
  at most one point per bucket that holds an order, so its size is bounded by run duration over
  `bucket_s` regardless of order count. A test with thousands of orders in a short window shall
  assert the bound. *(D-31)*
- **AC16.** When `run_id` is another run than the live one, the system shall allow admin only
  (bar 403); an unknown run shall be 404; `bucket_s` outside {60, 300, 900} shall be 422; a run
  with no orders shall return `[]`.

**Export**

- **AC17.** When an export is requested, the system shall return 202 immediately with a `queued`
  export and produce the file asynchronously.
- **AC18.** When an export completes, `Summary.total_revenue`, the sum of the `Sales` totals and
  `export.total_cents` shall all equal `SELECT sum(line_total_cents)` of the run at the export's
  snapshot, to the cent; `bar_price_total` shall equal `Σ qty × bar_price_cents`.
- **AC19.** When drinks are added or removed mid-run, the export shall still be one file covering
  the whole run, with removed drinks' lines present. *(v1's workbook rotation, `api.py:644-670`)*
- **AC20.** When an export is requested for a run that already has one queued or running, the
  system shall return that export. When another run's export runs and the slot is free, it shall
  queue; when the slot is taken, 409 `export_busy`. A final export shall never be refused.
- **AC21.** While an export is running, the system shall continue ticking at its cadence and
  serving orders with no stall. A timing test under order load shall assert tick spacing and
  order latency are unaffected.
- **AC22.** When a run has no orders, the export shall be a valid workbook with its headers and
  zero totals.
- **AC23.** When the export is requested on a live run, it shall cover exactly the orders
  committed at its snapshot.
- **AC24.** When a fourth manual export of a run completes, the oldest completed manual export of
  that run shall be deleted; final exports shall never be.
- **AC25.** When a non-admin calls any export or analytics route, the system shall return 403.
  The file response shall carry the xlsx content type, a `Content-Disposition` filename and
  `X-Content-Type-Options: nosniff`.

**Analytics**

- **AC26.** When the run list is requested, each run shall show its revenue, bar-price revenue,
  quantity and duration. Duration shall run from the run's first `price_tick` to its `ended_at`.
- **AC27.** When a run's detail is requested, the per-product table shall include removed drinks
  that sold, and its totals shall equal the database's Σ `line_total_cents`.
- **AC28.** When two runs are compared, the system shall return per-product revenue and quantity
  for both, with an empty side for a product in one run only.
- **AC29.** When a price curve is requested for a product and two runs, the system shall bucket
  it in SQL, align each run to minutes since its start, and leave a break in any bucket holding a
  `gap` tick. Its size shall be bounded by duration over `bucket_s`.
- **AC30.** When a run has no orders, or a product is absent from one run, every analytics view
  shall render an empty state rather than an error. *(old AC10)*
- **AC31.** When export or analytics queries run against a run with tens of thousands of orders,
  they shall complete within the heavy-read timeout and shall not use the live path's 5 s
  connection.

**Web, roles and safety**

- **AC32.** When the admin closes or deletes a run, the `ConfirmDialog` shall require typing the
  run's name, in Dutch ("Typ de naam '{name}' om te bevestigen"), and shall never call native
  `confirm`/`alert`.
- **AC33.** When an admin opens `/analytics`, they shall see the run list, a run detail with its
  export state, and a compare view of two runs with a price-curve overlay. A bar or display
  session shall not see the route.
- **AC34.** Every route this phase adds shall have an explicit authorization dependency and a
  row in the authorization matrix test.
- **AC35.** While the app is draining, every write route this phase adds shall return 503
  `shutting_down`; the export download and analytics reads shall still work.
- **AC36.** When the app runs with no network, the export and analytics shall work, and the
  built output shall make no request that leaves the origin.
- **AC37.** When "Sluit app" is used, the live run shall stay `live` and be rehydrated at the next
  boot. *(regression)*

## Verification

- **The D-20 gate, written first as a failing test.** Place orders, change a drink's bar price,
  place more, then assert the earlier lines' `bar_price_cents` are unchanged and `bar_price_total`
  is the per-line sum (AC12–AC13).
- **The cent gate.** An integration test seeds a run, exports it, reads the workbook back and
  asserts its totals equal `SELECT sum(line_total_cents)`, including a run with a mid-run add and
  remove and a run with no orders (AC18, AC19, AC22).
- **Close.** Integration test: a close racing a stream of orders (AC4); the holder empty and the
  ticker silent afterwards; a restart after close (AC5–AC6); a `run_closed` frame to a connected
  WebSocket client (AC3).
- **Export concurrency.** Coalescing, the queue slot, `export_busy`, a final export under load,
  and a boot with an interrupted row (AC7, AC20). **Timing test:** trigger an export under load
  and assert tick cadence and order latency are unaffected (AC21).
- **Identity and delete.** Rename a drink in one run and assert the compare row still joins; copy
  a run and assert the same `product_id`s; delete a run and assert no row of another run moved
  (AC8–AC11).
- **Seed two complete synthetic runs** and exercise the run list, detail, compare and price-curve
  views, including empty states (AC26–AC30).
- **Series bound.** Thousands of orders, assert the point count (AC15).
- **Authorization matrix rows** for every new route (AC25, AC34); draining returns 503 (AC35).
- **Vitest and component tests:** the typed-name dialog, the closed-run states on koers, bar and
  home, the compare view with an absent product, and the export status poll.
- **Playwright (in the gate):** from an empty database, create a borrel, add three drinks, go
  live, take orders from a bar context, change a bar price, add a drink, then close with the typed
  name. A second context logged in with a display key sees "Borrel afgelopen". Create a new borrel
  copying the first's drinks, take orders, close it, open `/analytics`, compare the two, download
  an export and delete one run.
- **Manual (exit check):** run two short borrels, compare them in `/analytics`, export the xlsx and
  check its totals against the database.

## Exit condition

Two past borrels are comparable in the UI, and a generated xlsx matches the database to the cent.
