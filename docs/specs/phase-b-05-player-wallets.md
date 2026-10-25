# Spec: B-05 — Player wallets with a QR code

Status: Approved · Depends on: Phase 3 (SD2 roles, SD7 the login limiter, SD8 sessions, SD9 the
Origin guard), Phase 5 (the order path's idempotency pattern), Phase 6 (SD24 draining, the keys
section), Phase 7 (SD3 deleting a run), Phase 8 (SD1 `APP_ENV=venue`, SD3 `schema_compat`), B-02
(SD9: the owner approves every icon) · Fixes: no open defect (files D-49, unscheduled) ·
Amends: [ADR 0001](../adr/0001-setup-decision-record.md) decision 13 and §4 · Backlog:
[B-05](../backlog.md)

Line references are to `main` at `374e206` (B-04 merged, PR #22).

## Problem

Players pay with a paper voucher: a 10×10 grid of 100 points (€10), where a €2,50 drink crosses
off 25 points. Crew sell the vouchers and do arithmetic on cards that are already partly crossed
off, and a half-used card is worth nothing at the next borrel. The app has no notion of a player
or of money held for one:

- **Every person the app knows is a crew key.** There are three roles, `display`, `bar` and
  `admin`, hard-coded in the database (`db/migrations/versions/0004_auth_key.py:43`), the server
  (`app/db/keys.py:20-21`, `app/api/deps.py:32`, `app/api/security.py:125-129`) and the client
  (`web/src/features/auth/useSession.ts:29`, `web/src/features/home/HomePage.tsx:49`). A key is
  made by an admin (`web/src/features/keys/KeysSection.tsx:163`, `app/cli/keys.py:76`).
- **An anonymous visitor only ever sees the login page.** Every route other than `/login` sits
  behind the session, and no session redirects to `/login?next=…` (`web/src/app/routes.tsx:46-50`);
  `/` is the admin's home (`app/api/security.py:128`).
- **No route can be called without a key** except login, health, the docs, the theme stylesheet
  and uploaded images; the allowlist is pinned and "nothing else, ever, without the human"
  (`tests/meta/test_route_authorization.py:35-52`). The only rate limit is on login, in memory,
  per IP (`app/api/security.py:178-207`).
- **ADR 0001 says the opposite of what this item needs.** Decision 13 is "single association, no
  tenant dimension" (`docs/adr/0001-setup-decision-record.md:29`), its trigger "a second
  association asks to use it" (`:73`) has long been met, and §4 says "the app stores no personal
  data" (`:58`).

The pricing engine is untouched: a wallet holds euros a player paid; it does not price anything.
Paying for drinks with a wallet is B-06.

## Decisions

Settled at the spec interview (2026-10-25). Q1–Q16 were put to the owner one at a time, each with
a recommendation; the owner's answer is recorded as given. SD17–SD26 were stated at the end of the
interview and approved as a whole. The planner must not reopen any of them.

**The wallet**

- **SD1 — A wallet carries over between borrels (Q1).** It belongs to the player, not to a run.
  Refunds are decided per event by the owner and paid outside the app; there is no refund or
  payout action.
- **SD2 — One association per deployment (Q9c).** Each association that uses the app has its own
  deployment and its own Postgres, set up by the owner, so a wallet of association A cannot exist
  in association B's database. There is no tenant table and no tenant column. ADR 0001 decision
  13 is amended to "one association per deployment; a tenant dimension inside one deployment is
  still deferred" (see SD26).
- **SD3 — Sign-up asks a name only (Q2); names are unique (Q13).**
  - A name is 1–40 characters after trimming, compared trimmed and case-folded
    (`name.strip().casefold()`, as drink names, Phase 6 SD14).
  - The sign-up page checks the name before submitting; the server checks again inside the
    sign-up transaction (a unique index), so of two players taking a name at once one wins and
    the other gets `name_taken`.
  - On a taken name the server offers up to three free names built from the name as typed: "Jan
    2", "Jan 3", … — the lowest free numbers, each within 40 characters.
  - A deleted wallet frees its name.
  - The check reveals to anyone holding the sign-up code whether a name exists. Accepted: it is
    rate-limited (SD6) and reveals no balance.
- **SD4 — The wallet lives in a cookie on the phone (Q2, SD19).** No email, no password, no
  recovery code. A lost phone or cleared browser data means signing up again; crew then move the
  balance (SD11).
- **SD5 — Personal data: one name, and it goes (Q3, Q10).** The app stores one free-text name per
  wallet, chosen by the player, and nothing else that identifies a person. Orders stay anonymous.
  ADR 0001 §4 is amended to say so (SD26).

**Sign-up**

- **SD6 — Open sign-up behind the deployment's sign-up code, rate-limited (Q9).**
  - The code is set by admin (SD14). With no code set, sign-up is closed (`signup_closed`).
  - The code is compared trimmed and case-insensitively. A wrong code is `signup_code_invalid`.
  - The poster's QR is a link `/speler?code=<code>` that fills the code in.
  - Sign-up and the name check share one per-IP limiter shaped as the login one, default **5 per
    minute**, an `app/core/config.py` setting (the only module reading the environment). Over it:
    429 `rate_limited` with `Retry-After`, as login.
  - A phone that already holds a valid wallet cookie gets its existing wallet back instead of a
    new one.
  - Sign-up and the name check are added to the public-route allowlist: **the owner approved
    this at the interview (Q9)**; it is the "with the human" that
    `tests/meta/test_route_authorization.py:38` asks for.

**Who may do what**

- **SD7 — A new role, `kassa` (Q4).** A kassa key sees only `/kassa` and may do only what that
  page does: look up, top up, reverse, move, new code. Admin may do everything a kassa key may.
  Display and bar keys may do none of it. A kassa key is made like any key, in "Toegangssleutels"
  and with `app.cli.keys create --role kassa`.
- **SD8 — The player is not a role.** A player has no `bb_session` and no access key; their
  routes are authorized by the wallet cookie (SD19) through a dependency of its own, which the
  route-authorization meta test recognises alongside `require_role`.

**Money**

- **SD9 — An append-only ledger in integer cents (Q5).** A wallet's balance is the sum of its
  entries. Every entry records its kind, amount, time, the live run at that moment (or none,
  SD13), and for crew actions the acting key and its label. A balance never goes below zero.
- **SD10 — A top-up is €10 to €100 in €5 steps, confirmed with the name (Q6, Q5, Q15).**
  - Amounts: €10, €15, €20, … €100. The kassa page starts at €10 with `[−]` / `[+]` in €5 steps.
    Anything else is 422.
  - Before booking, the page asks "€10,00 opwaarderen voor Jan?".
  - If that wallet was topped up in the last **2 minutes** by any key, the confirm instead reads
    "Jan is om 21:14 al opgewaardeerd met €10,00. Nog een keer €10,00?" with the button "Ja,
    nog een keer". It never refuses.
  - A top-up carries an `Idempotency-Key` as an order does (`app/api/orders.py:27`); a resend
    returns the stored entry and books nothing twice. The key is made with
    `crypto.getRandomValues`, never `crypto.randomUUID()` (SD24).
- **SD11 — Moving a balance after a lost phone (Q2, Q13, Q16).**
  - The kassa opens the player's **new** wallet (scan or code), chooses "Saldo overzetten
    van…", and searches the other wallets by name. Each match shows the name, sign-up date,
    balance and last top-up date; the kassa judges which is theirs. Typing an old short code
    finds a wallet exactly.
  - The confirm reads "€35,00 en de naam 'Jan' van Jan (aangemaakt 12 sep) naar Jan 2
    overzetten?".
  - In one transaction: the whole balance moves (an out entry on the old wallet, an in entry on
    the new), the old wallet is deleted (SD15), and the new wallet takes the old wallet's name.
  - A move from a wallet onto itself, or from a wallet with a zero balance, is refused
    (`nothing_to_move`).
- **SD12 — Reversing a top-up (Q5, SD22).** On a wallet's top-ups the kassa can choose
  "Terugdraaien". That writes one reversing entry of the same amount, naming the original, with
  the key label.
  - Any age. Once per top-up.
  - Refused (`insufficient_balance`) if it would take the balance below zero.
  - Only top-ups can be reversed: not reversals, moves or closing entries.
  - A reversal carries the **original's** run, so a borrel's top-up total is net of its
    reversals.
  - A deleted wallet's top-ups can no longer be reversed; a later fix is a reversal or move on
    the wallet the money went to.
- **SD13 — Wallets are independent of runs (Q7).** Sign-up and top-up work whether a run is
  live, draft or absent. An entry records the run that was **live** at that moment; with no live
  run it records none. Deleting a run (Phase 7 SD3) keeps its entries, with no run.

**The QR code**

- **SD14 — A fixed, opaque token, plus a short code (Q8, Q11).**
  - The QR encodes a random token (at least 128 bits), never the wallet id or the name. The
    scanner treats it as an opaque string.
  - Every wallet also has a **short code** of 8 characters from Crockford's base32 (no I, L, O,
    U), shown as `K7Q4-M2XD`. It is read case-insensitively, with or without the hyphen, `O` as
    `0` and `I`/`L` as `1`.
  - "Nieuwe code" (kassa or admin) replaces both; the old token and the old code stop working at
    once.
  - Neither is a credential for the player's own page: that is the cookie (SD19).
  - A guessable short code is harmless here (it can only add money). Whether either is safe for
    **paying** is B-06's question, and B-06 may change the scheme without changing the scanner
    or the ledger.

