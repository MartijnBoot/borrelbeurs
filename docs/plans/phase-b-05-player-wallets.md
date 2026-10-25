# Plan: B-05 — Player wallets with a QR code

Spec: [docs/specs/phase-b-05-player-wallets.md](../specs/phase-b-05-player-wallets.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-25)**
Design: [data-model.md](../design/data-model.md) gains three rows and the `kassa` role, and [frontend-architecture.md](../design/frontend-architecture.md) gains the routes, three feature folders and two dependencies (T22, an owner stop: `docs/design/`). [realtime-protocol.md](../design/realtime-protocol.md) is unchanged under PD1 reading A.
ADRs honoured: 0002 and 0012 (`exchange/` read, never changed), 0003 (wallet times come from the app clock, PD8), 0004 (one Postgres engine), 0006 (both QR packages bundled, no runtime request), 0011 (the migration runs at boot, unattended). ADR 0001 is amended by an addendum the owner approved at the interview (SD26, T22). No other ADR is reversed.
Backlog: [B-05](../backlog.md) · Fixes: no open defect (D-49 filed with the spec, unscheduled)

Line references are to `docs/phase-b-05-spec` at `12da59a` (`main` `374e206` plus the spec).

---

## Approach

**Server: one ledger, one repository, three routers.** Three new tables come in one migration (`0013_wallets`), which also widens `auth_key_role_check` (precedent: `0009_phase_6_admin.py:51-54`).
- **One repository.** Every wallet read and write goes through `app/db/wallets.py`, connection-taking like `app/db/profiles.py`. It owns the balance (`SUM(amount_cents)`), the row lock (`SELECT … FOR UPDATE` on `wallet`, locked in `wallet_id` order when there are two, as `app/db/keys.py:100-112`), and the one delete that writes the closing entry and blanks the row.
- **One transaction per action.** `app/runtime/wallets.py` holds each action as one `engine.begin()`: sign-up, top-up, reversal, move, new code, delete. The clean-up sweep is one transaction too (SD23). None of them touches `MarketHolder`. The live run is read inside the transaction with `current_run` (`app/db/runs.py:422-432`), so no wallet work runs inside the market's state lock.
- **Idempotency** reuses the order pattern (`app/api/orders.py:27,60-62`, `app/runtime/orders.py:137-150,254-261`): the same header pattern, a global UNIQUE on `wallet_entry.idempotency_key`, and a replay judged by comparing the stored entry with the request. There is no hash column.
- **Three routers.** `/api/wallet` is the player's: two public routes plus a new `require_wallet` dependency. `/api/kassa` is `require_role("kassa", "admin")`. `/api/admin/wallets…` is admin only.
- **The meta test learns a second marker**, so a wallet route with neither guard fails it (AC39).
- **Reused, not rewritten:** the sign-up limiter is a second `LoginLimiter` instance (`app/api/security.py:181-207`), the cookie flags come from `cookie_kwargs` (`:171-173`), and the clean-up loop copies the export worker's `clock.sleep_until` loop (`app/jobs/export_xlsx.py:376-433`).

**Web: two pages outside the crew shell, one inside, one settings section.**
- **`/`** renders a landing choice when there is no crew session, and the shell with `HomePage` when there is one.
- **`/speler`** sits beside `/login` outside the shell (`web/src/app/routes.tsx:82`). `SessionProvider` does not call `/api/auth/me` there, and the 401 hook does not send it to login (PD13).
- **`/kassa`** is a crew page like `/bar`. It is gated by `ROLE_ROUTES`, and its key is the new `kassa` role.
- **The Wallets section** is composed in the app layer, as `KeysSection` is (`SettingsPage.tsx:18-22`).
- **Feature folders.** Each surface gets its own: `features/player`, `features/kassa`, `features/wallets`. They share nothing but `lib/` and `components/`, because the boundaries rule forbids feature-to-feature imports (`web/eslint.config.js:123-138`).
- **The QR code** is drawn as SVG `<rect>`s from `uqr`'s boolean matrix, with no `innerHTML`. Scanning decodes canvas frames with `jsqr`, imported dynamically so only the kassa page loads it. Both packages are the planner's proposal and wait on T12, the owner's hard stop.

Rejected:
- **A tenant column, or a wallets "account" with a login.** SD2 and SD4.
- **A request-hash column for idempotency.** The order path proves that comparing the stored entry suffices. Each wallet write has at most three inputs (wallet, amount or entry, source wallet).
- **argon2 for the wallet cookie, as for access keys.** The cookie is a ≥128-bit random credential that must be found by its hash. A key carries its `key_id` and so can be verified slowly; the cookie carries nothing to look it up by. SHA-256 of a 256-bit random value is the standard choice for a high-entropy bearer token (PD5).
- **Client-side short-code normalisation.** The server normalises (AC14) and returns the display form, so the web has one spelling and no second copy of the rules (PD6).
- **`qrcode` (node-qrcode) as the generator.** It pulls `pngjs` and `yargs` (CLI) into the dependency tree. **`barcode-detector`/`zxing-wasm` as the decoder** fetches its `.wasm` from jsDelivr unless reconfigured (its README, "prepareZXingModule … locateFile"), which is ADR 0006's failure mode. **`qr-scanner`** ships a worker file and was last released 2022-11. Details in § New dependencies.
- **A "presence-only" WebSocket for the kassa page**, as the default. It is PD1 reading B: it changes the realtime protocol and `docs/design/realtime-protocol.md`.

---

## Decisions this plan makes

