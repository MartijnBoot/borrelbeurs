# Plan: B-13 — An organiser role

Spec: [docs/specs/phase-b-13-organiser-role.md](../specs/phase-b-13-organiser-role.md) (`Status: Approved`) · Status: **Owner-confirmed 2026-11-03 (OQ1 = B, every Confirm row); audit PASS 2026-11-03**
Design: `docs/design/data-model.md:35` and `docs/design/frontend-architecture.md:64-71` are amended (the spec's "Amends", approved at the interview). T9 makes the change. Nothing else in `docs/design/` changes.
ADRs honoured:
- 0002 and 0012: nothing under `exchange/` is read or changed (AC22).
- 0004: one migration on the one engine.
- 0007: `require_role()` stays the one authorization dependency. SD7's field check runs *beside* it and does not replace it.
- 0011: the new migration declares `min_code_revision` (PD1).

No product ADR is reversed. **No new dependency.**
Backlog: [B-13](../backlog.md) · Fixes: no open defect (D-44 stays fixed, AC12) · Amends: Phase 6 SD33, `data-model.md:35`, `frontend-architecture.md`'s role paragraph (T9)

Line references are to `main` at `f1f4c46`.

---

## Approach

**The server change is mostly role lists. SD7's field check is the one new piece of logic.**
- **The role.** `organiser` is appended to `Role`/`ROLES` (`app/db/keys.py:21-22`), `ALL_ROLES` (`app/api/deps.py:38`) and the socket's `Role` (`app/realtime/messages.py:67`). The spec's "four places" misses that last one: without it, an organiser's `hello` fails its own model. A migration widens `auth_key_role_check`, written the way `0013_wallets.py:52-56, 163-164` widened it for `kassa`.
- **The routes.** Each route named in SD5–SD11 gains `"organiser"` in its `require_role(...)` call. Nothing else in those handlers changes. The two role-dependent branches already do what the spec wants without edits:
  - the earnings series of another run is `principal.role != "admin"` → 403 (`app/api/earnings.py:59-60`, SD12);
  - the refund limit is `role == "bar"` (`app/runtime/wallets.py:252`, SD10).
- **SD7, the field check.** One table, `ORGANISER_CONFIG_FIELDS`, and one dependency on `PATCH /config` in `app/api/config.py`. The dependency reads the request's JSON keys **before** FastAPI validates the body against `ConfigPatch`. So a refused field is 403 whatever its value, and nothing reaches `write_draft_config`/`write_live_config` (`config.py:76-82`). That means no write and no broadcast. For admin the dependency does nothing.
- **`ROLE_ROUTES`** (`app/api/security.py:125-140`) gains the organiser's tuple, and kassa's grows to three addresses. `/auth/me`, `SPA_ROUTES`, `RequireRole` and `NavMenu` already follow from that table (B-12 plan, Approach).

**The client change is enums, two labels and two visibility rules, composed in `app/pages/`.**
- **The four hand-written `z.enum`s gain `'organiser'`.** "Organisator" joins `KeysSection`'s `ROLES` (`KeysSection.tsx:43-48`) and the home panel's `ROLES` (`HomePage.tsx:48-53`).
- **Two things on the settings screens need the current run's config:**
  - the landing's status line;
  - Betalen.

  Both are shown only to a session whose `allowed_routes` holds `/settings/spel` (PD6). That is SD14's own rule, so kassa sees neither and makes no request it would be refused. Features stay sibling-isolated: the rule is applied where the screens are composed (`SettingsScreens.tsx`, `SettingsPage.tsx`), as `canEditIdle` is in `routes.tsx:54-59`.
- **`/manipulation` needs no code change.** `canEditIdle` is already `role === 'admin'` (`routes.tsx:57`), so an organiser sees bar's page. T6 adds a test that pins it.

Rejected:
- **Splitting `PATCH /config` into two endpoints.** The spec rules out new endpoints (AC22), and SD7 chose the field cut.
- **The field check inside the handler, after body validation.** An organiser's `{"params": {"eta": -1}}` would then be 422 naming `eta`. That is "any other field … is 403" broken by an ordering accident, and it tells the organiser the field's rules.
- **The field check in `app/runtime/config_patch.py`.** SD7 puts the table in the API layer, and the runtime knows no roles.
- **Growing `ROLE_ROUTES["organiser"]` task by task.** It would edit `test_security.py` and `test_auth.py` in every server task. T1 sets the final tuple; see the interim note there.
- **Hiding Betalen with `role === 'kassa'`.** That is a role name the client would have to keep in step with the server. The `/settings/spel` rule follows `ROLE_ROUTES`, the one source (SD13).

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. **Owner** rows are user-visible choices the spec leaves open; CLAUDE.md makes each one an owner stop.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | The migration and rollback (SD1, SD16) | `db/migrations/versions/0017_organiser_role.py`, revises `0016`.<br>• `upgrade()` drops and recreates `auth_key_role_check` as `role IN ('display', 'bar', 'admin', 'kassa', 'organiser')`.<br>• `downgrade()` restores the four. It fails loudly (`auth_key_role_check`) while any `organiser` row exists, revoked or not.<br>• **`min_code_revision = "unchanged"`**, with the reason in the docstring. | `0013` set the precedent for `kassa`. Raising the floor would make the B-12 image **refuse to boot** on this schema. With it unchanged, the B-12 image boots, and only rows with the new role misbehave there (R2). At a venue, a booting old image beats a refused one. |
| PD2 | Role order | Appended last everywhere: `("display", "bar", "admin", "kassa", "organiser")` in `ROLES`, `ALL_ROLES`, `MARKET_ROLES` (minus kassa), the socket `Role` and the four client enums. | Stored values; the CLI's `--role` choices keep their order; the generated types change by one literal (AC22). |
| PD3 | `ROLE_ROUTES` (SD3, SD4; AC5) | `"organiser": ("/", "/koers", "/bar", "/manipulation", "/settings", "/settings/spel", "/settings/wallets", "/kassa")`<br>`"kassa": ("/kassa", "/settings", "/settings/wallets")` | Verbatim from SD3 and SD4, in their order. |
| PD4 | SD7's mechanism (AC11, AC12, AC16) | In `app/api/config.py`:<br>• `ORGANISER_CONFIG_FIELDS: Final = frozenset({"name", "wallet_required", "credit_limit_cents", "params.step_quant"})`.<br>• A dependency on `PATCH /{run_id}/config` only, resolved **after** the role check and **before** body validation. For an organiser it reads `await request.json()`, then:<br>  – collects every top-level key not in the table;<br>  – when `params` is a JSON object, adds each `params.<key>` other than `params.step_quant`;<br>  – if any were collected, raises `Forbidden` (403 `forbidden`) whose message names the first in sorted order, with `extra={"fields": [<every refused field, dotted, sorted>]}`.<br>• An unknown key (`"foo"`) is refused like a known one.<br>• A body that is not an object, or a `params` that is not an object, names no field: it passes to `ConfigPatch`'s 422, as for admin.<br>• For admin, display, bar and kassa the dependency does nothing. The last three never get past `require_role`.<br>**Confirm** (unknown keys are 403 for an organiser; the `fields` list) | "Any other field … is 403 naming the field, and nothing is written" (SD7). FastAPI solves dependencies before it validates the body, so a refused field with a bad value is still 403. The `fields` list lets a client name all of them, as `faults` does for a 422. |
| PD5 | The authorization matrix (AC20; SD7 "listed in the matrix test") | `tests/api/test_authorization_matrix.py`:<br>• `ACTORS` and `ALL` gain `organiser` (T1);<br>• each later task widens the rows it opens, through named sets: `SETUP = {organiser, admin}`, `WRITERS = {bar, organiser, admin}`, `KASSA = {kassa, organiser, admin}`, `WALLET_ADMIN = {organiser, kassa, admin}`, `REFUNDERS` and `MARKET` with `organiser`;<br>• T3 writes SD7's four fields out as a literal and asserts it equals `app.api.config.ORGANISER_CONFIG_FIELDS`. | The table stays independent of the code, as its docstring requires (`:3-7`). Every task that opens a route edits it, so the server tasks form a chain (Task graph). |
| PD6 | What the settings screens show kassa (SD4, SD14; AC7, AC8) | One rule, `holdsSpel = allowed_routes.includes('/settings/spel')`, applied in `app/pages/`:<br>• `SettingsPage` renders its status line through a child component, mounted only when `holdsSpel`. `useCurrentRun()` (`SettingsPage.tsx:47`) moves into it, so kassa never calls `GET /api/runs/current`;<br>• `WalletsScreenPage` drops the `betalen` section unless `holdsSpel`. `SettingsLayout` already drops its nav for one section (B-12 PD8).<br>The landing's tile line for Mensen en wallets ("Betalen, aanmeldcode, …", `SettingsPage.tsx:23`) is unchanged. **Confirm** (the line still says "Betalen" to kassa) | SD14 names the rule. Betalen reads the run's config (`PaymentSection.tsx:22` → `useRunConfig`), which only a `/settings/spel` holder may read. |
| PD7 | The labels (SD13; AC21) | `KeysSection` `ROLES` gains `{ value: 'organiser', label: 'Organisator' }`, last. `HomePage` `ROLES` becomes Scherm, Bar, Kassa, **Organisator**, Beheer, and the panel reads e.g. "Scherm: 1, Bar: 1, Kassa: 2, Organisator: 0, Beheer: 0". | The stored order (PD2) for the dropdown. On the panel the organiser sits before Beheer, nearest its rights. |
| PD8 | `/manipulation` (SD9; AC12, AC19) | No code change. `canEditIdle` and `PriceJumpSection showBounds` stay `role === 'admin'` (`routes.tsx:57`, `ManipulationPage.tsx:28`). An organiser sees Nieuws, Market events, Price jump without bounds, and no Idle: what bar sees. | SD9: "what bar sees, without Idle". |
| PD9 | e2e (spec Verification steps 1–5) | A new `web/e2e/organiser.spec.ts` that starts its own server through `startServer('organiser', …)` (`serverProcess.ts`), as `keys.spec.ts:30-41` does. The organiser and kassa keys are minted on Toegangssleutels by the admin. A wallet for the top-up comes from the page flow `wallets.spec.ts` uses (sign-up code, `/speler`). | A self-contained server: closing the live run (step 4) must not disturb the shared one other specs use. |
| PD10 | Existing tests B-13 makes untrue | Each changes in the task that causes it:<br>• `test_security.py:28-46`, `test_auth.py:70-88` (T1 organiser; T4 kassa);<br>• `test_keys.py:292` and `test_config.py:683` parametrize lists (T1, T3);<br>• `test_schema.py:347-360` role list (T1);<br>• `test_guard_migrations_hook.py:159-166, 231-239`: the head becomes `0017_organiser_role.py` (T1, as its docstring says to);<br>• `HomePage.test.tsx:117` (T6);<br>• the matrix (PD5).<br>Any **other** test that fails for a B-13 reason is a stop-and-ask. | Found by grepping `kassa`, `ROLE_ROUTES`, `"0016` and `Beheer: 0`. |

### Owner question — answered 2026-11-03: **B** (T7 part (c) is built)

**OQ1 — Does an organiser see Profielen's "Opslaan als profiel" and "Verwijderen" (SD6)?** The organiser may list and load profiles, not save or delete them. The spec has the server refuse (AC9) but says nothing about the buttons. Today `ProfilesSection` shows both to anyone on Spelopzet (`ProfilesSection.tsx:171-192`). A refused save shows "Verbindingsfout. Probeer opnieuw." (`saveFailure`, `:56-64`), because a 403 falls through to `CONNECTION`. The two readings differ on screen:
- **A** — the buttons stay. An organiser who presses one is refused, and is told it was a connection fault.
- **B (recommended)** — `ProfilesSection` takes `canManage: boolean`, passed from `SpelopzetPage` as `role === 'admin'`, as `canEditIdle` is. Without it, the list and "Profiel laden" show, and the save form and every "Verwijderen" do not. This is T7's part (c).

B matches SD9's own choice for Idle (hide what the role may not do). A shows a false error message. If the audit answers A, T7 part (c) is dropped and nothing else changes.

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `app/db/keys.py` | Modify | SD1, PD2: `Role`, `ROLES` |
| `app/db/models.py` | Modify | `auth_key_role_check` on `AuthKey` (`:283`), in step with 0017 (added at audit) |
| `db/migrations/versions/0017_organiser_role.py` | Create | PD1 |
| `app/api/deps.py` | Modify | `ALL_ROLES` (T1), `MARKET_ROLES` (T5) |
| `app/api/security.py` | Modify | PD3: organiser (T1), kassa (T4) |
| `app/realtime/messages.py` | Modify | the socket `Role` (AC18) |
| `app/cli/keys.py` | Modify | the usage docstring (`:3`); choices follow `ROLES` |
| `web/src/api/generated/schema.d.ts` | Modify (generated) | `bash scripts/gen_api_types.sh`: one literal at `:1175, :1452, :1509` |
| `app/api/runs.py`, `app/api/drinks.py`, `app/api/theme.py`, `app/api/profiles.py`, `app/api/admin.py`, `app/api/analytics.py` | Modify | SD5, SD6, SD11 role lists (T2) |
| `app/api/config.py` | Modify | `GET` and profile load (T2); PD4 (T3) |
| `app/api/wallets_admin.py`, `app/api/kassa.py`, `app/api/payments.py` | Modify | SD8, SD10 role lists and docstrings (T4) |
| `app/api/bar.py`, `app/api/market.py`, `app/api/news.py`, `app/api/orders.py`, `app/api/earnings.py` | Modify | SD9 role lists (T5) |
| `tests/api/test_authorization_matrix.py` | Modify | PD5 (T1–T5) |
| `tests/unit/test_security.py`, `tests/api/test_auth.py` | Modify | AC5 (T1, T4) |
| `tests/integration/test_migrations.py`, `tests/integration/test_schema.py`, `tests/meta/test_guard_migrations_hook.py` | Modify | AC3, PD10 |
| `tests/integration/test_cli_keys.py`, `tests/api/test_keys.py` | Modify | AC1, AC2 |
| `tests/api/test_ws.py`, `tests/api/test_ws_revoke.py` | Modify | AC4, AC18 |
| `tests/api/test_runs.py`, `test_go_live.py`, `test_close.py`, `test_drinks.py`, `test_theme.py`, `test_profiles.py`, `test_connections.py`, `test_analytics.py` | Modify | AC9, AC10 (T2) |
| `tests/api/test_config.py` | Modify | AC11, AC12, AC16 (T3) |
| `tests/api/test_wallets_admin.py`, `test_kassa_topup.py`, `test_payments_refund.py` | Modify | AC13–AC15 (T4) |
| `tests/api/test_orders.py`, `test_news.py`, `test_market.py`, `test_bar_wallets.py`, `test_earnings_series.py` | Modify | AC17 (T5) |
| `web/src/features/auth/useSession.ts`, `web/src/features/exchange/model/schemas.ts` | Modify | the session and socket enums (T6) |
| `web/src/features/keys/KeysSection.tsx`, `.test.tsx` | Modify | PD7 (T6) |
| `web/src/features/home/HomePage.tsx`, `.test.tsx` | Modify | PD7 (T6) |
| `web/src/features/auth/auth.test.tsx` | Modify | AC6 `RequireRole` per role, AC19 `/manipulation` without Idle (T6) |
| `web/src/app/pages/SettingsPage.tsx`, `SettingsPage.test.tsx` | Modify | PD6 (T7) |
| `web/src/app/pages/SettingsScreens.tsx`, `SettingsScreens.test.tsx` | Modify | PD6; OQ1 = B (T7) |
| `web/src/features/settings/ProfilesSection.tsx`, `.test.tsx` | Modify | OQ1 = B (T7) |
| `web/e2e/organiser.spec.ts` | Create | PD9 (T8) |
| `docs/design/data-model.md`, `docs/design/frontend-architecture.md`, `docs/specs/phase-6-admin.md` | Modify | AC23 (T9) |
| `CLAUDE.md`, `docs/runbooks/venue.md`, `docs/runbooks/rollback.md` | Modify | T9, **Confirm**: the role list in the key command (`CLAUDE.md:37`, `venue.md:21`) and R2's rollback note |

---

## Tasks

### T1 — The role, its migration, its keys and its socket
- **Implements:** AC1, AC2, AC3, AC4, AC5 (organiser half), AC18, AC20 (the actor). SD1, SD2, SD3, SD15, SD16; PD1–PD3, PD5 (first part), PD10.
- **Expected output:**
  - **The role:**
    - `Role`/`ROLES` (`keys.py:21-22`), `ALL_ROLES` (`deps.py:38`) and `messages.Role` (`messages.py:67`) end in `"organiser"` (PD2);
    - `MARKET_ROLES` is unchanged here (T5).
  - **`app/db/models.py:283`**'s `auth_key_role_check` names the five roles, matching 0017 (added at audit: the model carries the same CHECK).
  - **`0017_organiser_role.py`** as PD1. Its docstring says why `min_code_revision` is unchanged, and what an older image does with an organiser row (R2).
  - **`ROLE_ROUTES["organiser"]`** as PD3. Kassa is unchanged here (T4).
  - **`app/cli/keys.py:3`** names five roles. `--role organiser` works through `choices=ROLES`. `POST /api/keys` accepts `organiser` through `Role` (`keys.py:53`), with no code change.
  - **`schema.d.ts`** regenerated: only the three role literals change (AC22).
  - **Tests:**
    - `test_security.py`: the table;
    - `test_auth.py`: an organiser's login answers PD3's list and the rest are as they were;
    - `test_cli_keys.py`: `create --role organiser` stores the role and prints the key in the grouped form; `list` shows `organiser`;
    - `test_keys.py`: admin `POST /api/keys {role: "organiser"}` is 201, and `test_other_roles_are_403` covers `kassa` and `organiser`;
    - `test_migrations.py`: an organiser row is accepted at head. With one present, `downgrade -1` fails naming `auth_key_role_check`. Once it is gone, the downgrade succeeds and `organiser` is refused. A key of each old role logs in after the upgrade with its role, written as `test_0013_admits_the_kassa_role…` (`:477-502`);
    - `test_schema.py:347-360`: five roles accepted, an unknown one refused;
    - `test_guard_migrations_hook.py`: the head is `0017_organiser_role.py`;
    - `test_ws.py`: an organiser socket's hello has `role: "organiser"` and it gets the snapshot a bar socket gets;
    - `test_ws_revoke.py`: revoking an organiser key closes its socket 4401 and its next request is 401;
    - the matrix: `organiser` in `ACTORS` and `ALL`. Every other row leaves it out, which is what the code does at this point.
  - **The interim state:** an organiser key, which nobody holds yet, is admitted to its addresses. Its pages' calls are 403 until T2–T5. The client does not accept the role until T6.
- **Verification:**
  - `uv run pytest tests/unit/test_security.py tests/meta/test_guard_migrations_hook.py`;
  - `uv run pytest tests/api/test_auth.py tests/api/test_keys.py tests/api/test_ws.py tests/api/test_ws_revoke.py tests/api/test_authorization_matrix.py tests/api/test_static.py` (`.env.local` sourced; `test_static.py` unchanged, it pins AC6's reload half for every address);
  - `uv run pytest tests/integration/test_migrations.py tests/integration/test_schema.py tests/integration/test_cli_keys.py` (a separate run: MEMORY, pytest api+integration split);
  - `bash scripts/gen_api_types.sh && git diff --stat web/src/api/generated/`.
- **Depends on:** —
- **Autonomy note:** The builder may lay out the tests and word the docstrings. Stop and ask in any of these cases:
  - the generated types change anywhere except the role literal;
  - `pnpm -C web build` fails on the widened literal (an exhaustive `Record` over the generated `Role` somewhere);
  - the migration-scaffolding or schema-compat meta tests want anything other than `"unchanged"`.

### T2 — Setting up a night: runs, drinks, theme, profile load and the reads
- **Implements:** AC9, AC10. SD5, SD6, SD11, SD12.
- **Expected output:**
  - **`require_role("organiser", "admin")` on these routes:**
    - `POST /api/runs`, `GET /api/runs/current`, `…/go-live`, `…/close` (`runs.py:78, 93, 106, 121`);
    - `GET …/config` and `POST …/profile` (`config.py:60, 102`);
    - the three drink routes (`drinks.py:46, 63, 83`);
    - the three theme routes (`theme.py:124, 213, 233`);
    - `GET /api/profiles` (`profiles.py:56`);
    - `GET /api/admin/connections` (`admin.py:64`);
    - `GET /api/analytics/runs` (`analytics.py:74`).
  - **Unchanged:** `DELETE /api/runs/{id}` (`runs.py:135`), `PATCH …/config`, anchor-s0, `POST`/`DELETE /api/profiles`, shutdown, every other analytics and export route.
  - **Tests:**
    - the matrix: these rows become `SETUP`;
    - in each route's own test file, one organiser case answering what admin's does, body included:
      - `test_runs.py` (create a draft; `current`);
      - `test_go_live.py`;
      - `test_close.py`: the right name closes, a wrong name fails with admin's code (AC10);
      - `test_drinks.py` (add, change bounds and a/d/s0/c, delete);
      - `test_theme.py` (`PUT`, an image upload);
      - `test_profiles.py` (list; load onto a draft; save and delete 403);
      - `test_connections.py`;
      - `test_analytics.py` (`runs` 200; one detail route and one export route 403).
- **Verification:** `uv run pytest tests/api/test_authorization_matrix.py tests/api/test_runs.py tests/api/test_go_live.py tests/api/test_close.py tests/api/test_drinks.py tests/api/test_theme.py tests/api/test_profiles.py tests/api/test_connections.py tests/api/test_analytics.py`.
- **Depends on:** T1 (the matrix, `Role`).
- **Autonomy note:** The builder may choose which existing test in each file to parametrize over `admin`/`organiser` rather than copying it. Stop and ask if any handler body has to change, or if a route not listed here would need the organiser.

### T3 — `PATCH /config` cut by field
- **Implements:** AC11, AC12 (the server half), AC16. SD7; PD4, PD5 (the literal).
- **Expected output:**
  - **The route.** `PATCH /{run_id}/config` is `require_role("organiser", "admin")` plus PD4's dependency, and `ORGANISER_CONFIG_FIELDS` sits beside it in `app/api/config.py`. Its module docstring names SD7.
  - **Tests in `test_config.py`:**
    - each allowed field alone, and all four together, applied for an organiser as for admin, on a draft;
    - each refused field is 403 `forbidden`, the message naming it and `fields` listing it. The refused fields tested:
      - one param of every group: `params.eta`, `params.bm_enabled`, `params.demand_enabled`, `params.idle_targets`, `params.idle_rise_targets`;
      - `candle_interval_s`;
      - an unknown key;
    - a refused field with an invalid value (`{"params": {"eta": -1}}`) is still 403, not 422;
    - a mixed body (`name` valid + `params.eta` valid) is 403 and the run's revision, name and params are unchanged;
    - on the live run, the same mixed body is 403 and **no `config` message** is sent. The builder may use `tests/api/test_ws_fixture.py`/`ws_fixture.py` or the integration `test_config_live.py` pattern;
    - `test_other_roles_are_403` covers `display`, `bar`, `kassa` on `GET` and `PATCH`;
    - admin's existing tests unchanged.
  - **The matrix:** the `PATCH` row is `SETUP`, and the literal equality test of PD5 is added.
- **Verification:** `uv run pytest tests/api/test_config.py tests/api/test_authorization_matrix.py`; if the live case goes to integration, `uv run pytest tests/integration/test_config_live.py`.
- **Depends on:** T2 (`app/api/config.py`, the matrix).
- **Autonomy note:** The builder may shape the dependency (a function or a class, how it shares the role check) provided the invalid-value test proves it runs before body validation. Stop and ask in either case:
  - FastAPI's order turns out to validate the body first;
  - satisfying PD4 would need a change to `ConfigPatch` or `config_patch.py`.

### T4 — Wallets and the cash desk, for the organiser and the kassa
- **Implements:** AC5 (kassa half), AC13, AC14, AC15. SD4 (server), SD8, SD10; PD3 (kassa).
- **Expected output:**
  - **`wallets_admin.py:41`'s `Admin`** becomes `require_role("organiser", "kassa", "admin")`, renamed to fit (e.g. `WalletAdmin`).
  - **`kassa.py:33`** is `("kassa", "organiser", "admin")` and **`payments.py:27`** is `("bar", "kassa", "organiser", "admin")`. Their docstrings (`kassa.py:3`, `payments.py:3, 10-11`) name the organiser.
  - **`ROLE_ROUTES["kassa"]`** as PD3.
  - **Tests:**
    - the matrix: the four wallet rows `WALLET_ADMIN`, the kassa rows `KASSA`, refund `REFUNDERS`;
    - `test_security.py` and `test_auth.py`: kassa's three addresses;
    - `test_wallets_admin.py`: kassa and organiser list wallets, read and write wallet settings, and delete a wallet as admin does; bar and display get 403;
    - `test_kassa_topup.py`: an organiser top-up is booked with the organiser key's label as `actor_label`;
    - `test_payments_refund.py`: an organiser refunds a bar key's payment older than 10 minutes, and a bar key on the same is still `refund_not_allowed`.
- **Verification:** `uv run pytest tests/unit/test_security.py`; `uv run pytest tests/api/test_auth.py tests/api/test_authorization_matrix.py tests/api/test_wallets_admin.py tests/api/test_kassa_topup.py tests/api/test_payments_refund.py`.
- **Depends on:** T3 (the matrix); T1 (`security.py`).
- **Autonomy note:** The builder may name the dependency alias and lay out the tests. Stop and ask if `actions.refund` or any wallet action needs a change beyond the role list.

### T5 — The bar and the market for the organiser
- **Implements:** AC17. SD9 (server), SD12 (the other run's series).
- **Expected output:**
  - **`("bar", "organiser", "admin")`** on `bar.py:25`, `market.py:57, 74`, `news.py:61, 90`, `orders.py:67`, `earnings.py:48`.
  - **`MARKET_ROLES`** (`deps.py:42`) gains `organiser`. Its comment says the organiser reads the market's routes, as bar does.
  - **Tests:**
    - the matrix: those rows `WRITERS`, `GET /api/news` `MARKET`;
    - `test_the_bar_reads_only_the_live_runs_series` (`matrix:208-223`) parametrized over `bar` and `organiser` (another run 403);
    - one organiser case each:
      - `test_orders.py`: an order is placed and booked with the organiser's label;
      - `test_news.py`: post and delete;
      - `test_market.py`: a jump;
      - `test_bar_wallets.py`: look-up shows name and balance only; recent payments are its own;
      - `test_earnings_series.py`: the live run's series.
- **Verification:** `uv run pytest tests/api/test_authorization_matrix.py tests/api/test_orders.py tests/api/test_news.py tests/api/test_market.py tests/api/test_bar_wallets.py tests/api/test_earnings_series.py`.
- **Depends on:** T4 (the matrix); T1 (`deps.py`).
- **Autonomy note:** The builder may choose which existing test to parametrize. Stop and ask if the bar's own rules (look-up fields, the 10-minute payments list) would need to differ for the organiser: SD9 says "as for bar".

### T6 — The client knows the role
- **Implements:** AC6 (`RequireRole` per role), AC12 (the client half), AC19, AC21. SD9 (client), SD13; PD7, PD8.
- **Expected output:**
  - **`'organiser'` in the four enums:**
    - `useSession.ts:33`;
    - `schemas.ts:20`;
    - `KeysSection.tsx:28`;
    - `HomePage.tsx:46`.
  - **The labels** as PD7.
  - **Tests:**
    - `KeysSection.test.tsx`: the dropdown offers "Organisator"; creating one posts `{"role":"organiser",…}`; a listed organiser key shows "Organisator";
    - `HomePage.test.tsx`: the panel counts organiser sessions, in PD7's text;
    - `auth.test.tsx` (`Role` type at `:13`, key map at `:38`):
      - an organiser lands on `/`;
      - an organiser on `/settings/beheer` or `/analytics` sees "Geen toegang" and the address stays;
      - a kassa session on `/settings/spel`, `/settings/beheer` or `/analytics` sees "Geen toegang";
      - an organiser on `/manipulation` sees Nieuws, Market events and Price jump, and no Idle section.
- **Verification:** `pnpm -C web vitest run src/features/keys src/features/home src/features/auth`; `pnpm -C web lint && pnpm -C web build`.
- **Depends on:** T1 (the server answers the role; the generated types).
- **Autonomy note:** The builder may decide where the `/manipulation` case lives (`auth.test.tsx` or a routes test). Stop and ask if any other client file switches on the role name.

### T7 — The settings screens per role
- **Implements:** AC7, AC8; SD4 (client), SD6 (client, OQ1), SD14. PD6; OQ1.
- **Expected output:**
  - **(a)** `SettingsPage` as PD6: the status line component is mounted only when `holdsSpel`; the tiles as today.
  - **(b)** `WalletsScreenPage` as PD6: Betalen only when `holdsSpel`. Built from the session inside the component, so `WALLETS` stays one list plus a filter.
  - **(c) OQ1 = B (answered):**
    - `ProfilesSection` gains `canManage`;
    - `SpelopzetPage` passes `session.me.role === 'admin'`;
    - without it, the save form and the "Verwijderen" buttons are not rendered, and the list and "Profiel laden" are;
    - its header comment says so.
  - **Tests:**
    - `SettingsPage.test.tsx`:
      - organiser: tiles Spelopzet and Mensen en wallets, no Beheer, the status line;
      - kassa: one tile, no status line, **no `GET /api/runs/current` request**;
      - admin: as today;
    - `SettingsScreens.test.tsx`:
      - kassa: Mensen en wallets shows Wallets, not Betalen, and no request to `/api/runs/current` or `…/config`;
      - organiser and admin: both;
      - (c) organiser: Profielen without "Opslaan als profiel" and "Verwijderen", with "Laden" on a draft; admin unchanged;
    - `ProfilesSection.test.tsx`: `canManage={false}` (c).
- **Verification:** `pnpm -C web vitest run src/app/pages src/features/settings/ProfilesSection.test.tsx`; `pnpm -C web lint`.
- **Depends on:** T6 (the session enum accepts `organiser`).
- **Autonomy note:** The builder may name the status-line component and the filter. Stop and ask in any of these cases:
  - `settingsCoverage.test.tsx` (B-12 PD16) fails for an admin session;
  - B-12's `LeaveGuard` behaves differently for a role;
  - (c) would need `ProfilesSection` to know a role name rather than take `canManage`.

### T8 — The organiser end to end, and the gate
- **Implements:** the spec's Playwright flows 1–5 (AC1, AC5, AC6, AC8, AC10, AC11, AC14 at the browser); AC22 (the boundary). PD9.
- **Expected output:** `web/e2e/organiser.spec.ts`, serial, its own server (PD9):
  1. Admin, on Beheer's Toegangssleutels: an "Organisator" key and a "Kassa" key, each read from the one-time display; then logs out.
  2. The organiser logs in and lands on `/`. Then:
     - Spelopzet: one drink's Maximum and the Prijsstap saved;
     - Mensen en wallets: "Rood staan tot" saved;
     - `/kassa`: a wallet signed up on `/speler` is found and topped up.
  3. The organiser on `/settings/beheer`: "Geen toegang". Then a `PATCH /api/runs/{id}/config {"params": {"eta": …}}` from the page's own session (`page.evaluate(fetch…)`, as `keys.spec.ts:69`): 403. The admin's Drukdrempel is unchanged.
  4. The organiser closes the live run by its name on Spelopzet's Borrel section.
  5. The kassa logs in: `/settings/wallets` shows Wallets and no Betalen; `/settings/spel` is "Geen toegang".
- **The gate.** Once this passes:
  - `./scripts/check.sh` 13/13, output pasted;
  - `git diff --stat main -- exchange tests/engine/golden/fixtures` empty;
  - `git diff main -- web/src/api/generated` shows only the role literal;
  - no change to `pyproject.toml`, `uv.lock`, `web/package.json`, `pnpm-lock.yaml`.
- **Verification:** `pnpm -C web exec playwright test e2e/organiser.spec.ts`; then `./scripts/check.sh` (MEMORY: never piped through `tail`; DSN at `127.0.0.1`).
- **Depends on:** T3, T5, T7.
- **Autonomy note:** The builder may pick the drink, the amounts and the order of steps 2's three screens. Stop and ask in either case:
  - `startServer` cannot give a live run and a sign-up path together;
  - a step needs an endpoint or fixture that does not exist (AC22: no new endpoint).

### T9 — The docs
- **Implements:** AC23. SD13 (the docs).
- **Expected output:**
  - **`data-model.md:35`:** `role` display/bar/admin/kassa/organiser (`organiser`: B-13 SD1).
  - **`frontend-architecture.md:64-71`:** a *B-13* sentence beside the B-05 one. The organiser holds the setup and cash-desk addresses, not Beheer or Analyse; kassa also holds `/settings/wallets` without Betalen; the gating still comes from `allowed_routes`.
  - **`phase-6-admin.md` SD33:** an "*Amended by B-13:*" bullet for **organiser** (SD5–SD11 in one line) and a note on kassa's two settings addresses.
  - **Confirm:**
    - `CLAUDE.md:37` and `venue.md:21` name all five roles;
    - `rollback.md` gains R2's line: before rolling back past 0017, the B-12 image cannot log in or list an organiser key, so use `app.cli.keys list`/`revoke` there.
- **Verification:** `git diff --stat` shows only these files; `uv run pytest tests/meta/test_repo_hygiene.py` (the docs links).
- **Depends on:** —
- **Autonomy note:** The builder words the lines. Stop and ask before touching any other `docs/design/` text or any ADR (AC23: none is amended).

---

## Task graph

```
T1 ─┬─> T2 ─> T3 ─> T4 ─> T5 ─┐
    └─> T6 ─> T7 ─────────────┴─> T8
T9 (independent)
```

The server tasks are a chain because each one widens rows of `test_authorization_matrix.py`: one file, one writer at a time. T3, T4 and T5 also share `config.py`, `security.py` and `deps.py` with T1 and T2. Each server task is small (role lists), so the chain is cheap. The client branch runs beside it.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T9 | T1: `app/db/keys.py`, `app/db/models.py`, `0017_organiser_role.py`, `deps.py`, `security.py`, `messages.py`, `cli/keys.py`, `schema.d.ts`, T1's tests. T9: the docs, `CLAUDE.md` |
| 2 | T2, T6 | T2: the seven setup route files, the matrix, eight `tests/api` files. T6: four client enums, `KeysSection`, `HomePage`, `auth.test.tsx` |
| 3 | T3, T7 | T3: `config.py`, `test_config.py`, the matrix. T7: `app/pages/Settings*`, `ProfilesSection` |
| 4 | T4 | `wallets_admin.py`, `kassa.py`, `payments.py`, `security.py`, the matrix, wallet tests |
| 5 | T5 | five bar/market route files, `deps.py`, the matrix, their tests |
| 6 | T8 | `web/e2e/organiser.spec.ts` |

No two tasks in one group write the same file.

---

## Data changes

- **`0017_organiser_role`:** `auth_key_role_check` becomes `role IN ('display', 'bar', 'admin', 'kassa', 'organiser')`. No column, table or backfill. Expand-only.
- **`min_code_revision = "unchanged"`** (PD1).
- **`downgrade()`** restores the four-role CHECK. It fails, changing nothing, while an `organiser` row exists. Revoked rows count, as in `0013`, so the operator deletes them by hand first.
- **Existing keys and sessions are untouched** (AC3): no row changes role.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | FastAPI might validate the body before PD4's dependency in some version, making a refused-and-invalid field 422 | T3's explicit invalid-value test; the Autonomy note stops if it fails. FastAPI's `solve_dependencies` resolves sub-dependencies before body fields today |
| R2 | **Rollback to the B-12 image with an organiser row present.** That image's `ROLE_ROUTES[row.role]` (`auth.py:54`) raises on the key's login, and `GET /api/keys`'s `KeyInfo.role: Role` (`keys.py:65`) fails response validation. The admin's Toegangssleutels list errors until the row is deleted. Other keys work | The same trade-off `0013` made for `kassa`. Raising the floor (PD1) would refuse the boot entirely, which is worse at a venue. T9's rollback line (Confirm) names the CLI way out. **Confirm** that "unchanged" is the right call (SD16 gave it to the planner) |
| R3 | The spec's "four places" missed `app/realtime/messages.py:67` | Planned in T1 (AC18 depends on it). Any other copy of the role list found in building is the PD10 stop-and-ask |
| R4 | The server tasks form a 5-long chain on the matrix file | They are small. A wider graph would mean the matrix test failing between tasks |
| R5 | An organiser sees the home tile "Instellingen — Spelopzet, wallets en beheer" (`HomePage.tsx:31`), and kassa sees "Betalen" in its one tile's line (PD6) | Text only, and the spec does not ask for it. Left as is (Out of scope); the audit may overrule |
| R6 | ~~OQ1 unanswered~~ | Answered B by the owner 2026-11-03 |
| R7 | The organiser on `/manipulation` reads `GET …/config` through `PriceJumpSection.tsx:43`, which bar is refused | It is now allowed (SD5). `showBounds` stays admin-only (PD8), so nothing new is shown |

---

## Out of scope for this plan

- Rewording the home "Instellingen" tile or the Mensen en wallets tile per role (R5).
- The bar's 10-minute recent-payments list for the organiser (SD9: as for bar).
- Hiding the B-12 landing's Beheer-only texts beyond the tiles `allowed_routes` already filters.
- `fixtures.ts`'s `MintedRole` and `serve.py`'s keys: T8 mints its keys on the page (PD9).
- Everything in the spec's Out of scope: usernames, finer permissions, the engine, new settings, new endpoints, new dependencies.

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

AC → task: AC1–AC4 T1 · AC5 T1, T4 · AC6 T1 (reload), T6 · AC7, AC8 T7 · AC9, AC10 T2 · AC11 T3 · AC12 T3, T6 · AC13–AC15 T4 · AC16 T3 · AC17 T5 · AC18 T1 · AC19 T6 · AC20 T1–T5 · AC21 T6 · AC22 T1, T8 · AC23 T9

Audited by: MartijnBoot (owner, `/audit`), accepting the audit report and ticking every line on request; every **Confirm** row confirmed as written; `app/db/models.py` added to T1 at audit  Date: 2026-11-03
