# Plan: B-06 — Pay at the bar by scanning a player's wallet

Spec: [docs/specs/phase-b-06-wallet-payments.md](../specs/phase-b-06-wallet-payments.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-25)**
Design: [data-model.md](../design/data-model.md) (two `run` columns, two entry kinds, two `wallet_entry` columns), [realtime-protocol.md](../design/realtime-protocol.md) (the `run` fields) and [frontend-architecture.md](../design/frontend-architecture.md) (the basket, the held wallet, the shared scanner) change in T20. That task is an owner stop, because it touches `docs/design/`.
ADRs honoured:
- 0002 and 0012: `exchange/` is read, never changed (AC37).
- 0003: refund windows and entry times come from the app clock.
- 0004: one Postgres engine.
- 0006: no new dependency and no runtime request; the bar reuses the bundled `jsqr`.
- 0011: the migration runs at boot, unattended.

ADR 0001 §4 is amended by an addendum the owner approved at the interview (SD10, Q13; T20). No other ADR is reversed.
Backlog: [B-06](../backlog.md) · Fixes: D-49 (T11, T19)

Line references are to `docs/phase-b-06-spec` at `56c32de`, which is `fix/phase-b-05-review` plus the spec.

---

## Approach

**Server: the payment lives inside the order's one transaction. Everything else stays a B-05 wallet action.**
- **Inside the lock.** `place_order` (`app/runtime/orders.py:153-308`) gains three checks under the holder's lock, after the grace rule:
  - the switch, read from the holder's view. It needs no database.
  - the wallet and the balance against the limit, inside `write_order`'s `engine.begin()` (`app/db/orders.py:79-137`), before its first write. The wallet row is locked `FOR UPDATE` by the scanned credential itself, so a re-code between scan and lock is seen.
  - The `payment` entry is then one more `INSERT` in that transaction, and the receipt carries the wallet's name and balance after.
- **Outside the lock.** Refunds, the bar's lookup and list, and the kassa's list are new wallet actions in `app/runtime/wallets.py`. They follow `_book_once` (`:175-206`) and B-05's lock rules, and never touch `MarketHolder`.
- **The switch and the limit.** Both are `run` columns. They enter the holder's `MarketView` the way `candle_interval_ms` does (`holder.py:189-190`, `rehydrate.py:72-82`, `config.py:308`), so the order path, the snapshot and the `config` message read one value, changed only under the market lock.
- **SD8's debt rules** are four small changes:
  - in the repository: a closing for any non-zero balance, a move of any non-zero balance;
  - two refusals: a self-delete in debt, and the unchanged reversal check;
  - the CHECKs that let them through (T1).

**Web: the bar keeps its order path and gains a basket and a held wallet in front of it.**
- **One intent model.** Phase 5's intent model stays the one path from tap to request (`model/orderIntents.ts`), generalised from "one drink" to "these lines, this wallet". Retries and the 409 confirmation stay where they are.
- **The basket** is a small pure model. A drink tap now adds to it, and "Afrekenen" is the one tap that creates an intent, reading the displayed `Quote` once (Phase 5 SD1, SD2).
- **The scanner.** The kassa's scanner, camera check and decoder move to `src/components/scanner/`, so the bar can reuse them without a feature-to-feature import (`web/eslint.config.js:123-138`).
- **D-49 is fixed first**, as its own small task. Every later bar task then builds on keys that work over plain HTTP.

Rejected:
- **Reading the switch and the limit from the database inside the order transaction.** The snapshot is built from holder memory only (`app/realtime/publish.py:29-31`, AC15 of Phase 3), so the bar's view and the server's judgement would come from two places.
- **A separate "pay" route that books an order and then a payment.** SD14 wants one transaction. Two routes need a saga, and they cannot meet AC34.
- **Storing the order's `Idempotency-Key` on the payment entry.** `wallet_entry.idempotency_key` is a second namespace (`models.py:500`). A later kassa write that reused the string would be judged against the payment and answered 422 (`runtime/wallets.py:175-206`). The order's key stays the order's alone.
- **A rotating code, a PIN, a "pay" confirm step.** SD4 and SD11.
- **A new formatter for every euro amount.** Only balances can be negative. `formatEuro` stays as it is, because the koers deltas depend on its spelling (`format.ts:44`, `format.test.ts:41`).

---

## Decisions this plan makes

