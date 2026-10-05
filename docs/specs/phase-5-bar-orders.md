# Spec: Phase 5 — Bar page and the order path

Status: approved · Depends on: Phase 4 · Fixes: D-05

## Problem

This is where money changes hands, and where v1's worst user-facing defect lives: **a customer
can be charged a price they were never shown** (D-05).

v1's bar page (`legacy/v1/static/bar.html`, 411 lines) keeps two copies of the market:
`pendingState`, the last message received, and `appliedState`, the last one rendered
(`bar.html:182-183`). The buttons render the price from `appliedState` (`bar.html:262-265`),
but the order sends `snapshotVersion` (`bar.html:220`), which `onStateRaw` overwrites from
`pendingState` on every arrival (`bar.html:353-357`). The version and the price come from
different messages, so the server checks the order against prices the bartender never saw.
The anti-flicker hold that causes this exists for a good reason: prices must not change under
a bartender's thumb mid-tap. Its v1 form is a timer of `refresh_minutes` (`bar.html:336-340`,
at least 2 s, usually a minute or more), which is far longer than the tap.

The rest of the page has the same character:

- **No idempotency** (`bar.html:217-221`). A timeout shows "Server onbereikbaar"
  (`bar.html:249`) while the order may well have been charged, and tapping again charges
  twice. Phase 3 closed this on the server (D-06, SD20); the client still has to send a key
  that is stable across retries.
- **A 409 is a dead end.** It shows "Prijs gewijzigd, probeer opnieuw" and reloads
  (`bar.html:236-241`). The bartender is never told the new price, so the retry charges a
  price nobody announced.
- **Two competing revenue models.** On success the page pushes the order into `localOrders`
  at the *displayed* price, not the charged one (`bar.html:225-233`), and
  `computeLocalEarnings` (`bar.html:192-211`) derives revenue from that list. The list resets
  on reload, and `applyNow` falls back to it whenever the server sends no earnings
  (`bar.html:334`).
- **The revenue chart is rebuilt from scratch on every render.** `revChart.destroy()` and
  `new Chart` run on each one (`bar.html:313-314`). The chart has hardcoded colours
  (`bar.html:320-321`) and is hidden at ≤640 px by CSS but still constructed (`bar.html:34`).
- **Polling never stops** once the WebSocket opens (`bar.html:369-379`, `:390`).

Phase 3 delivered the server half: `POST /api/orders` with `Idempotency-Key`,
`{quote_version, lines: [{drink_id, qty, unit_price_cents}]}`
([app/api/orders.py:63](../../app/api/orders.py)). The grace rule judges each line under the
lock (SD18, ADR 0008 addendum). A 409 `price_changed` carries `version` and every line's
current `price_cents` ([app/runtime/orders.py:62](../../app/runtime/orders.py),
[app/core/errors.py:51](../../app/core/errors.py)). The snapshot carries `version` and
per-drink `earnings` (`{qty, revenue_cents}`), and every `order` broadcast carries
`earnings_delta` and every drink's new prices
([app/realtime/messages.py:122-152](../../app/realtime/messages.py)).

The client half does not exist. `/bar` is Phase 4's placeholder
([web/src/app/routes.tsx:25](../../web/src/app/routes.tsx)). The store holds neither the
engine `version` nor earnings
([web/src/features/exchange/model/applyMessage.ts:43-65](../../web/src/features/exchange/model/applyMessage.ts)),
and an `order` message updates prices only (`applyMessage.ts:116`). No server endpoint serves
a revenue time series: the snapshot carries totals only, by design (D-31).

**Why the hold length matters now.** Every 1 Hz tick bumps `version`. With
`quote_grace_versions = 2`, the server honours a held price only if it **equals** the live
price, or if it is within one `step_quant` **and** at most two versions old. A v1-length hold
of a minute would therefore produce a 409 on every tap whose price moved during that minute.
That is the "staff learn to mash retry" failure ADR 0008 rejected.

