# Spec: B-13 — An organiser role

Status: Approved · Depends on: B-12 (the settings screens and their addresses), Phase 3 (SD1 the
authorization matrix, SD4 the route audit, SD5/SD6 keys and roles), Phase 6 (SD33 the role summary,
D-44), B-05 (SD7 the `kassa` role, whose migration is the pattern), B-06 (SD9 the refund rule),
B-08 (SD1 the key format) · Fixes: no open defect (D-44 stays fixed: AC12) · Amends: Phase 6 SD33
(the role summary), `docs/design/data-model.md:35` (the role list), `docs/design/frontend-architecture.md`
(the role gating paragraph) · Backlog: [B-13](../backlog.md)

Line references are to `main` at `f1f4c46`.

## Problem

Kassa runs the bank, bar handles the bar. Whoever sets up the game has no role of their own.

- **Setting up a night needs the admin key.** Every route that makes a run, edits drinks, prices,
  looks, profiles or wallet settings is `require_role("admin")`
  (`app/api/runs.py:78-135`, `config.py:60-102`, `drinks.py:46-83`, `profiles.py:56-86`,
  `theme.py:124-233`, `wallets_admin.py:41`). The admin key also opens the engine's settings, the
  system actions and key creation (`keys.py:73-106`, `admin.py:44`).
- **Kassa cannot reach the wallet settings.** They are admin-only (`wallets_admin.py:41`) and
  sit on `/settings/wallets`, which only `admin` may open (`app/api/security.py:125-140`).
- **One endpoint saves both kinds of setting.** `PATCH /api/runs/{id}/config`
  (`app/api/config.py:65-82`) takes the Spelopzet and Betalen fields and the engine's alike
  (`app/runtime/config_patch.py:87-131`). A role check on the route cannot separate them.
- **Roles are a closed list in four places.** `Role` and `ROLES` (`app/db/keys.py:21-22`), the
  `auth_key_role_check` constraint (`db/migrations/versions/0013_wallets.py:53-55`), `ALL_ROLES`
  and `MARKET_ROLES` (`app/api/deps.py:38-42`) and the client's enums
  (`web/src/features/auth/useSession.ts:33`, `features/keys/KeysSection.tsx:28`,
  `features/home/HomePage.tsx:46`, `features/exchange/model/schemas.ts:20`).

## Decisions

Q1–Q11 were put to the owner one at a time at the interview on 2026-11-03, each with a
recommendation. The owner chose: Q1 A, Q2 B, Q3 A, Q4 A, Q5 A, Q6 C, Q7 C, Q8 A, Q9 A, Q10 A, Q11 B.
SD1–SD11 are those answers. SD12–SD16 were not asked: they are the spec writer's defaults, marked
so for the owner to object to at review. The planner must not reopen any of them.

**The role**

- **SD1 — A fifth role, `organiser` (Q10).** `Role` and `ROLES` gain `organiser`, as `kassa` was
  added in B-05. The English name is the stored value; the screen label is "Organisator". A new
  migration widens `auth_key_role_check` to the five roles; its `downgrade()` restores the four and
  fails loudly while an organiser key exists, as 0013's did for `kassa`. Existing keys and sessions
  keep working: no key changes role.
- **SD2 — Who makes the key (Q10).** Admin only, in both places: `app.cli.keys create --role
  organiser` and the Toegangssleutels page, whose role dropdown gains "Organisator". The organiser
  sees no keys page, creates and revokes no key. The "last admin key" rule is unchanged.

**What the organiser opens**

- **SD3 — The routes (Q7).** `ROLE_ROUTES["organiser"]` is `/`, `/koers`, `/bar`, `/manipulation`,
  `/settings`, `/settings/spel`, `/settings/wallets`, `/kassa`. Not `/settings/beheer`, not
  `/analytics`. Login lands on the first, `/`.
- **SD4 — The kassa key on settings (Q6).** `ROLE_ROUTES["kassa"]` becomes `/kassa`,
  `/settings`, `/settings/wallets`; the first is still `/kassa`. Of Mensen en wallets, kassa gets
  the wallet pieces (Aanmeldcode, "QR-code op het scherm", Bewaartermijnen, Totalen, Alle wallets,
  deleting a wallet) and **not Betalen**: "Wallet verplicht" and "Rood staan tot" are the
  organiser's and admin's. A kassa session therefore sees Mensen en wallets with one section
  hidden, and the landing shows one tile.

