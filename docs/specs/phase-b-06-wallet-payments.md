# Spec: B-06 — Pay at the bar by scanning a player's wallet

Status: Approved · Depends on: B-05 (the wallet, its ledger, the kassa and its camera), Phase 5
(the bar page, the quote and hold, the order intents), Phase 3 (SD17–SD21 the order path, SD18
the grace rule), Phase 6 (SD18 the `config` message, SD24 draining, the Globale instellingen
section), Phase 7 (SD3 deleting a run), Phase 8 (SD1 `APP_ENV=venue`, SD3 `schema_compat`), B-01
(the info popups) · Fixes: D-49 · Amends: [ADR 0001](../adr/0001-setup-decision-record.md) §4
(the B-05 addendum), B-05 SD5, SD9, SD15 and SD23, Phase 5 SD5 and its "no voids" ·
Backlog: [B-06](../backlog.md)

Line references are to `fix/phase-b-05-review` at `56c32de`: B-05 is built and reviewed but not
yet merged to `main` (`374e206`). B-06 builds on top of it.

## Problem

For a group order on one paper voucher, the bartender works out the points in their head and
crosses them off. Then they pick up a phone and enter every drink again on the bar page. At busy
moments this is the bottleneck. B-05 gave every player a wallet with a balance, but nothing can
spend it:

- **The bar page sells one drink per tap and knows no player.** Each "+1 {name}" button is an
  order of one drink (`web/src/features/bar/OrderPad.tsx:61-64`), by design: "no cart, no
  quantity selector and no multi-line order, although the server accepts them" (Phase 5 SD5,
  `docs/specs/phase-5-bar-orders.md:104-108`). The server takes 1..N lines of `qty` 1–99
  (`app/api/orders.py:30-48`).
- **An order touches no money but the revenue.** `place_order` judges the grace rule
  (`app/runtime/orders.py:187-206`) and then writes the state, the order, its lines, the receipt
  and the tick in one transaction (`app/db/orders.py:77-135`). No wallet appears anywhere on that
  path.
- **B-05 keeps wallets out of the market lock and out of debt.** "No wallet work runs inside the
  market's state lock" (B-05 SD23; `app/runtime/wallets.py:3-5`). "A balance never goes below
  zero" (B-05 SD9). A ledger entry is one of `topup`, `reversal`, `move_out`, `move_in` or
  `closing`, and a `closing` entry is always negative (`db/migrations/versions/0013_wallets.py:110-117`).
- **A mis-tap has no undo.** Phase 5 rules out voids, refunds and any correction of a committed
  order (`docs/specs/phase-5-bar-orders.md:229`). Once a tap spends a player's money, that
  becomes a real cost.
- **The bar page probably breaks at the venue (D-49).** It makes each `Idempotency-Key` with
  `crypto.randomUUID()` (`web/src/features/bar/useBarController.ts:76`, called per intent at
  `model/orderIntents.ts:229,262`). Browsers provide that only in a secure context, and the venue
  serves plain HTTP (Phase 8 SD1). B-05's kassa already uses a generator that works anywhere
  (`web/src/lib/idempotencyKey.ts:12`).
- **At the venue there is no camera either.** The kassa offers the camera only in a secure
  context (`web/src/features/kassa/camera.ts:6`), so at the venue a code has to be typed.

The pricing engine does not change: an order reaches it exactly as it does today, whoever pays.

## Decisions

These were settled at the spec interview on 2026-10-25. Q1–Q13 were put to the owner one at a
time, each with a recommendation, and each answer below is recorded as given. SD14–SD21 were
stated at the end of the interview and approved as a whole. The planner must not reopen any of
them.

**When a wallet must pay**

- **SD1 — A per-run switch, "Wallet verplicht" (Q1, Q2).**
  - A run has a boolean `wallet_required`.
    - **On:** every bar order must be paid from a wallet. The server refuses an order without
      one with 409 `wallet_required`.
    - **Off:** a wallet is optional (SD5).
  - A run created after this phase's migration starts with the switch **on**. Runs that exist
    when the migration runs get **off**, so a deploy never changes a borrel in progress.
  - Admin edits it in Globale instellingen, on a draft or a live run, like any other setting
    there. A live change takes effect for the next order that reaches the server. An order is
    judged by the switch as it stands when the order arrives, whatever the bar page showed.