## Decisions

Settled at the spec interview (2026-10-05). SD1 was put to the human with a recommendation.
The human then delegated it and every later question ("implement the recommended options"),
so every SD below records the recommendation taken. The planner must not reopen them; the
human may overrule any at spec approval.

**The quote and the hold**

- **SD1 — The hold covers the interaction only, not a cadence.** While the bartender is not
  touching the pad, the displayed quote follows the latest quote on every message that
  carries one. A press on any drink button (pointer down, or keyboard activation) starts a
  hold. The hold ends `HOLD_MS = 2000` after the last press is released, and never more than
  `HOLD_MAX_MS = 10000` after it started. When the hold ends, the displayed quote becomes the
  latest quote. `refresh_minutes` plays no part on the bar page.
- **SD2 — `Quote` is one immutable record, built by the reducer.**
  `type Quote = { readonly version: number; readonly prices: Readonly<Record<DrinkId, number>>; readonly receivedAt: number }`,
  frozen. `prices` holds `price_cents` (the charged track, Phase 3 SD24), keyed by
  `drink_id`. `receivedAt` is the client's monotonic clock (`performance.now()`) at receipt.
  `applyMessage` builds a new `Quote` from **one** message:
  - a `snapshot` (WebSocket or poll): `data.version` with `data.prices`;
  - a `tick`: the envelope's `version` with `data.drinks[*].price_cents`;
  - an `order`: the envelope's `version` with `data.prices`.

  The store exposes `quote: Quote | null`. The bar feature reads prices and versions only
  through a `Quote` and never combines a price from one message with a version from another.
  The hold buffer holds a reference to a `Quote`, never separate fields.
- **SD3 — Force-promote.** The displayed quote becomes the latest quote immediately, even
  inside a hold, on: an accepted order (2xx), a 409, any `snapshot` (reconnect, resync, new
  `boot_id`, poll), and the "Ververs" button. A running hold keeps its timers.
- **SD4 — Age and staleness.** Age is now − `displayedQuote.receivedAt` on the monotonic
  clock.
  - Above `AGE_SHOW_MS = 8000`, the pad shows "Prijzen van {n} s geleden" beside a "Ververs"
    button.
  - When the **latest** quote is older than `STALE_MS = 15000`, the pad is disabled with
    "Geen actuele prijzen — wacht op verbinding".

  The four constants are client constants in one module, not run settings. 8 s sits above
  Phase 4's 5 s poll interval, so the indicator does not flicker while polling.

**The order pad**

- **SD5 — One tap is one order of one drink.** Each button reads `+1 {name} — € 2,50` (Phase 4
  SD22 formatter). A tap posts `{quote_version, lines: [{drink_id, qty: 1, unit_price_cents}]}`
  from the displayed `Quote` at the instant of the tap. There is no cart, no quantity
  selector and no multi-line order, although the server accepts them.
- **SD6 — Taps are independent and concurrent.** Each tap captures its own quote and its own
  idempotency key, and may be in flight alongside others. The server serialises them (Phase 3
  AC8). The client does not queue or debounce: two taps are two orders, because "+1 Bier"
  twice is how a bartender sells two beers.
- **SD7 — Idempotency key.** `crypto.randomUUID()` per tap (36 characters, inside SD17's
  pattern). It is created when the tap creates the order intent, never at send time. Every
  retry of that intent sends the same key **and a byte-identical body**. A confirmation after
  a 409 is a new intent with a new key (ADR 0008).