**What the organiser may call**

- **SD5 — Setup (Q1, Q3, Q4).** The organiser joins the admin on: create a draft, go live, close
  (`POST /api/runs`, `…/go-live`, `…/close`); `GET /api/runs/current`; `GET …/config`; add, change
  and delete drinks, including the a/d/s0/c table and the bounds (`…/drinks`); the theme and
  images (`PUT /api/theme`, `POST`/`DELETE /api/theme/images/{slot}`). Deleting a run stays admin.
- **SD6 — Profielen (Q2).** The organiser may list (`GET /api/profiles`) and load
  (`POST /api/runs/{id}/profile`) a profile, not save (`POST /api/profiles`) or delete one. Loading
  overwrites the 22 engine settings of the draft: this is the one way the organiser changes engine
  values, by design.
- **SD7 — `PATCH /config` is cut by field (Q5).** For an organiser the body may hold only `name`,
  `wallet_required`, `credit_limit_cents` and `params.step_quant`. Any other field, including any other `params` key, is 403 `forbidden` naming
  the field, and **nothing is written**, even if the allowed fields in the same body are valid. The
  check runs before the body reaches the run. Admin is unchanged; bar, display and kassa stay 403
  on the whole route. The allowlist is one data table in the API layer, listed in the authorization
  matrix test.
- **SD8 — Wallets and the cash desk (Q6, Q8).** `GET /api/admin/wallets`, `DELETE
  /api/admin/wallets/{id}` and `GET`/`PUT /api/admin/wallet-settings` are open to `organiser`,
  `kassa` and `admin`. Every `/api/kassa/*` route is open to `organiser`, `kassa` and `admin`: the
  organiser has the full cash desk, so top-ups, reversals, moves and new codes. An organiser key is
  a money key, like kassa.
- **SD9 — The bar (Q7).** Every route open to `bar` and `admin` also opens to `organiser`: orders,
  news (`POST`/`DELETE`), market jumps and events, the earnings series of the live run, wallet
  look-up and recent payments. `GET /api/news` and the market feed are open to it (`MARKET_ROLES`,
  `ALL_ROLES`). On `/manipulation` the organiser sees what bar sees, **without Idle**
  (`canEditIdle` stays `role === 'admin'`, `web/src/app/routes.tsx:57`).
- **SD10 — Refunds (Q11).** `POST /api/payments/{id}/refund` opens to `organiser`. The bar's own
  limit (its own payments, within 10 minutes, `app/runtime/wallets.py:252`) applies to the `bar`
  role only, so the organiser refunds a payment of any age, as kassa and admin do.
- **SD11 — The reads (Q9).** The organiser also reads `GET /api/admin/connections` (the home
  page's panel) and `GET /api/analytics/runs` (Borrel's list of past runs), and nothing else under
  analytics: run detail, compare, price curve, exports and deleting a run stay admin.

**Defaults, not asked**

- **SD12 — Still admin only.** Beheer's calls (Globale instellingen and the demand switches
  through `PATCH /config`, anchor-s0, `POST /api/admin/shutdown`), `POST`/`DELETE /api/profiles`,
  the keys routes, delete-run and the analytics and export routes. The earnings series of another
  run (`earnings.py:61`) stays admin: the `bar` page does not need it.
- **SD13 — One role list, one place.** The role lists on the routes name `organiser` where SD5–SD11
  say so; `ROLE_ROUTES` stays the one source of the client's `allowed_routes` (Phase 3 SD4). The
  client adds `organiser` to its four role enums and shows "Organisator" in Toegangssleutels and in
  the home page's connected-clients panel.
- **SD14 — The landing's status line.** The status line of `/settings` (B-12 SD10) reads
  `GET /api/runs/current`, which kassa may not call. It is shown to a session whose
  `allowed_routes` contains `/settings/spel`; for kassa there is no status line and nothing says
  "onbekend".
- **SD15 — Sessions and revocation.** A session carries its role as before. Revoking an organiser
  key closes its sockets and refuses its next request like any key. `app.cli.keys list` and the
  Toegangssleutels list show the role.
- **SD16 — Rollback.** Whether `min_code_revision` rises for the new migration is the planner's
  call: an image before it does not know the `organiser` role and cannot read such a row.

## In scope

- `app/db/keys.py`, a new migration, `app/api/deps.py`, `app/api/security.py`
  (`ROLE_ROUTES`), the role lists on the routes named in SD5–SD11, the `PATCH /config` field check
  (SD7) and `app.cli.keys --role`.