- **SD2 — "Rood staan tot": a per-run credit limit (Q4, Q5).**
  - A run has `credit_limit_cents`: €0,00–€50,00 in €0,50 steps. A new run starts at €0,00.
    Anything else is 422.
  - A wallet payment may take a balance down to minus the limit of the run that is live when the
    order arrives, and no further. At €0,00 a balance never goes below zero, as in B-05.
  - It is edited where the switch is (SD1) and with the same rules.
- **SD3 — Neither setting travels.** The switch and the limit are run columns, not engine
  params. Neither is part of a B-04 profile (B-04 SD1's 22 settings stay 22) or copied by
  "kopieer drankjes uit" (`copy_from_run_id`). Both get a B-01-style info popup.

**The bar page**

- **SD4 — Scan first, then build, then pay (Q3).**
  1. The bartender scans the player's QR, or types the short code. The page shows the wallet
     large: "Jan — saldo €7,50".
  2. They tap drinks into a **basket**. Each tap adds one. A line has "−", and "Leegmaken"
     empties the basket. A line's quantity is 1–99, as the server allows.
  3. **"Afrekenen €8,40"** sends the order at once, with no further confirm.
  - Every price on the page, the basket's included, comes from the displayed `Quote` (Phase 5
    SD1, SD2). Pressing "Afrekenen" starts a hold, as pressing a drink button does. The order
    carries the `version` of the displayed `Quote` at that instant and every line's price from
    that same `Quote`.
  - A 409 `price_changed` opens Phase 5's confirmation, built for the basket. It shows every line
    whose price changed and the new total. "Bevestigen" is a new intent with a new key, built
    from the 409's quote. The wallet is checked again on that intent.
- **SD5 — With the switch off, one page, and the wallet is optional (Q10).** It is the same page
  with the same basket. With no wallet scanned, the button reads **"Afrekenen zonder wallet
  €8,40"** and books an unpaid order, as every order is today. With a wallet scanned, the
  wallet pays. With the switch on, the button stays disabled until a wallet is scanned, with
  "Scan eerst een wallet".
- **SD6 — The page lets go of a wallet (Q11).** A successful payment clears both the wallet and
  the basket. "Andere wallet" clears the wallet and "Annuleren" clears both. After **60 s** with
  no tap on the page, the wallet and the basket both clear. The wallet's name stays large on
  screen for as long as it is held.
- **SD7 — After paying:** "Betaald €8,40 — Jan, saldo −€0,90" for 3 s, taken from the receipt.
  The pending list (Phase 5 SD10) shows basket orders as it shows single orders today.

**Money**

- **SD8 — Debt sticks until admin forgives it (Q6).**
  - A player cannot delete a wallet whose balance is below zero. They get 409
    `balance_negative`, shown as "Eerst aanvullen bij de kassa".
  - Admin can delete it. The closing entry then writes the debt off, so a `closing` entry may be
    positive.
  - The automatic clean-up still deletes a wallet in debt after the inactivity period, writing
    the debt off, so a debtor's name does not stay forever (B-05 SD15's retention holds). A wallet
    in debt has ledger entries, so the unfunded period never applies to it.
  - A move carries a negative balance to the new wallet. `nothing_to_move` now means only "zero"
    or "the same wallet".
  - A top-up reversal still may not take a balance below zero (`insufficient_balance`, B-05
    SD12), whatever the limit.
  - A top-up is unchanged: €10–€100 in €5 steps, onto any balance, negative included.
- **SD9 — Refunding a payment returns the money only (Q7, Q8).**
  - "Terugboeken" writes one `refund` entry of the payment's whole amount, naming the payment.
    It is allowed once per payment. The order stays in revenue, and the prices it moved stay
    moved.
  - **The bar page** lists the wallet payments booked with its own key in the last **10
    minutes**, newest first, each with "Terugboeken". The list comes from the server, so a
    reload keeps it.
  - **The kassa** (and admin) see a found wallet's payments next to its top-ups, at any age,
    each with "Terugboeken".
  - A bar key refunding a payment it did not book, or one older than 10 minutes, gets 403
    `refund_not_allowed`. A payment already refunded gets 409 `already_refunded`. A deleted
    wallet gets 409 `wallet_deleted`.
  - The refund entry carries the **payment's** run, so a borrel's payment total is net of its
    refunds.
