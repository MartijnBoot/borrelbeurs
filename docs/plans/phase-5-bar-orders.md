# Plan: Phase 5 — Bar page and the order path

Spec: [docs/specs/phase-5-bar-orders.md](../specs/phase-5-bar-orders.md) · Status: Audited — PASS (human, 2026-10-05)
Design: [frontend-architecture.md](../design/frontend-architecture.md) ("The bar order path", "State"), [realtime-protocol.md](../design/realtime-protocol.md), [data-model.md](../design/data-model.md)
ADRs honoured: 0004 (Postgres only), 0006 (bundle everything, lightweight-charts v5), 0008 + addendum (honour the quoted price; the client conforms, the server is unchanged), 0009/0010 (hard stops: new dependency, `docs/design/`, user-visible spec ambiguity)
Fixes: D-05 · Brings forward Phase 7 AC6 (D-31)

---

## Approach

**One structural invariant, then UI on top of it.** D-05 dies by construction, not by care.
A `Quote` is a branded, frozen record that only one module,
`features/exchange/model/quote.ts`, can build, and only from **one** message (T4). The reducer
stamps it with the monotonic receipt time passed in by the client, so `applyMessage` stays
pure. The bar feature is then built as pure, timer-injected models, each unit-tested
under fake timers:
- the hold buffer (T6);
- the order-intent machine: send, retry, 409 queue, confirm, cancel, unknown (T7);
- the revenue-series adapter (T13).

A single `barController` (T8) is the **only** code path from a tap to a request body: it reads
the displayed `Quote` from the hold buffer and hands it to the intent machine. The SD20
property test drives that controller, the real reducer and the real models over 10 000+
random interleavings. It asserts AC1, AC9, AC10 and AC13 on every request the fake
transport sees. The React components (T10–T15) are thin bindings over those models. Server
work is one read-only endpoint, `GET /api/earnings/series` (T1): a SQL window over
`order_line ⋈ order`, outside the holder's lock. There is also one real-process proof that a
same-key retry after a restart replays (T17). There is no migration and nothing touches
`exchange/`.

Rejected:
- **Keeping `version` and `prices` as separate store fields and "being careful".** That is
  v1's design. AC2 asks for a test that fails if two messages are combined, and only a
  single constructor module plus a brand gives that test something to check (PD2).
- **Calling `performance.now()` inside the reducer.** It breaks the reducer's purity
  (`applyMessage.ts:2`) and makes the property test non-deterministic. The client passes
  `receivedAt` in (PD1).
- **Holding the displayed quote in the store.** The hold is per-page interaction state, not
  market state. The store holds the latest `Quote`; the bar feature holds the displayed one.
- **`fast-check`.** SD20 forbids it. A seeded mulberry32-style PRNG in the test file does the
  job.
- **Recomputing revenue client-side for the chart.** AC17 forbids it. Live chart points are
  the store's Σ `revenue_cents` after each server `order` message.
- **Importing `koers/ui/chartOptions.ts` from `bar`.** Sibling features are isolated
  (`eslint.config.js:84-98`). T14 moves the shared chart theme to `src/lib/chartTheme.ts`
  instead of copying it.
- **A Playwright test for AC26 (restart mid-retry).** The e2e harness runs one server for the
  whole suite and cannot restart it. AC26 is proven in two halves: T17 replays a same-key
  order after a real process restart, and T7/T8 resolve a 503 → 200 replay as one accepted
  order and rebuild from the new `boot_id`'s snapshot.

---

## Decisions this plan makes