- The client's role enums, Toegangssleutels' dropdown and label, the home page's roles list.
- Tests: the authorization matrix (a row per route and role), the route audit, `PATCH /config`'s
  allowlist, the key CLI and `POST /api/keys`, the migration, vitest for the enums and labels, and
  an e2e for an organiser session.
- The docs named under "Amends".

## Out of scope

- Usernames or passwords; per-key permissions finer than the five roles.
- The bar role gaining any config right (D-44), or a change to what bar and display do today.
- A new setting, a changed setting or a changed range; the pricing engine (`exchange/`), the
  golden fixtures and anything that feeds them.
- New endpoints. The organiser is added to existing role lists; the only new server logic is SD7's
  field check.
- An organiser who can make or revoke keys, delete a run, export, or open `/analytics`.
- Renaming existing roles, or moving a key between roles.
- A new dependency.

## Acceptance criteria

**The role and its keys — SD1, SD2, SD15**

- **AC1.** When `app.cli.keys create --role organiser --label <l>` runs, the system shall store an
  `organiser` key and print it once in the usual form; `list` shall show its role.
- **AC2.** When an admin posts `POST /api/keys {role: "organiser", label}`, the system shall create
  it; when an organiser, bar, kassa or display session calls any `/api/keys` route, the system shall
  return 403.
- **AC3.** When the migration is applied to a database with keys of the four old roles, every key
  shall still log in with the same role; when `downgrade()` runs while an organiser key exists, it
  shall fail and change nothing.
- **AC4.** When an organiser key is revoked, its open sockets shall close and its next request shall
  be 401, as for any key.

**Addresses — SD3, SD4**

- **AC5.** When an organiser key logs in, `allowed_routes` shall be exactly `/`, `/koers`, `/bar`,
  `/manipulation`, `/settings`, `/settings/spel`, `/settings/wallets`, `/kassa`, in that order, and
  the page shown is `/`. When a kassa key logs in, it shall be exactly `/kassa`, `/settings`,
  `/settings/wallets`. For `admin`, `bar` and `display` it shall be exactly what it was.
- **AC6.** When an organiser session opens `/settings/beheer` or `/analytics`, or a kassa session
  opens `/settings/spel`, `/settings/beheer` or `/analytics`, the page shall show "Geen toegang"
  and the address shall not change. A reload of an address the role does not hold shall still
  serve `index.html` and be refused by the client, as for B-12's addresses.
- **AC7.** When an organiser opens `/settings`, the landing shall show the tiles Spelopzet and
  Mensen en wallets and no Beheer tile; when a kassa session opens it, one tile, Mensen en wallets,
  and no status line (SD14).
- **AC8.** When a kassa session opens Mensen en wallets, it shall show the Wallets section and not
  Betalen; the organiser and admin shall see both.

**Setup — SD5, SD6, SD11**

- **AC9.** When an organiser session calls the routes of SD5, SD11 and the profile list and load,
  the system shall answer as it does for admin, with the same bodies and errors; when it calls
  `DELETE /api/runs/{id}`, `POST /api/profiles`, `DELETE /api/profiles/{id}`,
  `POST /api/runs/{id}/anchor-s0`, `POST /api/admin/shutdown`, or an analytics route other than
  `GET /api/analytics/runs`, or an export route, the system shall return 403.
- **AC10.** When an organiser closes a live run with the run's name, the run shall close as for
  admin; closing with the wrong name shall fail as for admin.

**The field check — SD7**

- **AC11.** When an organiser's `PATCH /config` body holds only `name`, `wallet_required`,
  `credit_limit_cents` and `params.step_quant`, the system shall apply it as for admin. When it
  holds any other field, including any other `params` key and `candle_interval_s`, the system
  shall return 403 `forbidden` naming the field and write nothing, even when the allowed fields
  in the same body are valid, on a draft and on the live run, and shall send no `config` message.
  A bar, kassa or display session shall still get 403 on the whole route.