- **SD10 — A payment names its order (Q13), and the name goes with the wallet.**
  - A `payment` entry holds its order's id. That is how the refund lists show "2× Bier, 1× Wijn
    — €8,40 om 21:14".
  - The link is `ON DELETE SET NULL`. When a run is deleted (Phase 7 SD3), its payments keep
    their amount, time and run-less ledger row and lose only the drinks list.
  - A deleted wallet's row holds no name (B-05 SD15), so what remains of its purchases is
    anonymous.
  - ADR 0001 §4 is amended by addendum, which the owner approved at the interview (Q13). Purchases
    are linked to a wallet's name while the wallet exists. Orders no longer stay anonymous while
    their wallet lives (B-05 SD5).
  - Wallets, names and payments stay out of the xlsx export and `/analytics`.

**The QR code and the venue**

- **SD11 — The B-05 scheme pays as it is (Q9).** The fixed QR token and the 8-character short
  code that top up a wallet also pay from it. There is no rotating code and no PIN. The bar's
  check against a screenshot is the name shown large (SD4). A copied code works until "Nieuwe
  code" at the kassa (B-05 SD14).
- **SD12 — The venue works with a typed code, and D-49 is fixed (Q12).**
  - Under `APP_ENV=venue` the bar offers only "Code typen", as the kassa does (B-05 SD17). Where
    the browser allows a camera, it offers both.
  - The bar's idempotency keys come from B-05's generator (`web/src/lib/idempotencyKey.ts`), so
    no bar code calls `crypto.randomUUID()`.
  - The offline rehearsal stays deferred (backlog, "Deferred work").

**Stated at the end and approved**

- **SD13 — The order carries what was scanned, never a wallet id.**
  - The order body may carry a `wallet` of `{qr_token}` or `{short_code}`, exactly as read.
  - The server resolves it inside the order. A wallet deleted or re-coded since the scan gets
    404 `wallet_not_found`. The page shows "Onbekende wallet", clears the wallet and keeps the
    basket.
  - A bar key may look a wallet up by token or code, and sees only its name and balance.
- **SD14 — One transaction, inside the state lock (amends B-05 SD23).**
  - The `payment` entry is written in the order's own transaction (`write_order`), under the
    holder's lock, after a `FOR UPDATE` lock on the wallet's row.
  - This is the route invariant "inside the state lock: pure numpy plus one short DB
    transaction". The wallet lock is part of that one transaction.
  - Every other wallet action (top-up, reversal, move, refund, new code, delete, clean-up) still
    runs outside the market lock and takes only wallet row locks. The market lock is always taken
    before any wallet lock, so the two cannot deadlock.
- **SD15 — The order of checks.** Under the lock, in this order:
  1. idempotency;
  2. the domain checks (Phase 3 SD17);
  3. the grace rule (409 `price_changed`);
  4. the switch (409 `wallet_required`);
  5. the wallet (404 `wallet_not_found`);
  6. the balance against the limit. Payment total > balance + limit gets 409
     `insufficient_balance` with `{balance_cents, credit_limit_cents}`.

  Every refusal charges nothing, writes nothing and moves no price.
- **SD16 — Idempotency covers the payment.**
  - The order's `Idempotency-Key` is the payment's: a replay returns the stored receipt and
    writes nothing.
  - For a wallet order, the receipt gains `wallet: {name, balance_after_cents}`, stored with the
    receipt, so a replay is byte-identical (Phase 3 PD7) even after the wallet has changed.
  - A replay whose body names a different wallet is 422 `idempotency_key_reused`.
- **SD17 — The bar knows the switch and the limit live.** Both travel on the `run` in the
  snapshot and in the `config` message (Phase 6 SD18). A change reaches open bar pages without
  a reload. Until it does, the server's judgement (SD15) decides.
- **SD18 — Too little balance on the page.** While building, if the basket's total exceeds
  balance + limit, the page shows "Saldo €7,50 — nog €5,00 tekort", and "Afrekenen" is disabled
  with that text. The server checks again (SD15). A 409 `insufficient_balance` shows the same
  text with the server's numbers and keeps the basket.
- **SD19 — Debt on every page.** A negative balance shows with a minus sign: "−€2,10" on the
  player page, the kassa and the bar. The player page is otherwise unchanged (B-05 SD21: no
  history).
- **SD20 — The Wallets section's totals.** Admin's Wallets section (B-05 SD16) shows two
  totals:
  - **"Tegoed"**: the sum of the positive balances, which is what the association still owes in
    drinks;
  - **"Rood"**: the sum of the negative balances, which is what players owe.

  Per borrel it shows top-ups net of reversals, as today, and **payments net of refunds**. The
  wallet list shows a negative balance with its minus sign.