Rows marked **Owner** are spec ambiguities with two user-visible readings (CLAUDE.md hard stop); the audit must rule on them. Rows marked **Confirm** are readings the audit confirms or overrules. The rest follow from the code and the spec.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | **Owner.** How the connection panel counts kassa connections (SD22, AC40) without breaking AC36 ("every non-wallet route shall be 403") | The panel counts open `/ws` sockets only (`app/api/admin.py:62-75`, `hub.peers()`). Every crew page holds one because `Providers` start the exchange client for any ready session (`web/src/app/providers.tsx:60-74`). `require_ws_role` already admits any valid session (`app/realtime/ws.py:81-97`). <br>**Reading A (recommended):** a kassa session keeps that socket and the exchange client exactly as other crew pages do. `/ws` and `GET /api/state` (the client's offline poll, `client.ts:201`) admit `kassa`. The kassa page ignores the market data. Every other non-wallet route, `GET /api/news` included, is 403 for kassa. AC36 is then read as "every non-wallet route *other than the market feed and the session's own routes*". No realtime change. <br>**Reading B:** AC36 literally. `GET /api/state` stays 403 for kassa, the hub sends kassa sockets no market frames, and the kassa page opens a presence-only socket instead of the exchange client. That touches `hub.py`, `ws.py`, `providers.tsx` and `realtime-protocol.md` (a `docs/design` stop), and adds one task before T17. | AC36 and AC40 cannot both hold literally with today's presence mechanism. The prices a kassa key would see under A are the ones the public board shows. |
| PD2 | **Owner.** Top-ups with no run in the per-borrel totals (SD16, AC34) | An entry has no run when no run was live (SD13) or its run was deleted (Phase 7 SD3). **Reading A (recommended):** a last row "Zonder borrel" with their net sum, shown only when that sum is non-zero. **Reading B:** they appear in no row, so the per-borrel list does not add up to all top-ups. | Two different screens. |
| PD3 | Role constants on the server | `app/db/keys.py`: `Role = Literal["display","bar","admin","kassa"]`, with `ROLES` likewise. `app/api/deps.py`: `ALL_ROLES` becomes all four and is used only by `me`/`logout` (`auth.py:98,104`) and, under PD1 A, `state.py:25` and the `/ws` marker. `MARKET_ROLES = ("display","bar","admin")` replaces `ALL_ROLES` on `GET /api/news` (`news.py:52`). `app/realtime/messages.py:58` `Role` gains `kassa`; otherwise a kassa `Hello` raises after accept. `ROLE_ROUTES["kassa"] = ("/kassa",)`, and admin's tuple gains `"/kassa"` **last**, so admin still lands on `/` (`LoginPage.tsx:45-48`). `SPA_ROUTES` picks `/kassa` up by itself (`main.py:101`) | Without the split, widening `ALL_ROLES` silently grants kassa five routes. `_me` raises `KeyError` for a role missing from `ROLE_ROUTES` (`auth.py:53`). |
| PD4 | Tables (§ Data changes) | **`wallet`:**<br>• the spec's columns;<br>• CHECK `wallet_name_check` `char_length(btrim(name)) BETWEEN 1 AND 40`;<br>• CHECK `wallet_deleted_check`: either `deleted_at IS NULL` and `name`, `name_key`, `qr_token`, `short_code`, `cookie_hash` all NOT NULL, or `deleted_at IS NOT NULL` and all five NULL;<br>• plain UNIQUE indexes on `name_key`, `qr_token`, `short_code`, `cookie_hash`, because NULLs are distinct, so a deleted wallet frees them.<br>**`wallet_entry`:**<br>• CHECK `wallet_entry_kind_check` on the five kinds;<br>• CHECK `wallet_entry_amount_check`, the sign by kind (`topup`/`move_in` > 0, `reversal`/`move_out`/`closing` < 0);<br>• CHECK `(kind = 'reversal') = (reverses_entry_id IS NOT NULL)`;<br>• CHECK `(kind = 'move_in') = (counterpart_entry_id IS NOT NULL)`;<br>• FKs: `run_id` → `run` `ON DELETE SET NULL` (the schema's first), `reverses_entry_id` and `counterpart_entry_id` → `wallet_entry`, `actor_key_id` → `auth_key`;<br>• indexes on `wallet_id` and `run_id`.<br>**`wallet_settings`:** the `theme` singleton shape (`id` SmallInteger, `server_default 1`, CHECK `id = 1`, no seeded row: a missing row means the defaults), with CHECKs `unfunded_days BETWEEN 1 AND 365`, `inactive_months BETWEEN 1 AND 60`, and `signup_code` NULL or 1–40 characters after trimming. | **Append-only** means `move_out` cannot be updated to point at its `move_in` later, so only `move_in` names its counterpart. **Seeding** a singleton in the migration would be wiped by the integration conftest's `TRUNCATE` (`tests/integration/conftest.py:133-147`); the `theme` style avoids it. **No column name** contains `total`, `revenue` or `earn` (`test_schema.py:75,149-154`). |
| PD5 | Credentials and codes (SD14, SD19) | All three come from `secrets`:<br>• **QR token:** `secrets.token_urlsafe(16)` (128 bits).<br>• **Cookie value:** `token_urlsafe(32)`. The database stores `hashlib.sha256(value).hexdigest()`.<br>• **Short code:** 8 symbols drawn by `secrets.choice` from Crockford's 32 (`0-9`, `A-Z` minus `I L O U`), stored uppercase without the hyphen. An `IntegrityError` naming the short-code or token index is retried in a savepoint (`begin_nested`, as `app/db/runs.py:255-267`) up to 5 times, then raised. | The spec's minimums. The token and short code are random, never derived from the id or the name. |
| PD6 | Short-code spelling | `normalise_short_code(text) -> str \| None` (pure, `app/runtime/wallet_codes.py`):<br>• strip, uppercase, drop `-` and spaces;<br>• map `O`→`0` and `I`/`L`→`1`;<br>• 8 symbols of the alphabet, or `None`.<br>`None` and no match are both 404 `wallet_not_found`. Every response carries `short_code` in display form `XXXX-XXXX`. The web never normalises or formats a code. | AC14 is the server's. One rule, one place. |
| PD7 | Names and suggestions (SD3) | `name_key` comes from `app.db.products.name_key` (moved there in B-04), reused. The suggestion base is the trimmed name as typed. For n = 2, 3, …, the candidate is `f"{base} {n}"`. If that exceeds 40 characters, the base is cut from the right (then `rstrip`) until it fits. The three lowest n whose `name_key` is free are returned, from one query of the taken keys with that prefix. **Confirm** | "Each within 40 characters" is the spec's; the cut is the planner's reading. |
| PD8 | Which clock wallet times use (SD10, SD15, SD23) | `wallet.created_at`, `deleted_at` and `wallet_entry.created_at` are written from the app clock (`clock_of(request).wall_ms()`, passed down as `now_ms`), as `run.ended_at` is (`app/db/runs.py:617`). The columns keep `server_default now()` only as a safety net. The 2-minute check, "last top-up", retention and the 24 h timer all read the same clock. **Confirm** | SD15 says "on the app clock". Mixing in DB `now()` would make the 2-minute warning and retention untestable with `FakeClock` (`tests/support/clock.py`). |
| PD9 | Idempotency on wallet writes (SD10) | The header is as `app/api/orders.py:27,60-62` (required on top-up, reversal and move). The key is stored on the entry the write creates (the `move_in` for a move). On the UNIQUE violation, or a key found before the write, the stored entry is compared:<br>• top-up: same `wallet_id` and `amount_cents`;<br>• reversal: same `reverses_entry_id`;<br>• move: same target wallet and the counterpart's wallet = `from_wallet_id`.<br>Equal gives 200 with the stored result, rebuilt from the entries. Otherwise 422 `idempotency_key_reused`. "New code" carries no key (it is not money, and a repeat just issues another code). | The order pattern. AC18 names only the top-up, and the interface puts the header on reversal and move too. |
| PD10 | The live run on an entry (SD13) | Inside the action's transaction: `current_run(conn)`, then `run_id` if its `status == "live"`, else `NULL`. A reversal copies the original's `run_id` (SD12), even if that is `NULL` now. | `run_one_live` guarantees at most one. Reading the holder outside its lock would race close/go-live. |
| PD11 | Lock order (SD23) | Each money action does `lock_wallet(conn, id)` (`FOR UPDATE`), then reads the balance, then inserts. Move: `lock_wallets(conn, a, b)` ordered by id. Delete: locks, closing entry, blank. The clean-up selects candidates `FOR UPDATE SKIP LOCKED`, re-checks each against the rules, then deletes. | A top-up and a delete, or two reversals, serialise on the row. SKIP LOCKED keeps a sweep from waiting on a kassa action. |
| PD12 | Settings route body | `PUT /api/admin/wallet-settings {signup_code: str \| null, unfunded_days: int, inactive_months: int}`, `extra="forbid"`, `StrictInt`. `signup_code` is trimmed, and `""` after trimming means `null` (closed). It is otherwise 1–40 characters. Comparison with a typed code is `strip().casefold()` on both sides. **Confirm** (the 40) | SD6 says "trimmed and case-insensitively". The spec sets no length. |
| PD13 | Public pages inside `SessionProvider` | `useSession.ts`:<br>• `SessionProvider` skips `/api/auth/me` on `/speler` (as on `/login`, `:50,53`);<br>• `useGoToLogin` (`:91-101`) does nothing on `/login` and `/speler`, and on `/` only calls `lost()`, so the session turns anonymous and `/` shows the landing without navigating.<br>`routes.tsx`:<br>• `/` becomes `RootRoute`: `anonymous` gives `<LandingPage/>`; `ready` gives the shell with `RequireRole route="/"` around `HomePage` (display and bar still see "Geen toegang", SD20);<br>• `/speler` is a sibling of `/login`. | Today any 401, including a player's 401 `no_wallet`, navigates to login (`http.ts:79`, `routes.tsx:67-74`). |
| PD14 | When the sign-up page checks the name (SD3, SD6) | On blur of the name field, when name and code are both filled, once per distinct (name, code). Submit sends `POST /api/wallet`, whose 409 `name_taken` carries the same suggestions. Picking a suggestion fills the field and submits. Never on each keystroke. **Confirm** | Name check and sign-up share the 5/minute limiter (SD6). A per-keystroke check would exhaust it in one word. |
| PD15 | Page texts the spec does not fix. **Confirm** | Money via `formatEuro` (`web/src/lib/format.ts:20-23`), so `€ 10,00` (no-break space), the app's one euro formatter. The spec's confirm texts keep their wording, with that spelling.<br>**Sign-up:**<br>• `signup_code_invalid` "Onjuiste aanmeldcode.";<br>• `signup_closed` "Aanmelden is nu gesloten.";<br>• `rate_limited` "Te veel pogingen. Probeer het over <n> seconden opnieuw." (from `Retry-After`);<br>• 422 "Kies een naam van 1 tot 40 tekens.";<br>• `name_taken` "Die naam is al bezet. Kies een andere:" plus the suggestions as buttons.<br>**Kassa:**<br>• `wallet_not_found` "Onbekende wallet" (spec);<br>• `already_reversed` "Deze opwaardering is al teruggedraaid.";<br>• `insufficient_balance` "Te weinig saldo om terug te draaien.";<br>• `wallet_deleted` "Deze wallet bestaat niet meer.";<br>• `nothing_to_move` "Er is niets over te zetten.";<br>• a network failure "Verbindingsfout. Probeer opnieuw." (as the settings sections).<br>**Buttons:** "Opwaarderen", "Terugdraaien", "Saldo overzetten van…", "Nieuwe code", "Code typen", "Camera", "Zoeken", "Annuleren", "Speler", "Crew", "Aanmelden". | Errors are tasks. The wording follows the existing pages. |
| PD16 | Venue path in Playwright (AC20, AC41, AC42) | Chromium is launched with `--host-resolver-rules=MAP wallets.test 127.0.0.1`, and the flow uses `http://wallets.test:<port>`. Chromium treats that origin as **not** secure (not localhost, not HTTPS), so `crypto.randomUUID`, `isSecureContext` and the camera behave as at `http://192.168.8.10`. `OriginGuard` compares `Origin` with `Host` (`security.py:213-223`), so writes pass. The harness already serves `SESSION_COOKIE_SECURE=false` (`tests/integration/realapp/harness.py:45-53`). **Confirm** | No test today reaches the app over a non-secure origin. A LAN IP is not reliable on CI runners. The browser's secure-context decision depends on the origin, not the socket. |
| PD17 | The kassa search (SD11, AC25) | `GET /api/kassa/wallets?name=<text>` (the spec's name), 1–40 characters:<br>• every non-deleted wallet whose `name_key` contains `casefold(text)` (`LIKE` with `%`/`_`/`\` escaped);<br>• plus, if `normalise_short_code(text)` matches one, that wallet first.<br>Each row: `wallet_id`, `name`, `created_at`, `balance_cents`, `last_topup_at`. The page drops the open wallet from the list ("every *other*"). | One box, as SD11 describes. |
| PD18 | Per-borrel order and "last activity" (SD16) | Borrels are ordered by `run.started_at DESC`. Only a live run is ever recorded, so every recorded run has `started_at`. The row label is the run's name. "Last activity" is the newest entry's `created_at`, or `created_at` of the wallet when it has none, the same rule the clean-up uses (SD15). Lists are sorted in Python by `(name_key, wallet_id)`, as B-04 PD6. | One definition, two users. |
| PD19 | Retention arithmetic | Unfunded: no entry and `created_at < now - unfunded_days days`. Inactive: `coalesce(max(entry.created_at), wallet.created_at) < now - inactive_months months` (Postgres `make_interval(months => …)` on the app-clock `now` passed in). | Calendar months, as the setting is in months. |
| PD20 | The poster QR | Not built. The owner makes the poster from the link `/speler?code=<code>` with any QR maker. The Wallets section shows that link as text beside the code (read-only). **Confirm** | SD6 names the link, and no AC asks the app to draw the poster. Showing the link costs one line and avoids a typo on the poster. |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `db/migrations/versions/0013_wallets.py` | Create | Three tables, role CHECK widened (PD4); `min_code_revision = "unchanged"` | T1 |
| `app/db/models.py` | Modify | `Wallet`, `WalletEntry`, `WalletSettings`; `auth_key_role_check` text | T1 |
| `tests/integration/test_schema.py` | Modify | `B_05_TABLES`; four roles accepted; wallet CHECKs; no-`total` tripwire still green | T1 |
| `tests/integration/test_migrations.py` | Modify | `0013` up/down, `kassa` accepted after, refused after downgrade | T1 |
| `tests/meta/test_guard_migrations_hook.py` | Modify | Head is `0013_wallets.py` (`:159-166,231-239`) | T1 |
| `app/db/keys.py`, `app/api/deps.py`, `app/api/security.py`, `app/realtime/messages.py`, `app/api/news.py`, `app/api/state.py`, `app/cli/keys.py` | Modify | The `kassa` role (PD3; `state.py` only under PD1 reading A) | T2 |
| `tests/unit/test_security.py`, `tests/api/test_auth.py`, `tests/api/test_static.py`, `tests/api/test_authorization_matrix.py`, `tests/integration/test_cli_keys.py` | Modify | Pins for the fourth role | T2 |
| `web/src/features/auth/useSession.ts`, `auth.test.tsx` | Modify | `Me.role` gains `kassa` (T3); public paths (T15) | T3, T15 |
| `web/src/features/home/HomePage.tsx`, `HomePage.test.tsx` | Modify | "Kassa" tile; `Kassa` connection count | T3 |
| `web/src/features/keys/KeysSection.tsx` (+ test) | Modify | Role option "Kassa" | T3 |
| `web/src/components/ui/NavMenu.tsx`, `NavMenu.test.tsx` | Modify | `'/kassa': 'Kassa'` | T3 |
| `web/src/features/exchange/model/schemas.ts` | Modify | `HelloData.role` gains `kassa` (`:20,143`) | T3 |
| `web/e2e/fixtures.ts`, `web/e2e/auth.spec.ts` | Modify | `Role` type; admin's nav gains Kassa | T3 |
| `app/db/wallets.py` | Create | Repository (PD4, PD5, PD9–PD11, PD17–PD19) | T4 (T9 extends) |
| `app/runtime/wallet_codes.py` | Create | Pure: tokens, cookie hash, short codes, suggestions (PD5–PD7) | T4 |
| `tests/unit/test_wallet_codes.py`, `tests/integration/test_wallets_repo.py` | Create | Codes; repository incl. delete and races | T4 |
| `app/runtime/wallets.py` | Create | One function per action, one transaction each | T5, T6, T7, T8, T9 |
| `app/api/wallet.py` | Create | `/api/wallet` routes, cookie set/clear | T5, T6 |
| `app/core/config.py`, `.env.example`, `tests/unit/test_config.py` | Modify | `signup_rate_per_minute` (default 5) | T5 |
| `app/main.py` | Modify | Routers, `signup_limiter`, `/speler` in `SPA_ROUTES` | T5, T7, T9 |
| `tests/meta/test_route_authorization.py` | Modify | Two public routes (T5); the wallet marker (T6) | T5, T6 |
| `tests/api/test_wallet_signup.py`, `tests/api/test_wallet_player.py` | Create | Player API | T5, T6 |
| `tests/api/test_standby.py` | Modify | Wallet routes 503 `standby` | T6 |
| `app/api/kassa.py` | Create | `/api/kassa` routes | T7, T8 |
| `tests/api/test_kassa_topup.py`, `tests/api/test_kassa_corrections.py` | Create | Kassa API | T7, T8 |
| `tests/api/test_draining.py` | Modify | `DRAINING_WRITES` rows for kassa and admin writes | T7, T8, T9 |
| `app/api/wallets_admin.py` | Create | `/api/admin/wallets`, `/api/admin/wallet-settings` | T9 |
| `tests/api/test_wallets_admin.py` | Create | Admin API, totals, AC32 | T9 |
| `tests/integration/test_export_workbook.py` | Modify | Wallets present, workbook unchanged (AC35) | T9 |
| `app/runtime/wallet_cleanup.py`, `app/runtime/boot.py` | Create / Modify | Sweep at boot and every 24 h | T10 |
| `tests/integration/test_wallet_cleanup.py` | Create | AC31 | T10 |
| `tests/integration/test_wallets_restart.py`, `tests/integration/test_wallet_concurrency.py` | Create | AC45, AC46, AC23 | T11 |
| `web/src/api/generated/schema.d.ts` | Modify (regenerated) | `./scripts/gen_api_types.sh`; never hand-edited | T2, T5–T9 |
| this plan | Modify | § Dependency approval (T12), § Icon approval (T14) | T12, T14 |
| `web/src/components/ui/pixelIcons.json`, `PixelIcon.test.tsx`, `scripts/pixel_icons.py`, `tests/unit/test_pixel_icons.py` | Modify | `wallet` grid | T13, T14 |
| `web/src/app/routes.tsx` | Modify | `RootRoute`, `/speler` (T15); `/kassa` page (T17) | T15, T17 |
| `web/src/app/pages/LandingPage.tsx` (+ test) | Create | "Speler" / "Crew" | T15 |
| `web/src/features/player/` (`index.ts`, `PlayerPage.tsx`, `SignupForm.tsx`, `api.ts`, tests) | Create | Sign-up (T15); wallet view, QR, poll (T16) | T15, T16 |
| `web/src/features/player/WalletView.tsx`, `QrCode.tsx`, `useVisiblePoll.ts` (+ tests) | Create | AC9, AC10 | T16 |
| `web/package.json`, `web/pnpm-lock.yaml` | Modify | `uqr` (T16), `jsqr` (T19) | T16, T19 |
| `web/src/features/kassa/` (`index.ts`, `KassaPage.tsx`, `TopUpPanel.tsx`, `TopupList.tsx`, `api.ts`, tests) | Create | Lookup, top-up (T17); reversal, move, new code (T18) | T17, T18 |
| `web/src/lib/idempotencyKey.ts` (+ test) | Create | `crypto.getRandomValues`, 16 bytes → 32 hex | T17 |
| `web/src/walletCode.provenance.test.ts` | Create | No `crypto.randomUUID` in wallet code (AC20) | T17 |
| `web/src/features/kassa/MoveDialog.tsx` (+ test) | Create | SD11 | T18 |
| `web/src/features/kassa/Scanner.tsx`, `decodeQr.ts`, `camera.ts` (+ tests) | Create | Camera where allowed (AC42) | T19 |
| `web/src/features/wallets/` (`index.ts`, `WalletsSection.tsx`, test) | Create | The admin section | T20 |
| `web/src/app/pages/SettingsPage.tsx`, `SettingsPage.test.tsx` | Modify | Section after Toegangssleutels, icon `wallet` | T20 |
| `web/e2e/wallets.spec.ts` | Create | The spec's flow, venue host (PD16) | T21 |
| `docs/adr/0001-setup-decision-record.md` | Modify | Addendum (SD26) | T22 |
| `docs/design/data-model.md`, `docs/design/frontend-architecture.md` | Modify | **Owner stop** | T22 |
| `docs/specs/phase-4-web-koers.md` | Modify | Amendment note on SD25's "no other dependency" | T22 |
| `docs/runbooks/venue.md`, `docs/backlog.md` | Modify | Wallets at the venue; `kassa` in the key line; B-05 → built | T22 |

Untouched, and checked at T22: `exchange/`, `tests/engine/`, `app/runtime/orders.py`, `app/db/orders.py`, `app/api/orders.py`, `web/src/features/bar/`, `app/jobs/export_xlsx.py`, `app/db/exports.py`, every existing migration.

---

## Tasks

### T1 — The schema: three tables and the `kassa` role in the database

- **Implements:** AC24 (only `topup` reversible, enforced by the reversal CHECK pair), AC33 (ranges, DB half), AC45 (what persists), AC47; SD9, SD15 (the blanked row), SD7 (role CHECK)
- **Expected output:**
  - `0013_wallets.py` per PD4, laid out as `0012_settings_profile.py` (docstring with one bullet per decision, `Revises: 0012`, `min_code_revision = "unchanged"`). It widens `auth_key_role_check` as `0009_phase_6_admin.py:51-54` does, with a `downgrade()` that restores the three-role CHECK and drops the tables in reverse order. The docstring states, as `0009:15-17` does, that the downgrade fails loudly while a `kassa` key exists.
  - The three models in `models.py`, column for column. `AuthKey`'s CHECK text gains `kassa`. `test_the_models_match_the_migrated_schema` does not compare CHECK text, so the new `test_schema.py` tests pin it by SQL.
  - `test_schema.py`:
    - `B_05_TABLES = frozenset({"wallet", "wallet_entry", "wallet_settings"})` in the inspected union;
    - the roles loop (`:344-349`) covers four;
    - by SQL in `_in_transaction`:
      - a deleted wallet with a name, and a live wallet without a token, both fail `wallet_deleted_check`;
      - a `topup` of −100 and a `reversal` of +100 fail `wallet_entry_amount_check`;
      - a `reversal` without `reverses_entry_id` fails;
      - a second reversal of one entry fails its UNIQUE;
      - a second `wallet_settings` row fails `id = 1`;
      - `unfunded_days` 0 and 366, and `inactive_months` 0 and 61, fail;
      - deleting a run sets `wallet_entry.run_id` to NULL and keeps the row.
  - `test_migrations.py`: a `kassa` key inserts at head; `downgrade 0012` with no kassa key succeeds and then refuses `kassa`.
  - `test_guard_migrations_hook.py`: the head assertions name `0013_wallets.py`.
- **Verification:** `uv run pytest tests/integration/test_schema.py tests/integration/test_migrations.py tests/meta/test_schema_compat_coverage.py tests/meta/test_guard_migrations_hook.py tests/integration/test_delete_run.py` (needs the compose `db`); `uv run mypy app`.
- **Depends on:** —
- **Autonomy note:** Index names, docstring wording and test layout are the builder's. The columns, their nullability and the CHECKs are PD4's. Adding a column (a phone, an email, a "display name"), seeding `wallet_settings`, or a `min_code_revision` other than `"unchanged"` is not the builder's: stop and ask. The guard hook blocks edits to `0012`; never work around it.

### T2 — The `kassa` role on the server

- **Implements:** AC36 (server half: `allowed_routes == ["/kassa"]`, 403 elsewhere), AC37 (the role exists for the matrix), AC40 (CLI); SD7, PD1 reading A, PD3
- **Expected output:**
  - PD3's constants. `app/cli/keys.py` takes `--role kassa` (choices come from `ROLES`; the usage docstring at `:3` names four). `app/api/keys.py` needs no change (`Role` widens it).
  - `/ws` keeps its marker, now `frozenset(ALL_ROLES)` (four roles). `GET /api/state` uses `ALL_ROLES` and `GET /api/news` `MARKET_ROLES`. Under PD1 reading B this bullet changes and the plan is amended first.
  - Tests:
    - `test_security.py:37-42` pins `ROLE_ROUTES` with kassa and admin's `/kassa`;
    - `test_auth.py:64-79` parametrises `/me` and login over four roles (kassa: `allowed_routes == ["/kassa"]`);
    - `test_static.py:119-130` adds `/kassa` to the SPA set;
    - `test_cli_keys.py` adds a `--role kassa` create.
  - `test_authorization_matrix.py`: `ACTORS` adds `"kassa"`. Rows: `ALL` (four) on `me`, `logout`, `/api/state`, `WS /ws`; the old three-role set renamed `MARKET` on `GET /api/news`. Every other row is unchanged, so kassa gets 403 on all of them (AC36).
  - Regenerated `schema.d.ts` (`Me.role`, `KeyInfo.role`, `CreateKeyRequest.role`).
- **Verification:** `uv run pytest tests/unit/test_security.py tests/api/test_auth.py tests/api/test_static.py tests/api/test_authorization_matrix.py tests/api/test_keys.py tests/api/test_ws.py tests/integration/test_cli_keys.py tests/meta/test_route_authorization.py`; `./scripts/gen_api_types.sh && git diff --stat -- web/src/api/generated` shows only `schema.d.ts`; `uv run mypy app`.
- **Depends on:** T1 (the CHECK must accept `kassa` before a test can mint one)
- **Autonomy note:** Constant names are the builder's. Granting kassa any route beyond PD1's ruling, or changing where admin lands, is not. If `earnings.py:61`'s inline `!= "admin"` or any other inline role comparison turns up that a fourth role changes, report it in the task notes. Change it only if a test proves kassa gains access through it.

### T3 — The `kassa` role on the web

- **Implements:** AC36 (a kassa login lands on `/kassa`), AC40 (Toegangssleutels, the tile, the count); SD7, SD22
- **Expected output:**
  - `kassa` added to every zod role enum: `useSession.ts:29`, `HomePage.tsx:49`, `KeysSection.tsx:23`, `exchange/model/schemas.ts:20,143`. Without this a kassa session loops to login, one kassa socket blanks the panel, and one kassa key blanks the key list (`tsc` cannot see it, because `Me` is `z.ZodType<MeData>`).
  - `KeysSection`'s `ROLES` gains `{value: 'kassa', label: 'Kassa'}`.
  - `HomePage`:
    - `TILES` gains `/kassa` "Kassa";
    - `ROLES` gains `['kassa', 'Kassa']`, so the line reads `Scherm: n, Bar: n, Kassa: n, Beheer: n`.
  - `NavMenu.LABELS` gains `'/kassa': 'Kassa'`.
  - `e2e/fixtures.ts:9` `Role` gains `kassa` (type only).
  - `e2e/auth.spec.ts` and `auth.test.tsx` `ALLOWED`/`NAV`: admin's routes end in `/kassa`.
  - Tests:
    - `HomePage.test.tsx`: a kassa connection counts as Kassa and the panel still renders;
    - `KeysSection` test: a listed kassa key renders "Kassa", and create sends `role: 'kassa'`;
    - `NavMenu.test.tsx`: the label;
    - `auth.test.tsx`: a kassa login lands on `/kassa`.
  - `/kassa` itself shows "Geen toegang" (the `*` route) until T17.
- **Verification:** `pnpm -C web exec vitest run src/features/home src/features/keys src/features/auth src/components/ui/NavMenu.test.tsx src/features/exchange`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src e2e`.
- **Depends on:** T2 (the generated `Me.role`)
- **Autonomy note:** Label order in the panel is the builder's, with Kassa before Beheer. Any new role-to-route table on the client is not (`useSession.ts:3-4`).

### T4 — The wallet repository and the codes

- **Implements:** AC4 (suggestions), AC12 (only the hash stored), AC14 (normalisation), AC29 (delete at repository level), AC32 (closing entry keeps the run's top-ups), AC47 (the blanked row); SD3, SD5, SD9, SD14, SD15, PD4–PD7, PD11, PD18, PD19
- **Expected output:**
  - `app/runtime/wallet_codes.py` (pure, imports `secrets`, `hashlib` only):
    - `new_qr_token()`, `new_cookie_value()`, `cookie_hash(value)`;
    - `new_short_code()`, `normalise_short_code(text)`, `display_short_code(code)`;
    - `suggestions(base: str, taken_keys: set[str], *, limit=3) -> list[str]` per PD7.
  - `app/db/wallets.py`:
    - frozen dataclasses `WalletRow`, `EntryRow`, `WalletSettingsRow` (defaults when absent: `None`, 30, 12);
    - errors as `AppError`s: `WalletNotFound` 404 `wallet_not_found`, `NoWallet` 401 `no_wallet`, `NameTaken` 409 `name_taken` (`extra={"suggestions": …}`), `AlreadyReversed`, `InsufficientBalance`, `WalletDeleted`, `NothingToMove` (409s), `IdempotencyKeyReused` 422;
    - functions:
      - `create_wallet` (PD5 retries; the name's UNIQUE violation becomes `NameTaken` with suggestions);
      - `get_by_cookie_hash`, `get_by_qr_token`, `get_by_short_code`, `get`;
      - `lock_wallet`, `lock_wallets`, `balance`;
      - `insert_entry(conn, …, now_ms)`;
      - `find_entry_by_key`;
      - `delete_wallet(conn, wallet_id, *, now_ms, actor_key_id=None, actor_label=None)`: lock, `closing` entry of −balance if > 0 (with the live run, PD10), blank the five columns, stamp `deleted_at`;
      - `replace_codes`;
      - `taken_name_keys(conn, prefix_key)`;
      - `get_settings`, `put_settings` (`theme.py:81-107` upsert).
  - `tests/unit/test_wallet_codes.py`:
    - alphabet and length;
    - normalisation table: `k7q4-m2xd`, `K7Q4M2XD`, ` k7q4 m2xd `, `O`→`0`, `I`/`L`→`1`, a `U` → `None`, 7 characters → `None`;
    - display form;
    - the suggestions: "Jan" with `jan 2` taken → `["Jan 3","Jan 4","Jan 5"]`, and a 40-character base → each suggestion ≤ 40 characters;
    - token sizes ≥ 128 bits;
    - the hash is not the value.
  - `tests/integration/test_wallets_repo.py`:
    - create, and get by each key;
    - a taken name, case- and space-different → `NameTaken` with suggestions;
    - two concurrent creates of one name → one row (as `test_profiles_repo.py:137-151`);
    - a forced short-code collision retried;
    - balance = the sum of the entries;
    - delete with balance 3500 → a `closing` −3500, the row blanked, `deleted_at` set, and the name free again;
    - delete with 0 → no entry;
    - a deleted wallet is not found by its old cookie hash, token or code;
    - settings defaults, then put and get.
- **Verification:** `uv run pytest tests/unit/test_wallet_codes.py tests/integration/test_wallets_repo.py`; `uv run mypy app`; `uv run ruff check app`.
- **Depends on:** T1
- **Autonomy note:** Function names, the dataclass fields beyond the spec's and the test layout are the builder's. Using `random` instead of `secrets`, deriving a code from the id, or storing the cookie value itself is not. If the repository grows past ~300 lines, the builder may move the settings functions into `app/db/wallet_settings.py`.

### T5 — Sign-up and the name check (public)

- **Implements:** AC3, AC4, AC5, AC6, AC7, AC8, AC11 (the cookie set on sign-up), AC19 (sign-up without a live run), AC39 (the two public routes), AC44 (sign-up draining); SD3, SD6, SD19, SD20 (`/speler` reload), PD12–PD14
- **Expected output:**
  - `app/core/config.py`: `signup_rate_per_minute: int = Field(default=5, ge=1)`, with a comment as `login_rate_per_minute` (`:95-97`). Added to `.env.example` and `ENV_VARS` (`tests/unit/test_config.py:19-32`), plus a bad-value test (as `:381-390`).
  - `app/main.py` lifespan: `application.state.signup_limiter = LoginLimiter(settings.signup_rate_per_minute, application.state.clock)`. `SPA_ROUTES` gains `/speler`. The `wallet` router is registered.
  - `app/runtime/wallets.py`: `name_check(engine, *, name, code)` and `sign_up(engine, *, name, code, cookie_value: str | None, now_ms)`. Order:
    1. draining (503, a dependency);
    2. limiter (429 `rate_limited` with `Retry-After`, keyed as `auth.py:58-60`);
    3. a valid cookie → 200 with that wallet;
    4. code (409 `signup_closed` / 403 `signup_code_invalid`);
    5. name (422 by pydantic, `StringConstraints(strip_whitespace=True, min_length=1, max_length=40)`);
    6. create (201).
  - `app/api/wallet.py`, `prefix="/wallet"`:
    - `POST /name-check {name, code}` → `{available, suggestions}`;
    - `POST "" {name, code}` → `WalletData{name, balance_cents, qr_token, short_code, created_at}`;
    - on 201 it sets `bb_wallet` with `max_age=400*24*3600`, `path="/"`, `**cookie_kwargs(settings)`.
    - The cookie constant `WALLET_COOKIE = "bb_wallet"` lives here.
  - `tests/meta/test_route_authorization.py`: `PUBLIC_ROUTES` gains exactly `("POST","/api/wallet")` and `("POST","/api/wallet/name-check")`. The allowlist pin test is updated, with a comment citing the owner's approval (spec SD6, Q9).
  - `tests/api/test_static.py`: `/speler` in the SPA set.
  - `tests/api/test_wallet_signup.py` (`wallet_settings` set through the repository):
    - free name → 201, balance 0, `Set-Cookie: bb_wallet` HttpOnly, SameSite=Strict, Max-Age 34560000, Secure exactly when `session_cookie_secure` (both values, via settings override) (AC3, AC11);
    - taken "jan" vs "Jan " → 409 with suggestions and no row; the name check gives the same (AC4);
    - two concurrent sign-ups of one free name → one 201, one 409 (AC5);
    - wrong code → 403; no code set → 409 `signup_closed`; `""`, `"   "`, 41 characters → 422; nothing created (AC6);
    - code `" ABC "` set, typed `"abc"` → accepted (SD6);
    - six requests mixing sign-up and check in 60 s → the sixth 429 with `Retry-After`, and `advance(60_000)` clears it (AC7);
    - sign-up with a valid cookie → 200, the same wallet, the row count unchanged (AC8);
    - no live run → 201 (AC19);
    - draining → 503 `shutting_down`, nothing created (AC44);
    - an anonymous request with no `bb_session` works (public).
- **Verification:** `uv run pytest tests/api/test_wallet_signup.py tests/meta/test_route_authorization.py tests/api/test_static.py tests/unit/test_config.py tests/api/test_authorization_matrix.py`; schema drift as T2; `uv run mypy app`.
- **Depends on:** T4 (repository), T2 (`test_static.py`'s SPA set and the matrix are already four-role)
- **Autonomy note:**
  - Request and response model names are the builder's.
  - The step order above is PD-fixed: the limiter counts before the cookie and code are looked at.
  - Adding any other route to `PUBLIC_ROUTES` is not the builder's: stop.
  - If `LoginLimiter` needs a change to serve two instances, stop and ask. It should need none.

### T6 — The player's own routes and the wallet guard

- **Implements:** AC11 (renewal), AC12, AC13 (API half), AC29 (player delete), AC38, AC39 (the second marker), AC44 (self-delete draining; standby); SD8, SD15, SD19, SD21
- **Expected output:**
  - `app/api/deps.py`:
    - `require_wallet(request) -> WalletRow` reads `bb_wallet` and calls `get_by_cookie_hash`;
    - missing, unknown or deleted → `NoWallet` (401 `no_wallet`), and the error response clears the cookie (an `AppError` subclass carrying a `Set-Cookie` delete header, so the route body never runs);
    - `REQUIRE_WALLET_MARKER = "__require_wallet__"` set on it.
  - `app/api/wallet.py`:
    - `GET ""` → `WalletData`, re-setting `bb_wallet` with the same value and the 400-day max-age;
    - `DELETE ""` (`require_wallet`, then `refuse_while_draining`) → `delete_wallet`, 204, cookie deleted.
  - `tests/meta/test_route_authorization.py`:
    - `_guarded` accepts either marker;
    - its fixture self-test gains a route guarded by a function carrying `REQUIRE_WALLET_MARKER` (guarded) and one with neither (reported) (AC39).
  - `tests/api/test_authorization_matrix.py`:
    - `WALLET_ROUTES = {("GET","/api/wallet"),("DELETE","/api/wallet")}`;
    - coverage becomes `served - public - WALLET_ROUTES == set(SD1)`;
    - a new test: every crew actor (display, bar, kassa, admin) and anonymous → 401 `no_wallet` on both (AC38).
  - `tests/api/test_standby.py`: in standby, `POST /api/wallet`, `GET /api/wallet` and `POST /api/kassa/lookup` → 503 `standby`. The last is a path the gate answers before routing, so it needs no T7.
  - `tests/api/test_wallet_player.py`:
    - `GET` renews the cookie (Max-Age, flags) after `advance` (AC11);
    - the QR token or short code sent as the `bb_wallet` value → 401 (AC12);
    - the stored `cookie_hash` ≠ the cookie value (AC12);
    - after an admin-style `delete_wallet` by repository → `GET` 401 `no_wallet` with a clearing `Set-Cookie` (AC13);
    - `DELETE` with balance 3500 (entries inserted by repository) → 204, a `closing` −3500, the row blank, the cookie cleared, the name free for a new sign-up (AC29);
    - draining → `DELETE` 503 and nothing written (AC44);
    - a phone with a crew session and a wallet cookie gets both (SD19).
- **Verification:** `uv run pytest tests/api/test_wallet_player.py tests/api/test_wallet_signup.py tests/meta/test_route_authorization.py tests/api/test_authorization_matrix.py tests/api/test_standby.py`; schema drift; `uv run mypy app`.
- **Depends on:** T5 (`wallet.py`, `runtime/wallets.py`, the meta test)
- **Autonomy note:** How the 401 clears the cookie is the builder's: a header on the error, or a handler. A route that answers a deleted wallet's cookie with anything but 401 `no_wallet` is not.

### T7 — Kassa: lookup and top-up

- **Implements:** AC14, AC15, AC16, AC17 (`recent_topup`), AC18, AC19, AC37 (these routes), AC44 (top-up draining); SD9, SD10, SD13, PD8–PD10
- **Expected output:**
  - `app/api/kassa.py`, `prefix="/kassa"`, every route `require_role("kassa", "admin")`, with writes followed by `refuse_while_draining`:
    - `POST /lookup {qr_token} | {short_code}` (exactly one, `extra="forbid"`) → `{wallet_id, name, balance_cents, created_at, last_topup_at, recent_topup: {at, amount_cents} | null}` (2 minutes on the app clock);
    - `GET /wallets/{wallet_id}/topups` → `[{entry_id, amount_cents, created_at, actor_label, reversed}]`, newest first;
    - `POST /wallets/{wallet_id}/topups {amount_cents}` with `Idempotency-Key` → 201, or 200 on replay. The amount is in `{1000, 1500, …, 10000}` (a `field_validator`), else 422. The entry carries the key, its label and PD10's run.
  - Registered in `main.py`; schema regenerated.
  - `test_authorization_matrix.py`:
    - `KASSA = frozenset({"kassa","admin"})` rows for the three routes;
    - `{wallet_id}` and `{entry_id}` in `_status`.
  - `test_draining.py`: the top-up with a valid body.
  - `tests/api/test_kassa_topup.py`:
    - lookup by token and by every PD6 spelling; an unknown token, an unknown code and a deleted wallet's old code → 404 (AC14);
    - top-up 1500 → the balance rises by 1500; one entry with `actor_key_id`, `actor_label` and the live run's id (`live_client`) (AC15);
    - 500, 1250, 10500, 0, −1000 → 422, nothing written (AC16);
    - a second lookup within 2 minutes shows `recent_topup`, and after `advance(120_001)` none (AC17);
    - a replay with the same key and body → 200, the same `entry_id`, one entry; the same key with 2000 → 422 `idempotency_key_reused` (AC18);
    - no live run → the entry's `run_id` is NULL (AC19);
    - top-up by an admin key (AC37);
    - draining → 503 (AC44).
- **Verification:** `uv run pytest tests/api/test_kassa_topup.py tests/api/test_authorization_matrix.py tests/api/test_draining.py tests/meta/test_route_authorization.py`; schema drift; `uv run mypy app`.
- **Depends on:** T6 (`runtime/wallets.py`, the matrix)
- **Autonomy note:** Response model names are the builder's. The amount set, the 2-minute window and the status codes are the spec's. Refusing a second top-up within 2 minutes is not allowed (SD10: "It never refuses").

### T8 — Kassa: reversal, search and move, new code

- **Implements:** AC21, AC22, AC23 (API half), AC24, AC25, AC26 (API half), AC27, AC28 (API half), AC37, AC44, AC46 (API half); SD11, SD12, SD14, PD9, PD11, PD17
- **Expected output:**
  - `app/api/kassa.py` gains:
    - `POST /topups/{entry_id}/reversal` with `Idempotency-Key`: 404 when the entry is not a top-up (AC24) or is unknown; 409 `wallet_deleted`, `already_reversed`, `insufficient_balance`. The reversal carries the original's run (SD12).
    - `GET /wallets?name=` (PD17).
    - `POST /wallets/{wallet_id}/move {from_wallet_id}` with `Idempotency-Key`. In one transaction:
      1. lock both wallets by id;
      2. refuse the same id, or a zero balance, with `nothing_to_move`; an unknown or deleted wallet is 404;
      3. write `move_out` −B, then `move_in` +B naming it;
      4. `delete_wallet(old)`, so the old name is freed first;
      5. set the new wallet's `name` and `name_key` to the old ones.
    - `POST /wallets/{wallet_id}/new-code` → `{qr_token, short_code}` via `replace_codes`.
  - Matrix and draining rows; schema regenerated.
  - `tests/api/test_kassa_corrections.py`:
    - reversal of a 1500 top-up: one `reversal` −1500 naming it, with the key label and the original's run even after a go-live of another run (AC21);
    - a second reversal → 409 `already_reversed`; a reversal past zero (1500 topped up, 1000 moved away) → `insufficient_balance`; a reversal on a deleted wallet → `wallet_deleted`. Each writes nothing (AC22);
    - two concurrent reversals of 1000 and 1500 on a 2000 balance → exactly one succeeds, the balance ≥ 0 (AC23, AC46);
    - reversing a `reversal`, `move_in`, `move_out` or `closing` → 404 (AC24);
    - search "an" finds "Jan" and "Anna" with all four fields; a typed short code finds its wallet first (AC25);
    - move: the entries, the old row blanked, the new name "Jan", the new balance, `GET /api/wallet` with the new cookie shows "Jan" (AC26);
    - same wallet, or a zero balance → 409, nothing written (AC27);
    - new code: the old token and code → 404, the new ones found, the cookie still 200 (AC28);
    - matrix rows for display, bar and anonymous (AC37);
    - draining on all three writes (AC44).
- **Verification:** `uv run pytest tests/api/test_kassa_corrections.py tests/api/test_kassa_topup.py tests/api/test_authorization_matrix.py tests/api/test_draining.py`; schema drift; `uv run mypy app`.
- **Depends on:** T7 (`kassa.py`, the matrix, draining)
- **Autonomy note:** The order inside the move is fixed as above, because the name's UNIQUE index requires the old name freed before the new wallet takes it. A non-top-up entry is 404, so no route reveals other entries' existence; if the builder thinks 409 is better, stop and ask. If this task exceeds ~400 source lines, split new code into T8b, keeping the dependency chain.

### T9 — Admin: the list, the totals, delete and the settings

- **Implements:** AC30, AC32, AC33, AC34 (API half), AC35, AC37 (admin rows), AC44 (admin delete, settings); SD15, SD16, PD2, PD12, PD18
- **Expected output:**
  - `app/db/wallets.py` gains:
    - `list_wallets` (name, balance, last activity; Python sort);
    - `outstanding_cents` (sum over non-deleted);
    - `topups_per_run` (topup + reversal grouped by `run_id`, joined to `run` for name and `started_at`, PD18 order, plus PD2's no-run row under reading A).
  - `app/api/wallets_admin.py` (`prefix="/admin"`), every route `require_role("admin")`:
    - `GET /wallets` → `{outstanding_cents, per_borrel: [{run_id | null, name, net_topup_cents}], wallets: [{wallet_id, name, balance_cents, last_activity_at}]}`;
    - `DELETE /wallets/{wallet_id}` → 204 (draining);
    - `GET` and `PUT /wallet-settings` (PUT draining) per PD12.
  - Registered; schema regenerated; matrix and draining rows.
  - `tests/api/test_wallets_admin.py`:
    - the list order "alpha, Beta, gamma", the balances, last activity;
    - outstanding = the sum of non-deleted balances;
    - per-borrel net of a reversal, newest first;
    - an admin delete → as AC29 (AC30);
    - per-borrel totals equal before and after deleting a funded wallet, by player, admin and repository (AC32);
    - periods 0, 366, 61, `1.5`, `"30"` → 422, and 1, 365, 60 accepted (AC33);
    - code `"  "` → `null`, and a sign-up afterwards → `signup_closed`;
    - admin-only rows (AC37);
    - draining (AC44).
  - `test_export_workbook.py`: with wallets, entries and settings present, the workbook's sheet names and every cell equal those of the same run without them (AC35).
- **Verification:** `uv run pytest tests/api/test_wallets_admin.py tests/integration/test_export_workbook.py tests/api/test_authorization_matrix.py tests/api/test_draining.py`; schema drift; `uv run mypy app`.
- **Depends on:** T8 (matrix, draining, `runtime/wallets.py`, schema)
- **Autonomy note:** Field names are the builder's, except that no API field may suggest money the association earned. Under PD2 reading B, drop the no-run row. Any change to `app/jobs/export_xlsx.py` or `app/db/exports.py` is not the builder's: AC35 says unchanged.

### T10 — The automatic clean-up

- **Implements:** AC31, AC44 (not while draining); SD15, PD11, PD19
- **Expected output:**
  - `app/runtime/wallet_cleanup.py`:
    - `sweep(engine, *, now_ms) -> int`: one transaction; settings read; candidates `FOR UPDATE SKIP LOCKED`, re-checked; `delete_wallet` for each; returns the count.
    - `run_cleanup(app_state, engine, clock)`: every `CLEANUP_INTERVAL_MS = 24*3600*1000` on `clock.sleep_until`; skips while `app_state.draining`; logs and swallows `Exception` as `run_worker` (`export_xlsx.py:414-416`).
  - `boot.py` `_boot`:
    - `await sweep(…)` after `interrupt_unfinished` (`:234-237`), logged as `wallet_cleanup` with the count, a failure logged and not fatal;
    - the loop appended to `booted.tasks` after the ticker (index 0, `:383` cancels `[1:]`).
  - `tests/integration/test_wallet_cleanup.py` (`FakeClock`, timestamps written by SQL relative to it), deletes and keeps:
    - unfunded and 31 days old: deleted;
    - unfunded and 29 days: kept;
    - funded with its last entry 13 months old: deleted, with its closing entry;
    - 11 months: kept;
    - a wallet whose page was opened (a `GET /api/wallet`) but has no new entry is still deleted (activity is entries only);
    - a 1-day setting obeyed;
    - the loop: `advance(24h)` runs a second sweep; with `draining = True` it does not;
    - boot runs one sweep (an API client boot over a database seeded with an expired wallet);
    - a wallet locked by an open transaction is skipped, not waited for.
- **Verification:** `uv run pytest tests/integration/test_wallet_cleanup.py tests/integration/test_boot.py tests/meta/test_clock_seam.py`; `uv run mypy app`.
- **Depends on:** T4 (`delete_wallet`, settings)
- **Autonomy note:** The interval constant and log names are the builder's. Running the sweep inside the advisory-lock watchdog, the export worker, or the ticker is not. `app/runtime` is clock-seam scanned, so no `import time`.

### T11 — Restart and concurrency, end to end

- **Implements:** AC23, AC45, AC46; spec Verification › Integration
- **Expected output:**
  - `tests/integration/test_wallets_restart.py`: wallets with top-ups, a reversal and a move; the app stopped mid-sequence (a `create_app` lifespan exit), a fresh `create_app` on the same database. Every wallet, entry and setting is as committed, and every balance equals the SQL sum of its entries (AC45).
  - `tests/integration/test_wallet_concurrency.py`: a seeded random sequence (≥ 200 operations over 5 wallets) of top-ups, reversals, moves and deletes, run in concurrent batches with `asyncio.gather(..., return_exceptions=True)`. After each batch:
    - no balance < 0;
    - the ledger sum equals each balance;
    - each top-up is reversed at most once;
    - deleted wallets sum to 0.

    Expected refusals are counted, unexpected exceptions fail (AC23, AC46).
- **Verification:** `uv run pytest tests/integration/test_wallets_restart.py tests/integration/test_wallet_concurrency.py`.
- **Depends on:** T8
- **Autonomy note:** **Changes no source file.** If an assertion fails, the locking or the transaction is wrong: stop and report. Do not patch around it in a test.

### T12 — Dependency approval — **hard stop, owner** (SD18)

- **Implements:** AC43 (the approved packages); SD18
- **Expected output:**
  - The build stops and shows the owner § New dependencies below.
  - The owner approves, or names other packages. Either way the answer, its date and the exact versions go into § Dependency approval, committed as `docs(phase-b-05): T12 — QR dependencies approved`.
  - If the owner names other packages, the plan is amended (T16, T19) and re-audited before either task starts.
- **Verification:** § Dependency approval holds a dated answer from the owner naming both packages and their versions.
- **Depends on:** —
- **Autonomy note:** **Stop. This is the owner's.** The builder may not add either package, a substitute, or a transitive helper before the answer. Silence is not approval. T1–T11, T13 and T15 do not depend on it and may proceed.

### T13 — The `wallet` grid

- **Implements:** AC34 (the icon's grid); SD25
- **Expected output:**
  - A 16×16 `wallet` in `pixelIcons.json`, a wallet as the starting motif, in the style of the existing 16×16 grids.
  - `PixelIcon.test.tsx`: 18 large grids, 23 total (`:2,11-29,57-61`).
  - `SPOTS` gains `"wallet": ("Instellingen › Wallets", "(nieuw)", "--text")`, so `tests/unit/test_pixel_icons.py:192-194` holds.
  - The contact sheet shows it. Not placed on any page.
- **Verification:** `pnpm -C web exec vitest run src/components/ui/PixelIcon.test.tsx src/noEmoji.test.ts`; `uv run pytest tests/unit/test_pixel_icons.py`; `uv run python -m scripts.pixel_icons sheet` writes `.dev/pixel-icons.html`.
- **Depends on:** —
- **Autonomy note:** The drawing is the builder's first proposal. Reusing an existing grid (`banknote` included) is not allowed (SD25).

### T14 — Icon approval — **hard stop, owner** (SD25, B-02 SD9)

- **Implements:** AC34 (the approved icon)
- **Expected output:** The build stops after T13 and gives the owner the absolute path of `.dev/pixel-icons.html`. On a redraw request, the builder edits only `wallet`, re-runs T13's checks, and stops again. On "go", § Icon approval records the date, each round and the redraws, committed as `docs(phase-b-05): T14 — icon approved`.
- **Verification:** § Icon approval holds a dated "go".
- **Depends on:** T13
- **Autonomy note:** **Stop. The owner's.** T20 depends on it. Silence is not approval.

### T15 — The landing choice, `/speler` and sign-up

- **Implements:** AC1, AC2, AC3 (page), AC4 (page), AC6 (page), AC7 (page), AC13 (`/speler` shows sign-up); SD20, PD13–PD15
- **Expected output:**
  - `useSession.ts` and `routes.tsx` per PD13.
  - `app/pages/LandingPage.tsx`: the theme's logo, then "Speler" (`<Link to="/speler">`) and "Crew" (`<Link to="/login">`). No shell, no nav.
  - `features/player/`:
    - `api.ts`: zod `Wallet{name, balance_cents, qr_token, short_code, created_at}`, plus `getWallet`, `signUp`, `nameCheck`;
    - `PlayerPage.tsx`: `GET /api/wallet` → a 401 `no_wallet` gives `SignupForm`, success a placeholder that T16 replaces with `WalletView`, a network failure PD15's text with a retry;
    - `SignupForm.tsx`: name (`maxLength={40}`) and code (prefilled from `?code=`), the PD14 check, submit, PD15's texts, the suggestions as buttons;
    - `index.ts` exports `PlayerPage`.
  - Tests:
    - `LandingPage.test.tsx`: both links (AC1);
    - `auth.test.tsx`:
      - anonymous `/` shows the landing and does not navigate to login;
      - an admin `/` still shows `HomePage`, display "Geen toegang" (AC1);
      - anonymous `/speler` makes no `/api/auth/me` call;
    - `SignupForm.test.tsx`:
      - `?code=abc` prefills; without, empty (AC2);
      - a 201 calls `onSignedUp` (AC3);
      - blur → one name check; 409 → three suggestion buttons, and a click submits with that name (AC4);
      - 403, 409 closed, 422 and 429 texts (AC6, AC7);
    - `PlayerPage.test.tsx`: 401 → sign-up (AC13).
- **Verification:** `pnpm -C web exec vitest run src/features/player src/features/auth src/app`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`.
- **Depends on:** T3 (`useSession.ts`), T6 (`GET /api/wallet` answers 401 `no_wallet`)
- **Autonomy note:**
  - Markup and CSS are the builder's. Reuse `Button`, `Field` and the login page's module CSS where it fits; a new shared component is not the builder's.
  - Making `/speler` call `/api/auth/me`, or letting a player 401 reach the login redirect, is not allowed.
  - If PD13's `lost()`-at-`/` breaks an existing `auth.test.tsx` expectation other than anonymous `/`, stop and ask.

### T16 — The player's wallet page with its QR code

- **Implements:** AC9, AC10, AC13 (page after delete), AC26 (the new page shows the old name), AC28 (the new code on refresh), AC29 (page), AC43 (`uqr` bundled); SD21, SD15
- **Expected output:**
  - `uqr` at T12's approved exact version in `web/package.json` dependencies, lockfile updated.
  - `QrCode.tsx`: `encode(token, { ecc: 'M', border: 2 })` → an `<svg role="img" aria-label="QR-code">` with one `<rect>` per dark module, `shape-rendering="crispEdges"`, black on white regardless of theme. It is memoised on the token.
  - `useVisiblePoll.ts`: calls `load` every 10 s while `document.visibilityState === 'visible'`, immediately on `visibilitychange` to visible and on `focus`, and stops on unmount.
  - `WalletView.tsx` shows:
    - the name;
    - `formatEuro(balance_cents)`;
    - `QrCode`;
    - the short code as served;
    - "Wallet verwijderen" behind `ConfirmDialog` "Je saldo van <€> vervalt." → `DELETE` → sign-up;
    - the hint "Bewaar deze pagina — je wallet staat op deze telefoon.";
    - nothing else.
  - A 401 from a poll → sign-up.
  - Tests:
    - `QrCode.test.tsx`: the rect count equals `encode(token).data` dark cells, and the token decodes back once T19 lands (T19 adds that round trip);
    - `WalletView.test.tsx`: exactly the listed texts (AC9); the delete confirm text, its cancel sending nothing, confirm → `DELETE` then sign-up (AC29);
    - `useVisiblePoll.test.ts` (fake timers): a 10 s refetch while visible, none while hidden, immediate on focus and on visible (AC10);
    - `PlayerPage.test.tsx`: a served name change and new code appear after a poll (AC26, AC28); a 401 mid-session → sign-up (AC13).
- **Verification:** `pnpm -C web exec vitest run src/features/player`; `pnpm -C web exec tsc -b`; `pnpm -C web build && uv run python scripts/check_built_assets.py web/dist`.
- **Depends on:** T15, T12 (the approved generator)
- **Autonomy note:**
  - Module size and layout are the builder's. The QR must be large enough to scan (≥ 200 CSS px).
  - `dangerouslySetInnerHTML` or `renderSVG` into the DOM is not allowed (`htmlSinks` lint).
  - Showing history, prices or a top-up button on this page is out of scope (SD21).

### T17 — The kassa page: code entry, lookup, top-up

- **Implements:** AC14 (page), AC15, AC16, AC17, AC18 (a retry resends the same key), AC20; SD10, SD22, PD15
- **Expected output:**
  - `lib/idempotencyKey.ts`: `newIdempotencyKey()`, 16 bytes from `crypto.getRandomValues` as 32 hex characters (matches `^[A-Za-z0-9_-]{8,128}$`). It works without a secure context.
  - `features/kassa/`:
    - `api.ts`: zod schemas for lookup, top-ups and the top-up result.
    - `KassaPage.tsx`: "Code typen" (a field and "Zoeken"); on a found wallet, the name and `formatEuro` balance, `TopUpPanel` and `TopupList`; 404 → "Onbekende wallet".
    - `TopUpPanel.tsx`:
      - starts at €10,00, with `[−]`/`[+]` in €5 steps between €10 and €100 (disabled at the ends);
      - "Opwaarderen" opens `ConfirmDialog` with "<€X> opwaarderen voor <naam>?", or, when `recent_topup` is set, "<naam> is om HH:mm al opgewaardeerd met <€Y>. Nog een keer <€X>?" with "Ja, nog een keer" (`formatHourMinute`);
      - one idempotency key per confirmed intent, reused on a network retry of that intent;
      - success re-looks-up the wallet.
    - `TopupList.tsx`: read-only list (amount, `formatDayMonthTime`, label, "teruggedraaid").
    - `index.ts`.
  - `routes.tsx` `PAGES` gains `['/kassa', <KassaPage/>]`.
  - `walletCode.provenance.test.ts`, in the `import.meta.glob` style of `quote.provenance.test.ts:48-100`: no `randomUUID` in `src/features/player`, `src/features/kassa`, `src/features/wallets` or `src/lib/idempotencyKey.ts`, with a walk-sees-a-file check and a planted hit (AC20).
  - Tests:
    - `idempotencyKey.test.ts`: the pattern, distinct values, works with `crypto.randomUUID` deleted from the global (AC20);
    - `KassaPage.test.tsx`:
      - typed code → lookup body `{short_code: <as typed>}`;
      - 404 → "Onbekende wallet" (AC14);
    - `TopUpPanel.test.tsx`:
      - the steps: 1000 → `[−]` disabled; nineteen `[+]` → 10000 and `[+]` disabled (AC16);
      - the plain confirm text and its POST body and header (AC15);
      - the 2-minute variant text and button (AC17);
      - cancel sends nothing;
      - a rejected fetch then "Opnieuw" sends the same `Idempotency-Key` (AC18).
- **Verification:** `pnpm -C web exec vitest run src/features/kassa src/lib src/walletCode.provenance.test.ts`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`.
- **Depends on:** T15 (`routes.tsx`), T7 (the routes)
- **Autonomy note:** Layout is the builder's. Any use of `crypto.randomUUID`, or fixing D-49 in `useBarController.ts`, is not (SD24). A top-up without the confirm is not allowed.

### T18 — The kassa page: reversal, move, new code

- **Implements:** AC21, AC22 (page), AC25 (page), AC26 (page), AC28 (page); SD11, SD12, SD14, PD15, PD17
- **Expected output:**
  - `TopupList` gains "Terugdraaien" on each non-reversed top-up, behind a confirm "<€X> van <datum> terugdraaien?". On confirm it POSTs with a fresh key, then re-looks-up. The 409 texts come from PD15.
  - `MoveDialog.tsx`, opened by "Saldo overzetten van…":
    - a search field → `GET /api/kassa/wallets?name=`, the open wallet filtered out;
    - each row shows name, `aangemaakt <d mmm>`, balance and last top-up;
    - choosing one confirms "<€B> en de naam '<oud>' van <oud> (aangemaakt <d mmm>) naar <nieuw> overzetten?" → POST → re-lookup;
    - `nothing_to_move` → PD15.
    - `d mmm` reuses `formatDayMonthTime`'s parts helper, or a new `formatDayMonth` in `lib/time.ts` with a CET and a CEST test (builder's choice, PD14 of B-04).
  - "Nieuwe code" behind "Nieuwe code maken voor <naam>? De oude QR-code en code werken dan niet meer." → POST → shows the new short code.
  - Tests:
    - `TopupList.test.tsx`: confirm, body and header, 409 texts, cancel (AC21, AC22);
    - `MoveDialog.test.tsx`: the open wallet excluded, the row fields (AC25), the confirm text exactly, the POST body (AC26);
    - `KassaPage.test.tsx`: new code shown (AC28).
- **Verification:** `pnpm -C web exec vitest run src/features/kassa src/lib/time.test.ts`; `pnpm -C web exec tsc -b`.
- **Depends on:** T17, T8
- **Autonomy note:** The new-code confirm text is the planner's (the spec gives none): **Confirm** at audit. Merging two wallets in any other way than a move is out of scope.

### T19 — The kassa camera

- **Implements:** AC14 (scan), AC42, AC43 (`jsqr` bundled, round trip); SD17, SD18
- **Expected output:**
  - `jsqr` at T12's approved exact version in `web/package.json`.
  - `camera.ts`: `canUseCamera() = window.isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function'`.
  - `decodeQr.ts`: `decode(image: {data, width, height}) -> string | null` over `jsQR(…, { inversionAttempts: 'dontInvert' })`, loaded with `await import('jsqr')` so only the kassa chunk carries it.
  - `Scanner.tsx`: "Camera" opens `getUserMedia({ video: { facingMode: 'environment' } })` into a `<video>`, samples a canvas about every 200 ms, and on a token calls `onToken` and stops every track. Permission denied → "Geen toegang tot de camera." and the code field stays.
  - `KassaPage` shows "Camera" only when `canUseCamera()`. A token goes to lookup as `{qr_token}`.
  - Tests:
    - `camera.test.ts`: false without a secure context, false without `mediaDevices`, true with both;
    - `KassaPage.test.tsx`: no "Camera" and no error text when not secure; both when secure (AC42);
    - `decodeQr.test.ts`: a token encoded with `uqr`, painted 8 px per module into an RGBA array, decodes back to the token; noise decodes to `null` (AC43).
- **Verification:** `pnpm -C web exec vitest run src/features/kassa`; `pnpm -C web build && uv run python scripts/check_built_assets.py web/dist` (exit 0); `pnpm -C web exec tsc -b`.
- **Depends on:** T18 (`KassaPage.tsx`), T16 (`package.json`, lockfile, `uqr` for the round trip), T12
- **Autonomy note:** Sampling rate and stream constraints are the builder's. A worker, wasm, or `BarcodeDetector` path is not: it would be a different dependency decision. If the round trip fails at every module size tried, stop.

### T20 — The Wallets section on `/settings`

- **Implements:** AC30 (page), AC33 (page), AC34; SD16, SD25, PD2, PD12, PD20
- **Expected output:**
  - `features/wallets/WalletsSection.tsx`:
    - **Aanmeldcode:** a field with "Opslaan" and "Wissen". When set, it shows the link `<origin>/speler?code=<code>` (PD20); when not, "Aanmelden is gesloten."
    - **Bewaartermijnen:** two whole-number fields, unfunded days and inactive months, with one "Opslaan". A 422 shows "Kies 1–365 dagen en 1–60 maanden."
    - **Totals:** "Openstaand saldo: <€>"; per borrel "<naam>: <€>", newest first, plus PD2's row.
    - **The list:** name, balance, "laatst actief <d mmm>". "Verwijderen" opens "Wallet '<naam>' verwijderen? Het saldo van <€> vervalt.", then `DELETE` and a reload. When empty, "Nog geen wallets". A fetch failure shows PD15's text.
  - `SettingsPage.tsx`: `{ id: 'wallets', label: 'Wallets', icon: 'wallet', content: <WalletsSection/> }` after `sleutels`.
  - `SettingsPage.test.tsx`:
    - "eleven" sections, Wallets last;
    - the nav, anchor `#wallets`, the narrow select;
    - one `aria-hidden` icon;
    - `/api/admin/wallets` and `/api/admin/wallet-settings` served in `openWithLiveRun`.
  - `WalletsSection.test.tsx`: every bullet above, including a clear sending `{signup_code: null, …}`, the delete confirm and cancel, the empty text, and the totals rendering (AC30, AC33, AC34).
- **Verification:** `pnpm -C web exec vitest run src/features/wallets src/app/pages/SettingsPage.test.tsx`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`.
- **Depends on:** T9, T14
- **Autonomy note:** Layout and CSS reuse (`settings.module.css`-style module in the feature) are the builder's. An `(i)` explanation, a new shared component, or showing names anywhere but this list is not.

### T21 — The Playwright flow, over the venue path

- **Implements:** the spec's Playwright and venue-path steps, covering AC1, AC3, AC4, AC15, AC17, AC20, AC21, AC26, AC34, AC40, AC41, AC42, AC43 end to end
- **Expected output:** `web/e2e/wallets.spec.ts`. It has its own `startServer('wallets', ['--empty'])` and serial mode (as `profiles.spec.ts`), and `test.use({ launchOptions: { args: ['--host-resolver-rules=MAP wallets.test 127.0.0.1'] } })`. Its `baseURL` is `http://wallets.test:<port>` (PD16). Every context blocks and records non-origin requests (as `offline.spec.ts:28-62`), and the spec asserts none at the end (AC43). The flow:
  1. Admin: create and go live with a borrel; set the sign-up code; create a "Kassa" key in Toegangssleutels and read it from the shown secret (AC40).
  2. Player A at `/`: the "Speler" button, then `/speler?code=…`, signs up as "Jan" (AC1, AC3).
  3. Player B tries "jan" and is offered "jan 2" (AC4).
  4. Kassa logs in, lands on `/kassa`, and sees no "Camera" (AC42, insecure origin). It types Jan's short code, tops up €15 with one `[+]` (AC15, AC20, AC41), sees the 2-minute text on a second top-up and confirms it (AC17), then reverses that second one (AC21).
  5. A's page shows `€ 15,00` within 10 s.
  6. B signs up as "Jan 2"; the kassa moves the balance from "Jan" (AC26).
  7. B's page shows "Jan" and `€ 15,00`, and A's page shows sign-up.
  8. Admin `/settings` Wallets shows `€ 15,00` outstanding and the borrel's `€ 15,00` (AC34). The home page shows "Kassa: 1" (AC40, under PD1 A).
  - A second, small test on the loopback `baseURL`: the kassa page shows "Camera" (secure context, AC42).
- **Verification:** `pnpm -C web exec playwright test e2e/wallets.spec.ts`; then `pnpm -C web exec playwright test` (the whole suite, as the gate runs it).
- **Depends on:** T16, T18, T19, T20, T3
- **Autonomy note:**
  - Selectors and helpers are the builder's.
  - If Chromium in CI treats `wallets.test` as secure, or the resolver flag is ignored, stop and ask: do not substitute `127.0.0.1` (that would not test AC20).
  - "Kassa: 1" depends on PD1. Under reading B, this assertion follows the amended plan.

### T22 — Documents, ADR addendum, backlog, and the exit gate

- **Implements:** AC48, AC49; spec In scope › Documents
- **Expected output:**
  - **ADR 0001:** an `## Addendum (B-05, 2026-10-25)` per SD26 (decision 13, §4 and §7's identity trigger), plus "*Amended by B-05*" marks beside decision 13 (`:29`), §4 (`:58`) and the §7 rows (`:73-74`). The original text is not rewritten.
  - **`data-model.md`:** rows for `wallet`, `wallet_entry`, `wallet_settings` after `asset`, in the row format at `:24-38`. The `auth_key` row (`:35`) names four roles.
  - **`frontend-architecture.md`:** the dependency budget (`:11-14`) names seven runtime dependencies (plus `uqr`, `jsqr`, with B-05 SD18); the feature list gains `player/`, `kassa/`, `wallets/`; the routes line (`:54-57`) gains `/speler`, `/kassa` and the landing at `/`.
  - **`phase-4-web-koers.md`:** an indented `> **Amended by B-05** …` note at SD25 (`:163-167`).
  - **`venue.md`:** the key line (`:19-20`) lists `kassa`; one bullet: wallets at the venue are the venue database's own, and every player starts at zero there (SD17).
  - **`backlog.md`:** B-05 → `built → docs/plans/phase-b-05-player-wallets.md (spec: docs/specs/phase-b-05-player-wallets.md)`.
  - **The builder writes the ADR addendum and both `docs/design/` edits, shows them to the owner, and waits for a go before committing them** (CLAUDE.md: `docs/design/` and product ADRs are the owner's).
- **Verification:**
  - `git diff --stat <T1's base>..HEAD -- exchange tests/engine app/runtime/orders.py app/db/orders.py app/api/orders.py web/src/features/bar app/jobs/export_xlsx.py app/db/exports.py` is empty (AC49);
  - `bash scripts/golden_linux.sh` green;
  - `engine-guardian` on the whole B-05 diff reports no maths change;
  - `./scripts/check.sh` green, output pasted.
- **Depends on:** T21, T11, T10
- **Autonomy note:**
  - Wording is the builder's, subject to the owner's go.
  - A golden diff or a guardian finding is a hard stop.
  - The manual exit check (spec Verification › Manual) is the owner's. The item is not done without it:
    - a poster QR on Render;
    - camera top-ups on an iPhone and an Android phone;
    - a delete, re-sign-up and move.

---

## Task graph

```
T1 ──► T2 ──► T3
T1 ──► T4
T4 + T2 ──► T5 ──► T6 ──► T7 ──► T8 ──► T9
T4 ──► T10
T8 ──► T11
T12 (owner)          T13 ──► T14 (owner)

T3 + T6 ──► T15
T15 + T12 ──► T16
T15 + T7 ──► T17
T17 + T8 ──► T18
T18 + T16 + T12 ──► T19
T9 + T14 ──► T20
T16 + T18 + T19 + T20 + T3 ──► T21
T21 + T11 + T10 ──► T22
```

| Group | Tasks | Files they write |
|---|---|---|
| 1 | T1, T12, T13 | **T1:** `0013_wallets.py`, `models.py`, `test_schema.py`, `test_migrations.py`, `test_guard_migrations_hook.py` · **T12:** this plan (§ Dependency approval) · **T13:** `pixelIcons.json`, `PixelIcon.test.tsx`, `scripts/pixel_icons.py`, `test_pixel_icons.py` |
| 2 | T2, T4, T14 | **T2:** `keys.py`, `deps.py`, `security.py`, `messages.py`, `news.py`, `state.py`, `cli/keys.py`, `test_security.py`, `test_auth.py`, `test_static.py`, matrix, `test_cli_keys.py`, `schema.d.ts` · **T4:** `app/db/wallets.py`, `wallet_codes.py`, `test_wallet_codes.py`, `test_wallets_repo.py` · **T14:** `pixelIcons.json` (redraws), this plan (§ Icon approval) |
| 3 | T3, T5, T10 | **T3:** `useSession.ts`, `auth.test.tsx`, `HomePage.*`, `KeysSection.*`, `NavMenu.*`, `schemas.ts`, `e2e/fixtures.ts`, `e2e/auth.spec.ts` · **T5:** `runtime/wallets.py`, `api/wallet.py`, `config.py`, `.env.example`, `main.py`, `test_config.py`, `test_route_authorization.py`, `test_static.py`, `test_wallet_signup.py`, `schema.d.ts` · **T10:** `wallet_cleanup.py`, `boot.py`, `test_wallet_cleanup.py` |
| 4 | T6 | `deps.py`, `api/wallet.py`, `runtime/wallets.py`, `test_route_authorization.py`, matrix, `test_standby.py`, `test_wallet_player.py`, `schema.d.ts` |
| 5 | T7, T15 | **T7:** `api/kassa.py`, `runtime/wallets.py`, `main.py`, matrix, `test_draining.py`, `test_kassa_topup.py`, `schema.d.ts` · **T15:** `useSession.ts`, `routes.tsx`, `LandingPage.*`, `features/player/*`, `auth.test.tsx` |
| 6 | T8, T16, T17 | **T8:** `api/kassa.py`, `runtime/wallets.py`, matrix, `test_draining.py`, `test_kassa_corrections.py`, `schema.d.ts` · **T16:** `features/player/*` (new files plus `PlayerPage.*`), `package.json`, lockfile · **T17:** `lib/idempotencyKey.*`, `features/kassa/*`, `routes.tsx`, `walletCode.provenance.test.ts` |
| 7 | T9, T11, T18 | **T9:** `app/db/wallets.py`, `wallets_admin.py`, `runtime/wallets.py`, `main.py`, matrix, `test_draining.py`, `test_wallets_admin.py`, `test_export_workbook.py`, `schema.d.ts` · **T11:** two new test files · **T18:** `features/kassa/*`, `lib/time.*` |
| 8 | T19, T20 | **T19:** `features/kassa/*`, `package.json`, lockfile · **T20:** `features/wallets/*`, `SettingsPage.*` |
| 9 | T21 | `web/e2e/wallets.spec.ts` |
| 10 | T22 | the documents |

No file is written by two tasks in one group:
- T2 and T5 both write `test_static.py` and the matrix, so T5 depends on T2.
- T5 → T6 → T7 → T8 → T9 is a chain because they share `runtime/wallets.py`, the matrix, `test_draining.py`, `main.py` and the generated schema.
- T16 and T19 share `package.json`, and T17, T18 and T19 share `features/kassa/`.
- T2 writes `state.py` under PD1 reading A only.

### Coverage

| AC | Task(s) | AC | Task(s) | AC | Task(s) |
|---|---|---|---|---|---|
| AC1 | T15, T21 | AC18 | T7, T17 | AC35 | T9 |
| AC2 | T15 | AC19 | T5, T7 | AC36 | T2, T3 |
| AC3 | T5, T15, T21 | AC20 | T17, T21 | AC37 | T2, T7, T8, T9 |
| AC4 | T4, T5, T15, T21 | AC21 | T8, T18, T21 | AC38 | T6 |
| AC5 | T4, T5 | AC22 | T8, T18 | AC39 | T5, T6 |
| AC6 | T5, T15 | AC23 | T8, T11 | AC40 | T2, T3, T21 |
| AC7 | T5, T15 | AC24 | T1, T8 | AC41 | T5 (cookie flags), T21 |
| AC8 | T5 | AC25 | T8, T18 | AC42 | T19, T21 |
| AC9 | T16 | AC26 | T8, T16, T18, T21 | AC43 | T12, T16, T19, T21 |
| AC10 | T16 | AC27 | T8 | AC44 | T5–T10 |
| AC11 | T5, T6 | AC28 | T8, T16, T18 | AC45 | T1, T11 |
| AC12 | T4, T6 | AC29 | T4, T6, T16 | AC46 | T8, T11 |
| AC13 | T6, T15, T16 | AC30 | T9, T20 | AC47 | T1, T4 |
| AC14 | T4, T7, T17, T19 | AC31 | T10 | AC48 | T22 |
| AC15 | T7, T17, T21 | AC32 | T4, T9 | AC49 | T22 |
| AC16 | T7, T17 | AC33 | T1, T9, T20 | | |
| AC17 | T7, T17, T21 | AC34 | T9, T13, T14, T20, T21 | | |

Every task maps to at least one AC: T12 serves AC43, T13 and T14 serve AC34, and T22 serves AC48, AC49 and the spec's Documents scope.

---

## New dependencies (SD18; approval is T12, a hard stop)

Evidence gathered 2026-10-25 from the npm registry (`registry.npmjs.org`, `api.npmjs.org/downloads`).

| Role | Proposed | Licence | Latest | Released | Runtime deps | Unpacked | Weekly downloads | Why |
|---|---|---|---|---|---|---|---|---|
| Generator | **`uqr`** (unjs) | MIT | 0.1.3 | 2026-04-03 | none | 79 kB | ~4.1 M | Zero-dependency ESM, tree-shakable. `encode()` returns a boolean matrix, so the page draws SVG rects itself (no HTML sink). Maintained by the unjs org. |
| Decoder | **`jsqr`** | Apache-2.0 | 1.4.0 | 2021-04-24 | none | 280 kB | ~2.6 M | Pure JS: no worker, no wasm, no network. It takes RGBA pixels, which is what a canvas gives. Stable but **unmaintained since 2021**: the risk is in § Risks. |

Considered and not proposed:
- **`qrcode`** (MIT, 1.5.4, 2024-08): depends on `pngjs`, `yargs` and `dijkstrajs`, and is Node-oriented.
- **`lean-qr`** (MIT, 2.7.4, 2026-09): a good generator alternative, but ~53 k weekly downloads.
- **`qrcode-generator`** (MIT, 556 kB).
- **`barcode-detector`** (MIT, 3.2.3, 2026-10, wraps `zxing-wasm`): actively maintained, but its `.wasm` is fetched from jsDelivr unless `prepareZXingModule` is given a `locateFile` override (its README). It is ~3.7 MB unpacked, so it breaks ADR 0006 by default.
- **`qr-scanner`** (MIT, 1.4.2, 2022-11): needs a worker file bundled.
- **`@zxing/browser`/`@zxing/library`** (MIT/Apache-2.0): 5.8 MB and 11.9 MB unpacked.
- **The native `BarcodeDetector`:** absent on iOS Safari, so it cannot be the only path.

The standard library will not do: the browser has no QR encoder, and no QR decoder on iOS.

## Dependency approval (SD18)

T12 fills this in. Neither package is added before it holds the owner's answer.

| Date | Owner's answer | Generator (exact version) | Decoder (exact version) |
|---|---|---|---|
| 2026-10-25 | Approve both (at the start of `/build b-05`; versions re-checked on npm that day) | `uqr` 0.1.3 (MIT, no runtime deps) | `jsqr` 1.4.0 (Apache-2.0, no runtime deps) |

## Icon approval (SD25, B-02 SD9)

T14 fills this in. No page shows the icon (T20) before it holds "go".

| Round | Date | Owner's answer | Grids redrawn |
|---|---|---|---|
| 1 | 2026-10-25 | Go (first proposal, T13 `fe4730f`) | none |

---

## Data changes

- **Migration `0013_wallets`:** creates `wallet`, `wallet_entry` and `wallet_settings` per PD4, plus their indexes, and widens `auth_key_role_check` to four roles. No backfill: the tables start empty, and the settings row appears on the first `PUT`.
- **Expand-only, `min_code_revision = "unchanged"`** (the spec's interface, Phase 8 SD3). The previous image ignores the new tables. One known gap: if a `kassa` key exists when rolling back to the B-04 image, that image's `GET /api/keys` fails validating `KeyInfo.role` (500), and the kassa key's sessions are refused. Every other route works. See § Risks.
- **The downgrade** restores the three-role CHECK (it fails loudly while a kassa key exists, as `0009`'s does) and drops the tables. The round trip is tested by `test_migrations.py`.
- **No column of an existing table changes.** The `wallet_entry.run_id` FK is `ON DELETE SET NULL`, so `delete_run` (`app/db/runs.py:646-656`) needs no change, and its timing bound (`test_delete_run.py:222-255`) is protected by the `run_id` index.
- **Personal data:** one column, `wallet.name`. It is NULL on every deleted row (CHECK `wallet_deleted_check`).
- **The OpenAPI schema grows** by 15 routes and the `kassa` role literal.

---

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| **PD1 / PD2:** the owner rules reading B | PD1 B adds a realtime task (hub filter plus a presence socket) and a `realtime-protocol.md` change before T17. The plan is amended and re-audited first. PD2 B removes one row from T9 and T20. |
| **A whole room signing up on Render shares one public IP** (association Wi-Fi NAT). At 5 per minute per IP (SD6), a poster moment at a borrel will hit 429s. | `SIGNUP_RATE_PER_MINUTE` is a setting (T5). PD14 avoids spending the budget on keystrokes. The owner may raise it for Render. Not reopened here (SD6 set the default). |
| **`jsqr` is unmaintained since 2021** | It is stable and pure, and has no network or worker surface. `decodeQr.ts` is the one call site, so a later swap is one file. The owner decides at T12. |
| **The rollback gap** (§ Data changes) | Before rolling back past B-05, revoke **and** delete any kassa key (or accept a 500 on the key list until roll-forward). One line in the rollback note of the T22 runbook edit if the owner wants it. Otherwise it is listed here only. |
| **The 401 hook and public pages:** an existing test may assume anonymous `/` redirects to `/login` | PD13 is the spec's SD20. T15 updates the affected `auth.test.tsx` cases and stops on anything else. |
| **The CHECK text in `models.py` is not compared** by `test_the_models_match_the_migrated_schema` (alembic does not compare CHECK text) | T1 pins every new CHECK and the role CHECK by SQL in `test_schema.py`. |
| **Chromium treats a mapped `.test` host as secure**, or the CI image strips the flag | T21's autonomy note: stop. Do not substitute loopback. The Vitest checks (T17, T19) still pin the code paths. |
| **The 2-minute warning and the clean-up rely on the app clock**, while DB `now()` stamps other tables (`auth_key`, `run.created_at`) | PD8: wallet times are app-clock only, and every comparison is within wallet tables. |
| **A top-up's FK insert takes `KEY SHARE` on the live run row** and briefly waits behind a live config write holding `FOR UPDATE` | Milliseconds; no deadlock, because wallet actions never lock a run `FOR UPDATE`. No wallet work happens inside the market lock. |
| **Under PD1 A, kassa sockets receive market frames** | The same frames the public board shows. The kassa page renders none of it. |
| **D5 (found while planning):** "Kopieer" on Toegangssleutels throws over plain HTTP at the venue (`navigator.clipboard` is undefined outside a secure context, `KeysSection.tsx:183`), the same class as D-49 | Not fixed here. A candidate for the defect register: the owner files it (this plan edits no other file). T21 reads the kassa key from the shown text, not the clipboard. |
| **D6 (found while planning):** the mobile "Sectie" select snaps back to the first section (`MobileSectionNav.tsx:26`) | Existing behaviour; a defect-register candidate. A twelfth section makes it slightly more visible. |
| **`docs/design/frontend-architecture.md` is already stale** (no `keys/`, `analytics/`; names a "ws transport" and `useElementSize` that do not exist) | T22 adds B-05's facts only. The rest is out of scope. |
| **The spec's §Verification says "the migration up from `0012`"** | Matches: the head is `0012` (B-04). |

**Uncertain, for the audit and the owner:**
- **PD1 (owner):** how the kassa is counted without a market feed. I recommend reading A, but it bends AC36's wording.
- **PD2 (owner):** the "Zonder borrel" row.
- **PD16:** the venue path is simulated with a mapped hostname, not a LAN address. I believe Chromium's secure-context rule makes this equivalent. T21 fails loudly if not.
- **PD8:** wallet timestamps from the app clock rather than `now()`. This differs from most tables, but matches `run.ended_at` and SD15's wording.
- **PD7, PD12, PD15, PD20, and T18's new-code text:** wordings and bounds the spec does not fix.
- **Unverified:** whether `jsqr` decodes reliably from a phone camera in a dim borrel room. Only the owner's manual check on an iPhone and an Android phone (spec § Manual) settles it. The Vitest round trip proves only the wiring.
- **Unverified:** that `require_wallet`'s 401 can carry a `Set-Cookie` deletion through `handle_app_error` (`AppError.headers` exists, `errors.py:48,72`, so I expect yes).

---

## Out of scope for this plan

As the spec, plus:
- Fixing D-49 (`useBarController.ts:76`), D5 (clipboard over HTTP) or D6 (the section select). This plan only reports D5 and D6.
- Drawing the poster QR in the app (PD20 shows the link only).
- An explanation `(i)` for the Wallets section.
- The stale parts of `frontend-architecture.md` and the missing `schema_compat` row in `data-model.md`.
- `ALL_ROLES`'s other inline role checks beyond what a kassa test proves (T2's note).
- Any change to the export, the order path, the bar page or `exchange/`.

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

Audit notes (2026-10-25):
- PD1 ruled reading A: a kassa session keeps `/ws` and `GET /api/state`; AC36 is read as every
  non-wallet route other than the market feed and the session's own routes.
- PD2 ruled reading A: a "Zonder borrel" row, shown only when its net sum is non-zero.
- PD7, PD8, PD12, PD14, PD15, PD16, PD20 and T18's new-code confirm text confirmed as written.
- Accepted as written: the thin AC24 (T8's 404 is the real guard), AC41 (the venue covered by
  T21 only) and AC44 (standby pinned on three routes) mappings; the size of T2, T3, T5, T9 and
  T17; T8's T8b split left to the builder.

Audited by: MartijnBoot (owner)  Date: 2026-10-25

---

## Review changes (after the audit)

Approved by the owner at `/review b-05` (2026-10-25). None changes an AC; R3 departs from PD10.

- **C1** (`TopUpPanel.tsx`): after a network failure "Opwaarderen" is off until "Opnieuw" has an
  answer. A fresh key under the 2-minute warning from before a lost booking would book it twice.
- **R1** (`app/core/logging.py`): uvicorn's access lines carry the path without its query, so
  `?name=` on the kassa search and `?code=` on the poster link never reach a log (SD5, SD15).
- **R2** (`TopUpPanel.tsx`, `KassaPage.tsx`): the kassa looks the wallet up again before the
  top-up confirm, so SD10's "by any key" holds across kassa phones and an old top-up no longer
  warns; a lookup answering after a later one is dropped.
- **R3** (`app/db/wallets.py`, `app/runtime/wallet_cleanup.py`): the clean-up's closing entries
  carry no run. With the live run, its one transaction key-share locked the run's row, and a
  config write under the state lock (`FOR UPDATE` on that row) waited for the whole sweep. A
  closing entry counts towards no borrel's total, so no total changes. Player, admin and move
  deletes keep PD10.
- **R3**'s `data-model.md` wording was approved by the owner at `/review b-05` (2026-10-25).