**Retention and the admin's view**

- **SD15 — Three ways a wallet goes (Q10, SD21).**
  1. The player deletes it from their page ("Wallet verwijderen"; the confirm says "Je saldo
     van €35,00 vervalt.").
  2. Admin deletes it from the Wallets section.
  3. The automatic clean-up:
     - a wallet with **no ledger entry at all** that is older than the **unfunded period**
       (default 30 days, 1–365);
     - a wallet whose newest entry, or its creation if it has none, is older than the
       **inactivity period** (default 12 months, 1–60).

     A visit to the player page is not activity. The clean-up runs at boot and once every 24 h
     on the app clock, and is skipped while draining.

  Deleting a wallet writes a **closing entry** for any balance left, so a deleted wallet's
  ledger sums to zero, and removes its name, token, short code and cookie credential. The ledger
  entries and an anonymous wallet row remain, so a borrel's top-up totals never change after the
  fact.
- **SD16 — A "Wallets" section on `/settings`, admin only (Q14).** After "Toegangssleutels",
  with a new pixel icon (SD25). It holds:
  - the sign-up code, which can be changed or cleared;
  - the two retention periods;
  - **totals**: the outstanding balance across all wallets (what the association still owes in
    drinks), and top-ups per borrel (net of reversals, from each entry's run, newest borrel
    first);
  - **the list** of wallets: name, balance and last activity, sorted by case-folded name, with
    "Verwijderen" behind a confirm ("Wallet 'Jan' verwijderen? Het saldo van €35,00 vervalt.").

  Nothing about wallets goes into the xlsx export (`app/jobs/export_xlsx.py`), so SD15's
  retention holds: final exports are never pruned.

**The venue**

- **SD17 — Wallets work at the venue too, without a camera where there is none (Q11).**
  - Under `APP_ENV=venue` everything works as on Render. The venue's database is its own, so
    its wallets are separate from Render's (SD2): at the venue every player starts at zero.
  - The kassa page always offers "Code typen". It opens the camera only where the browser
    allows it (a secure context: HTTPS on Render, `localhost`), and otherwise shows only the code
    field, with no error.
- **SD18 — One QR generator and one QR decoder, as new dependencies (Q12).**
  - Both are bundled by Vite, with no runtime network request (ADR 0006, the built-output check
    `scripts/check_built_assets.py`, the offline e2e `web/e2e/offline.spec.ts`).
  - Both have a permissive licence (MIT, Apache-2.0 or BSD).
  - The planner names candidates with evidence of licence, size and maintenance; **the owner
    approves the exact packages before the build adds them. That approval is a hard stop.**
    Neither may be swapped for another without the owner.

**Stated at the end and approved**

- **SD19 — The wallet cookie.** `bb_wallet`: HttpOnly, SameSite=Strict, path `/`, Secure as the
  crew cookie (`app/api/security.py` `cookie_kwargs`, so plain HTTP at the venue).
  - Its value is a random credential (at least 128 bits) distinct from the QR token and the
    short code; the database stores only its hash.
  - It is renewed on every visit to the player page with a 400-day max-age.
  - It is separate from `bb_session`, so one phone can be crew and player at once.
  - A cookie whose wallet is deleted is answered 401 `no_wallet` and cleared.
- **SD20 — The landing page and `/speler`.**
  - At `/`, a visitor without a crew session sees two buttons: **Speler** (to `/speler`) and
    **Crew** (to `/login`). A crew session at `/` behaves exactly as today.
  - `/speler` shows sign-up (name and sign-up code) without a wallet cookie, and the wallet page
    with one. It is outside the crew shell and needs no session. A reload of `/` and `/speler`
    serves the app, not a 404 (`SPA_ROUTES`, `app/main.py:101`).
- **SD21 — The player page** shows the name, the balance in euros, the QR code, the short code,
  "Wallet verwijderen", and a hint "Bewaar deze pagina — je wallet staat op deze telefoon."
  Nothing else: no prices, no history. The balance refreshes every 10 s while the page is visible
  and when it regains focus. A player has no WebSocket.
- **SD22 — The kassa page (`/kassa`)** offers the camera (where allowed) and "Code typen". A found
  wallet shows its name and balance, then:
  - top up (SD10);
  - its top-ups, newest first, each with "Terugdraaien" (SD12);
  - "Saldo overzetten van…" (SD11);
  - "Nieuwe code" (SD14).

  An unknown token or code is "Onbekende wallet". Admin's home (`/`) gets a "Kassa" tile, and the
  connection panel counts kassa connections.
- **SD23 — Draining, standby, restart and concurrency.**
  - While draining, every wallet write is refused 503 `shutting_down` (Phase 6 SD24,
    `app/api/deps.py:116-124`), sign-up and self-delete included. In standby every wallet route
    is 503 as every `/api/*` is (`app/api/standby.py`).
  - Each sign-up, top-up, reversal, move, new code, delete and clean-up is one transaction. A
    balance check and the entry it guards happen under a lock on the wallet's row, so two
    reversals, or a reversal and a move, at once cannot take a balance below zero. A move locks
    both wallets in wallet-id order.
  - A restart leaves the old state or the new one, never half.
  - No wallet work runs inside the market's state lock (route invariant, Phase 3).
- **SD24 — D-49 is filed, not fixed.** The bar page makes its idempotency keys with
  `crypto.randomUUID()` (`web/src/features/bar/useBarController.ts:76`), which browsers only
  provide in a secure context. The venue serves plain HTTP (Phase 8 SD1), so an order tap there
  likely throws; the tests run on `127.0.0.1`, which counts as secure. It goes into the defect
  register as D-49, open and unscheduled. B-05's own pages avoid the problem (SD10).
- **SD25 — The Wallets section gets a new pixel icon**, drawn by the build (a wallet is the
  starting motif; the owner may change it) and approved by the owner before it reaches the page
  (B-02 SD9). **That approval is a hard stop.** No existing icon is reused.
- **SD26 — ADR 0001 is amended by an addendum, approved by the owner at the interview (Q3,
  Q9c).**
  - Decision 13 becomes "one association per deployment".
  - §4 says the app stores one free-text name per player wallet and nothing else that identifies
    a person, with SD15's retention.
  - §7's "Entra or hosted identity" trigger ("accounts need to persist across events") is
    answered: a wallet persists, but it is a cookie and a name, not an account with a login.

## The interface

For the planner to refine, not to rename without a reason. Wallet routes are under `/api/wallet`
(the player), `/api/kassa` (kassa and admin) and `/api/admin/wallets` (admin).

**Tables**, in one new migration, expand-only (`min_code_revision = "unchanged"`, Phase 8 SD3):

- `wallet`:
  - `wallet_id` (identity);
  - `name` and `name_key`, both nullable, NULL once deleted; `name_key` is unique among
    non-deleted wallets;
  - `qr_token`, unique, NULL once deleted;
  - `short_code`, unique, NULL once deleted;
  - `cookie_hash`, NULL once deleted;
  - `created_at`, `deleted_at`.
- `wallet_entry`:
  - `entry_id`, `wallet_id` (FK `wallet`);
  - `kind`: `topup` / `reversal` / `move_out` / `move_in` / `closing`;
  - `amount_cents`: signed integer, non-zero, the sign fixed by the kind;
  - `run_id`: FK `run`, `ON DELETE SET NULL`;
  - `reverses_entry_id`: unique, for a reversal;
  - `counterpart_entry_id`: for a move;
  - `actor_key_id` (FK `auth_key`, nullable) and `actor_label`;
  - `idempotency_key`: unique, nullable;
  - `created_at`.
- `wallet_settings`: a singleton like `theme`, holding `signup_code` (nullable),
  `unfunded_days`, `inactive_months`.
- `auth_key_role_check` gains `kassa`.

**The player** (the wallet cookie, SD8; sign-up and the name check public, SD6):

- `POST /api/wallet/name-check {name, code}` → `{available, suggestions}`.
- `POST /api/wallet {name, code}` → 201 with the wallet and sets `bb_wallet`; 200 with the
  existing wallet if the cookie already holds one. Errors: 409 `name_taken {suggestions}`, 403
  `signup_code_invalid`, 409 `signup_closed`, 429 `rate_limited`, 422 for the name.
- `GET /api/wallet` → `{name, balance_cents, qr_token, short_code, created_at}` and renews the
  cookie; 401 `no_wallet` (and clears it).
- `DELETE /api/wallet` → 204, with SD15's closing entry.

**The kassa** (kassa and admin):

- `POST /api/kassa/lookup {qr_token | short_code}` → `{wallet_id, name, balance_cents,
  created_at, last_topup_at, recent_topup}` (`recent_topup`: the time and amount of a top-up in
  the last 2 minutes, else null); 404 `wallet_not_found`.
- `GET /api/kassa/wallets?name=<fragment>` → matches for SD11.
- `GET /api/kassa/wallets/{wallet_id}/topups` → its top-ups, each with whether it was reversed.
- `POST /api/kassa/wallets/{wallet_id}/topups {amount_cents}` with `Idempotency-Key` → 201, or
  200 on a replay; 422 `idempotency_key_reused` for a different body under the same key.
- `POST /api/kassa/topups/{entry_id}/reversal` with `Idempotency-Key`. Errors: 409
  `already_reversed`, 409 `insufficient_balance`, 409 `wallet_deleted`.
- `POST /api/kassa/wallets/{wallet_id}/move {from_wallet_id}` with `Idempotency-Key`; 409
  `nothing_to_move`.
- `POST /api/kassa/wallets/{wallet_id}/new-code` → the new token and short code.

**Admin:**

- `GET /api/admin/wallets` → the list and the totals (SD16).
- `DELETE /api/admin/wallets/{wallet_id}` → 204.
- `GET` / `PUT /api/admin/wallet-settings` → `{signup_code, unfunded_days, inactive_months}`.

On all of them: an unknown or deleted wallet is 404 `wallet_not_found` (the player's own routes:
401 `no_wallet`). A wallet route on a deleted wallet writes nothing.

## In scope

- **Persistence:** the migration above, `docs/design/data-model.md` (the three tables and the
  `kassa` role).
- **Server:**
  - the `kassa` role everywhere the three roles are listed today (the Problem's list), with
    `ROLE_ROUTES["kassa"] = ("/kassa",)` and `/kassa` added to admin's;
  - the wallet-cookie dependency and its recognition by `tests/meta/test_route_authorization.py`;
    sign-up and the name check in its `PUBLIC_ROUTES` (SD6);
  - the routes above, with their rows in `tests/api/test_authorization_matrix.py`;
  - the sign-up limiter and its setting in `app/core/config.py`;
  - the clean-up at boot and every 24 h;
  - `/`, `/speler` and `/kassa` in `SPA_ROUTES`;
  - the OpenAPI types regenerated (`web/src/api/generated/schema.d.ts`).
- **Web:**
  - the landing choice at `/`;
  - `/speler` (sign-up, the name check and its suggestions, the wallet page, self-delete);
  - `/kassa` (camera where allowed, "Code typen", lookup, top-up with its two confirms,
    reversal, move, new code);
  - the Wallets section on `/settings` with its icon;
  - `kassa` in the keys section's role select, the session's `Me`, admin's home tile and the
    connection panel;
  - the two approved QR dependencies (SD18);
  - component tests and Playwright flows.
- **Documents:**
  - the ADR 0001 addendum (SD26);
  - D-49 in `docs/specs/defect-register.md` (SD24, done with this spec);
  - `docs/design/frontend-architecture.md` (the routes and the dependency count);
  - `docs/runbooks/venue.md` (wallets there are the venue's own);
  - B-05's backlog status.

## Out of scope

- **Paying with a wallet** (B-06), and anything about a drink order: the bar page, the order path
  and `exchange/` are read, never changed.
- Refunds or payouts of any kind (SD1).
- A player's history of top-ups or purchases, on their page or anywhere else.
- Rename, other than the name a move hands over (SD11). Merging wallets, other than a move.
- Email, phone numbers, passwords, a recovery code, a self-service restore, accounts.
- A PWA, an install prompt, push notifications, offline caching of the player page.
- A rotating QR code, a PIN, or any change to the code scheme (B-06, SD14).
- Top-up amounts other than SD10's, and the €10 unit or €5 step as a setting.
- Wallets, names or entries in the xlsx export or in `/analytics` (SD16).
- Multi-tenancy inside one deployment; a tenant table or column (SD2).
- Moving wallets between databases: Render to venue, or between associations.
- Fixing D-49 (SD24).
- Security headers (CSP, Permissions-Policy); the browser's default `camera` allowlist (`'self'`)
  suffices, as the app sends none today.
- A player seeing the board, the bar or any crew page.
- Any change to the pricing maths, to any default, or to any range.

## Acceptance criteria

**The landing page and sign-up — SD3, SD6, SD20**

- **AC1.** When a visitor without a crew session opens `/`, the system shall show "Speler" and
  "Crew"; "Crew" shall go to `/login`, "Speler" to `/speler`. With a crew session `/` shall be
  what it is today.
- **AC2.** When `/speler?code=<code>` is opened without a wallet cookie, the sign-up form shall
  show with the code filled in; without `code`, empty.
- **AC3.** When a player signs up with a free name and the right code, the system shall create a
  wallet with a balance of €0,00, set `bb_wallet`, and show the wallet page.
- **AC4.** When the name is taken (trimmed, case-folded), the system shall return 409
  `name_taken` with up to three free suggestions "<naam> 2", "<naam> 3", … (lowest free numbers,
  at most 40 characters), create nothing, and the page shall offer them. The pre-submit check
  shall give the same answer.
- **AC5.** When two sign-ups for the same free name arrive at once, exactly one wallet shall be
  created and the other shall get `name_taken`.
- **AC6.** If the code is wrong, the system shall return 403 `signup_code_invalid`; if no code is
  set, 409 `signup_closed`; in both cases nothing is created. A name empty after trimming or over
  40 characters shall be 422.
- **AC7.** When a sixth sign-up or name check arrives from one IP within 60 s (at the default 5),
  the system shall return 429 `rate_limited` with `Retry-After`.
- **AC8.** When a sign-up arrives with a valid wallet cookie, the system shall return that wallet
  and create none.

**The player page — SD14, SD19, SD21**

- **AC9.** The wallet page shall show the name, the balance in euros, a QR code encoding the
  wallet's token, the short code as `XXXX-XXXX`, "Wallet verwijderen" and the "Bewaar deze
  pagina" hint, and nothing else.
- **AC10.** When a top-up is booked for a wallet whose page is open and visible, the page shall
  show the new balance within 10 s, and at once when it regains focus.
- **AC11.** Every `GET /api/wallet` shall renew `bb_wallet` with a 400-day max-age. The cookie
  shall be HttpOnly, SameSite=Strict, and Secure exactly when the crew cookie is.
- **AC12.** The QR token and the short code shall not open the player page or authorize any
  player route; the cookie value shall be neither, and only its hash shall be stored.
- **AC13.** When the wallet behind a cookie has been deleted, the player routes shall return 401
  `no_wallet` and clear the cookie, and `/speler` shall show sign-up.

**Top-up — SD9, SD10, SD13**

- **AC14.** When a kassa or admin key looks up a wallet by QR token or short code, the system
  shall return its name and balance; the short code shall match case-insensitively, with or
  without the hyphen, `O` read as `0` and `I`/`L` as `1`. An unknown one shall be 404
  `wallet_not_found`, shown as "Onbekende wallet".
- **AC15.** When the kassa confirms "€X opwaarderen voor <naam>?", the system shall write one
  `topup` entry of X with the key and its label and the live run's id (or none), and the balance
  shall rise by X.
- **AC16.** The amount shall start at €10,00 and move in €5 steps between €10,00 and €100,00; a
  request outside that set shall be 422 and write nothing.
- **AC17.** If the wallet had a top-up in the last 2 minutes, the confirm shall be "<naam> is om
  HH:mm al opgewaardeerd met €Y. Nog een keer €X?" with "Ja, nog een keer", and confirming
  shall book it.
- **AC18.** When a top-up is resent with the same `Idempotency-Key` and body, the system shall
  return the stored entry and write nothing; with a different body, 422
  `idempotency_key_reused`.
- **AC19.** When sign-up and top-up happen with no live run, they shall succeed, and the entry
  shall carry no run.
- **AC20.** No wallet page shall call `crypto.randomUUID()`; the kassa page shall book a top-up
  when served over plain HTTP from a non-loopback address.

**Reversal — SD12**

- **AC21.** When the kassa confirms "Terugdraaien" on a top-up, the system shall write one
  `reversal` entry of minus its amount, naming it, with the key label and the original's run.
- **AC22.** If that top-up was already reversed, the system shall return 409 `already_reversed`;
  if the reversal would take the balance below zero, 409 `insufficient_balance`; if the wallet
  is deleted, 409 `wallet_deleted`. In each case nothing is written.
- **AC23.** When two reversals that together exceed the balance arrive at once, at most the
  balance's worth shall succeed, and the balance shall never be below zero.
- **AC24.** Only `topup` entries shall be reversible.

**Moving a balance — SD11**

- **AC25.** When the kassa searches by name on a found wallet, the system shall list every
  other non-deleted wallet whose name contains the fragment (case-folded), each with its name,
  sign-up date, balance and last top-up date; a typed short code shall find one exactly.
- **AC26.** When the kassa confirms "€B en de naam '<oud>' van <oud> (aangemaakt …) naar
  <nieuw> overzetten?", the system shall, in one transaction:
  - write a `move_out` of −B on the old wallet and a `move_in` of +B on the new;
  - delete the old wallet (SD15);
  - give the new wallet the old one's name.

  The new player page shall then show the old name and the new balance.
- **AC27.** A move onto the same wallet, or from a wallet with a zero balance, shall be 409
  `nothing_to_move` and write nothing.

**New code — SD14**

- **AC28.** When the kassa confirms "Nieuwe code", the system shall replace the wallet's token
  and short code; the old ones shall be `wallet_not_found` at once; the player page shall show
  the new ones on its next refresh; the cookie shall keep working.

**Deleting and retention — SD15, SD16**

- **AC29.** When a player confirms "Wallet verwijderen" ("Je saldo van €B vervalt."), the
  system shall:
  - write a `closing` entry of −B (if B > 0);
  - remove the name, token, short code and cookie hash;
  - stamp `deleted_at`;
  - clear the cookie.

  The name shall then be free for a new sign-up.
- **AC30.** When admin deletes a wallet from the Wallets section, the same shall happen.
- **AC31.** When the clean-up runs, it shall delete as in AC29:
  - every wallet with no entry and older than the unfunded period;
  - every wallet whose newest entry (or creation) is older than the inactivity period.

  It shall run at boot and every 24 h, shall not run while draining, and shall touch no other
  wallet. Opening the player page shall not count as activity.
- **AC32.** A borrel's top-up total shall be the same before and after any wallet is deleted.
- **AC33.** The unfunded period shall accept whole days 1–365 (default 30) and the inactivity
  period whole months 1–60 (default 12); anything else is 422.

**The Wallets section — SD16, SD25**

- **AC34.** `/settings` shall show "Wallets" after "Toegangssleutels", admin only, with its own
  anchor and mobile-nav entry and its approved pixel icon. It shall contain:
  - the sign-up code (changeable; clearing it closes sign-up);
  - the two periods;
  - the outstanding total, equal to the sum of every non-deleted wallet's balance;
  - top-ups per borrel, net of reversals, newest borrel first;
  - the wallet list (name, balance, last activity; case-folded name order) with "Verwijderen"
    behind its confirm;
  - "Nog geen wallets" when the list is empty.
- **AC35.** The xlsx export shall be unchanged: no sheet, column or value from a wallet.

**Roles and permissions — SD7, SD8**

- **AC36.** A kassa key shall log in and land on `/kassa`; its `allowed_routes` shall be exactly
  `["/kassa"]`; every non-wallet route shall be 403 for it.
- **AC37.** Every `/api/kassa` route shall be allowed for kassa and admin, and 401/403 for
  display, bar, a revoked key and no session; every `/api/admin/wallets` and wallet-settings
  route, admin only.
- **AC38.** The player routes shall need the wallet cookie and no crew session; a crew session
  without a wallet cookie shall be 401 `no_wallet` there.
- **AC39.** The public-route allowlist shall be today's plus exactly the sign-up and the name
  check, and the meta test shall fail for any wallet route with neither `require_role` nor the
  wallet dependency.
- **AC40.** Admin shall be able to create a `kassa` key in "Toegangssleutels" and with
  `app.cli.keys create --role kassa`; admin's home shall show a "Kassa" tile and count kassa
  connections.

**The venue — SD17**

- **AC41.** Under `APP_ENV=venue`, sign-up, the player page and every kassa action shall work
  as on Render.
- **AC42.** Where the browser offers no camera (no secure context), the kassa page shall show
  only "Code typen", with no error; where it does, both.

**Dependencies — SD18**

- **AC43.** The QR generator and decoder shall be the two packages the owner approved, bundled;
  the built-output check and the offline e2e shall pass with no request leaving the origin.

**Draining, restart, concurrency — SD23**

- **AC44.** While draining, every wallet write (sign-up, self-delete, top-up, reversal, move, new
  code, admin delete, settings) shall be 503 `shutting_down` and write nothing; in standby every
  wallet route shall be 503 `standby`.
- **AC45.** When the app restarts, every wallet, entry and setting shall be as last committed,
  and every balance shall equal the sum of its entries.
- **AC46.** No balance shall ever be below zero after any sequence of top-ups, reversals and
  moves, including concurrent ones.

**Personal data — SD5, SD26**

- **AC47.** No table shall gain a column identifying a person other than `wallet.name`, and a
  deleted wallet's row shall hold no name, token, short code or cookie hash.
- **AC48.** ADR 0001 shall carry SD26's addendum.

**No maths change**

- **AC49.** `exchange/`, the order path and the bar page shall be unchanged, and the golden
  fixtures shall replay unchanged.

## Verification

- **API (pytest):**
  - sign-up: free, taken with suggestions, concurrent same name, wrong, closed and rate-limited
    code, an existing cookie (AC3–AC8);
  - the player routes, renewal and cookie flags, a deleted wallet's cookie (AC11–AC13);
  - lookup by token and every short-code spelling (AC14);
  - top-up: amounts, no live run, replay and reuse (AC15, AC16, AC18, AC19);
  - reversal: twice, past zero, on a deleted wallet, concurrent pair, non-top-up (AC21–AC24);
  - move: search, the transaction, the name handed over, refusals (AC25–AC27);
  - new code (AC28); deletes by player and admin, and per-borrel totals unchanged (AC29, AC30,
    AC32); periods (AC33);
  - the matrix for every route and the meta test's allowlist (AC36–AC39); draining and standby
    (AC44).
- **Integration (pytest):**
  - the clean-up on the app clock moved past both periods, at boot and on the 24 h timer, and
    not while draining (AC31);
  - a restart with wallets mid-use, every balance equal to its entries (AC45);
  - a random sequence of top-ups, reversals and moves, concurrent, never below zero (AC46);
  - the migration up from `0012`, the role check accepting `kassa` (AC47).
- **Vitest:**
  - the landing choice (AC1);
  - sign-up and its suggestions (AC2, AC4);
  - the wallet page's contents and refresh (AC9, AC10);
  - the kassa page: both confirms, the step buttons, reversal, move confirm text, new code,
    "Onbekende wallet", the camera hidden without a secure context (AC14–AC17, AC21, AC26,
    AC42);
  - the Wallets section (AC34);
  - no `crypto.randomUUID` in wallet code (AC20).
- **Playwright (in the gate):** admin sets a sign-up code and makes a kassa key. A player opens
  `/speler?code=…` and signs up as "Jan"; a second player tries "jan" and is offered "jan 2". The
  kassa types Jan's short code and tops up €15, sees the 2-minute warning on a second top-up, and
  reverses it. Jan's page shows €15,00. A second browser signs up as "Jan 2"; the kassa moves the
  balance from "Jan". "Jan 2"'s page shows "Jan" and €15,00, and the first browser's page shows
  sign-up. Admin sees €15,00 outstanding and the top-ups under the live borrel.
- **The venue path:** the kassa flow in the Playwright run above, against the app reached on a
  non-loopback address over plain HTTP (AC20, AC41, AC42).
- **The gate:** `./scripts/check.sh` green; `bash scripts/golden_linux.sh` green (AC49);
  `engine-guardian` on the diff reports no maths change.
- **Manual (exit check, the owner):**
  - approve the two packages (SD18) and the icon (SD25);
  - on Render, sign up from your own phone through a printed poster QR;
  - top up from a second phone as kassa **with the camera**, on an iPhone and an Android phone;
  - delete and re-sign-up one wallet and move its balance back.

## Exit condition

A player can sign up with the association's code and a unique name, show a QR code, and see a
balance that kassa crew top up by scan or typed code, reverse and move after a lost phone. The
balance is always the sum of an append-only ledger that never goes below zero. Names leave on
deletion or retention, and the pricing maths has not moved.