- **SD21 — Nothing else moves.** `exchange/`, the grace rule, `quote_grace_versions`, the hold
  constants, the QR/code scheme, the financial panel, the revenue series, analytics and the
  xlsx export are unchanged. A refund does not touch revenue.

## The interface

This is for the planner to refine, not to rename without a reason.

**Migration**, one new revision, expand-only (`min_code_revision = "unchanged"`, Phase 8 SD3):

- `run.wallet_required boolean NOT NULL`: existing rows get `false`; `create_run` sets `true`
  (SD1).
- `run.credit_limit_cents integer NOT NULL DEFAULT 0`, checked 0–5000 and a multiple of 50
  (SD2).
- `wallet_entry.kind` gains `payment` (negative) and `refund` (positive).
- `wallet_entry.order_id` is a nullable FK to `order`, `ON DELETE SET NULL`. It is set for a
  `payment` when written, and unique.
- `wallet_entry.refunds_entry_id` is unique and names the refunded payment.
- `wallet_entry_amount_check` allows a positive `closing` (SD8).

**Orders:**

- `POST /api/orders` takes an optional `wallet: {qr_token} | {short_code}` (SD13).
- New errors: 409 `wallet_required`, 404 `wallet_not_found`, 409 `insufficient_balance
  {balance_cents, credit_limit_cents}`.
- The receipt gains `wallet: {name, balance_after_cents} | null` (SD16).

**The bar** (bar and admin):

- `POST /api/bar/wallet-lookup {qr_token | short_code}` returns `{name, balance_cents}`, or 404
  `wallet_not_found` (SD13).
- `GET /api/bar/payments` returns this key's wallet payments from the last 10 minutes, each with
  its lines, total, name, time and whether it was refunded.
- `POST /api/payments/{entry_id}/refund` with `Idempotency-Key`. Bar is allowed only within its
  own 10 minutes; kassa and admin at any age. Errors: 403 `refund_not_allowed`, 409
  `already_refunded`, 409 `wallet_deleted`.

**The kassa** (kassa and admin):

- `GET /api/kassa/wallets/{wallet_id}/payments` returns its payments, newest first, with lines
  (where the order still exists) and whether each was refunded.

**Run config:**

- `wallet_required` and `credit_limit_cents` go through `PATCH /api/runs/{run_id}/config`,
  validated there.
- They appear on the `run` in the snapshot and in the `config` message.

**Player:**

- `DELETE /api/wallet` gains 409 `balance_negative` (SD8).

## In scope

- **Persistence:** the migration above, and `docs/design/data-model.md` (the two run columns,
  the two entry kinds, `order_id`, `refunds_entry_id`).
- **Server:**
  - the wallet part of `place_order` and `write_order` (SD13–SD16);
  - the run config fields, their validation, their place in the snapshot and the `config`
    message;
  - the bar lookup, the bar's payments list, the refund route, the kassa's payments list;
  - SD8's changes to self-delete, admin delete, clean-up and move;
  - SD20's totals;
  - the authorization-matrix rows for every new route;
  - the OpenAPI types regenerated.
- **Web:**
  - the bar page: scan or "Code typen", the wallet held large, the basket, "Afrekenen" in both
    modes, the basket's 409 confirmation, SD18's shortfall, SD6's release, SD7's message, the
    recent-payments list with "Terugboeken";
  - the bar's idempotency keys from `web/src/lib/idempotencyKey.ts` (D-49);
  - Globale instellingen: "Wallet verplicht" and "Rood staan tot", with info popups;
  - the kassa: a found wallet's payments with "Terugboeken";
  - negative balances on the player, kassa and bar pages, and the self-delete refusal;
  - the Wallets section's two totals and payments per borrel;
  - the bar reuses the kassa's scanner and camera check; no new dependency.
- **Tests:** the property test extended to baskets (the Verification section), with Vitest,
  component, pytest and Playwright coverage.
- **Documents:**
  - the ADR 0001 addendum (SD10);
  - a note on Phase 5 SD5 and its "no voids" out-of-scope line, superseded by B-06;
  - a note on B-05 SD5, SD9, SD15 and SD23;
  - `docs/design/realtime-protocol.md` (the `run` fields);
  - `docs/design/frontend-architecture.md` (the basket, the held wallet);
  - D-49's row in `docs/specs/defect-register.md`;
  - `docs/runbooks/venue.md` (typed codes at the bar);
  - B-06's backlog status.