- **AC12.** *(D-44)* When a bar session calls any config, drinks, anchor-s0, runs, theme, keys or
  connections route, the system shall return 403; when it opens `/manipulation`, it shall see no
  Idle section. The same holds for an organiser's Idle: the section shall not be shown, and `PATCH
  /config` with `idle_targets` or `idle_rise_targets` shall be 403 (AC11).

**Wallets and the cash desk — SD4, SD8, SD10**

- **AC13.** When an organiser or kassa session calls `GET /api/admin/wallets`, `DELETE
  /api/admin/wallets/{id}` or `GET`/`PUT /api/admin/wallet-settings`, the system shall answer as
  for admin. A bar or display session shall still get 403.
- **AC14.** When an organiser session calls any `/api/kassa/*` route, the system shall answer as
  for kassa; an entry it writes shall carry the organiser key's label as its actor.
- **AC15.** When an organiser refunds a payment of another key's, or older than 10 minutes, the
  system shall refund it; a bar key shall still be refused with `refund_not_allowed`.
- **AC16.** When a kassa session calls `PATCH /config`, the system shall return 403 on the whole
  route.

**The bar and the market — SD9, SD12**

- **AC17.** When an organiser session calls the routes open to `bar`, the system shall answer as
  for bar; `GET /api/earnings/series` for a run other than the live one shall be 403.
- **AC18.** When an organiser session connects to `/ws`, it shall receive the same messages as a
  bar session; the hello shall carry `role: "organiser"`.
- **AC19.** When an organiser opens `/manipulation`, it shall show the news, jump and market events
  sections and no Idle section.

**Client — SD13**

- **AC20.** The authorization matrix shall list every route and role with a row, the route audit
  (`tests/meta/test_route_authorization.py`) shall find the role dependency on each route, and
  the matrix's completeness check shall fail when a route has no row.
- **AC21.** When Toegangssleutels' form is open, the role dropdown shall offer "Organisator", and
  a created organiser key shall show "Organisator" in the list; the home page's connected clients
  shall count organiser sessions under "Organisator".

**Boundaries**

- **AC22.** The diff shall touch nothing under `exchange/` or `tests/engine/golden/fixtures/`,
  shall add no dependency, and shall add no endpoint. The generated API types shall change only
  where a `Role` value is listed.
- **AC23.** `docs/design/data-model.md:35`, `docs/design/frontend-architecture.md`'s role paragraph
  and Phase 6 SD33 shall carry the new role. No ADR names the roles (ADR 0007 speaks of the
  `require_role()` dependency only), so none is amended.

## Verification

- **Python (pytest):** `tests/unit/test_security.py` (the five role lists, AC5);
  `tests/api/test_authorization_matrix.py` with a row per route (AC9, AC13, AC14, AC17, AC20);
  `tests/api/test_config.py` for the allowlist: each allowed field, each refused field, a mixed
  body that writes nothing, a live run that sends no message, kassa and bar 403 (AC11, AC12,
  AC16); `tests/api/test_keys.py` and the CLI test (AC1, AC2); a migration test as for 0013
  (AC3); `tests/api/test_payments_refund.py` for the organiser against the bar (AC15);
  `tests/api/test_ws.py` for the organiser's socket and revocation (AC4, AC18);
  `tests/api/test_static.py` for the reload of the addresses (AC6).
- **Web (vitest):** the role enums and labels (AC21); the landing's tiles and status line per role
  (AC7); Mensen en wallets without Betalen for kassa (AC8); `/manipulation` without Idle (AC19);
  `RequireRole` per role (AC6).
- **e2e (Playwright):**
  1. As admin, create an organiser key on Toegangssleutels, copy it, log out.
  2. Log in as the organiser: land on `/`; open Spelopzet, change a drink's bound and Prijsstap;
     open Mensen en wallets, set "Rood staan tot"; open `/kassa` and top up a wallet.
  3. As the organiser, open `/settings/beheer`: "Geen toegang". Post a `PATCH /config` with `eta`
     from the page's session: 403, and Drukdrempel unchanged for the admin.
  4. Close the live run with its name.
  5. Log in as a kassa key: `/settings/wallets` shows Wallets and no Betalen; `/settings/spel`
     is "Geen toegang".
- **The gate:** `./scripts/check.sh`, 13/13, output pasted. `git diff --stat main` shows nothing
  under `exchange/`, so `golden_linux.sh` and `engine-guardian` are not required (AC22).
- **Manual exit check (the owner's):** on a phone, log in with an organiser key at a mock set-up,
  change prices and wallet settings, then try Beheer and the keys page and see them refused.

## Exit condition

The host of an event can set up a night, run its bar and cash desk and close it with an organiser
key, while the server, not the menu, refuses every engine setting, system action and key change.