PD7, PD11, PD12 and PD13 set user-visible behaviour the spec leaves open. **The audit must
confirm them** (ADR 0009: spec ambiguity that changes user-visible behaviour).

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | Where `Quote.receivedAt` comes from | `applyMessage(state, message, receivedAt)` and `applyPolledState(state, data, receivedAt)` take it as a parameter. `createExchangeClient` gets a new dep `monotonicNow(): number`, which `app/providers.tsx` binds to `performance.now`. The existing `now` (wall clock, used for skew) is unchanged | Keeps the reducer pure (`applyMessage.ts:1-4`) and the property test deterministic |
| PD2 | How AC2's "a test shall fail" is made real | `quote.ts` exports the `Quote` type with a `unique symbol` brand and the only builders: `quoteFromSnapshot(data, at)`, `quoteFromTick(msg, at)`, `quoteFromOrder(msg, at)`, `quoteFromPriceChanged(body, at)`. Each takes **one** message or body and returns `Object.freeze`d data with frozen `prices`. A Vitest source scan (`quote.provenance.test.ts`) fails if any file under `web/src` other than `quote.ts` contains `as Quote`, `<Quote>` or a call to a `quoteFrom*` builder outside `applyMessage.ts` and `features/bar/model/orderIntents.ts` | A brand makes a hand-built `Quote` a type error; the scan catches the cast escape hatch. The property test (T8) adds the runtime half: every posted `(quote_version, unit_price_cents)` pair matches one recorded message |
| PD3 | How the bar knows a quote arrived by `snapshot` (SD3 force-promote) | The store already bumps `snapshotGen` on every snapshot, WS or poll (`applyMessage.ts:186`). The controller force-promotes when `snapshotGen` changes | Reuses the existing signal the koers chart already uses (`DrinkChart.tsx:84`) |
| PD4 | Tick or order envelope with `version: null` | No new `Quote`; the latest stays. The server never sends one for a tick or an order with a live run, and a test pins this | The envelope types `version` nullable (`schemas.ts:140`) for non-run messages; a quote without a version cannot be honoured |
| PD5 | Store additions | `quote: Quote \| null`, `earnings: Record<DrinkId, {qty, revenue_cents}>`, `lastOrderTsMs: number \| null` (the in-sequence `order` envelope's `ts_ms`, for the live chart point, SD16). A snapshot replaces `earnings` wholesale and sets `lastOrderTsMs` to `null`. A new `boot_id` resets all three through `initialState` | SD15 and SD16. `lastOrderTsMs` lets the chart tell "an order applied" from "a snapshot replaced" without a second subscription channel |
| PD6 | `lib/http` for orders | `request` gains optional `headers` and `signal`. `HttpError` gains `details: Readonly<Record<string, unknown>>`: the parsed `error` object, so a 409's `version` and `prices` survive. A network failure or timeout still rejects with the original error, which the intent machine classifies | `ErrorEnvelope` is already `looseObject` (`http.ts:13`); today the extras are parsed and then dropped |
| PD7 | Pending-entry lifetimes (SD10) | "besteld" lingers 3 s, then goes. "Geannuleerd" lingers 3 s. "Fout bij bestellen" (422) lingers 3 s. "Onbekend" stays until "Opnieuw" or "Sluiten". "Sluiten" replaces the entry with "Mogelijk toch geboekt — controleer de omzet" for 3 s. **Confirm at the audit** | SD10 gives 3 s for success only; one lifetime for every transient state is the simplest reading |
| PD8 | The one path from tap to request | `features/bar/model/barController.ts`: `press()`, `release()`, `tap(drinkId)`, `refresh()`, and `confirm()`/`cancel()` for the head conflict. `tap` reads `holdBuffer.displayed` **once**, synchronously, and passes that `Quote` to `intents.create`. Components call only the controller, through `useBarController` | Gives the property test the same code path the UI uses, so AC1 is tested on the real wiring |
| PD9 | When a 409 force-promotes | On arrival (SD3), even if its dialog is queued behind another. The dialog shows the price from **its own** 409 body (SD9), not the store | SD3 lists "a 409"; SD9 fixes the dialog's record |
| PD10 | Press events | `pointerdown` and a `keydown` of Enter or Space start a press. `pointerup`, `pointercancel`, `pointerleave` and `keyup` end it. `click` is the tap. The press starts before `click` fires, so the tap reads a quote that is already held | Matches SD1's "pointer down, or keyboard activation"; `pointerleave` stops a dragged-off finger holding forever (`HOLD_MAX_MS` caps it anyway) |
| PD11 | "Opnieuw" on an Onbekend entry | One attempt with the same key and body. A network error, timeout or 503 returns it to Onbekend; there are no automatic retries the second time. **Confirm at the audit** | SD8 says "the same key and body" and nothing more; restarting the 1-2-4 s schedule behind a manual press would hide it for 7 s |
| PD12 | Series buckets (SD16) | Bucket end = `(wall_ts_ms / 60000) * 60000 + 60000` on `order.wall_ts_ms`. **Only buckets that contain an order** are returned, and the cumulative value comes from `sum(sum(line_total_cents)) OVER (ORDER BY bucket)`. With no orders the response is `[]`. **Confirm at the audit**: the line between two sparse points slopes rather than steps | Bounded by run length / 60 s either way (AC20). Emitting empty buckets would need `generate_series` and the run's start time, for a visual nicety |
| PD13 | Revenue line colour | `--accent` for the line. The grid and axis text use `--grid` and `--muted` through the shared `chartColors` (v1's hardcoded `#1a2744` / `#9aa7bd`, `bar.html:320-321`, are exactly those tokens in Blauw). **Confirm at the audit** | v1 leaves the line at Chart.js's default; a token is required (SD18) and `--accent` is the manifest's emphasis colour |
| PD14 | Shared chart theme | `BASE_OPTIONS` and `chartColors` move from `features/koers/ui/chartOptions.ts` to `src/lib/chartTheme.ts`. `chartOptions.ts` re-imports them; the candle and SMA pieces stay in koers | Avoids a duplicated `chartColors` across sibling features |
| PD15 | `≤640 px` detection (SD17) | A `useMediaQuery('(max-width: 640px)')` hook in `features/bar` (`window.matchMedia` with a `change` listener). `RevenueChart` is not rendered at all when it matches, so it neither constructs a chart nor fetches | Nothing equivalent exists in the web code today; CSS-only hiding is v1's bug (`bar.html:34`) |
| PD16 | AC17's lint rule | `no-restricted-syntax` selectors, added to the shared list: (a) any `Identifier[name='computeLocalEarnings']`; (b) a `BinaryExpression[operator='*']` with an operand that is or ends in an identifier or member whose name matches `/qty\|quantity/i`. Test files (`*.test.ts(x)`, `e2e/`) are exempt | "A lint rule or test for AC17" (spec Verification). (b) is the shape of `computeLocalEarnings` (`bar.html:200-205`) |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `app/db/orders.py` | Modify | `earnings_series(conn, run_id, bucket_ms=60_000)` — SQL bucketing (PD12) | T1 |
| `app/api/earnings.py` | Create | `GET /api/earnings/series`, bar + admin, 409 `no_live_run` | T1 |
| `app/main.py` | Modify | Include the earnings router | T1 |
| `tests/api/test_authorization_matrix.py` | Modify | SD1 row `("GET", "/api/earnings/series"): WRITERS` | T1 |
| `tests/api/test_earnings_series.py` | Create | Authorization, 409, response shape | T1 |
| `tests/integration/test_earnings_series.py` | Create | Bucketing, cumulative, bounded size, final = `SELECT sum(line_total_cents)` | T1 |
| `web/src/api/generated/schema.d.ts` | Modify (generated) | Regenerated by `scripts/gen_api_types.sh` | T1 |
| `web/eslint.config.js` | Modify | PD16 selectors | T2 |
| `web/src/lint-rules.test.ts` | Modify | Self-tests for PD16 | T2 |
| `web/src/lib/http.ts`, `http.test.ts` | Modify | PD6 | T3 |
| `web/src/features/exchange/model/quote.ts` | Create | `Quote` and its only builders (PD2) | T4 |
| `web/src/features/exchange/model/quote.test.ts` | Create | Builders, freezing, one-message provenance | T4 |
| `web/src/features/exchange/model/quote.provenance.test.ts` | Create | AC2's source scan (PD2) | T4 |
| `web/src/features/exchange/model/applyMessage.ts`, `.test.ts` | Modify | `quote` (T4); `earnings`, `lastOrderTsMs` (T5) | T4, T5 |
| `web/src/features/exchange/model/client.ts`, `client.test.ts` | Modify | `monotonicNow` dep, `receivedAt` through (PD1) | T4 |
| `web/src/features/exchange/model/selectors.ts` | Modify | `selectQuote` (T4); `selectEarnings`, `selectTotals` (T5) | T4, T5 |
| `web/src/features/exchange/model/store.ts` | Modify | `dispatch(message, receivedAt)` | T4 |
| `web/src/features/exchange/index.ts` | Modify | Export `Quote`, builders needed by bar, selectors | T4, T5 |
| `web/src/app/providers.tsx` | Modify | `monotonicNow: () => performance.now()` | T4 |
| `web/src/features/bar/model/constants.ts` | Create | `HOLD_MS`, `HOLD_MAX_MS`, `AGE_SHOW_MS`, `STALE_MS` (SD4: one module) | T6 |
| `web/src/features/bar/model/holdBuffer.ts`, `.test.ts` | Create | Pure hold buffer, injected scheduler | T6 |
| `web/src/features/bar/model/orderIntents.ts`, `.test.ts` | Create | Intent machine (SD5–SD10), injected transport/timers/uuid | T7 |
| `web/src/features/bar/api/orders.ts`, `orders.test.ts` | Create | `postOrder(key, body, signal)`; Zod `Receipt`, `PriceChangedBody` | T7 |
| `web/src/features/bar/model/barController.ts` | Create | PD8 | T8 |
| `web/src/features/bar/model/money.property.test.ts` | Create | SD20 property test | T8 |
| `web/src/features/bar/useBarController.ts` | Create | React binding: one controller per page mount | T8 |
| `web/src/components/ui/ConfirmDialog.tsx`, `.module.css`, `.test.tsx` | Create | SD9 dialog: focus trap, Escape = cancel | T9 |
| `web/src/features/bar/OrderPad.tsx`, `.module.css`, `.test.tsx` | Create | Buttons, age, staleness, Ververs | T10 |
| `web/src/features/bar/useNow.ts` | Create | 1 Hz monotonic clock for the age line | T10 |
| `web/src/features/bar/PendingOrders.tsx`, `.module.css`, `.test.tsx` | Create | SD10 list, Opnieuw / Sluiten | T11 |
| `web/src/features/bar/OrderConflict.tsx`, `.test.tsx` | Create | The head 409 in a `ConfirmDialog` | T11 |
| `web/src/features/bar/FinancialPanel.tsx`, `.module.css`, `.test.tsx` | Create | SD15 panel | T12 |
| `web/src/features/bar/model/revenueSeries.ts`, `.test.ts` | Create | Same-second merge, history/live merge | T13 |
| `web/src/features/bar/api/earningsSeries.ts`, `.test.ts` | Create | `fetchEarningsSeries()` via `lib/http` | T13 |
| `web/src/lib/chartTheme.ts` | Create | `BASE_OPTIONS`, `chartColors` (PD14) | T14 |
| `web/src/features/koers/ui/chartOptions.ts` | Modify | Re-import from `lib/chartTheme` | T14 |
| `web/src/features/bar/RevenueChart.tsx`, `.test.tsx` | Create | Stable host, imperative feed | T14 |
| `web/src/features/bar/useMediaQuery.ts` | Create | PD15 | T14 |
| `web/src/features/bar/BarPage.tsx`, `.module.css`, `.test.tsx` | Create | Layout (SD18), empty state (SD14) | T15 |
| `web/src/features/bar/index.ts` | Create | The feature's entry point: `BarPage` | T15 |
| `web/src/app/routes.tsx` | Modify | `/bar` → `BarPage` | T15 |
| `web/e2e/bar.spec.ts` | Create | Spec's Playwright list | T16 |
| `tests/integration/test_restart_replay.py` | Create | AC26 server half, real process | T17 |
| `docs/design/frontend-architecture.md`, `docs/design/realtime-protocol.md`, `docs/specs/phase-7-analytics.md` | Modify | Spec's "Document updates" | T18 |

No new dependency. `lightweight-charts`, `zod`, `zustand`, Testing Library and Playwright are
already in `web/package.json`.

---

## Tasks

Every task leaves `./scripts/check.sh` green. Branches follow `feature/phase-5-tN-<slug>`.
Nothing touches `exchange/` (Python) or the golden fixtures. Reuse, by name:
- **Server:** `app/api/deps.py` (`require_role`, `db_engine`), `app/runtime/holder.py`
  (`NoLiveRunError`, `holder.run_id`), `app/db/orders.py` (`earnings_by_drink` as the query
  shape), `app/api/state.py` as the read-endpoint shape, and `tests/api/conftest.py` /
  `tests/integration/conftest.py` fixtures. Also `tests/integration/realapp/harness.py`
  (`start_app`, `spawn_app`, the `order`/`state` client).
- **Web:** `lib/http.ts` (`request`, `HttpError`), `lib/format.ts` (`formatEuro`),
  `components/ui/Button.tsx`, `features/exchange` (store, selectors, `applyMessage`),
  `features/koers/ui/DrinkChart.tsx` and its test's `lightweight-charts` mock as the chart
  pattern, `features/koers/KoersPage.tsx` for the empty state, `features/auth/RequireRole.tsx`
  and `app/pages/NoAccess.tsx` for roles, and `web/e2e/fixtures.ts` (`loginAs`, `server`).

Web tests use `// @vitest-environment jsdom` only where a DOM is needed. Single-file runs
use `pnpm --dir web exec vitest run <path>`.

### T1 — `GET /api/earnings/series`

- **Implements:** AC20; the server half of AC19 (the database total); SD16 (history); SD19; PD12
- **Expected output:**
  - `app/db/orders.py: earnings_series(conn, run_id, *, bucket_ms=60_000) -> list[tuple[int, int]]`.
    It is one statement:
    - `GROUP BY` the bucket end over `order_line JOIN "order"`, filtered on `run_id`;
    - `sum(sum(line_total_cents)) OVER (ORDER BY bucket)`;
    - ascending; integer division on `wall_ts_ms`.
  - `app/api/earnings.py`: router `prefix="/earnings"`, `GET /series`,
    `require_role("bar", "admin")`, returning `list[EarningsPoint]` with
    `EarningsPoint{t_ms: int, cum_revenue_cents: int}` (`extra="forbid"`). It reads
    `holder.run_id` without `mutate` and queries on `db_engine(request)`. With no live run it
    raises `NoLiveRunError` (409 `no_live_run`).
  - The router is included in `app/main.py`'s `api_router`, and the matrix gets its row.
  - `web/src/api/generated/schema.d.ts` is regenerated.
- **Verification:**
  - `uv run pytest tests/integration/test_earnings_series.py tests/api/test_earnings_series.py tests/api/test_authorization_matrix.py tests/meta/test_route_authorization.py -v`;
  - integration: orders at known `wall_ts_ms` across three minutes, two in one bucket, give
    three points with the right bucket ends and cumulative values;
  - the final point equals `SELECT sum(line_total_cents) … WHERE run_id = :r`;
  - 2 000 orders in one minute give one point (bounded size);
  - another run's orders are excluded; no orders gives `[]`;
  - API: display 403, anonymous 401, bar and admin 200, no live run 409 `no_live_run`;
  - `./scripts/check.sh`, whose drift step proves the types are regenerated.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** SQL expression style (Core `select` vs `text`), test data shape,
    model names.
  - **Must stop and ask if:** the query needs an index or any schema change (there is no
    migration in this phase), or `holder.run_id` cannot be read without the lock.

### T2 — AC17 lint rule

- **Implements:** AC17; PD16
- **Expected output:** the PD16 selectors in `web/eslint.config.js`, in the shared
  `no-restricted-syntax` list, with an override that exempts `**/*.test.{ts,tsx}` and `e2e/**`.
  New cases in `web/src/lint-rules.test.ts`:
  - `const r = line.qty * line.unit_price_cents` in a feature file is flagged;
  - `qty * price` is flagged;
  - `function computeLocalEarnings() {}` is flagged;
  - `t_ms / 1000` and `a * b` are clean;
  - the same violating snippet in a `*.test.ts` path is clean.
- **Verification:** `pnpm --dir web exec vitest run src/lint-rules.test.ts`; `pnpm --dir web lint` (the current tree has no violation: `grep` finds no `qty *` in `web/src`).
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the exact selector text and message wording.
  - **Must stop and ask if:** a selector that catches both shapes also flags existing
    non-test code that is not revenue arithmetic.

### T3 — `lib/http`: headers, signal, error details

- **Implements:** the transport half of AC10 (timeout via `signal`) and AC12/AC13 (the 409's
  `version` and `prices` reach the caller); PD6
- **Expected output:** `request(method, path, {body, schema, headers?, signal?})` and
  `HttpError.details`. Existing callers are unchanged.
- **Verification:** `pnpm --dir web exec vitest run src/lib/http.test.ts`:
  - a custom header is sent;
  - an aborted signal rejects with the abort error, not an `HttpError`;
  - a 409 `{error: {code, message, version, prices}}` gives `details.version` and
    `details.prices`;
  - the existing cases still pass.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the field name (`details`), the test structure.
  - **Must stop and ask if:** an existing caller's behaviour would change.

### T4 — `Quote` in the store

- **Implements:** AC2; the reducer halves of AC1, AC25 (a polled snapshot's quote) and AC26
  (a new `boot_id` clears the quote; the next snapshot rebuilds it); SD2; PD1, PD2, PD4
- **Expected output:**
  - `features/exchange/model/quote.ts` per PD2: a branded `Quote` with `version`, `prices`
    (`Record<DrinkId, number>` of `price_cents`) and `receivedAt`, frozen with frozen
    `prices`.
  - `applyMessage(state, message, receivedAt)` sets `quote` from a `snapshot` (`data.version`,
    `data.prices[*].price_cents`), an in-sequence `tick` (the envelope `version`,
    `data.drinks[*].price_cents`) and an in-sequence `order` (the envelope `version`,
    `data.prices[*].price_cents`). A frame that is dropped (gap, stale seq, awaiting resync)
    leaves `quote` unchanged.
  - `applyPolledState` takes `receivedAt`.
  - `client.ts` gets `monotonicNow` (PD1); `providers.tsx` passes `performance.now`;
    `store.ts`'s `dispatch` takes `receivedAt`.
  - `selectQuote` is exported from the feature's `index.ts`, together with the `Quote` type
    and `quoteFromPriceChanged`, which T7 needs.
- **Verification:**
  - `pnpm --dir web exec vitest run src/features/exchange`, covering:
    - `quote.test.ts`: each builder takes one message, is `Object.isFrozen` (deeply), and
      carries exactly that message's version and prices;
    - `quote.provenance.test.ts` (PD2's scan; a planted `as Quote` in a temp copy fails it);
    - `applyMessage.test.ts`: quote per message type; a gap or stale frame does not move it;
      a new `boot_id` gives `quote: null`; a polled snapshot sets it with the given
      `receivedAt`; PD4's null version;
    - `client.test.ts`: `receivedAt` is `monotonicNow()`.
  - `./scripts/check.sh`, with the existing koers tests unchanged and green.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the brand's mechanics, helper names, how the existing tests pass
    `receivedAt` (a constant is fine).
  - **Must stop and ask if:** a `Quote` would need fields from two messages for any case
    (that would be a spec gap), or the change breaks a koers behaviour test.

### T5 — Earnings in the store

- **Implements:** AC17 (earnings come only from `snapshot.earnings` and
  `order.earnings_delta`), AC18; the store half of AC16 and AC19; SD15; PD5
- **Expected output:**
  - `earnings` is set wholesale by every `snapshot`. Each in-sequence `order` adds its
    `earnings_delta` per drink (`qty`, `revenue_cents`). `lastOrderTsMs` is set to the
    order envelope's `ts_ms`; a snapshot sets it to `null`. A new `boot_id` resets both.
  - `selectEarnings` and `selectTotals` (`{revenueCents, qty}` as sums of the server's
    numbers) are exported.
- **Verification:** `pnpm --dir web exec vitest run src/features/exchange/model/applyMessage.test.ts`:
  - snapshot sets earnings;
  - two orders add their deltas, including a drink absent from the snapshot;
  - a snapshot after any orders shows exactly its own aggregates (AC18);
  - a dropped or stale `order` changes nothing;
  - a new boot clears earnings;
  - `lastOrderTsMs` follows orders and is cleared by a snapshot.

  Also `pnpm --dir web lint`, as T2's rule holds.
- **Depends on:** T4
- **Autonomy note:**
  - **May decide alone:** selector shapes and names.
  - **Must stop and ask if:** a delta arrives for a drink not in `drinks` and the right
    behaviour is unclear. The default is to add it anyway: it is the server's number.

### T6 — Hold buffer

- **Implements:** AC4, AC5, AC6 (the buffer's `promote()`), AC7 and AC8 (age and staleness
  as pure functions); SD1, SD3, SD4
- **Expected output:**
  - `model/constants.ts` holds the four SD4 constants: `HOLD_MS = 2000`,
    `HOLD_MAX_MS = 10000`, `AGE_SHOW_MS = 8000`, `STALE_MS = 15000`.
  - `model/holdBuffer.ts`: `createHoldBuffer({ now, setTimeout, clearTimeout, onChange })`
    with:
    - `offer(latest: Quote | null)`: shown at once when not holding;
    - `pressStart()` and `pressEnd()`;
    - `promote()`: the latest becomes displayed and running timers are kept;
    - `displayed` and `latest`;
    - `dispose()`.
  - Pure helpers `ageMs(displayed, now)`, `showAge(displayed, now)` and
    `isStale(latest, now)`.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar/model/holdBuffer.test.ts` on an injected fake clock:
  - no press: every offer is displayed (AC4);
  - press → offers held → released → displayed changes exactly `HOLD_MS` after the last
    release (AC5);
  - a second press inside the hold extends it from the new release;
  - continuous presses end at `HOLD_MAX_MS` from the start (AC5);
  - `promote()` mid-hold shows the latest and the hold's timers still end it (AC6);
  - `showAge` is true only above 8 000 ms (AC7);
  - `isStale` is true above 15 000 ms on the latest (AC8);
  - `null` latest is stale.
- **Depends on:** T4
- **Autonomy note:**
  - **May decide alone:** the API shape within the above, the scheduler interface.
  - **Must stop and ask if:** SD1's "ends `HOLD_MS` after the last press is released" and
    "never more than `HOLD_MAX_MS` after it started" conflict for some sequence. They
    should not: `min` of the two.

### T7 — Order-intent machine and the order API

- **Implements:** AC3 (receipt price on the entry), AC9, AC10, AC11, AC13 (new key and the
  409 record), AC14 (conflicts queue in tap order), AC15; the client half of AC26 (a 503
  then a 200 replay is one accepted entry); SD5–SD10, SD12; PD7, PD9, PD11
- **Expected output:**
  - `api/orders.ts`: `postOrder({key, body, signal})` calls `request('POST', '/api/orders', …)`
    with the `Idempotency-Key` header and `AbortSignal.timeout(8000)`. Responses are
    validated with Zod:
    - `Receipt` (`app/runtime/orders.py:80`);
    - `PriceChangedBody` (`{version, prices: [{drink_id, price_cents}]}`, from
      `HttpError.details`).
  - `model/orderIntents.ts`: `createOrderIntents({ post, uuid, setTimeout, clearTimeout,
    onChange, onPromote })`. Its behaviour:
    - `create(quote, drink)` builds the body `{quote_version, lines: [{drink_id, qty: 1,
      unit_price_cents}]}` from that one `Quote`. It freezes the body, takes a fresh
      `uuid()` key and sends at once.
    - Retries: 1 s, 2 s, 4 s on a network error, timeout or 503, with the same key and the
      same serialised body. After that the entry is `unknown`.
    - `retry(id)` makes one attempt (PD11); `dismiss(id)` follows PD7.
    - A 2xx gives `accepted` with the receipt's `unit_price_cents` and calls `onPromote`.
    - A 409 calls `onPromote`, builds the record with `quoteFromPriceChanged`, and queues a
      conflict in tap order.
    - `confirm()` creates a new intent from the head conflict's record (new key);
      `cancel()` sends nothing and marks it cancelled.
    - A 422 gives `failed`, with no retry. A 401 leaves the entry in flight; `lib/http`
      sends the page to login (SD12).
    - Exposes `entries` and `headConflict`.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar/model/orderIntents.test.ts src/features/bar/api/orders.test.ts`, on fake timers with a scripted `post`:
  - two creates within 100 ms on one drink give two posts with distinct keys (AC9);
  - network, timeout and 503 retry at +1, +2, +4 s with identical key and body string; the
    fourth failure gives `unknown`; a 200 on retry gives one `accepted` (AC10, AC11, AC26);
  - `retry` sends the same key and body once;
  - a 409 queues a conflict holding the 409's version and price; `confirm` posts a new key
    with exactly those; `cancel` posts nothing (AC12, AC13);
  - two 409s queue in tap order, even if they arrive in reverse (AC14);
  - a 422 is `failed` with exactly one post (AC15);
  - an accepted entry shows the receipt price, not the tapped one (AC3);
  - `api/orders.test.ts`: the header is sent, the receipt is parsed, a 409 is parsed into
    `PriceChangedBody`, a malformed 409 is a typed error.
- **Depends on:** T3, T4
- **Autonomy note:**
  - **May decide alone:** state names, internal data structures, how "tap order" is keyed
    (a monotonic counter is fine).
  - **Must stop and ask if:** byte-identical bodies cannot be guaranteed by serialising
    once per intent, or the 409 body lacks a price for the tapped drink. The server sends
    every line's price (`app/runtime/orders.py:176-180`), so that would be a server bug.

### T8 — Bar controller and the SD20 property test

- **Implements:** AC1 (the exit check), AC2 (runtime provenance), AC6 (controller wiring
  for accepted, 409, snapshot and Ververs), AC9, AC10, AC13 (asserted per request), AC25
  (polls in the interleaving), AC26 (a `hello` with a new `boot_id` in the interleaving);
  SD20; PD3, PD8
- **Expected output:**
  - `model/barController.ts`: `createBarController({ store, holdTimers, intents deps })`
    subscribes to the store. It offers each new `quote` to the hold buffer, calls
    `promote()` on a `snapshotGen` change (PD3), and wires `onPromote` from the intents. It
    exposes `press`, `release`, `tap(drinkId)`, `refresh`, `confirm`, `cancel`, `retry`,
    `dismiss`, `dispose` and a read model (`displayed`, `latest`, `entries`,
    `headConflict`). `tap` reads `displayed` once (PD8). A tap with no displayed quote, a
    stale latest (AC8) or an open conflict (AC14) is refused.
  - `useBarController.ts` creates one controller per mount with `performance.now` and the
    real timers, disposes it on unmount (StrictMode-safe, like `providers.tsx:140-153`), and
    exposes its read model through `useSyncExternalStore`.
  - `model/money.property.test.ts` uses a real `createStore(initialState)`, the real
    `applyMessage`, the real hold buffer and intents, a deterministic scheduler and a fake
    transport. Each case:
    - runs a seeded random interleaving of `tick`, `order`, `snapshot` (WS),
      `applyPolledState`, `hello` (same or new `boot_id`), press, release, tap, refresh,
      clock advances, and transport outcomes (201, 200 replay, 409, 422, 503, network
      error, timeout);
    - records every message's `(version, prices)`;
    - asserts for every request sent:
      - **AC1:** `(quote_version, unit_price_cents)` equals the controller's `displayed`
        at that tap, and that pair appears together in one recorded message (or in the
        409 body, for a confirm);
      - **AC10:** a retry's key and body string equal the original's;
      - **AC9, AC13:** every new intent's key is unseen.
  - It runs `≥10 000` cases (`PROPERTY_CASES` env, default 10 000) and prints the case
    count and the seed. `PROPERTY_SEED` replays one; a failure message includes its seed.
- **Verification:**
  - `pnpm --dir web exec vitest run src/features/bar/model/money.property.test.ts`, pasting
    the printed case count and seed. Then **mutation proof**, reverted before commit: make
    `tap` read `latest` instead of `displayed`, and paste the test's failure with its seed.
  - `pnpm --dir web exec vitest run src/features/bar` for the controller's own example
    tests: snapshot promotes, 409 promotes, a stale or conflicted tap is refused.
- **Depends on:** T6, T7
- **Autonomy note:**
  - **May decide alone:** the PRNG (mulberry32 or similar, inline), the event weights, the
    scheduler design. Also the per-test timeout; keep the run under about 30 s and say how
    long it took.
  - **Must stop and ask if:** the property fails on a legitimate interleaving that the spec
    did not foresee (do not weaken the assertion), or 10 000 cases cannot run in the gate
    within 60 s.

### T9 — `ConfirmDialog`

- **Implements:** the dialog half of AC12, AC13 (cancel) and AC14; SD9 (`components/ui`,
  reused by Phase 6)
- **Expected output:** `components/ui/ConfirmDialog.tsx`:
  `{open, message, confirmLabel, cancelLabel, onConfirm, onCancel}`.
  - It renders `role="dialog"`, `aria-modal="true"` and a labelled message.
  - Initial focus goes to the confirm button. Tab and Shift+Tab cycle within the dialog;
    Escape calls `onCancel`. Focus returns to the previously focused element on close.
  - CSS Module with theme tokens only.
- **Verification:** `pnpm --dir web exec vitest run src/components/ui/ConfirmDialog.test.tsx` (jsdom):
  - focus starts on confirm; Tab from the last button wraps to the first, and Shift+Tab
    wraps back;
  - Escape → `onCancel` once;
  - each button calls its handler;
  - closed renders nothing;
  - focus is restored.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** native `<dialog>` vs a div overlay. jsdom's `showModal` support is
    partial, so a div with a manual trap is acceptable. Also the styling.
  - **Must stop and ask if:** a focus-trap library seems needed (a new dependency is a hard
    stop).

### T10 — `OrderPad`

- **Implements:** AC4, AC7 and AC8 (UI), the pad half of AC6 ("Ververs"), AC14 (pad
  disabled while a conflict is open), AC25 (usable while `offline`); SD5, SD11, SD18
  (button grid); PD10
- **Expected output:** `OrderPad.tsx` takes the controller's read model and actions.
  - One button per drink in the store's order, keyed by `drink_id`, labelled
    `+1 {name} — {formatEuro(displayed.prices[id])}`. PD10's press handlers; `click` → `tap`.
  - The age line "Prijzen van {n} s geleden" plus a "Ververs" button when `showAge` holds.
  - When `isStale(latest)`: every button is disabled with the message
    "Geen actuele prijzen — wacht op verbinding". Buttons are also disabled while
    `headConflict` is set.
  - The status line reads "Klaar" when there are no entries.
  - The pad carries `data-quote-version={displayed.version}`, which T16 reads.
  - `useNow.ts` re-renders once a second for the age.
  - CSS Module: two-column grid, buttons at least 56 px high at ≤768 px, tokens only.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar/OrderPad.test.tsx` (jsdom, fake timers, a real controller over a test store):
  - labels show the displayed quote's price;
  - pointer-down, a new tick, then click posts the held price (AC1 at the UI seam);
  - after 8 s without a quote the age line shows and "Ververs" promotes (AC6, AC7);
  - after 15 s every button is disabled with the message, and a fresh tick re-enables them
    (AC8);
  - with `status: 'offline'` and a polled snapshot, the buttons work (AC25);
  - with a conflict open, the buttons are disabled (AC14).
- **Depends on:** T8
- **Autonomy note:**
  - **May decide alone:** markup, class names, which element carries the message.
  - **Must stop and ask if:** a press handler would need to read prices from the store
    rather than the controller.

### T11 — Pending orders and the 409 dialog

- **Implements:** AC3, AC11, AC12, AC13, AC14, AC15 (UI), the pending half of AC16; SD8–SD10; PD7
- **Expected output:**
  - `PendingOrders.tsx` renders entries:
    - "1× {name} — bezig…";
    - "1× {name} besteld — {receipt price}";
    - "{name}: niet bevestigd — opnieuw proberen?" with "Opnieuw" and "Sluiten";
    - "Fout bij bestellen";
    - "Geannuleerd";
    - "Mogelijk toch geboekt — controleer de omzet", with PD7's lifetimes.
  - `OrderConflict.tsx` shows the head conflict in `ConfirmDialog` reading
    "{name}: prijs is nu {formatEuro} — bevestigen?" with "Bevestigen" and "Annuleren".
  - Pending state stays component- and controller-local; nothing writes the store.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar/PendingOrders.test.tsx src/features/bar/OrderConflict.test.tsx` (jsdom, fake timers, scripted transport):
  - in flight shows "bezig…" (AC16);
  - a 201 shows the receipt's price for 3 s, then disappears (AC3);
  - three failed retries show Onbekend; "Opnieuw" re-posts the same key; "Sluiten" shows
    the warning line (AC11);
  - a 409 shows the dialog text with the 409's price; Bevestigen posts a new key at that
    price; Annuleren posts nothing and shows "Geannuleerd" (AC12, AC13);
  - two 409s show one dialog, then the next (AC14);
  - a 422 shows "Fout bij bestellen" and makes one post (AC15).
- **Depends on:** T8, T9
- **Autonomy note:**
  - **May decide alone:** markup and the layout of the list.
  - **Must stop and ask if:** PD7 is overruled at the audit (follow the audit's choice).

### T12 — `FinancialPanel`

- **Implements:** AC16 (the panel does not move on a tap), AC18 (UI), the display half of
  AC19; SD15
- **Expected output:** "💶 Financieel overzicht" showing:
  - "Totale omzet" ({formatEuro(Σ revenue_cents)});
  - "Totaal aantal drankjes" (Σ qty);
  - one line per drink in the store's drink order, "{name}: {qty}× — {formatEuro}".

  It reads `selectEarnings`/`selectTotals` only. A slot for the chart is rendered by
  `BarPage`, not here. It has no bar-price figures, sales count or download link.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar/FinancialPanel.test.tsx` (jsdom):
  - renders a snapshot's aggregates exactly;
  - an `order` dispatch adds its delta;
  - a later snapshot replaces the total (AC18);
  - a store `setState` that only adds a pending entry elsewhere does not change the text
    (AC16);
  - no element contains "bar prijs" or "verkopen".

  Also `pnpm --dir web lint` (AC17's rule).
- **Depends on:** T5
- **Autonomy note:**
  - **May decide alone:** markup and styles.
  - **Must stop and ask if:** a figure seems to need arithmetic beyond summing the server's
    `qty` and `revenue_cents`.

### T13 — Revenue series adapter and fetch

- **Implements:** AC21 (pure half); SD16 (live and merge rules)
- **Expected output:**
  - `api/earningsSeries.ts`: `fetchEarningsSeries()` → Zod-validated
    `{t_ms, cum_revenue_cents}[]` via `request('GET', '/api/earnings/series', …)`. A 409
    gives `[]`.
  - `model/revenueSeries.ts`, all pure:
    - `livePoint(tsMs, totalCents)` floors to the second;
    - `appendLive(points, p)` replaces the last point when it has the same second, appends
      when it is later, and ignores it when it is earlier;
    - `merge(history, live)` drops history at or after the first live point's time;
    - `toChartData` maps to `{time: seconds, value}`, strictly ascending.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar/model/revenueSeries.test.ts src/features/bar/api/earningsSeries.test.ts`:
  - two sales in one second give one point with the later value (AC21);
  - history at or after the first live point is dropped;
  - output times are strictly ascending for random inputs (a small seeded loop);
  - fetch parses a valid body; a 409 gives `[]`; a malformed body is a typed error.
- **Depends on:** T1
- **Autonomy note:**
  - **May decide alone:** function names, where the units conversion lives.
  - **Must stop and ask if:** T1's response shape differs from SD16's.

### T14 — `RevenueChart`

- **Implements:** AC21 (no ordering error, on the component), AC22, AC23, AC24; SD16 (the
  chart), SD17; PD13, PD14, PD15
- **Expected output:**
  - `lib/chartTheme.ts` holds `BASE_OPTIONS` and `chartColors` moved from koers;
    `koers/ui/chartOptions.ts` re-imports them, so `DrinkChart.test.tsx` is unchanged and
    green.
  - `RevenueChart.tsx` follows the `DrinkChart.tsx` pattern: one `createChart` and one
    `LineSeries` on mount, and the series is fetched on mount and on every `snapshotGen`
    change.
    - After a fetch it calls `setData(merge(history, live))`.
    - For each store change where `lastOrderTsMs` changed with no `snapshotGen` change, it
      calls `update(livePoint(lastOrderTsMs, selectTotals().revenueCents))`.
    - Theme → `applyOptions` with `chartColors` + `{color: tokens['--accent']}`.
    - `remove` once on unmount; StrictMode-safe.
    - A fetch that resolves after unmount is ignored.
  - `useMediaQuery.ts` per PD15.
- **Verification:**
  - `pnpm --dir web exec vitest run src/features/bar/RevenueChart.test.tsx src/features/koers/ui/DrinkChart.test.tsx` (jsdom, the mocked `lightweight-charts` from `DrinkChart.test.tsx`, extended so `update` throws on an older time like the real library). It checks:
    - mount fetches and calls `setData` once;
    - two `order` dispatches give two `update`s and no `setData` (AC22);
    - two orders in one second give no throw (AC21);
    - a snapshot refetches and calls `setData` again;
    - a theme change gives `applyOptions` and no new `createChart` (AC23);
    - unmount gives `remove` exactly once under StrictMode (AC22);
    - with `matchMedia('(max-width: 640px)')` matching, there is no `createChart` and no
      fetch (AC24).
  - `pnpm --dir web lint`, for the boundaries rule.
- **Depends on:** T5, T13
- **Autonomy note:**
  - **May decide alone:** whether the media-query branch lives in `RevenueChart` or its
    parent, the line width, the price formatter (reuse `formatEuro` via `BASE_OPTIONS`).
  - **Must stop and ask if:** moving the chart theme changes any koers test expectation.

### T15 — `BarPage` and the `/bar` route

- **Implements:** AC27, AC28; SD14, SD18, SD19; composes T10–T14
- **Expected output:**
  - `BarPage.tsx`:
    - "🍺 Bar — Bestellen" header;
    - a "Bestellingen" card (`OrderPad`, `PendingOrders`, `OrderConflict`) and a
      "💶 Financieel overzicht" card (`FinancialPanel`, `RevenueChart`);
    - the cards sit side by side and stack at ≤1000 px;
    - with `selectEmpty`, only "Geen actieve borrel" (no pad, no panel, no controller), as
      `KoersPage.tsx:38-39` does.
  - `index.ts` exports `BarPage`. `routes.tsx` maps `/bar` to `<BarPage />` (`RequireRole`
    already gives display "Geen toegang").
- **Verification:**
  - `pnpm --dir web exec vitest run src/features/bar/BarPage.test.tsx src/app` (jsdom):
    - empty → "Geen actieve borrel" and no buttons; then a snapshot dispatch shows the pad
      without remount (AC27);
    - a live store renders both cards;
    - the routes test: a session without `/bar` in `allowed_routes` sees "Geen toegang",
      and with it sees the page (AC28).
  - `./scripts/check.sh` (build, references and e2e still green).
- **Depends on:** T10, T11, T12, T14
- **Autonomy note:**
  - **May decide alone:** layout CSS and the component split inside the page.
  - **Must stop and ask if:** display's `allowed_routes` turns out to include `/bar`
    (Phase 3 SD2 says it does not).

### T16 — Bar e2e

- **Implements:** AC1, AC3, AC9, AC10, AC12, AC13, AC19, AC24, AC28 (in the real browser
  against the real server)
- **Expected output:** `web/e2e/bar.spec.ts`, using `loginAs` and the real server. Database
  facts come through the API, with the page's cookies (`page.request`):
  `/api/earnings/series` gives the SQL Σ `line_total_cents` and `/api/state` gives
  `earnings`. Cases:
  1. tap → the intercepted request's `quote_version`/`unit_price_cents` equal the button's
     price and the version shown to the page. The confirmation shows the receipt's price
     (AC1, AC3).
  2. a forced 409: `page.route` continues the first `POST /api/orders` with
     `unit_price_cents` raised far outside grace. The real server answers 409.
     - The dialog shows that 409's price, and the earnings are unchanged.
     - Confirm → a new key, and the receipt equals the dialog price. If a second 409
       arrives, the test confirms again and asserts against the last dialog (AC12, AC13).
  3. a double-tap within 100 ms gives two distinct keys and two orders (AC9).
  4. the first request is aborted (`route.abort()`), then let through. The retry carries the
     same key and body, and the earnings qty rises by exactly 1 (AC10).
  5. two bar contexts tap. Both panels converge on the same "Totale omzet", equal to the
     series' final `cum_revenue_cents` (AC19).
  6. at a 640 px viewport there is no `canvas` in the financial card, and no
     `/api/earnings/series` request (AC24).
  7. display opening `/bar` sees "Geen toegang" (AC28).
- **Verification:** `pnpm --dir web build && pnpm --dir web exec playwright test e2e/bar.spec.ts`, then `./scripts/check.sh`. Report the e2e step's time; stop above 3 minutes total (Phase 4 R6).
- **Depends on:** T15
- **Autonomy note:**
  - **May decide alone:** selectors (prefer roles and text) and the test order. The
    displayed version is read from T10's `data-quote-version`.
  - **Must stop and ask if:** case 1 is flaky because the price moves between the read and
    the click. Assert against the intercepted request and the pre-click DOM inside the
    hold, never weaken to "approximately". Also stop if the shared run's state makes the
    tests order-dependent.

### T17 — Same-key replay across a real restart

- **Implements:** the server half of AC26; SD13
- **Expected output:** `tests/integration/test_restart_replay.py`, on `harness.py`'s real
  process:
  1. Seed a live run, start the app, log in as bar.
  2. Post an order with key K and get 201 with body B.
  3. Kill the app and restart it on the same database.
  4. Post K with the same body and get **200 with body byte-identical to B**.
  5. `/api/state` earnings and a `SELECT count(*) FROM "order" WHERE idempotency_key = K`
     both show one order.
  6. Posting K with a different body gives 422 `idempotency_key_reused`.
- **Verification:** `uv run pytest tests/integration/test_restart_replay.py -v`
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the harness calls and timeouts (copy `test_real_process.py`'s
    shape). Use `harness.py`'s urllib client, never `TestClient` or `curl` (memory note).
  - **Must stop and ask if:** the replay is not byte-identical after restart. That is a
    Phase 3 defect, not a Phase 5 one.

### T18 — Documentation

- **Implements:** the spec's "Document updates" (In scope), which record the contracts AC2
  and AC20 rest on: SD1, SD2, SD16
- **Expected output:**
  - `frontend-architecture.md` "The bar order path":
    - the `Quote` type changes to `prices: Readonly<Record<DrinkId, number>>`,
      `receivedAt` (monotonic);
    - the hold is SD1's interaction hold with its four constants;
    - force-promotion includes every snapshot;
    - the controller is the single tap path.
  - `realtime-protocol.md`: the bar applies `order.earnings_delta` to the store's
    `earnings`, and a snapshot replaces it.
  - `phase-7-analytics.md`: AC6's endpoint exists as `GET /api/earnings/series` (60 s,
    live run); Phase 7 extends it with a run parameter and bucket sizes.
- **Verification:** `./scripts/check.sh` (formatting only), plus a human read of the diff.
- **Depends on:** T1, T5, T8
- **Autonomy note:** **`docs/design/` is a hard stop (ADR 0009).** The builder drafts the
  edits and **stops for human approval of the diff before committing**. Nothing else in the
  design docs changes. ADR 0008 is not edited (spec: "none needed").

---

## Task graph

```
T1, T2, T3, T4, T9, T17                 (no dependencies)
T5 ← T4      T6 ← T4      T7 ← T3, T4      T13 ← T1
T8 ← T6, T7  T12 ← T5     T14 ← T5, T13
T10 ← T8     T11 ← T8, T9                  T18 ← T1, T5, T8
T15 ← T10, T11, T12, T14
T16 ← T15
```

Critical path: T4 → T7 → T8 → T11 → T15 → T16 (T3 runs alongside T4).

Shared files are ordered by dependency:
- `features/exchange/model/applyMessage.ts`, `applyMessage.test.ts`, `selectors.ts`, `index.ts`: T4 → T5.
- `features/koers/ui/chartOptions.ts`: T14 only.
- `app/routes.tsx`: T15 only.
- `web/eslint.config.js`: T2 only.
- `app/main.py`, `tests/api/test_authorization_matrix.py`, `web/src/api/generated/schema.d.ts`: T1 only.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T2, T3, T4, T9, T17 | T1: `app/db/orders.py`, `app/api/earnings.py`, `app/main.py`, `tests/api/test_authorization_matrix.py`, `tests/api/test_earnings_series.py`, `tests/integration/test_earnings_series.py`, `web/src/api/generated/schema.d.ts` · T2: `web/eslint.config.js`, `web/src/lint-rules.test.ts` · T3: `web/src/lib/http{,.test}.ts` · T4: `web/src/features/exchange/{index.ts, model/quote*.ts, model/applyMessage{,.test}.ts, model/client{,.test}.ts, model/store.ts, model/selectors.ts}`, `web/src/app/providers.tsx` · T9: `web/src/components/ui/ConfirmDialog*` · T17: `tests/integration/test_restart_replay.py` |
| 2 | T5, T6, T7, T13 | T5: `web/src/features/exchange/{index.ts, model/applyMessage{,.test}.ts, model/selectors.ts}` · T6: `web/src/features/bar/model/{constants,holdBuffer,holdBuffer.test}.ts` · T7: `web/src/features/bar/model/orderIntents{,.test}.ts`, `web/src/features/bar/api/orders{,.test}.ts` · T13: `web/src/features/bar/model/revenueSeries{,.test}.ts`, `web/src/features/bar/api/earningsSeries{,.test}.ts` |
| 3 | T8, T12, T14 | T8: `web/src/features/bar/model/{barController,money.property.test}.ts`, `web/src/features/bar/useBarController.ts` · T12: `web/src/features/bar/FinancialPanel*` · T14: `web/src/lib/chartTheme.ts`, `web/src/features/koers/ui/chartOptions.ts`, `web/src/features/bar/{RevenueChart*,useMediaQuery.ts}` |
| 4 | T10, T11, T18 | T10: `web/src/features/bar/{OrderPad*,useNow.ts}` · T11: `web/src/features/bar/{PendingOrders*,OrderConflict*}` · T18: `docs/design/frontend-architecture.md`, `docs/design/realtime-protocol.md`, `docs/specs/phase-7-analytics.md` |
| 5 | T15 | `web/src/features/bar/{BarPage*,index.ts}`, `web/src/app/routes.tsx` |
| 6 | T16 | `web/e2e/bar.spec.ts` |

No two tasks in one group write the same file. T5 depends on T4 because they share
`applyMessage.ts`, not for logic alone. Builders run one at a time (ADR 0010 §1), so the groups
give the merge order.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main`, with the output pasted.
- T8's property run pasted, with its case count, seed and the mutation proof.
- `uv run pytest tests/engine` green, so the golden fixtures are untouched.
- D-05 closed, with T4, T8 and T16 as evidence; D-31's series endpoint present (T1).
- The spec's manual exit check (two phones, five minutes of fast taps, a 20 s access-point
  pull, every receipt compared with `order_line.unit_price_cents`) is the user's step per
  the memory notes.

---

## Data changes

None. No migration, no new column, no backfill.
- `GET /api/earnings/series` reads `order.wall_ts_ms`, `order.run_id` and
  `order_line.line_total_cents`, all present since Phase 2.
- There is no index on `order(run_id, wall_ts_ms)`. At borrel scale (thousands of orders per
  run) the query is a few milliseconds, so none is added; see R4.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **The spec's approved text is uncommitted.** `HEAD` (9887c0d) approves an older Phase 5 spec. The working tree holds a full rewrite (SD1–SD21, dated 2026-10-05) still marked `approved`. This plan follows the working-tree text | The human confirms the working-tree spec is the approved one and commits it before T1. If the older text is meant, the plan must be redone |
| R2 | **User-visible choices the spec leaves open:** PD7 (lifetimes), PD11 ("Opnieuw" makes one attempt), PD12 (sparse buckets, so the line slopes), PD13 (`--accent`) | Each is marked "confirm at the audit". Each is a few lines to change if overruled |
| R3 | **The property test's runtime.** 10 000 cases with real Zustand stores in the gate | T8 uses an injected scheduler, not `vi.useFakeTimers`, and keeps cases short (≤ ~60 events). It must report the time and stop above 60 s |
| R4 | **Series query without an index** on `order(run_id, wall_ts_ms)` | Fine at borrel scale. Phase 7 owns cross-run analytics and may add one. It is noted, not added: an index would be a migration this phase does not otherwise need |
| R5 | **E2E price movement.** The real server ticks at 1 Hz, so a price read before a click can be stale by the click | T16 asserts against the intercepted request and the hold: a pointer-down then click within `HOLD_MS` freezes the shown price. Case 2 tolerates a second 409 by confirming again |
| R6 | **E2E against one shared run.** T16's cases add orders to the same run Phase 4's specs use | Phase 4's specs do not assert on earnings. T16 asserts on deltas (before vs after), never absolute totals |
| R7 | **AC26 is not proven end to end in a browser** (no restart in the e2e harness) | Two halves: T17 (real process restart, same-key replay, one order) and T7/T8 (503 → 200 replay resolves once; a new `boot_id` then snapshot rebuilds). Stated in Approach |
| R8 | **`docs/design/` edits are a hard stop** (ADR 0009) | T18 stops for approval of the diff. It depends on nothing downstream, so a wait blocks no build task |
| R9 | **`HOLD_MAX_MS` vs a staleness edge.** If ticks stop mid-hold, the displayed quote can be up to 10 s old while the latest is fresh | That is SD1/SD4 as written: staleness is judged on the **latest**, age on the **displayed**. The server's grace rule then decides; a 409 surfaces the price. No mitigation needed; noted so a reviewer does not "fix" it |
| R10 | **Windows test speed** (memory: a `localhost` DSN crawls) | Use `127.0.0.1` in `.env.local`; never pipe `check.sh` through `tail` |

---

## Out of scope for this plan

Everything in the spec's Out of scope, and also:
- Any change to `POST /api/orders`, the grace rule or `quote_grace_versions`. The client
  conforms to Phase 3 SD18.
- An index on `order` for the series query (R4).
- A run parameter or other bucket sizes on the series endpoint (Phase 7).
- Persisting pending intents (SD12); a service worker (spec).
- Editing ADR 0008 (the spec says none is needed).
- Making `HOLD_MS`, `HOLD_MAX_MS`, `AGE_SHOW_MS` or `STALE_MS` configurable (spec).

---

## Audit (plan-auditor — PASS required before implementation starts)

AC → task map:

| AC | Tasks |
|---|---|
| AC1 | T4, T8, T10, T16 |
| AC2 | T4, T8 |
| AC3 | T7, T11, T16 |
| AC4 | T6, T10 |
| AC5 | T6 |
| AC6 | T6, T8, T10 |
| AC7 | T6, T10 |
| AC8 | T6, T10 |
| AC9 | T7, T8, T16 |
| AC10 | T3, T7, T8, T16 |
| AC11 | T7, T11 |
| AC12 | T3, T7, T9, T11, T16 |
| AC13 | T4, T7, T8, T9, T11, T16 |
| AC14 | T7, T9, T10, T11 |
| AC15 | T7, T11 |
| AC16 | T5, T11, T12 |
| AC17 | T2, T5 |
| AC18 | T5, T12 |
| AC19 | T1, T5, T12, T16 |
| AC20 | T1 |
| AC21 | T13, T14 |
| AC22 | T14 |
| AC23 | T14 |
| AC24 | T14, T16 |
| AC25 | T4, T8, T10 |
| AC26 | T4, T7, T8, T17 |
| AC27 | T15 |
| AC28 | T15, T16 |

Human audit, 2026-10-05. The human answered "accept all lines" for the whole checklist, so every
line is ticked on that instruction. Findings raised at the audit and accepted with it:

- **T4 is over the size limit** (11 files). Accepted as one task: the files are one coupled
  change (`Quote` through reducer, client, store and providers). The builder stops and asks if
  it passes about 400 lines.
- **T7 and T8 may approach 400 lines** with their tests. Accepted. The same stop-and-ask applies.
- **T7 has no verification for SD8's 401 case.** Accepted. The builder adds one test: a 401
  leaves the entry in flight and the page goes to login.
- **T14 does not list AC16's chart half.** Accepted. The builder adds one test: a pending entry
  does not move the chart.
- PD7, PD11, PD12 and PD13 are confirmed as written.
- R1: the working-tree spec is the approved one. It is committed together with this plan.

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
- [x] PD7, PD11, PD12, PD13 confirmed or overruled
- [x] R1 resolved: the working-tree spec is the approved one and is committed

Audited by: MartijnBoot (human, `/audit` "accept all lines")  Date: 2026-10-05