## Out of scope

- **Any change to the pricing maths:** `exchange/`, the golden fixtures, the grace rule,
  `quote_grace_versions`, the hold constants (Phase 5 SD1, SD4).
- **A rotating QR code, a PIN, or any other change to the code scheme (SD11).**
- **Voiding an order:** taking it out of revenue, the panel, the series, analytics or the xlsx,
  or rewinding the engine (SD9). A refund returns money only.
- Refunding part of a payment, or one line of it.
- A purchase or top-up history on the player's page (B-05 SD21 stands).
- Wallets, names, payments or refunds in the xlsx export or `/analytics`.
- A credit limit per wallet or per deployment (SD2 is per run), or interest, reminders or any
  collection of a debt.
- A top-up amount other than B-05's, or a top-up that clears a debt automatically.
- Splitting a basket over two wallets, or partly paying it in cash.
- Persisting the basket or the held wallet across a reload (Phase 4 SD27, Phase 5 SD12).
- The venue's own till, and payment inside the app (B-05).
- The switch or the limit in a B-04 profile or copied by `copy_from_run_id` (SD3).
- Rehearsing the offline venue path (backlog, "Deferred work").
- D5 from the B-05 plan (clipboard over HTTP) and any other defect not named in the header.

## Acceptance criteria

**The switch and the limit — SD1, SD2, SD3, SD17**

- **AC1.** When a run is created, it shall have "Wallet verplicht" on and "Rood staan tot"
  €0,00, whether or not it was created from a profile or from `copy_from_run_id`. When the
  migration runs, every existing run shall get the switch off and a limit of €0,00.
- **AC2.** When admin saves "Wallet verplicht" or "Rood staan tot" on a draft or live run, the
  system shall store it. On a live run it shall broadcast it in the `config` message, and open
  bar pages shall follow without a reload. A limit outside €0,00–€50,00, or off the €0,50 grid,
  shall be 422 and store nothing. Bar, kassa and display keys shall get 403.
- **AC3.** Both fields shall have an info popup in Globale instellingen. Neither shall be saved
  into, or loaded from, a profile.

**Paying — SD4, SD13, SD14, SD15, SD16**

- **AC4.** When the bartender scans a QR or types a short code, the bar page shall show the
  wallet's name and balance large. An unknown or deleted one shall show "Onbekende wallet".
- **AC5.** When the bartender taps drinks and then "Afrekenen €T", the system shall post one
  order. Its `quote_version` and every line's `unit_price_cents` shall equal the displayed
  `Quote`'s at the instant of the tap, and it shall carry the scanned token or code. *(Phase 5
  AC1 for a basket.)*