Rows marked **Owner** are spec ambiguities with two user-visible readings (CLAUDE.md hard stop); the audit must rule on them. Rows marked **Confirm** are readings the audit confirms or overrules. The rest follow from the code and the spec.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | **Owner — ruled A at the audit (2026-10-25).** Does a run made by `app.cli.import_v1` start with "Wallet verplicht" on? | **Ruled: Reading A.** AC1 says "when a run is created". The interface says "`create_run` sets `true`" (spec :217). `import_v1` calls `create_draft_run` directly (`app/cli/import_v1.py:49`), not `create_run`. The venue runbook creates its borrel that way (`docs/runbooks/venue.md:21`). <br>**Reading A (recommended):** off. The column's server default is `false`, and only `create_run` passes `true`. An imported v1 borrel had no wallets. At the venue every player starts at zero (B-05 SD17), so "on" would block every order until each player has topped up at the venue's kassa. Admin can turn it on in Globale instellingen. <br>**Reading B:** on. `import_v1` passes `true`, and `tests/integration/realapp/harness.py:69` (`seed_live_run`) turns it off for the drills and the shared e2e server. | Two venue behaviours. Under either reading, `create_draft_run` keeps `false` as its default, because about 38 test files build runs with it. |
| PD2 | A wallet order whose total is €0,00 | It is booked. It writes a `payment` entry of 0, so every wallet order has exactly one payment entry (AC34) and the replay can find its wallet (PD7). A refund of it writes a `refund` of 0. **Confirm** | A drink's price may be 0 (`p_min_cents ≥ 0`, `runtime/drinks.py:78`). A CHECK of `< 0` would turn such an order into an `IntegrityError` inside the lock, which the holder answers 503 (`holder.py:477-479`). Refusing it instead would make a free drink unorderable while the switch is on. |
| PD3 | The schema (§ Data changes) | `0014_wallet_payments`, laid out as `0013_wallets.py`, with `min_code_revision = "unchanged"`:<br>**`run`:**<br>• `wallet_required boolean NOT NULL DEFAULT false`;<br>• `credit_limit_cents integer NOT NULL DEFAULT 0`;<br>• CHECK `run_credit_limit_cents_check`: `credit_limit_cents BETWEEN 0 AND 5000 AND credit_limit_cents % 50 = 0`.<br>**`wallet_entry`:**<br>• `order_id bigint` FK `order.order_id ON DELETE SET NULL`, UNIQUE `wallet_entry_order_id_key`;<br>• `refunds_entry_id bigint` FK `wallet_entry.entry_id`, UNIQUE `wallet_entry_refunds_entry_id_key`;<br>• `wallet_entry_kind_check` gains `payment` and `refund`;<br>• `wallet_entry_amount_check` becomes: `topup` > 0, `reversal` < 0, `payment` ≤ 0, `refund` ≥ 0, and `move_out`/`move_in`/`closing` ≠ 0;<br>• CHECK `wallet_entry_order_check`: `order_id IS NULL OR kind = 'payment'`;<br>• CHECK `wallet_entry_refund_check`: `(kind = 'refund') = (refunds_entry_id IS NOT NULL)`. | **The move signs:** SD8 and AC28 carry a negative balance, so `move_out` is +X and `move_in` is −X. The spec's interface relaxes only `closing` (`0013:114-118`). **No pairing CHECK on `order_id`:** `ON DELETE SET NULL` must be able to clear it (AC24). **`DEFAULT false`:** the backfill (SD1), the raw `INSERT INTO run` in 11 test files, and an older image creating a run all need it. No column name matches `revenue\|total\|earn` (`test_schema.py:76,151-156`). |
| PD4 | Where the order reads the switch and the limit, and what saving them does | `MarketView` gains `wallet_required` and `credit_limit_cents`, loaded by `rehydrate` and replaced by `commit_transition`, as `candle_interval_ms` is. A live PATCH of either field goes through `write_live_config`, so it is one transition: version + 1 and a `config` tick, as a name-only change already is (`config.py:259-332`). An order is judged under the same lock that swaps the view, so "as it stands when the order arrives" (SD1) is exact. **Confirm**: such a save ages quotes in flight by one version, as a rename does today. | One source for the bar's view, the snapshot and the judgement (SD17). A separate no-transition path would mean a second way to change run config. |
| PD5 | The order path (SD13–SD16) | **Body:** `OrderBody.wallet: WalletQuery \| None = None`. `WalletQuery` is B-05's `LookupRequest` (`app/api/kassa.py:41-53`, exactly one of `qr_token`/`short_code`), moved to `app/api/wallet_query.py` and imported by the kassa, the bar and orders.<br>**Step, after the grace rule:**<br>• `view.wallet_required and wallet is None` → 409 `wallet_required` (new `WalletRequired` in `runtime/orders.py`).<br>**`write_order`** gains `payment: PaymentInput \| None` (credential, limit, actor label). With one, the transaction opens with:<br>• `SET LOCAL lock_timeout = '2s'`;<br>• `lock_wallet_by_qr_token` or `lock_wallet_by_short_code` (one `SELECT … WHERE <credential> = :c AND deleted_at IS NULL FOR UPDATE`, after `normalise_short_code`); none → `WalletNotFound` 404;<br>• `balance`; `total > balance + limit` → `InsufficientBalance` with `extra={"balance_cents","credit_limit_cents"}`.<br>Only then `compare_and_set` and the inserts. The `payment` entry is −total, with `order_id`, `run_id = view.run_id`, `actor_key_id`, `actor_label` and **no** `idempotency_key`.<br>**Receipt:** `wallet: PaidWallet{name, balance_after_cents} \| None`.<br>**The API** passes `principal.label` (`api/orders.py:66-78`, today only the id). | **Locking by credential:** under READ COMMITTED a `FOR UPDATE` re-checks its `WHERE` after waiting, so a "Nieuwe code" committed meanwhile gives no row, which is the right 404 (AC12). **`lock_timeout`:** a wallet locked by the clean-up's one long transaction (`wallet_cleanup.py:30-39`) would otherwise hold the market lock until the 10 s step timeout. Two seconds gives a 503 the bar retries with the same key. **Any `AppError`** raised inside `engine.begin()` rolls the transaction back and leaves the step unchanged (`holder.py:460-479`), so "every refusal writes nothing" holds by construction. |
| PD6 | Replay bytes with a new receipt field (Phase 3 PD7) | `Receipt.body()` becomes `model_dump_json(exclude_unset=True)`. Every new receipt sets `wallet` explicitly, `null` included. A receipt stored before B-06 has no `wallet` key, so it replays exactly as it was first sent. **Confirm** | Without this, a retry across the deploy gains `"wallet":null` and stops being byte-identical. |
| PD7 | "A replay whose body names a different wallet" (SD16) | `StoredOrder` gains `payment_wallet_id` (a left join on `wallet_entry.order_id`). The replay is judged as today, and then:<br>• a wallet in the body but no payment, or a payment but no wallet in the body → 422;<br>• the body's credential resolving now to a live wallet other than `payment_wallet_id` → 422;<br>• resolving to that wallet, or to none (re-coded or deleted since), → the stored receipt.<br>This is the same on the `NoLiveRunError` path outside the lock (`runtime/orders.py:300-308`). **Confirm** | The receipt holds a name, not an id. A genuine retry after "Nieuwe code" must not be refused: every replay writes nothing, so leniency here cannot charge twice. |
| PD8 | SD8 in code | `app/db/wallets.py`:<br>• `delete_wallet` writes a `closing` of −balance when the balance ≠ 0 (today `> 0`, `:422`);<br>• `EntryKind` gains `payment` and `refund`.<br>`app/runtime/wallets.py`:<br>• `move` refuses only `amount == 0` (today `<= 0`, `:336`);<br>• `delete_own_wallet` locks, reads the balance and raises the new `BalanceNegative` 409 `balance_negative` when < 0;<br>• `reverse` is unchanged: its `balance < amount` check already refuses going below zero, whatever the limit (AC29). | The clean-up and admin delete then write debt off with no new code. A closing from the clean-up still carries no run (B-05 /review R3). |
| PD9 | The new routes (interface) | **Router `app/api/bar.py`** (`prefix="/bar"`, `require_role("bar", "admin")`):<br>• `POST /api/bar/wallet-lookup` body `WalletQuery` → `BarWallet{name, balance_cents}`, or 404;<br>• `GET /api/bar/payments` → this key's payments of the last 10 min, newest first.<br>**Router `app/api/payments.py`** (`prefix="/payments"`, `require_role("bar", "kassa", "admin")`, then draining):<br>• `POST /api/payments/{entry_id}/refund` with `Idempotency-Key` → 201, or 200 on replay. Order:<br>&nbsp;&nbsp;1. idempotency (`_book_once`);<br>&nbsp;&nbsp;2. not a `payment` → 404 `payment_not_found`;<br>&nbsp;&nbsp;3. a bar key whose entry has another `actor_key_id`, or is older than `BAR_REFUND_WINDOW_MS = 600_000` on the app clock (`now − created_at > window`) → 403 `refund_not_allowed`;<br>&nbsp;&nbsp;4. lock the wallet; deleted → 409 `wallet_deleted`;<br>&nbsp;&nbsp;5. already refunded → 409 `already_refunded`;<br>&nbsp;&nbsp;6. insert `refund` +\|amount\| with the payment's `run_id`, `refunds_entry_id`, the actor and the key.<br>**Kassa** (`app/api/kassa.py`):<br>• `GET /api/kassa/wallets/{wallet_id}/payments`.<br>**List rows:**<br>• `PaymentData{entry_id, amount_cents, created_at, lines: [{name, qty}] \| null, refunded}`;<br>• the bar adds `name: str \| null` (the wallet's; `null` once deleted);<br>• the kassa adds `actor_label`.<br>`amount_cents` is the amount paid, positive, and `lines` is `null` once the order is gone (AC24). | 404 before 403 keeps the matrix honest: a bar key on an unknown id is not 401/403 (`test_authorization_matrix.py:201`). It also tells no one whether a payment exists that they may not see. The list amount is positive, as `TopupData`'s is. |
| PD10 | SD20's totals | `GET /api/admin/wallets` drops `outstanding_cents` for `positive_balance_cents` (the sum of balances > 0) and `negative_balance_cents` (the sum of balances < 0, ≤ 0), both over live wallets. `per_borrel` rows gain `net_payment_cents` = −(the sum of `payment` + `refund` entries) for that run. A run with payments but no top-ups gets a row. The no-run row (B-05 PD2 A) shows when either sum is non-zero. **Confirm** (the names) | "Outstanding" would net credit against debt. No field name suggests money the association earned (B-05 T9). |
| PD11 | How a negative balance is spelled (SD19) | `formatBalance(cents)` is added to `lib/format.ts`: `cents < 0 ? '−' + formatEuro(-cents) : formatEuro(cents)`, with U+2212. That gives `−€ 2,10` and `€ 7,50`. It is used for every balance: player, kassa, bar, the Wallets list, "Rood", and the saldo in the paid message. `formatEuro` itself is unchanged. **Confirm** | The spec writes "−€2,10" (U+2212). `formatEuro(-210)` gives `€ -2,10` (`format.test.ts:14`), and that spelling is pinned by the koers deltas. The no-break space is B-05 PD15's spelling. |
| PD12 | The bar page's model (SD4–SD7) | **`model/basket.ts`** (pure): ordered lines `{drink_id, qty}`.<br>• `add` (up to 99), `remove`, `clear`;<br>• `totalCents(lines, quote)` is `null` if a price is missing;<br>• `shortfallCents(total, balance, limit)`.<br>**`orderIntents.ts`:**<br>• `create(quote, lines, wallet)`;<br>• the entry holds `lines` and `wallet` instead of `drinkId`;<br>• the 409 record must price every line, else `failed`;<br>• `confirm` rebuilds the body from the 409's record with the same lines and wallet, and a new key;<br>• a new state `refused`, holding `{code, details}`, for `wallet_required`, `wallet_not_found` and `insufficient_balance`.<br>**`barController.ts`:**<br>• `add(drinkId)` changes only the basket (no request);<br>• `checkout()` reads `hold.displayed` once and calls `intents.create`, refusing as `tap` does today (stale, no quote, conflict pending);<br>• drink buttons and "Afrekenen" both press and release the hold (SD4).<br>**While an intent for the basket is open** (sending, retrying, conflict, unknown), the basket and the wallet are shown but locked. On accept both clear (SD6). On a refusal or a cancel both stay, except that `wallet_not_found` clears the wallet (AC12). **Confirm** (the lock) | One path from tap to request remains (frontend-architecture.md:178-181). AC11, AC12 and AC18 all require the basket to still exist while the answer is pending. |
| PD13 | The basket total and the `qty * price` lint ban | `revenueArithmetic` (`eslint.config.js:40-52`) bans `qty` × anything in production code (Phase 5 AC17: revenue comes from the server). The basket total is not revenue. It is the price on screen that AC17 (B-06) asks the page to compute. One override turns the rule off for `src/features/bar/model/basket.ts` only, with a comment citing B-06 AC17, and `lint-rules.test.ts` pins that it still fires in every other bar file. **Confirm** | Renaming variables to dodge the rule would hide the decision. |
| PD14 | Reusing the kassa's scanner (SD12) | `Scanner.tsx`, `camera.ts` and `decodeQr.ts` (+ tests) move from `features/kassa/` to `src/components/scanner/`, with their CSS classes in a `Scanner.module.css`. `jsqr` stays a dynamic import. The kassa imports them from there, unchanged in behaviour. | The boundaries rule forbids `bar → kassa` (`eslint.config.js:123-138`). `components` admits any file. |
| PD15 | Letting go (SD6, AC19) | "No tap on the page" means no `pointerdown` or `keydown` inside the bar page's root. The 60 s timer (`WALLET_IDLE_MS = 60_000`, `model/constants.ts`) runs only while a wallet or a non-empty basket is held and no basket intent is open. It restarts on each tap. It runs on the controller's injected `setTimeout`, as the hold does. **Confirm** | Clearing a basket while its order is in flight would break PD12. |
| PD16 | The bar's recent payments (SD9, AC20) | Fetched on mount, after every accepted wallet order, after every refund, and every 30 s while the page is open, so a payment drops out once it is older than 10 min. The server decides the window. The page never filters by its own clock. **Confirm** | A phone's clock may be wrong. 30 s means a payment may stay listed for up to 30 s past its window, and a refund then answers 403 `refund_not_allowed` with PD18's text. |
| PD17 | **Owner (wording) — approved as written at the audit (2026-10-25).** The two info popups (SD3, AC3) | Their names and paragraphs are in § The table below, E40 and E41, in B-01's form. `tests/unit/test_setting_explanations_text.py` reads that section of **this plan** as its source for E40–E41, as it reads the B-01 and B-03 specs. `test_setting_explanations_values.py` gains rules for both. | B-01 SD3 makes the source text the fixture. The spec gives no text, and editing the approved spec is not this plan's to do. |
| PD18 | Page texts the spec does not fix. **Confirm** | Euro amounts use `formatEuro`, balances `formatBalance`. The spec's own texts keep their wording, in that spelling.<br>**Bar:**<br>• the picker: "Code typen" with "Zoeken"; "Camera" where `canUseCamera()`; a lookup 404 "Onbekende wallet"; any other lookup failure (network, 503 `shutting_down` or `standby`, an unparsable answer) "Verbindingsfout. Probeer opnieuw.", as the kassa's `refusalText` does (`kassa/errors.ts:12-16`). On either failure no wallet is held and the typed code stays in the field;<br>• the held wallet: "<naam>" large, "saldo <B>", "Andere wallet", "Annuleren";<br>• a basket line: "<n>× <drank> — <€>" with "−"; "Leegmaken";<br>• the button: "Afrekenen <€T>"; "Afrekenen zonder wallet <€T>"; disabled "Scan eerst een wallet"; disabled "Saldo <B> — nog <€X> tekort";<br>• the 409 dialog: "Prijzen zijn veranderd:", one "<drank>: <€ oud> → <€ nieuw>" per changed line, "Nieuw totaal: <€>", "Bevestigen", "Annuleren";<br>• answers: "Betaald <€T> — <naam>, saldo <B>"; without a wallet "<regels> besteld — <€T>"; "Onbekende wallet";<br>• the list: "Betalingen (laatste 10 minuten)"; a row "<regels> — <€> om HH:mm, <naam of 'verwijderde wallet'>"; "Terugboeken" or "teruggeboekt"; empty "Nog geen betalingen"; the confirm "<€> terugboeken naar <naam>?";<br>• refusals: `already_refunded` "Deze betaling is al teruggeboekt."; `refund_not_allowed` "Terugboeken kan hier alleen binnen 10 minuten na de betaling."; `wallet_deleted` "Deze wallet bestaat niet meer."; a network failure "Verbindingsfout. Probeer opnieuw."<br>**Kassa:**<br>• "Betalingen"; a row "<regels> — <€> op <d mmm HH:mm>, <label>"; no lines "Bestelling niet meer beschikbaar"; the same buttons and refusals.<br>**Player:** "Eerst aanvullen bij de kassa".<br>**Admin:**<br>• "Tegoed: <€>"; "Rood: <B>";<br>• per borrel "<naam>: opgewaardeerd <€>, besteed <€>";<br>• deleting a wallet in debt: "Wallet '<naam>' verwijderen? De schuld van <€> vervalt." | Errors are tasks. The wording follows B-05's pages. |
| PD19 | Self-delete in debt on the player page (AC26) | When the shown balance is < 0, "Wallet verwijderen" shows "Eerst aanvullen bij de kassa" and sends nothing. Otherwise the confirm is as today. A 409 `balance_negative` (the balance fell meanwhile) shows the same text. **Confirm** | B-05's confirm, "Je saldo van … vervalt.", would be false for a debt. Sending the DELETE without a confirm could delete a wallet whose balance has since reached zero. |
| PD20 | The e2e flow (spec Verification › Playwright) | A new `web/e2e/payments.spec.ts`, with its own `startServer('payments', ['--empty'])` and serial mode. Steps 1–6 run on loopback. That origin is secure, so "Camera" is offered: AC32's "both". Step 7 repeats the bar flow on `http://payments.test:<port>`, mapped by `--host-resolver-rules` exactly as B-05 PD16. There it asserts `isSecureContext === false`, no "Camera", and a booked order with and without a wallet (AC31, AC32). | B-05 PD16's equivalence argument, reused. |
| PD21 | Documents beyond the spec's list. **Confirm** | Besides the spec's list, T20 also adds "Amended by B-06" notes at:<br>• Phase 5 SD7 (`crypto.randomUUID()` per tap, `phase-5-bar-orders.md:112-113`);<br>• Phase 6 SD2's new-run defaults (`phase-6-admin.md:111-112`);<br>• B-05 SD14 ("whether either is safe for paying is B-06's question"), SD16 (the one outstanding total) and SD22 (the kassa page's contents). | Each is made untrue by B-06. Leaving them would mislead the next spec. |
| PD22 | The basket's 409 dialog in `ConfirmDialog` | `ConfirmDialog`'s `message` widens from `string` to `ReactNode` (`components/ui/ConfirmDialog.tsx:20-29`), so the changed lines are a list, not one run-on string. Every existing caller passes a string and is unaffected. **Confirm** | A list of changed lines reads on a phone. A shared-component change, so it is named here. |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `db/migrations/versions/0014_wallet_payments.py` | Create | PD3 | T1 |
| `app/db/models.py` | Modify | `Run` (two columns, one CHECK), `WalletEntry` (two columns, the CHECK texts) | T1 |
| `tests/integration/test_schema.py`, `tests/integration/test_migrations.py`, `tests/meta/test_guard_migrations_hook.py` | Modify | Pins for PD3; `0014` up from `0013` (AC1); head is `0014_wallet_payments.py` | T1 |
| `app/db/runs.py`, `app/cli/import_v1.py` (only under PD1 B) | Modify | The columns on create, read, update; `create_run` sets `true` | T2 |
| `app/runtime/config_patch.py`, `app/runtime/config.py` | Modify | Two top-level `ConfigPatch` fields; merge, record, `RunConfigData` | T2 |
| `app/runtime/holder.py`, `app/runtime/rehydrate.py`, `app/realtime/messages.py`, `app/realtime/publish.py`, `tests/api/ws_fixture.py` | Modify | The view, `ConfigChanged`, `RunInfo` (snapshot and `config`) | T2 |
| `web/src/features/exchange/model/schemas.ts`, `__fixtures__/ws-messages.json` | Modify (fixture regenerated) | `RunInfo` gains both fields | T2 |
| `app/db/wallets.py`, `app/runtime/wallets.py`, `app/api/wallet.py` | Modify | SD8 (PD8) | T3 |
| `app/api/wallet_query.py` | Create | `WalletQuery` (moved from `kassa.py`) | T4 |
| `app/api/orders.py`, `app/runtime/orders.py`, `app/db/orders.py` | Modify | The payment (PD5, PD6) | T4, T5 |
| `web/e2e/analytics.spec.ts` | Modify | Its UI-made borrels turn the switch off (T4), then order through the basket (T12) | T4, T12 |
| `web/src/features/bar/api/orders.ts` (+ test) | Modify | `Receipt` takes `wallet` (T4); the basket body (T12) | T4, T12 |
| `app/api/bar.py` | Create | Lookup and payments list | T6 |
| `app/api/payments.py` | Create | The refund | T7 |
| `app/api/kassa.py` | Modify | `WalletQuery` import (T4), payments list (T7) | T4, T7 |
| `app/main.py` | Modify | Two routers | T6, T7 |
| `app/api/wallets_admin.py` | Modify | PD10 | T8 |
| `tests/api/test_authorization_matrix.py`, `tests/api/test_draining.py`, `tests/api/test_standby.py` | Modify | Rows for every new route | T6, T7 |
| `web/src/api/generated/schema.d.ts` | Modify (regenerated) | `./scripts/gen_api_types.sh`; never hand-edited | T2, T4, T6, T7, T8 |
| `web/src/lib/format.ts`, `format.test.ts` | Modify | `formatBalance` (PD11) | T9 |
| `web/src/features/player/WalletView.tsx` (+ test) | Modify | Balance spelling; PD19 | T9 |
| `web/src/features/kassa/KassaPage.tsx`, `MoveDialog.tsx` (+ tests) | Modify | Balance spelling (T9); scanner import (T10); payments (T16) | T9, T10, T16 |
| `web/src/components/scanner/` (`Scanner.tsx`, `Scanner.module.css`, `camera.ts`, `decodeQr.ts`, tests) | Create (moved) | PD14 | T10 |
| `web/src/features/kassa/KassaPage.module.css` | Modify | Scanner classes leave | T10 |
| `web/src/features/bar/useBarController.ts`, `model/orderIntents.ts`, `model/barController.ts` | Modify | Keys (T11); basket and intents (T12); wallet (T13); release (T14) | T11–T14 |
| `web/src/walletCode.provenance.test.ts` | Modify | Bar in scope; `.test.tsx` skipped like `.test.ts` | T11 |
| `web/src/features/bar/model/basket.ts` (+ test) | Create | PD12 | T12 |
| `web/src/features/bar/OrderPad.tsx`, `OrderConflict.tsx`, `PendingOrders.tsx`, `BarPage.tsx`, `api/orders.ts` (+ tests, `money.property.test.ts`) | Modify | The basket (T12); the wallet (T13); release (T14); the list (T15) | T12–T15 |
| `web/src/components/ui/ConfirmDialog.tsx` (+ test) | Modify | PD22 | T12 |
| `web/eslint.config.js`, `web/src/lint-rules.test.ts` | Modify | PD13 | T12 |
| `web/e2e/bar.spec.ts`, `web/e2e/admin.spec.ts` | Modify | The basket replaces "+1" | T12 |
| `web/src/features/bar/WalletPicker.tsx`, `HeldWallet.tsx`, `api/wallets.ts` (+ tests) | Create | SD4, SD12, SD13 | T13 |
| `web/src/features/bar/model/constants.ts` | Modify | `WALLET_IDLE_MS` | T14 |
| `web/src/features/bar/RecentPayments.tsx` (+ test) | Create | SD9 | T15 |
| `web/src/features/kassa/PaymentList.tsx`, `api.ts`, `errors.ts` (+ tests) | Create / Modify | SD9 | T16 |
| `web/src/features/wallets/WalletsSection.tsx`, `api.ts` (+ test), `web/src/app/pages/SettingsPage.test.tsx`, `web/e2e/wallets.spec.ts` | Modify | PD10 | T8 |
| `web/src/features/settings/GlobalSection.tsx`, `useRunConfig.ts`, `explanations.json`, `index.ts` (+ tests) | Modify | SD1, SD2, SD3 | T17 |
| `tests/unit/test_setting_explanations_text.py`, `tests/unit/test_setting_explanations_values.py` | Modify | PD17 | T17 |
| `tests/integration/test_wallet_payments_races.py`, `test_wallet_payments_restart.py` | Create | AC9, AC34 | T18 |
| `tests/integration/test_export_workbook.py`, `tests/api/test_analytics.py`, `tests/integration/test_delete_run.py`, `tests/integration/test_wallet_cleanup.py` | Modify | AC36, AC24, AC27 end to end | T18 |
| `web/e2e/payments.spec.ts` | Create | PD20 | T19 |
| `docs/adr/0001-setup-decision-record.md`, `docs/design/*.md` | Modify | **Owner stop** | T20 |
| `docs/specs/phase-5-bar-orders.md`, `phase-6-admin.md`, `phase-b-05-player-wallets.md`, `defect-register.md`, `docs/runbooks/venue.md`, `docs/backlog.md` | Modify | Amendment notes; D-49 closed; venue; backlog | T20 |

Untouched, and checked at T20: `exchange/`, `tests/engine/golden/`, `app/runtime/grace.py`, `app/jobs/export_xlsx.py`, `app/db/exports.py`, `app/db/analytics.py`, `web/src/features/bar/FinancialPanel.tsx`, `web/src/features/bar/RevenueChart.tsx`, and every existing migration.

---

## Tasks

### T1 — The schema

- **Implements:** AC1 (the backfill), AC24 (`SET NULL`, the DB half), AC27 and AC28 (signs the DB admits), AC34 (the CHECKs that keep a payment tied to one order); SD1, SD2, SD8, SD10, PD2, PD3
- **Expected output:**
  - `0014_wallet_payments.py` per PD3, laid out as `0013_wallets.py`:
    - a docstring with one bullet per decision;
    - `Revises: 0013`, `min_code_revision = "unchanged"`;
    - `op.add_column` with `server_default`, as `0007_run_grace_and_candles.py:31-42`;
    - the two CHECKs on `wallet_entry` dropped and recreated by name;
    - `downgrade()` restores both CHECKs and drops the new constraints and columns. The docstring says it fails loudly while any `payment`/`refund`, positive `closing`, or wrongly signed move row exists (as `0009:15-17`).
  - `models.py`: `Run` and `WalletEntry` mirror it column for column, CHECK text included. The `0013` docstring's "the schema's first `ON DELETE SET NULL`" stays as written: it is history.
  - `test_schema.py`, by SQL in `_in_transaction`:
    - all seven kinds are accepted with their signs, including a `payment` of 0, a `refund` of 0, a `closing` of +210, and a `move_out` of +210 with its `move_in` of −210;
    - rejected: a `topup` of 0, a `payment` of +1, a `refund` of −1, a `closing` of 0, a `move_in` of 0;
    - the unknown-kind test (`:823-830`) uses another kind than `payment`;
    - a `refund` without `refunds_entry_id`, a second refund of one payment, and an `order_id` on a `topup` all fail;
    - a second `payment` naming one order fails;
    - `credit_limit_cents` −50, 5050 and 25 fail, and 0, 50 and 5000 pass;
    - deleting a run with a paid order sets that entry's `order_id` and `run_id` to NULL and keeps the row, as `:886-906`.
  - `test_migrations.py`: upgrade to `0013`, insert a run, upgrade to head. That run has `wallet_required = false` and `credit_limit_cents = 0` (AC1, as `:200-221`). The `0013` round-trip test still passes through `0014`'s downgrade.
  - `test_guard_migrations_hook.py:158-166,231-239` name `0014_wallet_payments.py`.
- **Verification:** `uv run pytest tests/integration/test_schema.py tests/integration/test_migrations.py tests/meta/test_schema_compat_coverage.py tests/meta/test_guard_migrations_hook.py tests/integration/test_delete_run.py` (needs the compose `db`); `uv run mypy app`.
- **Depends on:** —
- **Autonomy note:**
  - Constraint and index names other than PD3's, the docstring wording and the test layout are the builder's.
  - A different default, a pairing CHECK on `order_id`, or a `min_code_revision` other than `"unchanged"` is not: stop and ask.
  - The guard hook blocks edits to `0013`. Never work around it.

### T2 — The switch and the limit on the server and on the wire

- **Implements:** AC1, AC2 (stored, 422, the `config` broadcast), AC3 (neither in a profile or a copy); SD1, SD2, SD3, SD17, PD1, PD4
- **Expected output:**
  - **Run creation** (`app/db/runs.py`):
    - `create_draft_run(…, wallet_required: bool = False)`;
    - `create_run` passes `True`, on every path: plain, `profile_id` and `copy_from_run_id`;
    - under PD1 B, `import_v1` passes `True` and `seed_live_run` turns it off.
  - **Reading and writing the columns** (`app/db/runs.py`):
    - `RunRow` and `get_run` (`:176-185, :337-352`) and `update_run` (`:355-367`) carry both columns;
    - revision 1's config (`:519-528`) carries both too, so it stays equal to the GET body (Phase 6 PD6).
  - `config_patch.py`: `ConfigPatch` (`:117-126`) gains `wallet_required: StrictBool | None` and `credit_limit_cents: Annotated[int, Field(strict=True, ge=0, le=5000, multiple_of=50)] | None`. They are **not** `ParamsPatch` fields, so `PROFILE_FIELDS` stays 22 (`:129-134`, `test_profile_settings.py:59-61`).
  - `config.py`:
    - `_is_empty`, `_merged` and `_record` handle both fields;
    - `RunConfigData` gains both;
    - `commit_transition` puts them in the view and in `ConfigChanged`.
  - `holder.py`: `MarketView`, `_empty_view` and `ConfigChanged` gain both fields. `rehydrate.py` selects them (`:72-82`) and carries them on `RehydratedRun`.
  - **On the wire:**
    - `messages.py` `RunInfo` gains `wallet_required: StrictBool` and `credit_limit_cents: NonNegative`, so both the snapshot and `config` carry them;
    - `publish.py` fills them from the holder and from the event;
    - `ws_fixture.py` constructs them, and the fixture is re-recorded with `uv run python -m tests.api.ws_fixture --write`.
  - `schemas.ts` `RunInfo` (strict, `:46-51`) gains both, in the same commit as the server. Every web test that hand-builds a `run` gains both fields:
    - `BarPage.test.tsx`, `PendingOrders.test.tsx`, `OrderPad.test.tsx`, `barController.test.ts`;
    - `FinancialPanel.test.tsx`, `HomePage.test.tsx`, `KoersPage.test.tsx`, `IdleSection.test.tsx`, `ManipulationPage.test.tsx`;
    - `money.property.test.ts:50-55`.
  - Tests:
    - `test_config.py`:
      - the GET shape (`:110-119`) with both;
      - a draft PATCH of each is stored, and so is the revision (`:186-206`);
      - 422 for `credit_limit_cents` −50, 25, 5050, `"250"`, `2.5` and `null`, and for `wallet_required` `"true"`, `1` and `null`, with nothing stored;
      - a live PATCH of each gives one `config` frame whose `run` carries the new value (as `:472-496`) (AC2).
    - `test_config_live.py`: a live switch change is one transition and changes the view, as `:305-332`.
    - `test_runs.py` (api and integration):
      - a new run has on and 0, from a plain create, from a profile, and from `copy_from_run_id` of a run that is off at 250 (AC1, AC3);
      - under PD1 A, an imported run is off (`tests/integration/test_import_v1.py`).
    - `test_profiles.py`: a profile saved from a run that is off at 250 holds neither, and loading it leaves both columns as they were (AC3).
    - `test_publish.py:250-255,357-372` and `test_messages.py:236,269` pin the new `run` fields. `test_ws_fixture.py` stays green.
    - AC2's 403 for bar, kassa and display is the matrix's existing `PATCH /api/runs/{run_id}/config: ADMIN` row, unchanged.
  - The schema is regenerated.
- **Verification:**
  - `uv run pytest tests/api/test_config.py tests/integration/test_config_live.py tests/integration/test_config_draft.py tests/api/test_runs.py tests/integration/test_runs.py tests/api/test_profiles.py tests/unit/test_profile_settings.py tests/unit/test_publish.py tests/unit/test_messages.py tests/api/test_ws_fixture.py tests/integration/test_rehydrate.py tests/integration/test_import_v1.py tests/api/test_authorization_matrix.py`
  - `./scripts/gen_api_types.sh && git diff --stat -- web/src/api/generated`
  - `pnpm -C web exec tsc -b`
  - `pnpm -C web exec vitest run src/features`
  - `uv run mypy app`
- **Depends on:** T1
- **Autonomy note:**
  - Field order and helper names are the builder's.
  - Putting either field under `params`, or into a profile, is not.
  - If a stored revision is read back somewhere that validates it against `RunConfigData` (so that old revisions without the fields would fail), stop and report: the plan assumes none is.
  - A live save must stay one transition (PD4). If the builder thinks a wallet-only save should skip the version bump, stop and ask.

### T3 — Debt: delete, clean-up, move, reversal

- **Implements:** AC26 (API), AC27, AC28, AC29; SD8, PD8
- **Expected output:**
  - PD8's changes in `app/db/wallets.py` and `app/runtime/wallets.py`, plus the new error `BalanceNegative` (409 `balance_negative`). `DELETE /api/wallet` (`app/api/wallet.py:139-150`) answers it before the cookie is cleared.
  - Kind filters stay as they are, so `topups` and `topups_per_run` still read only `topup`/`reversal` (`:541,555,584,665`).
  - Tests (entries inserted through the repository, a `payment` of −850 making a balance of −350):
    - `test_wallets_repo.py`: `delete_wallet` at −350 writes a `closing` of +350, the ledger sums to 0, and the row is blanked (AC27).
    - `test_wallet_player.py`: `DELETE /api/wallet` at −350 → 409 `balance_negative`, no entry, the row intact, the cookie kept (AC26). At 0 it is still 204.
    - `test_wallets_admin.py`: admin delete at −350 → 204 and `("closing", 350, live run, label)` (AC27).
    - `test_wallet_cleanup.py`: an inactive wallet at −350 is swept with a `closing` of +350 and no run (AC27, R3).
    - `test_kassa_corrections.py`:
      - a move from a wallet at −350 → `move_out` +350 and `move_in` −350, the old row blanked, the new balance −350 plus whatever it had (AC28);
      - zero, or the same wallet → `nothing_to_move` (AC28);
      - a reversal of a 1000 top-up on a balance of 500, with any limit set on the live run → 409 `insufficient_balance` (AC29);
      - the `topup_not_found` parametrisation (`:210-255`) gains `payment` and `refund`.
- **Verification:** `uv run pytest tests/integration/test_wallets_repo.py tests/api/test_wallet_player.py tests/api/test_wallets_admin.py tests/integration/test_wallet_cleanup.py tests/api/test_kassa_corrections.py tests/integration/test_wallet_concurrency.py`; `uv run mypy app`.
- **Depends on:** T1
- **Autonomy note:**
  - This task changes no OpenAPI schema. If declaring the 409 would change `schema.d.ts`, leave it undeclared, as B-05's 409s are.
  - A refusal by the clean-up or by admin delete of a wallet in debt is not allowed (SD8).
  - Reading the run's limit in a reversal is not allowed (AC29).

### T4 — Paying in the order

- **Implements:** AC5 (the server takes the wallet), AC6, AC7, AC8, AC12 (server), AC14 (server), AC15 (server), AC16, AC33 (orders, unchanged), AC34 (failure at any statement writes nothing), AC37 (the replay comparison); SD13–SD16, SD21, PD2, PD5, PD6
- **Expected output:**
  - `app/api/wallet_query.py`: `WalletQuery` moved from `kassa.py:41-53`. `kassa.py` imports it.
  - `api/orders.py`:
    - `OrderBody.wallet: WalletQuery | None = None`;
    - `place_order` receives the principal's id and label.
  - `runtime/orders.py`:
    - `WalletRequired` 409;
    - the switch check after the grace rule;
    - `Receipt.wallet: PaidWallet | None`, and `body()` per PD6;
    - `receipt_for` takes the paid wallet;
    - `write_order` is called with `PaymentInput(query, limit=view.credit_limit_cents, actor_label)` when the body names one.
  - `db/orders.py` `write_order`: PD5's statements, in order, before `compare_and_set`. `payment` stays optional, so the durability harness (`tests/integration/durability/harness.py`) is untouched.
  - `db/wallets.py`:
    - `lock_wallet_by_qr_token` and `lock_wallet_by_short_code`;
    - `InsufficientBalance` takes `extra`.
  - `web/e2e/analytics.spec.ts`: after each "Nieuwe borrel" it PATCHes `{wallet_required: false}` over the admin API, so its "+1" orders still book.
  - **Every other test that books an order on a run made by `create_run`** (`POST /api/runs`, a profile, or `copy_from_run_id`) now meets the switch on. The builder finds them all: `rg -n "create_run\(|/api/runs['\"]" tests web/e2e`, then each hit that later posts `/api/orders` or taps a drink. Each gets `{wallet_required: false}` by PATCH (or `create_draft_run`'s default), unless the test is about the switch. The list found is written in the commit message. `web/e2e/admin.spec.ts` and `profiles.spec.ts` are checked here, not left to T12. **The whole gate (`./scripts/check.sh`) is green at T4's tip**, not only T4's named tests.
  - `web/src/features/bar/api/orders.ts`: the strict `Receipt` zod (`:21-37`) gains `wallet` as optional and nullable, so the bar keeps parsing receipts once the server sends `"wallet": null`. `api/orders.test.ts` pins a receipt with `wallet: null` and one without the key.
  - Tests:
    - `tests/api/test_orders.py`, on `live_client` with a wallet funded by a kassa top-up and the run's limit set by PATCH:
      - paid: 201; the receipt's `wallet` is `{name, balance_after_cents}`; one `payment` entry of −`total_cents` with `order_id`, the live run, the bar key's id and label, and no key; the balance falls by the total (AC6);
      - the limit at 250: an order to exactly −250 is accepted; at −251 → 409 `insufficient_balance {balance_cents, credit_limit_cents}`; no order, no entry, version and prices unchanged (AC7, AC8);
      - switch on, no wallet → 409 `wallet_required`, nothing written, no price moved (AC14); switch off, no wallet → 201, `wallet: null`, no entry (AC15); switch off, with a wallet → paid (AC15);
      - turned on by PATCH between two orders without a wallet → the second is 409 (AC16);
      - `wallet_not_found` after "Nieuwe code", after a delete, and for a malformed code (AC12);
      - the order of checks: a stale price with a bad wallet → 409 `price_changed`; switch on with a bad credential and no wallet → `wallet_required`; an unknown wallet with too little balance → 404 (SD15);
      - a €0,00 order with a wallet → one `payment` of 0 (PD2);
      - a body with both `qr_token` and `short_code` → 422.
    - `tests/integration/test_place_order.py`:
      - a wallet variant of `WRITE_ORDER_STATEMENTS` and of `test_a_failure_at_any_statement_is_503_and_changes_nothing` (`:426-490`): a failure at any statement writes no order, no entry and moves no price (AC34);
      - a wallet held `FOR UPDATE` by another transaction → the order is 503 within about 2 s, and the holder is not diverged (PD5);
      - the same order sequence with and without wallets gives equal `holder.state` (`y` bytes and version) and equal receipts' prices (AC37), using `_market` (`:139-180`) as `:557-586` does.
    - `tests/integration/test_orders.py:41` counts the payment's statements in its wallet variant.
    - `test_draining.py`'s orders row is unchanged and green (AC33).
  - The schema is regenerated.
- **Verification:**
  - `uv run pytest tests/api/test_orders.py tests/integration/test_place_order.py tests/integration/test_orders.py tests/integration/test_bar_price_snapshot.py tests/integration/test_durability.py tests/api/test_kassa_topup.py tests/api/test_draining.py`
  - `uv run pytest tests/unit tests/meta tests/engine`
  - schema drift as T2
  - `pnpm -C web exec playwright test e2e/analytics.spec.ts`
  - `uv run mypy app`
- **Depends on:** T2 (the view's fields), T3 (`app/db/wallets.py`, `EntryKind`)
- **Autonomy note:**
  - Names of the input dataclasses are the builder's. So is putting the payment statements in `db/orders.py` or in a `db/wallets.py` helper called from it.
  - Not the builder's:
    - the check order (SD15);
    - the lock taken before any write;
    - storing the order's key on the entry;
    - any change to `exchange/`, `grace.py` or the hold constants.
  - If AC37's comparison differs, stop and run `engine-guardian`.

### T5 — Replaying a wallet order

- **Implements:** AC10, AC34 (replay across a restart); SD16, PD6, PD7
- **Expected output:**
  - `db/orders.py`: `find_order_by_key` returns `payment_wallet_id`.
  - `runtime/orders.py`: `_replay` judges the wallet per PD7, on both the locked path and the `NoLiveRunError` path. For the second it resolves the credential with `get_by_qr_token`/`get_by_short_code` (unlocked).
  - Tests:
    - `tests/api/test_orders.py`:
      - a paid order resent with the same key and body → 200 with identical bytes, `wallet.balance_after_cents` included, even after a top-up has changed the balance; no new entry (AC10);
      - the same key naming another live wallet → 422; with the wallet left out → 422; a key first used without a wallet, resent with one → 422 (AC10);
      - a resend after "Nieuwe code" → the stored receipt (PD7);
      - a receipt stored without a `wallet` key (written by SQL as a pre-B-06 order) replays with no `wallet` key in its bytes (PD6).
    - `tests/integration/test_restart_replay.py` gains a paid order: the app is killed, restarted, and the replay is 200 with identical bytes and still one `payment` entry (AC34). Its run turns the switch on by PATCH and a wallet is funded through the kassa routes.
- **Verification:** `uv run pytest tests/api/test_orders.py tests/integration/test_restart_replay.py tests/integration/test_place_order.py`; `uv run mypy app`.
- **Depends on:** T4
- **Autonomy note:** This task changes no OpenAPI shape. A replay that writes anything is a bug: stop. Refusing a genuine retry because its token no longer resolves is not allowed (PD7).

### T6 — The bar's lookup and its recent payments (server)

- **Implements:** AC4 (server), AC20 (server), AC33 (standby), AC35 (these two routes); SD9, SD13, PD9
- **Expected output:**
  - `app/api/bar.py` per PD9, registered in `main.py`.
  - `runtime/wallets.py`: `bar_lookup` reuses `lookup` (`:148-166`) and returns only the name and balance. `recent_payments(engine, *, actor_key_id, now_ms)` filters `now − created_at ≤ BAR_REFUND_WINDOW_MS`.
  - `db/wallets.py`: `payments(conn, *, wallet_id=None, actor_key_id=None, since=None) -> list[(EntryRow, refunded, wallet_name | None, lines | None)]`. Lines come from `order_line` joined to `drink.name`, in order of `drink_id`. `refunded` comes from an outer join on `refunds_entry_id`.
  - Matrix rows: both routes `WRITERS` (`:26`). Standby gains both.
  - `tests/api/test_bar_wallets.py`:
    - lookup by token and by code → exactly `{name, balance_cents}`; unknown or deleted → 404 (AC4, AC35);
    - two bar keys: each sees only its own payments, with lines, total, name and `refunded` (AC20);
    - a payment after `advance(600_001)` is gone from the list (AC20);
    - a payment whose wallet was deleted shows `name: null`;
    - admin sees its own.
- **Verification:** `uv run pytest tests/api/test_bar_wallets.py tests/api/test_authorization_matrix.py tests/api/test_standby.py tests/meta/test_route_authorization.py`; schema drift; `uv run mypy app`.
- **Depends on:** T4 (payment entries exist; `db/wallets.py`, `schema.d.ts`)
- **Autonomy note:** Response model names are the builder's. Showing a bar key a `wallet_id`, a `short_code` or another key's payments is not.

### T7 — Refunds, and the kassa's payments list (server)

- **Implements:** AC21, AC22, AC23 (server), AC33 (refund draining, standby), AC35; SD9, PD9
- **Expected output:**
  - `app/api/payments.py` per PD9, registered.
  - `runtime/wallets.py` `refund(engine, *, entry_id, key, actor, role, now_ms)`. Its `same()` compares kind `refund` and `refunds_entry_id`.
  - `kassa.py`: `GET /wallets/{wallet_id}/payments`, using T6's `payments`.
  - Matrix:
    - a new `REFUNDERS = frozenset({"bar","kassa","admin"})` for the refund;
    - `KASSA` for the list.
  - Draining gets the refund row. Standby gets both routes.
  - `tests/api/test_payments_refund.py`:
    - a bar refund of its own payment within 10 min → 201; one `refund` of +total naming it, with the payment's run (even after that run is closed and another is live), the key and its label; the balance rises by the total; `order` rows, `order_line`, the earnings series and the engine version are unchanged (AC21);
    - a second → 409 `already_refunded`; after the wallet is deleted → 409 `wallet_deleted`; another bar key's payment, or `advance(600_001)` → 403 `refund_not_allowed`; a top-up's id → 404 `payment_not_found`; each writes nothing (AC22);
    - kassa and admin refund a payment older than 10 min booked by a bar key → 201 (AC23);
    - a replay with the same key → 200, one entry; the same key on another payment → 422 (AC23);
    - the kassa list for a wallet: newest first, lines, `refunded`, at any age (AC23);
    - draining → 503 (AC33).
- **Verification:** `uv run pytest tests/api/test_payments_refund.py tests/api/test_bar_wallets.py tests/api/test_authorization_matrix.py tests/api/test_draining.py tests/api/test_standby.py`; schema drift; `uv run mypy app`.
- **Depends on:** T6 (`runtime/wallets.py`, `db/wallets.py`, `main.py`, matrix, standby, schema)
- **Autonomy note:**
  - Not the builder's:
    - a partial refund;
    - a refund that touches the order or revenue (SD9);
    - a bar refund outside its window.
  - If the step order makes the matrix answer 403 to a bar on an unknown id, the order is wrong: fix the order, not the matrix.

### T8 — The Wallets section's totals

- **Implements:** AC30, AC25 (the Wallets list); SD20, PD10, PD18
- **Expected output:**
  - `db/wallets.py`: `balance_totals` (positive and negative sums) and `payments_per_run` (`payment` + `refund` by `run_id`).
  - `runtime/wallets.py` `overview` merges them with `topups_per_run` into PD10's rows.
  - `wallets_admin.py`'s `WalletsOverview` gets PD10's fields.
  - `WalletsSection.tsx`:
    - "Tegoed" and "Rood";
    - per-borrel rows with both amounts;
    - the list's balances via `formatBalance`;
    - the debt confirm text (PD18).
  - `wallets/api.ts` follows the generated type.
  - Tests:
    - `test_wallets_admin.py`:
      - the exact dicts (`:171-174, 186-190, 206-212, 266`) gain the new fields;
      - wallets at +4000, +1000 and −350 → 5000 and −350;
      - a run with a payment of 840 and its refund → `net_payment_cents` 0; with a second unrefunded payment of 300 → 300;
      - a payment with no run → the no-run row.
    - `WalletsSection.test.tsx`: the texts, the debt confirm, `−€ 3,50` in the list.
    - `SettingsPage.test.tsx:178` mock.
    - `wallets.spec.ts:229-230` read "Tegoed: € 15,00" and the new borrel row.
- **Verification:** `uv run pytest tests/api/test_wallets_admin.py`; `pnpm -C web exec vitest run src/features/wallets src/app/pages/SettingsPage.test.tsx`; schema drift; `pnpm -C web exec tsc -b`; `pnpm -C web exec playwright test e2e/wallets.spec.ts`.
- **Depends on:** T7 (`db/wallets.py`, `runtime/wallets.py`, schema), T9 (`formatBalance`), T17 (`SettingsPage.test.tsx`)
- **Autonomy note:** Layout is the builder's. Any figure called revenue, earnings or omzet is not.

### T9 — Debt on the player and kassa pages

- **Implements:** AC25 (player, kassa), AC26 (page); SD19, PD11, PD19
- **Expected output:**
  - `lib/format.ts` `formatBalance`. `format.test.ts`: −210 → `−€ 2,10`, 0 → `€ 0,00`, 750 → `€ 7,50`, and `formatEuro(-30)` unchanged.
  - `WalletView.tsx`: the balance via `formatBalance`; PD19.
  - `KassaPage.tsx` balance and `MoveDialog.tsx` amount via `formatBalance`.
  - Tests:
    - `WalletView.test.tsx`: the exact-text pin (`:41-56`) with a negative balance; at −210, delete shows the text and sends nothing; at 0 the confirm opens; a 409 `balance_negative` shows the text;
    - `KassaPage.test.tsx`: `−€ 2,10`.
- **Verification:** `pnpm -C web exec vitest run src/lib src/features/player src/features/kassa`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`.
- **Depends on:** T3 (the server's `balance_negative`), T10 (`KassaPage.tsx`)
- **Autonomy note:** Changing `formatEuro`, or using `formatBalance` for anything but a balance, is not the builder's (PD11).

### T10 — The scanner becomes shared

- **Implements:** AC32 (the bar's camera, enabler); SD12, PD14
- **Expected output:**
  - `Scanner.tsx`, `camera.ts`, `decodeQr.ts` and their tests are moved, with `git mv`, to `src/components/scanner/`. Their classes leave `KassaPage.module.css` for `Scanner.module.css`. `jsqr` stays `await import('jsqr')`.
  - `KassaPage.tsx` imports from the new place. No other change.
- **Verification:** `pnpm -C web exec vitest run src/components/scanner src/features/kassa src/lint-rules.test.ts`; `pnpm -C web exec eslint src`; `pnpm -C web build && uv run python scripts/check_built_assets.py web/dist`.
- **Depends on:** —
- **Autonomy note:** A pure move. Behaviour, texts and the sampling rate stay as they are. Any test assertion that changes is a regression: stop.

### T11 — D-49: the bar's keys

- **Implements:** AC31 (the code half); SD12, D-49
- **Expected output:**
  - `useBarController.ts:76` uses `newIdempotencyKey` from `lib/idempotencyKey.ts`. The deps field `uuid` is renamed `newKey` in `orderIntents.ts:68` and `barController.ts:39`, and in every test's deps.
  - `walletCode.provenance.test.ts`:
    - `src/features/bar/` joins `WALLET_CODE`;
    - `.test.tsx` is skipped like `.test.ts` (`:28`);
    - the "outside" self-test (`:62-65`) uses `src/features/koers/` instead of the bar;
    - a planted call in a bar file is caught.
  - The bar's test files may keep `crypto.randomUUID()` in their own deps. The scan skips them.
- **Verification:** `pnpm -C web exec vitest run src/features/bar src/walletCode.provenance.test.ts src/lib`; `pnpm -C web exec tsc -b`; `rg -n randomUUID web/src --glob '!*.test.*'` prints nothing.
- **Depends on:** —
- **Autonomy note:** A rename and a swap. The intent's retry and key rules stay as they are.

### T12 — The basket, without a wallet

- **Implements:** AC2 (the bar follows the switch live), AC5 (no-wallet half), AC11 (no-wallet half), AC14 (page), AC15 (page), AC17; SD4, SD5, SD7, PD12, PD13, PD18, PD22; spec Verification › Property test (baskets)
- **Expected output:**
  - `model/basket.ts` per PD12, with `basket.test.ts`.
  - `orderIntents.ts`, `barController.ts`: per PD12, with `wallet` always `null` in this task. The intent stays the only caller of `quoteFromPriceChanged` (`quote.provenance.test.ts:20-23`).
  - `OrderPad.tsx`:
    - one button per drink, "<drank> — <€>", which adds 1;
    - the basket's lines with "−" and "Leegmaken";
    - the button per PD18, reading `run.wallet_required` and `credit_limit_cents` from `useExchange((s) => s.run)`;
    - with the switch on, it stays disabled with "Scan eerst een wallet" until T13.
  - `OrderConflict.tsx` builds PD18's dialog from the entry's lines and the 409 record.
  - `PendingOrders.tsx` texts per line set.
  - `ConfirmDialog` per PD22. `api/orders.ts`: `OrderBody` lines from the basket (its `Receipt` already takes `wallet`, T4).
  - PD13's lint override and its `lint-rules.test.ts` pin.
  - `money.property.test.ts`:
    - events gain "add", "remove", "empty" and "checkout";
    - the simulated server checks every line;
    - the assertions cover every line: `quote_version` and each `unit_price_cents` equal the displayed `Quote` at the tap, from one message; retries carry the same key and body; new intents carry new keys;
    - still ≥ 10 000 cases; it prints the count and seed.
  - Tests:
    - `basket.test.ts`: add to 99 and no further; "−" to 0 removes the line; empty; the total from a quote; `null` when a price is missing (AC17).
    - `orderIntents.test.ts`: a three-line body; a 409 confirm with the same lines and a new key; a cancel sends nothing and keeps the basket; `wallet_required` → `refused`.
    - `OrderPad.test.tsx`:
      - a tap adds; a double tap gives `2×`;
      - with the switch off, "Afrekenen zonder wallet €T" posts one order of the basket at the displayed version (AC5, AC15);
      - with the switch on, it is disabled with "Scan eerst een wallet" (AC14);
      - a `config` message turning it on switches the button without a reload (AC2);
      - the basket clears on 201 and stays on a 409.
    - `PendingOrders.test.tsx` and `BarPage.test.tsx` texts.
  - e2e:
    - `bar.spec.ts`: "+1" taps become basket taps and "Afrekenen zonder wallet"; `lines` has the basket's length; the double tap is one line of 2; the 409, retry and convergence tests keep their intent;
    - `analytics.spec.ts` `order()` (`:122-148`) adds a drink and checks out;
    - `admin.spec.ts:197-208` counts drink buttons by the new name.
- **Verification:** `pnpm -C web exec vitest run src/features/bar src/components/ui/ConfirmDialog.test.tsx src/lint-rules.test.ts src/features/exchange`; `pnpm -C web exec eslint src e2e`; `pnpm -C web exec tsc -b`; `pnpm -C web exec playwright test e2e/bar.spec.ts e2e/analytics.spec.ts e2e/admin.spec.ts`. The property run's output shows the case count and seed.
- **Depends on:** T2 (`run` fields on the client), T4 (`analytics.spec.ts`; the receipt shape), T11 (the same bar files)
- **Autonomy note:**
  - Markup, CSS and module splits inside `features/bar/` are the builder's.
  - Not the builder's:
    - a second path from tap to request;
    - a price from anywhere but `hold.displayed`;
    - a basket that survives a reload (out of scope);
    - turning the lint rule off for more than `basket.ts`.
  - If the property test needs `fast-check`, stop (Phase 5 SD20).
  - If this task passes ~400 source lines, split `OrderConflict`/`PendingOrders` into T12b, keeping the chain.

### T13 — The held wallet and paying

- **Implements:** AC4, AC5 (the wallet in the body), AC11 (the same wallet on confirm), AC12 (page), AC13 (bar), AC14, AC18, AC25 (bar), AC32 (bar); SD4–SD7, SD11–SD13, SD18, PD12, PD18; spec Verification › Property test (wallet outcomes)
- **Expected output:**
  - `api/wallets.ts`: `lookupWallet(query)` → `{name, balance_cents}`, its zod typed against the generated `BarWallet`.
  - `WalletPicker.tsx`: "Code typen" and "Zoeken", sending `{short_code}` as typed. "Camera" appears only when `canUseCamera()`, and opens the shared `Scanner`, sending `{qr_token}`. A 404 shows "Onbekende wallet".
  - `HeldWallet.tsx`: the name large and "saldo <B>" (`formatBalance`).
  - The controller holds `{query, name, balance_cents}`, and the intent carries `wallet: query`.
  - **The button:**
    - "Afrekenen €T" when a wallet is held;
    - the shortfall per SD18, from `run.credit_limit_cents`;
    - "Scan eerst een wallet" while the switch is on and no wallet is held.
  - **The answers:**
    - **accepted:** "Betaald €T — <naam>, saldo <B>" from the receipt for `LINGER_MS`, then both clear;
    - **`wallet_not_found`:** "Onbekende wallet"; the wallet clears and the basket stays;
    - **`insufficient_balance`:** the shortfall text from `details`, and the held balance is updated from it;
    - **`wallet_required`:** "Scan eerst een wallet".
  - `money.property.test.ts`:
    - events gain "scan", "unknown wallet" and "rescan";
    - the server answers 409 `insufficient_balance`, 409 `wallet_required` and 404 `wallet_not_found`;
    - it asserts that every wallet request carries the held query, the confirm included.
  - Tests:
    - `WalletPicker.test.tsx`: the typed body; the 404 text; a network failure, a 503 `shutting_down` and a 503 `standby` each show "Verbindingsfout. Probeer opnieuw.", hold no wallet and keep the typed code (PD18); no "Camera" and no error when not secure, both when secure (AC32).
    - `OrderPad.test.tsx`:
      - the body carries `wallet` (AC5);
      - the confirm carries the same wallet and a new key (AC11);
      - the 404 clears the wallet and keeps the basket (AC12);
      - the shortfall disables the button with the text (AC18);
      - the paid text, then both clear after 3 s under fake timers (AC13);
      - `−€ 0,90` (AC25).
- **Verification:** `pnpm -C web exec vitest run src/features/bar src/components/scanner`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`; `pnpm -C web build && uv run python scripts/check_built_assets.py web/dist`.
- **Depends on:** T12, T10, T6 (the lookup route and its generated type)
- **Autonomy note:**
  - Layout is the builder's. Showing more of a wallet than its name and balance is not (SD13).
  - Not the builder's:
    - a confirm step before paying (SD4);
    - a check on the page that replaces the server's (SD15, SD18).

### T14 — Letting go of a wallet

- **Implements:** AC19; SD6, PD15
- **Expected output:**
  - "Andere wallet" clears the wallet. "Annuleren" clears both.
  - `WALLET_IDLE_MS` per PD15. The root's `onPointerDownCapture` and `onKeyDownCapture` reset it.
- **Verification:** `pnpm -C web exec vitest run src/features/bar`. The tests, under fake timers:
  - 59 999 ms keeps both, 60 000 clears both;
  - a tap at 30 s restarts the timer;
  - no clear while an intent is open;
  - "Andere wallet" keeps the basket;
  - "Annuleren" clears both.
- **Depends on:** T13
- **Autonomy note:** The constant's name is the builder's. Clearing during an open intent is not.

### T15 — Refunding at the bar

- **Implements:** AC20 (page), AC21 (bar), AC22 (texts); SD9, PD16, PD18
- **Expected output:**
  - `RecentPayments.tsx` and its `api/wallets.ts` calls, per PD16 and PD18. It is placed under the pending orders in `BarPage.tsx`.
  - "Terugboeken" confirms, then POSTs with a fresh `newIdempotencyKey()`. A network failure keeps the key for "Opnieuw" (B-05 /review C1).
- **Verification:** `pnpm -C web exec vitest run src/features/bar`; `pnpm -C web exec tsc -b`. The tests:
  - the rows' texts and the empty text;
  - a re-fetch on mount, after a paid order, after a refund, and every 30 s;
  - the confirm and the POST's header;
  - each refusal's text;
  - cancel sends nothing.
- **Depends on:** T14 (`BarPage.tsx`, the controller), T7 (the route)
- **Autonomy note:** Filtering by the phone's clock is not allowed (PD16).

### T16 — Refunding at the kassa

- **Implements:** AC23 (page); SD9, PD18
- **Expected output:**
  - `PaymentList.tsx` under `TopupList`. `KassaPage.open()` loads lookup, top-ups and payments.
  - `api.ts`: `payments`, `refund`. `errors.ts` gains the refund texts.
- **Verification:** `pnpm -C web exec vitest run src/features/kassa`; `pnpm -C web exec tsc -b`. The tests: `KassaPage.test.tsx`'s fetch mock serves the payments path; the rows, "teruggeboekt", "Bestelling niet meer beschikbaar"; the confirm, header, refusals and cancel.
- **Depends on:** T7, T9 and T10 (`KassaPage.tsx`)
- **Autonomy note:** Layout is the builder's. Merging top-ups and payments into one list is not, unless the owner asks.

### T17 — Globale instellingen: "Wallet verplicht" and "Rood staan tot"

- **Implements:** AC2 (admin saves), AC3 (the popups); SD1–SD3, PD17
- **Expected output:**
  - `useRunConfig.ts` `RunConfig.run` gains both fields.
  - `GlobalSection.tsx`:
    - a `Switch` "Wallet verplicht" and a `MoneyField` "Rood staan tot (€)", each with its `InfoButton`;
    - the submit sends both at the top level beside `candle_interval_s` (`:89-97`), never under `params`.
  - `explanations.json` gains E40 and E41 from § The table. `settings/index.ts`'s count comment is corrected.
  - `test_setting_explanations_text.py`:
    - reads § The table of this plan for E40–E41;
    - `SETTINGS_IDS` gains 40 and 41.
  - `test_setting_explanations_values.py`:
    - `start["wallet_required"] = ("Standaard", True)`;
    - `start["credit_limit_cents"] = ("Standaard", 0)`;
    - `allowed["credit_limit_cents"] = render_range(ConfigPatch, "credit_limit_cents", scale=100)`;
    - the count is 41.
  - Tests:
    - `GlobalSection.test.tsx`: the body of a switch save is `{wallet_required: false}`, and of a limit save `{credit_limit_cents: 250}`; a 422 shows under the field.
    - `SettingsPage.test.tsx:213` reads `12 + 6`, and the `CONFIG` mock gains both fields.
- **Verification:** `pnpm -C web exec vitest run src/features/settings src/app/pages/SettingsPage.test.tsx`; `uv run pytest tests/unit/test_setting_explanations_text.py tests/unit/test_setting_explanations_values.py`; `pnpm -C web exec tsc -b`.
- **Depends on:** T2
- **Autonomy note:** Placement inside the section is the builder's. A word of E40 or E41 that differs from § The table is not. If `render_range` renders the range differently from E41's text, stop and show both.

### T18 — Races, restart, run deletion and personal data, end to end

- **Implements:** AC9, AC24, AC27, AC34, AC36 (export and analytics); spec Verification › Integration
- **Expected output:**
  - `tests/integration/test_wallet_payments_races.py`, through the real app (`live_client`):
    - two bar sessions charge one wallet concurrently, together over balance + limit: the ones that fit succeed, the rest are 409, and the balance never goes below −limit (AC9);
    - a seeded sequence of at least 200 operations over 3 wallets mixes wallet orders, kassa top-ups, reversals, moves and refunds in concurrent batches, with no deadlock. After each batch, every balance equals its entries, is ≥ −limit, and each payment is refunded at most once.
  - `tests/integration/test_wallet_payments_restart.py`: orders paid and unpaid, a refund, a stop and a fresh `create_app`. Every order has its payment or none as committed, and every balance equals its entries (AC34; `test_wallets_restart.py`'s `_committed()` pattern).
  - `test_delete_run.py`: deleting a run with payments and a refund keeps the entries' amount, time and wallet, with `order_id` and `run_id` NULL. Balances are unchanged, and the kassa list shows those rows with `lines: null` (AC24).
  - `test_wallet_cleanup.py`: the boot sweep of an inactive wallet in debt (AC27).
  - `test_export_workbook.py:373-419` adds payments, a refund and an `order_id`: the workbook is unchanged (AC36).
  - `tests/api/test_analytics.py`: every `/api/analytics` response for a run is equal before and after its orders are paid and refunded (AC36).
- **Verification:** `uv run pytest tests/integration/test_wallet_payments_races.py tests/integration/test_wallet_payments_restart.py tests/integration/test_delete_run.py tests/integration/test_wallet_cleanup.py tests/integration/test_export_workbook.py`, then separately `uv run pytest tests/api/test_analytics.py` (one pytest over `tests/api` and `tests/integration` sweeps its own scratch DB).
- **Depends on:** T5, T7
- **Autonomy note:** **Changes no source file.** A failure means the locking or the transaction is wrong: stop and report. Do not patch around it in a test.

### T19 — The Playwright flow

- **Implements:** the spec's Playwright steps 1–7: AC2, AC4, AC5, AC13, AC15, AC18, AC21, AC25, AC26, AC31 and AC32 end to end; D-49
- **Expected output:** `web/e2e/payments.spec.ts` per PD20:
  1. Admin creates and goes live with a borrel, sets "Rood staan tot" to €2,50 in Globale instellingen, and creates a kassa key. A player signs up, and the kassa tops up €10.
  2. The bar types the player's code, sees the name large, builds 3× a drink and pays. It sees "Betaald", and the player's page shows the new balance within 10 s (AC13).
  3. The bar builds over balance + €2,50 and sees the shortfall disabled (AC18). It removes a line and pays into the negative, and the player page shows "−€ …" (AC25).
  4. The bar refunds that payment from "Betalingen (laatste 10 minuten)", and the balance returns (AC21).
  5. The player cannot delete the wallet while it is in debt (AC26).
  6. Admin turns the switch off. "Afrekenen zonder wallet" books an order, and the database has no new entry (AC15).
  7. On `http://payments.test:<port>`:
     - `isSecureContext === false` and no "Camera";
     - a typed-code payment and an unpaid order both book;
     - no cross-origin request is made (AC31, AC32).

  On loopback the bar shows "Camera" (AC32).
- **Verification:** `pnpm -C web exec playwright test e2e/payments.spec.ts`, then `pnpm -C web exec playwright test` (the whole suite, as the gate runs it).
- **Depends on:** T8, T15, T16, T17, T9
- **Autonomy note:** Selectors and helpers are the builder's. If Chromium treats `payments.test` as secure, stop (B-05 T21's note). Do not substitute loopback.

### T20 — Documents, the ADR addendum, and the exit gate

- **Implements:** AC36 (the ADR), AC37 (guardian, golden); spec In scope › Documents; PD21
- **Expected output:**
  - **ADR 0001:**
    - `## Addendum (B-06, <date>)` in B-05's format (`:91-115`), per SD10: purchases are linked to a wallet's name while the wallet exists. It replaces B-05's "Orders stay anonymous." (`:106`).
    - `*Amended by B-06*` marks beside §4 (`:55-59`).
  - **`data-model.md`:**
    - the `run` row (`:24`) gains the two columns;
    - the `wallet_entry` row (`:40`) gains `payment`/`refund`, the new signs, `order_id` and `refunds_entry_id`, and "a closing for any non-zero balance".
  - **`realtime-protocol.md`:** the `snapshot` and `config` rows (`:50,55`) name the `run` fields, including the two new ones.
  - **`frontend-architecture.md`:**
    - the bar order path (`:146-185`): the basket, the held wallet, PD12's lock;
    - `components/scanner/` shared by kassa and bar (`:17-18`).
  - **Specs:** "Amended by B-06" notes, in the `phase-6-admin.md:109-110` format, at:
    - Phase 5 SD5 and the out-of-scope lines `:228-229`;
    - B-05 SD5, SD9, SD15 and SD23;
    - PD21's list.
  - **`defect-register.md`:** D-49 → fixed, with a `### B-06 evidence` row (T11, T19).
  - **`venue.md`:** the bar takes typed codes (`:41-43`); under PD1 A, the imported borrel starts with "Wallet verplicht" off.
  - **`backlog.md`:** B-06 → built.
  - **The builder writes the ADR addendum and every `docs/design/` edit, shows them to the owner, and waits for a go before committing them.**
- **Verification:**
  - `git diff --stat <T1's base>..HEAD -- exchange tests/engine/golden app/runtime/grace.py app/jobs/export_xlsx.py app/db/exports.py app/db/analytics.py web/src/features/bar/FinancialPanel.tsx web/src/features/bar/RevenueChart.tsx` is empty;
  - `bash scripts/golden_linux.sh` green;
  - `engine-guardian` on the whole B-06 diff reports no maths change (AC37);
  - `./scripts/check.sh` green, output pasted.
- **Depends on:** T19, T18
- **Autonomy note:**
  - Wording is the builder's, subject to the owner's go.
  - A golden diff or a guardian finding is a hard stop.
  - The manual exit check (spec Verification › Manual) is the owner's: camera scans on an iPhone and an Android phone, a round of four while prices move, a refund from the bar and one from the kassa, and a dry run with the switch off.

---

## Task graph

```
T1 ──► T2 ──► T17
T1 ──► T3
T2 + T3 ──► T4 ──► T5
            T4 ──► T6 ──► T7
T10 ──┐
T3 ───┴──► T9
T11 + T2 + T4 ──► T12 ──► T13 ◄── T10, T6
                          T13 ──► T14 ──► T15 ◄── T7
T7 + T9 + T10 ──► T16
T7 + T9 + T17 ──► T8
T5 + T7 ──► T18
T8 + T15 + T16 + T17 + T9 ──► T19
T19 + T18 ──► T20
```

| Group | Tasks | Files they write |
|---|---|---|
| 1 | T1, T10, T11 | **T1:** `0014_wallet_payments.py`, `models.py`, `test_schema.py`, `test_migrations.py`, `test_guard_migrations_hook.py` · **T10:** `components/scanner/*`, `kassa/KassaPage.tsx`, `KassaPage.module.css`, the moved tests · **T11:** `useBarController.ts`, `orderIntents.ts`, `barController.ts`, bar test deps, `walletCode.provenance.test.ts` |
| 2 | T2, T3 | **T2:** `db/runs.py`, `config_patch.py`, `runtime/config.py`, `holder.py`, `rehydrate.py`, `messages.py`, `publish.py`, `ws_fixture.py`, `schemas.ts`, `ws-messages.json`, the web tests' `run` fixtures (bar, financial, home, koers, idle, manipulation), the config/runs/profiles/publish/messages tests, `schema.d.ts` · **T3:** `db/wallets.py`, `runtime/wallets.py`, `api/wallet.py`, the wallet tests |
| 3 | T4, T9, T17 | **T4:** `wallet_query.py`, `api/orders.py`, `kassa.py`, `runtime/orders.py`, `db/orders.py`, `db/wallets.py`, `analytics.spec.ts`, `bar/api/orders.*`, `test_orders.py` (api, integration), `test_place_order.py`, `schema.d.ts` · **T9:** `lib/format.*`, `player/WalletView.*`, `kassa/KassaPage.*`, `kassa/MoveDialog.*` · **T17:** `settings/GlobalSection.*`, `useRunConfig.ts`, `explanations.json`, `settings/index.ts`, two Python explanation tests, `SettingsPage.test.tsx` |
| 4 | T5, T6, T12 | **T5:** `runtime/orders.py`, `db/orders.py`, `tests/api/test_orders.py`, `test_restart_replay.py` · **T6:** `api/bar.py`, `runtime/wallets.py`, `db/wallets.py`, `main.py`, matrix, `test_standby.py`, `test_bar_wallets.py`, `schema.d.ts` · **T12:** `features/bar/*` (not `api/wallets.ts`), `ConfirmDialog.*`, `eslint.config.js`, `lint-rules.test.ts`, `bar.spec.ts`, `analytics.spec.ts`, `admin.spec.ts` |
| 5 | T7, T13 | **T7:** `api/payments.py`, `kassa.py`, `runtime/wallets.py`, `db/wallets.py`, `main.py`, matrix, `test_draining.py`, `test_standby.py`, `test_payments_refund.py`, `schema.d.ts` · **T13:** `features/bar/*` incl. `api/wallets.ts`, `WalletPicker.*`, `HeldWallet.*` |
| 6 | T8, T14, T16, T18 | **T8:** `db/wallets.py`, `runtime/wallets.py`, `wallets_admin.py`, `schema.d.ts`, `features/wallets/*`, `SettingsPage.test.tsx`, `wallets.spec.ts`, `test_wallets_admin.py` · **T14:** `features/bar/*` · **T16:** `features/kassa/*` (not `KassaPage.module.css`'s scanner part) · **T18:** two new test files, `test_delete_run.py`, `test_wallet_cleanup.py`, `test_export_workbook.py`, `test_analytics.py` |
| 7 | T15 | `features/bar/RecentPayments.*`, `BarPage.tsx`, `api/wallets.ts` |
| 8 | T19 | `web/e2e/payments.spec.ts` |
| 9 | T20 | the documents |

No file is written by two tasks in one group:
- T4 and T5 share `runtime/orders.py`, `db/orders.py` and `test_orders.py`, so T5 depends on T4.
- T3, T4, T6, T7 and T8 share `db/wallets.py`, and T3, T6, T7 and T8 share `runtime/wallets.py`. That makes a chain: T3 → T4 → T6 → T7 → T8.
- T2, T4, T6, T7 and T8 regenerate `schema.d.ts`. They sit in groups 2, 3, 4, 5 and 6, one per group. T3, T5, T9–T18 must not change the OpenAPI schema; each says so where it could.
- T4 and T12 share `analytics.spec.ts`, so T12 depends on T4.
- T11, T12, T13, T14 and T15 share `features/bar/`, so they form a chain.
- T9, T10 and T16 share `KassaPage.tsx`, so T9 and T16 depend on T10, and T16 on T9.
- T8 and T17 share `SettingsPage.test.tsx`, so T8 depends on T17.
- T3 and T18 both write `test_wallet_cleanup.py`, in groups 2 and 6.
- T2 and T11 both touch the bar's tests, in groups 2 and 1.

### Coverage

| AC | Task(s) | AC | Task(s) | AC | Task(s) |
|---|---|---|---|---|---|
| AC1 | T1, T2 | AC14 | T4, T12, T13 | AC27 | T1, T3, T18 |
| AC2 | T2, T12, T17, T19 | AC15 | T4, T12, T19 | AC28 | T1, T3 |
| AC3 | T2, T17 | AC16 | T4 | AC29 | T3 |
| AC4 | T6, T13, T19 | AC17 | T12 | AC30 | T8 |
| AC5 | T4, T12, T13, T19 | AC18 | T13, T19 | AC31 | T11, T19 |
| AC6 | T4 | AC19 | T14 | AC32 | T10, T13, T19 |
| AC7 | T4 | AC20 | T6, T15 | AC33 | T4, T6, T7 |
| AC8 | T4 | AC21 | T7, T15, T16, T19 | AC34 | T1, T4, T5, T18 |
| AC9 | T18 | AC22 | T7, T15 | AC35 | T6, T7 |
| AC10 | T5 | AC23 | T7, T16 | AC36 | T18, T20 |
| AC11 | T12, T13 | AC24 | T1, T18 | AC37 | T4, T20 |
| AC12 | T4, T13 | AC25 | T8, T9, T13, T19 | | |
| AC13 | T13, T19 | AC26 | T3, T9, T19 | | |

Every task maps to at least one AC: T10 serves AC32 (the spec's "the bar reuses the kassa's scanner"), T11 serves AC31, and T20 serves AC36, AC37 and the Documents scope.

### Test plan per acceptance criterion

The verification each task names is the AC's test. The spec's Verification section maps as follows:
- **Property test:** T12 (baskets), T13 (wallet outcomes).
- **API:** T2–T8.
- **Integration:** T1 (migration), T4 (failure injection, AC37), T5 (restart replay), T18.
- **Engine:** T4's comparison test, then T20's guardian and golden run.
- **Vitest and component tests:** T9, T10–T17.
- **Playwright:** T19.
- **The gate:** T20.
- **Manual:** the owner, after T20.

---

## The table

The two info popups (PD17), in B-01's form: the field, its name, and the explanation, one paragraph per line. The popup's title is the name. `tests/unit/test_setting_explanations_text.py` reads this section (T17). The wording is the owner's to approve at the audit.

### Globale instellingen (`/settings`), after E10

**E40 — `wallet_required`.** **Wallet verplicht** (a switch)

> Aan: elke bestelling aan de bar wordt betaald uit de wallet van een speler. Zonder gescande wallet kan de bar niet afrekenen.
> Uit: de bar kan ook zonder wallet afrekenen; de bestelling telt dan mee zoals altijd en er gaat van geen saldo iets af. Met een gescande wallet betaalt die wallet.
> Standaard: aan. Elke borrel die je hier aanmaakt begint aan, ook vanuit een profiel of met gekopieerde drankjes.
> Tijdens de borrel: geldt voor de volgende bestelling die binnenkomt. Heeft geen invloed op de prijzen.

**E41 — `credit_limit_cents`.** **Rood staan tot (€)**

> Hoe ver het saldo van een wallet onder nul mag zakken als de bar ermee afrekent. Bij de kassa gaat een saldo nooit onder nul: een opwaardering terugdraaien kan alleen als het saldo dat toelaat.
> Hoger: spelers kunnen meer drinken voordat ze aanvullen. 0: niemand staat rood.
> Standaard: 0. Toegestaan: 0 tot en met 50, in veelvouden van 0,5.
> Tijdens de borrel: geldt voor de volgende betaling die binnenkomt. Een wallet die al dieper rood staat, blijft zo staan tot hij wordt aangevuld. Heeft geen invloed op de prijzen.

---

## Data changes

- **Migration `0014_wallet_payments`** (PD3):
  - on `run`, two columns with server defaults: the backfill is the default, `false` and 0;
  - on `wallet_entry`, two nullable FK columns, each with a UNIQUE index;
  - two CHECKs replaced, two added.
  - No table is created. No row is rewritten.
- **Expand-only, `min_code_revision = "unchanged"`** (the spec's interface, Phase 8 SD3). The B-05 image keeps booting on this schema. What it then does wrong is in § Risks.
- **The downgrade** drops what it added and restores both CHECKs. It fails loudly while any B-06 row exists: a payment, a refund, a positive closing, or a debt move. The round trip is tested by `test_migrations.py`.
- **`delete_run`** (`app/db/runs.py:631-660`) needs no change. `ON DELETE SET NULL` clears `order_id` through its unique index, which keeps the timing bound (`test_delete_run.py:222-255`).
- **Personal data:** no new name column. A payment links to a wallet whose name is NULL once it is deleted (B-05 `wallet_deleted_check`).
- **The OpenAPI schema** gains 4 routes, the `wallet` field on the order body and receipt, two `run` config fields, and PD10's overview fields.

---

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| **PD1:** the owner rules reading B | `import_v1` passes `true`; `seed_live_run` PATCHes it off for the drills and the shared e2e server; `venue.md` says to turn it off or on. T2 and T20 change by a line each. |
| **Rolling back to the B-05 image on this schema** ("unchanged"). That image ignores the switch, so orders without a wallet are accepted. It answers a replay of a stored wallet receipt with 422, because `Receipt` is `extra="forbid"` (`runtime/orders.py:104,142-145`). Its `delete_wallet` leaves a debt on a blanked wallet (`left > 0`). Its totals net debt against credit. | The spec chose expand-only, and this plan does not reopen it. Every effect is visible, nothing corrupts a balance of a live wallet, and a roll-forward heals all but the deleted debtors' ledgers. T20's `venue.md`/Render note: before rolling back past B-06, turn the switch off and do not delete wallets in debt. If the owner wants a contract floor instead, T1 changes one line and the plan is re-audited. |
| **A wallet order waits on a wallet row while holding the market lock**: the clean-up's one transaction, or a kassa action | Kassa actions hold a wallet row for milliseconds. PD5's `lock_timeout = 2s` bounds the worst case to a 503 that the bar retries with the same key. The clean-up runs at boot and every 24 h. |
| **A live save of the switch ages quotes by one version** (PD4) | That is the same as a rename today. With `quote_grace_versions` 2, a bar order in flight still passes the grace rule. |
| **Two strict schemas** (`RunInfo` on both sides, the bar's `Receipt`) must change in step | T2 changes `RunInfo` server, client and fixture in one commit. T4 changes the receipt on the server and in the bar's zod in one commit, because an old strict zod would turn every 201 into `invalid_response` and three retries (`orderIntents.ts:109`). T12 depends on T4 for that file. |
| **The B-01 text test reads a plan** (PD17) | It is the cheapest honest source: audited, committed, and named by the test. The alternative, editing the approved spec, is the owner's to choose at the audit. |
| **The lint exemption** (PD13) could be read as weakening Phase 5 AC17 | It is scoped to one file, pinned by a test, and that file computes no revenue. The revenue still comes from the server's receipts (`FinancialPanel` is untouched). |
| **AC9 inside one process** | Orders are already serialised by the holder's `asyncio.Lock`, so the real race is with kassa actions. T18 tests both, and the `FOR UPDATE` is what protects the kassa race. |
| **`formatBalance` versus the spec's spelling.** The spec writes `−€0,90`; the app writes `−€ 0,90`. | B-05 PD15 set the no-break space. PD11 keeps it, and the e2e matchers use `\s`. |
| **The bar now loads the scanner module.** `jsqr` is still lazy. | The built-assets check (T10, T13) and `offline.spec.ts` stay green. No runtime request leaves the origin. |
| **The property test's simulated server grows** (lines, wallets) | It stays inline (no `fast-check`, Phase 5 SD20), and the builder keeps it under one file. |
| **Unverified:** that `SELECT … FOR UPDATE` with the credential in its `WHERE` returns no row after a concurrent `replace_codes` commits | T4 adds a test: hold a "Nieuwe code" transaction open, start the order, commit the code. The order must be 404. |
| **Unverified:** that `SET LOCAL lock_timeout` in an asyncpg transaction surfaces as an `OperationalError` the holder maps to 503 without marking it diverged | T4's lock-wait test. |
| **Unverified:** that nothing reads stored `run_config_revision.config` back through a strict model | T2's autonomy note: stop if something does. |

**Uncertain, for the audit and the owner:**
- **PD1 (owner):** whether the imported venue borrel starts with the switch on.
- **PD17 (owner):** the popup texts, and the plan as their source.
- **PD2:** a €0,00 payment entry rather than a refusal.
- **PD7:** a lenient replay when the scanned code no longer resolves.
- **PD11:** the minus spelling.
- **PD12:** the basket locked while its order is open.
- **PD13:** the lint exemption.
- **PD16:** the 30 s refresh.
- **PD18:** the page texts.
- **PD21:** the extra amendment notes.
- **PD22:** `ConfirmDialog` taking a node.
- **The task sizes:**
  - T2 (wide but mechanical);
  - T4 (the core, about 250 source lines);
  - T12 (the basket, close to 400: the autonomy note allows a T12b).
- **Not planned:** a rehearsal of the offline venue path (deferred in the backlog). PD20's mapped hostname stands in for plain HTTP, as in B-05.

---

## Out of scope for this plan

As the spec, plus:
- D5 (clipboard over HTTP) and D6 (the section select) from B-05's plan, and every other defect but D-49.
- Correcting `frontend-architecture.md`'s older staleness beyond B-06's facts.
- A `fast-check` dependency, or any new dependency.
- An admin UI for payments outside the kassa page (admin uses `/kassa`, as in B-05).
- A no-transition path for wallet-only config saves (PD4).
- Merging top-ups and payments into one kassa list (T16).

---

## Audit (plan-auditor — PASS required before implementation starts)

Human audit (`/audit b-06`), 2026-10-25. **Result: PASS.**

Rulings:
- **PD1 (owner):** Reading A. An imported run starts with "Wallet verplicht" off; only `create_run` passes `true`. The PD1 row in § Risks is moot.
- **PD17 (owner):** E40 and E41 approved as written in § The table, with this plan as the text test's source.
- **Confirm rows:** PD2, PD4, PD6, PD7, PD10, PD11, PD12, PD13, PD15, PD16, PD18, PD19, PD21 and PD22 confirmed as stated. That includes PD7's lenient replay after a re-code or delete, and PD4's version bump on a live save of the switch or the limit.

Findings folded into the plan:
- **The picker's failure texts** (PD18, T13): any lookup failure other than 404 shows "Verbindingsfout. Probeer opnieuw.", holds no wallet and keeps the typed code.
- **The switch defaulting on breaks existing order tests** (T4): T4 finds and fixes every test and spec that books on a `create_run` run, and the whole gate is green at T4's tip.

Noted, accepted as is:
- **Size:** T2, T4, T12 and T13 are over 10 files. T2's files are mechanical fixture edits. T12 already has its T12b split.
- **Schema:** PD3 relaxes the move and zero-payment signs beyond the spec's interface, which names only `closing`.
- **Rollback:** a rollback to the B-05 image is covered by § Risks.

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

Audited by: MartijnBoot (owner, `/audit b-06`)  Date: 2026-10-25