- **SD8 — Retry policy.** The request times out after 8 s (`AbortSignal.timeout`).
  - On a network error, a timeout or a 503 (`persistence_unavailable`, `shutting_down`), the
    client retries automatically after 1 s, 2 s and 4 s, with the same key and body.
  - After the third failed retry, the pending entry becomes "Onbekend" with
    "{name}: niet bevestigd — opnieuw proberen?" and two actions:
    - "Opnieuw": the same key and body. A 200 replay resolves it as accepted.
    - "Sluiten": dismiss, with the line "Mogelijk toch geboekt — controleer de omzet".
  - A 422 is shown as "Fout bij bestellen" and never retried.
  - A 401 follows Phase 4 SD12. Pending entries are lost; see SD12.
- **SD9 — The 409 confirmation.** A 409 `price_changed` opens a `ConfirmDialog` reading
  "{name}: prijs is nu € 2,70 — bevestigen?" with "Bevestigen" and "Annuleren".
  - The dialog holds the 409 response's `version` and that line's `price_cents` as one
    `Quote`-shaped record. "Bevestigen" posts a new intent (new key) from exactly that record.
  - "Annuleren" charges nothing and shows "Geannuleerd".
  - A second 409 opens a new dialog with the newer price.
  - While a dialog is open, the pad is disabled. 409s from other in-flight taps queue and open
    one at a time, in tap order.
  - `ConfirmDialog` is built in this phase in `components/ui/` (focus trap, Escape =
    "Annuleren"). Phase 6 reuses it.