- **AC6.** When a wallet order is accepted, the system shall, in one transaction:
  - write the order and its lines;
  - move the engine as for any order;
  - write one `payment` entry of −(the receipt's `total_cents`) naming the order, the live run
    and the bar key and its label.

  The wallet's balance shall fall by exactly the receipt's total.
- **AC7.** If the total exceeds balance + the run's limit, the system shall return 409
  `insufficient_balance` with the balance and the limit. It shall write no order and no entry,
  and the engine's version and prices shall be unchanged.
- **AC8.** With limit L, a payment shall be accepted that takes the balance to exactly −L, and
  refused if it would go one cent lower.
- **AC9.** When two bar sessions charge the same wallet at once and together exceed balance +
  limit, at most the orders that fit shall succeed. The balance shall never go below −limit.
- **AC10.** When a wallet order is resent with the same `Idempotency-Key` and body, the system
  shall return the stored receipt byte for byte, with the same `wallet.balance_after_cents`, and
  write nothing. Naming another wallet under that key shall be 422 `idempotency_key_reused`.
- **AC11.** When a 409 `price_changed` answers a basket, the page shall show every changed line
  and the new total. "Bevestigen" shall post a new key with the 409's version and prices, and the
  same wallet. "Annuleren" shall send nothing and keep the basket and the wallet.
- **AC12.** If the wallet was deleted or re-coded between the scan and "Afrekenen", the system
  shall return 404 `wallet_not_found` and write nothing. The page shall show "Onbekende wallet",
  clear the wallet and keep the basket.
- **AC13.** When a payment is accepted, the bar shall show "Betaald €T — <naam>, saldo €B" from
  the receipt for 3 s, and clear the wallet and the basket. The player's page shall show the new
  balance within 10 s (B-05 AC10).

**With and without the switch — SD1, SD5**

- **AC14.** With the switch on and no wallet scanned, "Afrekenen" shall be disabled with "Scan
  eerst een wallet". An order posted without a wallet shall be 409 `wallet_required`, write
  nothing and move no price.
- **AC15.** With the switch off and no wallet scanned, "Afrekenen zonder wallet €T" shall book
  the basket as an order with no payment entry, exactly as an order is booked today. With a
  wallet scanned, the wallet shall pay (AC6).
- **AC16.** When the switch is turned on while a bar page still shows it off, an order without a
  wallet that arrives after the change shall be 409 `wallet_required`.

**The basket and letting go — SD4, SD6, SD18**

- **AC17.** A tap on a drink shall add one to its basket line, "−" shall remove one, and
  "Leegmaken" shall empty the basket. A line shall hold 1–99, and the total shall be computed
  from the displayed `Quote`.
- **AC18.** While the basket's total exceeds balance + limit, the page shall show "Saldo €B —
  nog €X tekort" and disable "Afrekenen".
- **AC19.** After 60 s with no tap on the page, a held wallet and the basket shall clear.
  "Andere wallet" shall clear the wallet only, and "Annuleren" both.

**Refunds — SD9, SD10**

- **AC20.** The bar page shall list the wallet payments booked with its own key in the last 10
  minutes, each with its lines, total, name and time, and "Terugboeken". The list shall survive
  a reload.
- **AC21.** When "Terugboeken" is confirmed, the system shall write one `refund` entry of +the
  payment's amount, naming it, carrying the payment's run and the acting key and label. The
  balance shall rise by that amount. The order, the revenue, the panel and the engine shall be
  unchanged.
- **AC22.** A second refund of the same payment shall be 409 `already_refunded`. A refund on a
  deleted wallet shall be 409 `wallet_deleted`. A bar key refunding another key's payment, or one
  older than 10 minutes, shall be 403 `refund_not_allowed`. In each case nothing shall be written.
- **AC23.** The kassa page shall list a found wallet's payments, newest first, at any age, with
  "Terugboeken". Kassa and admin may refund any of them. A resend with the same
  `Idempotency-Key` shall write nothing.
- **AC24.** When a run is deleted, its payments shall keep their amount, time and wallet, and
  lose their order link and run. Every balance shall be unchanged.

**Debt — SD8, SD19, SD20**

- **AC25.** A negative balance shall show as "−€X" on the player page, the kassa and the bar.
- **AC26.** When a player deletes a wallet with a negative balance, the system shall return 409
  `balance_negative` and write nothing. The page shall show "Eerst aanvullen bij de kassa".
- **AC27.** When admin deletes a wallet in debt, or the clean-up deletes one after the
  inactivity period, the system shall write a positive `closing` entry so its ledger sums to
  zero, and blank it as B-05 AC29 does.
- **AC28.** A move from a wallet in debt shall carry the negative balance to the new wallet.
  Only a zero balance or the same wallet shall be `nothing_to_move`.
- **AC29.** A top-up reversal that would take a balance below zero shall still be 409
  `insufficient_balance`, whatever the run's limit.
- **AC30.** The Wallets section shall show "Tegoed" (the sum of positive balances) and "Rood"
  (the sum of negative balances), and per borrel the top-ups net of reversals and the payments
  net of refunds.

**The venue and D-49 — SD12**

- **AC31.** No bar code shall call `crypto.randomUUID()`. Over plain HTTP from a non-loopback
  address, the bar page shall book an order with and without a wallet. *(D-49)*
- **AC32.** Where the browser offers no camera, the bar page shall show only "Code typen", with
  no error. Where it does, both.

**Draining, standby, restart**

- **AC33.** While draining, orders (as today) and refunds shall be 503 `shutting_down` and
  write nothing. In standby every new route shall be 503 `standby`.
- **AC34.** When the app restarts, every order shall have its payment entry or none as
  committed, never one without the other. Every balance shall equal the sum of its entries.

**Roles**

- **AC35.** The bar lookup and the bar payments list shall be allowed for bar and admin. The
  kassa payments list for kassa and admin. The refund route for bar (SD9's limits), kassa and
  admin. Every one shall be 401/403 for every other role and for no session. A bar lookup shall
  return only the name and the balance.

**Personal data — SD10**

- **AC36.** ADR 0001 shall carry SD10's addendum. A deleted wallet's row shall hold no name, and
  the xlsx export and `/analytics` shall hold nothing from a wallet, a payment or a refund.

**No maths change — SD21**

- **AC37.** For the same sequence of orders, the engine's state and prices shall be the same
  whether the orders were paid by wallet or not. `exchange/` shall be unchanged, and the golden
  fixtures shall replay unchanged.

## Verification

- **Property test (Phase 5 SD20, extended).** The existing money property test gains baskets, a
  held wallet, "Afrekenen", the 409 confirmation on a basket, and the outcomes 409
  `insufficient_balance`, `wallet_required` and 404 `wallet_not_found`. For every request sent,
  it asserts:
  - `quote_version` and every line's price equal the displayed `Quote` at the tap, from one
    message (AC5);
  - retries carry the same key and body, and new intents carry new keys (AC10, AC11).

  At least 10 000 cases. Evidence: the run output with the case count and seed.
- **API (pytest):**
  - paying: the entry, the receipt, the balance (AC6);
  - the limit: exactly −L and one cent past it (AC7, AC8);
  - `wallet_required` (AC14, AC16), and switch off with and without a wallet (AC15);
  - `wallet_not_found` after "Nieuwe code" and after a delete (AC12);
  - replay and reuse (AC10);
  - the order of checks (SD15), with no price moved on any refusal;
  - refunds: bar window and own key, kassa any age, twice, on a deleted wallet (AC20–AC23);
  - self-delete in debt, admin delete in debt, a move in debt, a reversal past zero
    (AC26–AC29);
  - the totals (AC30); the config fields (AC1, AC2); the matrix for every new route (AC35);
  - draining and standby (AC33).
- **Integration (pytest):**
  - two concurrent wallet orders on one wallet, together over the limit (AC9);
  - a wallet order racing a kassa top-up, reversal and move on the same wallet, with no deadlock
    and every balance equal to its entries;
  - a restart between an order and its replay (AC34);
  - a run deleted with payments (AC24);
  - the clean-up deleting a wallet in debt (AC27);
  - the migration up from `0013`, with existing runs getting the switch off (AC1).
- **Engine:** `engine-guardian` on the diff. A test that replays one order sequence with and
  without wallets and compares state and prices (AC37). `bash scripts/golden_linux.sh` green.
- **Vitest and component tests:**
  - the basket (AC17);
  - the shortfall (AC18);
  - the release timer under fake timers (AC19);
  - both button modes (AC14, AC15);
  - the basket's 409 dialog (AC11);
  - the paid message (AC13);
  - the recent-payments list (AC20);
  - the camera hidden without a secure context (AC32);
  - the kassa's payments (AC23);
  - negative balances (AC25);
  - the Wallets totals (AC30);
  - the settings fields and popups (AC3);
  - no `crypto.randomUUID` in bar code (AC31).
- **Playwright (in the gate):**
  1. Admin sets "Rood staan tot" to €2,50. A player signs up, and the kassa tops up €10.
  2. The bar types the player's code, builds 3× a drink and pays. The bar sees "Betaald", and
     the player's page shows the new balance.
  3. The bar builds an order over balance + €2,50 and sees the shortfall disabled. It removes a
     line and pays into the negative, and the player page shows "−€…".
  4. The bar refunds that payment, and the balance returns.
  5. The player cannot delete the wallet while it is in debt.
  6. Admin turns the switch off: "Afrekenen zonder wallet" books an order with no wallet entry.
  7. The bar flow above is repeated against a non-loopback address over plain HTTP (AC31,
     AC32).
- **The gate:** `./scripts/check.sh` green.
- **Manual (exit check, the owner):** on Render, with two phones:
  - scan a player's QR **with the camera** on the bar page, on an iPhone and on an Android
    phone;
  - pay a round of four drinks while prices move, and refund one payment from the bar and one
    from the kassa;
  - on a dry run, turn the switch off and book without a wallet.

## Exit condition

A bartender can scan a player's QR or type their code and build a round. The round can be paid
in one go: the round's order and its wallet payment are committed together or not at all, at
the prices on screen, down to the run's credit limit. A wrong payment can be refunded. The bar
page works over plain HTTP at the venue. The pricing maths has not moved.