- **SD10 — Pending UI, never revenue.** A component-local `pendingOrders` list shows each
  intent: "1× Bier — bezig…" while in flight; "1× Bier besteld — € 2,50" for 3 s on success,
  using the **receipt's** `unit_price_cents`; the SD8 and SD9 states otherwise. Pending
  entries never touch the store, the totals or the revenue. The status line reads "Klaar"
  when the list is empty (v1's word).

**Connection, empty state, restart**

- **SD11 — The pad works whenever there is a fresh quote.** That includes Phase 4's `offline`
  state, where the 5 s poll supplies snapshots. The pad is gated by SD4's staleness, not by
  socket state. Phase 4's connection banner is shown as on every page.
- **SD12 — Accepted loss on reload.** Pending intents live in component memory only, and
  Phase 4 SD27 bans `localStorage`/`sessionStorage`. A reload or a 401 while an intent is
  unresolved loses the client's knowledge of it; the server's idempotency still prevents a
  double charge. This is not fixed in Phase 5.
- **SD13 — Restart mid-borrel.** A new `boot_id` discards live state (Phase 4 SD16), and the
  following snapshot force-promotes (SD3). In-flight retries continue with their keys:
  idempotency is stored in Postgres and survives the restart (Phase 3 SD20, AC18d).
- **SD14 — Empty state.** With no live run, `/bar` shows "Geen actieve borrel" in the themed
  shell, with no pad and no panel, and shows the page without reload once a run is live.

**The financial overview**

- **SD15 — The panel shows server aggregates only.** The store gains `earnings`, set
  wholesale by each `snapshot` and incremented by each in-sequence `order` message's
  `earnings_delta`. That is applying the server's numbers, not modelling revenue; a resync
  snapshot replaces it. The panel shows:
  - "Totale omzet" (Σ `revenue_cents`);
  - "Totaal aantal drankjes" (Σ `qty`);
  - per drink, "{name}: {qty}× — € x,xx".

  Not shown: "Omzet bij bar prijs" and the per-drink bar-price pills, because the bar-price
  aggregate and its naming are Phase 7's (D-20, Phase 7 AC5). "(n verkopen)" is dropped: with
  SD5, one sale is one drink, so it duplicates the total drinks. The "Download bestand" link
  is also dropped (Phase 7 export). v1 keeps serving the real borrels until cutover, so
  nothing in production loses these in the meantime.
- **SD16 — The revenue chart is cumulative revenue for the whole live run, on
  lightweight-charts.**
  - **History:** a new read-only `GET /api/earnings/series` (bar, admin) returns the live
    run's cumulative revenue in fixed 60 s buckets, aggregated in SQL from `order_line`
    (`[{t_ms, cum_revenue_cents}]`, bucket-end times, ascending), outside the state lock. It
    returns 409 `no_live_run` without a live run. This brings Phase 7's "bucketed earnings
    series endpoint" forward and satisfies Phase 7 AC6 early; Phase 7 extends it with a run
    parameter and other bucket sizes.
  - **Live:** each in-sequence `order` message appends a point at its envelope's `ts_ms`
    floored to the second, valued at the store's Σ `revenue_cents` after applying it. A point
    in the same second replaces the previous one, so times stay strictly ascending.
  - **Merge:** history points at or after the first live point's time are dropped.
  - **Refetch:** the series is refetched on every snapshot, so a reconnect cannot leave a gap.

  The chart uses theme tokens via `applyOptions`, as on the koers page. It is a stable host
  with imperative feed: `setData` on a fetch, `update` per order, `remove` once on unmount.
- **SD17 — At ≤640 px the revenue chart is not constructed**, and the series is not fetched.
  The KPIs and per-drink lines still render.

**Layout, roles, testing**

- **SD18 — Layout ports v1.** "🍺 Bar — Bestellen" header; two cards, "Bestellingen" and
  "💶 Financieel overzicht", side by side and stacked at ≤1000 px. A two-column button grid,
  with 56 px minimum button height at ≤768 px. CSS Modules, theme tokens only, no hardcoded
  colours.
- **SD19 — Roles are unchanged.** `/bar` and the series endpoint are for bar and admin (Phase
  3 SD2). Both see the financial panel, as in v1. Display gets "Geen toegang" (Phase 4 SD13).
- **SD20 — The property test uses no new dependency.** A seeded PRNG generator in the test,
  ≥10 000 cases per run, prints the case count and the seed, and replays a failing seed.
  `fast-check` is not added.
- **SD21 — Market events have no treatment on the bar page** (v1 has none). Prices still move
  through ticks, and SD1 still applies.

## In scope

- `features/bar`: `BarPage`, `OrderPad`, the hold buffer (pure, timer-injected), the order
  intent state machine (send, retry, 409, confirm, cancel, unknown), `FinancialPanel`,
  `RevenueChart`.
- `features/exchange`: `Quote` and `quote` in the store, `earnings` in the store, and the
  `order` message applying `earnings_delta`. Built in the reducer per SD2 and SD15.
- `components/ui/ConfirmDialog`.
- Server: `GET /api/earnings/series` (SD16), its authorization, its OpenAPI types regenerated.
- The `/bar` route replacing its placeholder.
- The SD20 property test; Vitest, component and Playwright tests below.
- Document updates:
  - `frontend-architecture.md`: the hold as SD1, `Quote` keyed by `drink_id`;
  - `realtime-protocol.md`: the bar's use of `order.earnings_delta`;
  - Phase 7's spec: AC6's endpoint now exists;
  - ADR 0008: none needed, since the client follows the addendum as written.

## Out of scope

- Carts, quantities other than 1, multi-line orders from the UI (SD5).
- Voids, refunds, undoing a mis-tap, or any correction of a committed order.
- Persisting pending intents across reload (SD12).
- Revenue at bar price, `bar_price_*` aggregates, the sales count, the xlsx download (Phase 7;
  D-20).
- Cross-run analytics, a run selector or other bucket sizes on the series endpoint (Phase 7).
- `/manipulation` for the bar role, and any drink, price or settings change (Phase 6).
- Drinks added or removed mid-run while the bar page is open (Phase 6; D-02).
- Market-event visuals on the bar page (SD21).
- Changing `quote_grace_versions` or any grace behaviour on the server. The client conforms
  to Phase 3 SD18.
- Making the hold constants (SD1, SD4) configurable.
- Sound or haptic feedback, a printed receipt, offline order queueing beyond SD8's retries.
- Service worker, PWA install, fullscreen, wake lock.
- Any change to pricing behaviour. The golden fixtures stay green.

## Acceptance criteria

**The money invariant — D-05**

- **AC1.** When a bartender taps a drink, the system shall post `quote_version` and
  `unit_price_cents` equal to the `version` and that drink's price of the **displayed**
  `Quote` at the instant of the tap, for any interleaving of ticks, orders, snapshots, polls,
  holds and taps. *(D-05)*
- **AC2.** The bar feature shall obtain a price only through a `Quote`. A `Quote` shall be
  frozen and built from exactly one server message; a test shall fail if any code path builds
  one from fields of two messages. *(D-05)*
- **AC3.** When an order is accepted (201, or a 200 replay), the confirmation shall show the
  receipt's `unit_price_cents`, which for an honoured quote equals the price displayed at the
  tap.

**The hold**

- **AC4.** While no press is active and no hold is running, when a message carrying a quote
  is applied, the displayed prices shall update to it.
- **AC5.** When a press starts, the displayed quote shall not change until `HOLD_MS` after
  the last press is released, or until `HOLD_MAX_MS` after the hold began, whichever comes
  first, except by SD3's force-promotions; then it shall become the latest quote.
- **AC6.** When an order is accepted, a 409 arrives, a snapshot arrives, or "Ververs" is
  tapped, the displayed quote shall become the latest quote immediately, even during a hold.
- **AC7.** While the displayed quote is older than 8 s, the pad shall show "Prijzen van
  {n} s geleden" and "Ververs".
- **AC8.** While the latest quote is older than 15 s, every drink button shall be disabled
  and the pad shall show "Geen actuele prijzen — wacht op verbinding". When a fresh quote
  arrives, the buttons shall be enabled again.

**Idempotency, retries and 409**

- **AC9.** When two taps occur, including two within 100 ms on the same drink, the system
  shall post two requests with distinct idempotency keys.
- **AC10.** When a request fails with a network error, a timeout or a 503, the system shall
  retry it after 1 s, 2 s and 4 s with the **same** key and a byte-identical body. When a
  retry returns 200, the system shall show it as accepted once, and the server shall hold one
  order for it.
- **AC11.** When all automatic retries fail, the entry shall show "Onbekend" with "Opnieuw"
  (same key and body) and "Sluiten". "Sluiten" shall show "Mogelijk toch geboekt — controleer
  de omzet".
- **AC12.** When the server returns 409 `price_changed`, the system shall show "{name}: prijs
  is nu € X — bevestigen?" with the 409's price for that drink, and nothing shall have been
  charged.
- **AC13.** When the bartender confirms after a 409, the system shall post a **new**
  idempotency key, with `quote_version` and `unit_price_cents` equal to the 409 response's
  `version` and that drink's price. When they cancel, no request shall be sent.
- **AC14.** While a confirmation dialog is open, the pad shall be disabled. When further 409s
  arrive, they shall open one at a time in tap order.
- **AC15.** When a request returns 422, the system shall show "Fout bij bestellen" and shall
  not retry.

**Pending UI and revenue**

- **AC16.** While an order is in flight, it shall show as "bezig…" in the pending list, and
  the revenue, totals and chart shall not change until the server's `order` message or
  snapshot arrives.
- **AC17.** The web bundle shall contain no revenue computation from prices × quantities:
  revenue and quantities shall come only from `snapshot.earnings` and `order.earnings_delta`.
  *(deletes `computeLocalEarnings`)*
- **AC18.** When a snapshot arrives after any sequence of `order` messages, the panel shall
  show exactly the snapshot's aggregates.
- **AC19.** When two orders from different bar sessions are accepted, both bar pages shall
  show the same totals, equal to the database's Σ `line_total_cents` and Σ `qty`.

**Revenue chart**

- **AC20.** When `GET /api/earnings/series` is called by bar or admin during a live run, the
  system shall return cumulative revenue in 60 s buckets computed in SQL. The final point's
  value shall equal Σ `line_total_cents` for the run. The response size shall be bounded by
  run length / 60 s, regardless of order count. Called by display or anonymously, it shall
  return 403 or 401; with no live run, 409 `no_live_run`.
- **AC21.** When two sales occur in the same second, the chart shall hold one point for that
  second with the later cumulative value, and shall raise no lightweight-charts ordering
  error.
- **AC22.** When an `order` message arrives, the chart shall be updated with `update` only;
  `setData` shall happen only after a series fetch, and `remove` exactly once on unmount.
- **AC23.** When the theme changes, the chart's colours shall update via `applyOptions`
  without recreating the chart.
- **AC24.** At ≤640 px the revenue chart shall not be constructed and the series shall not be
  fetched.

**Connection, restart, empty state, roles**

- **AC25.** While the socket is down and polling supplies snapshots, the pad shall remain
  usable, and each tap shall use the polled snapshot's `version` and prices.
- **AC26.** When the server restarts while an order's retry is pending, the retry shall
  resolve as accepted with one order in the database, and the page shall rebuild from the new
  snapshot.
- **AC27.** With no live run, `/bar` shall show "Geen actieve borrel" in the themed shell,
  and shall show the pad without reload once a run is live.
- **AC28.** When a display session opens `/bar`, it shall see "Geen toegang". Bar and admin
  sessions shall see the pad and the panel.

## Verification

- **Property test (SD20), the exit check.** The hold buffer, the order intent machine and
  the reducer run under fake timers. Each case drives a random interleaving of `tick`,
  `order`, `snapshot` (WS and poll), `hello` with a new `boot_id`, press, release, tap,
  "Ververs", timer advances, and request outcomes (201, 200 replay, 409, 422, 503, network
  error, timeout). It asserts, for every request sent:
  - AC1: `(quote_version, unit_price_cents)` equals the displayed quote at the tap, and that
    quote came from one message;
  - AC10: retries carry the same key and body;
  - AC9 and AC13: new intents carry new keys.

  At least 10 000 cases. Evidence: the run output with the case count and seed.
- **Vitest:**
  - the reducer: `quote` from snapshot, tick and order (AC2); `earnings` from snapshot and
    deltas, and replaced on resync (AC18);
  - the hold timings (AC4–AC8);
  - the retry schedule (AC10–AC11);
  - the chart adapter: same-second merge, history/live merge (AC21);
  - a lint rule or test for AC17.
- **Component tests (Testing Library):**
  - `OrderPad`: 409 dialog, confirm, cancel, queueing and pad disabled (AC12–AC15);
    staleness (AC8);
  - `ConfirmDialog`: focus trap and Escape;
  - `RevenueChart` against mocked lightweight-charts (AC22–AC24).
- **Python:** `GET /api/earnings/series` authorization, the 409, bucketing, bounded size and
  the final total equal to `SELECT sum(line_total_cents)` (AC20).
- **Playwright (in the gate):**
  - tap → order posted at the displayed price and version, confirmation shows the receipt
    price (AC1, AC3);
  - a forced 409 → dialog with the new price, nothing charged; confirm → new key, charged at
    the confirmed price (AC12–AC13);
  - double-tap → two keys (AC9);
  - a request aborted once → retried with the same key, one order in the database (AC10);
  - two bar contexts converge on the same totals (AC19);
  - 640 px → no chart canvas (AC24);
  - display → "Geen toegang" (AC28).
- **Manual (exit check):** a mock service round with two phones on the same access point,
  tapping fast for five minutes while prices move. Compare every receipt shown with the
  database's `order_line.unit_price_cents`. Pull the access point for 20 s mid-round and
  confirm no order is lost or doubled.

## Exit condition

The price shown is the price charged, or the order is rejected with the new price put to the
bartender. A property test over thousands of interleavings enforces this and would fail if the
invariant broke.
