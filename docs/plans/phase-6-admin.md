# Plan: Phase 6 — Manipulation, settings and the admin hub

Spec: [docs/specs/phase-6-admin.md](../specs/phase-6-admin.md) (`Status: Approved`, 2026-10-06; the working-tree text) · Status: Draft — awaiting plan-auditor
Design: [architecture.md](../design/architecture.md) ("Non-destructive drink add and remove", "Durability", "Authorization"), [data-model.md](../design/data-model.md), [realtime-protocol.md](../design/realtime-protocol.md), [frontend-architecture.md](../design/frontend-architecture.md) ("Forms", "State")
ADRs honoured: 0003 (one writer; the in-process go-live addendum is written in T39), 0004 (Postgres only; images are `bytea`), 0005 (server-side theme; the token count is corrected in T39), 0006 (no new runtime asset source), 0008 (the order path is unchanged except the `drink_unavailable` refusal), 0009/0010 (hard stops: new dependency, `docs/design/`, product ADR text, pricing maths), 0011 (the migration runs at boot), 0012 (`flow_ema` semantics unchanged)
Fixes: D-02, D-03, D-04, D-19, D-26, D-29, D-44, D-45, D-46, D-47, D-48

---

## Approach

**Engine first, then the one write path, then thin forms.** D-02 and D-45 are engine problems, so
they are fixed in `exchange/` as pure functions:
- an active mask, `MarketSpec.active` (T2);
- three lifecycle helpers: hold the quoted prices across a spec change, append a slot, and
  cancel jumps (T3).

Both are proven bitwise against today's outputs with every slot active, and the golden replay
stays green. Persistence then stores every slot (T5). Every live admin write becomes one
`holder.mutate("config", ...)` transition. It commits, in one transaction:
- the row change;
- one `run_config_revision`, allocated under a row lock on `run`;
- the `engine_state` compare-and-set;
- a `price_tick` of source `config`.

After the commit it emits one `ConfigChanged`, which the publisher turns into the new `config`
message (T7, T11). A draft write is the same validation and revision without the holder.

Go-live (T9) takes the boot path: `go_live` commits, then under the state lock the empty holder
adopts what `rehydrate` returns. The ticker re-anchors at the run's interval and the hub clears
its replay log. Every socket is then sent a snapshot.

D-03, D-04 and D-46 die in the web layer, by construction:
- a `NumberField` that can only yield `number | null` (T21);
- a `useEditableRecord` hook whose save body is the dirty fields and nothing else (T23);
- every section built on those two, with the D-03 gate test written first (T28).

Rejected:
- **Rebuilding the market on a drink change (v1).** That is D-02.
- **Calling `retarget_y_to_hold_quantized_prices` after mutating the bounds (v1).** That is
  D-45. T3's helper computes `p_q` under the *old* spec first.
- **A new holder method per write kind.** Every write goes through the existing `mutate`.
  Go-live is the one exception: `mutate` refuses an empty holder by design
  (`holder.py:325-326`), so the holder gains exactly one `adopt` path.
- **A form library.** SD27 forbids it, and `frontend-architecture.md` rejects react-hook-form.
- **One migration per feature.** Every migration mirrors into `app/db/models.py` and
  `tests/integration/test_migrations.py`. Spread over feature tasks they would chain six tasks
  on one file. One additive migration (T1) lets the engine and web tasks start at once.
- **Splitting the route tasks to run in parallel.** Every task that adds or changes a route must
  regenerate `web/src/api/generated/schema.d.ts`, because `check.sh`'s drift step enforces it,
  and must add a row to `tests/api/test_authorization_matrix.py`, whose completeness check
  rejects a row without a served route. So the server route tasks form one chain by
  construction (see Task graph). The engine and web work run beside it. Builders run one at a
  time anyway (ADR 0010 §1).
- **`python-multipart` for uploads.** It is not installed (`uv.lock` has no entry), and FastAPI's
  `UploadFile` needs it. PD1 was decided (b) by the human on 2026-10-06: T18 adds it.

---

## Decisions this plan makes

The spec leaves these open. The ones marked **Confirm** change user-visible behaviour or the API
surface. Under ADR 0009 the audit must confirm or overrule them. **PD1 was a hard stop and is
answered:** the human chose (b), `python-multipart`, on 2026-10-06, keeping SD29's wording.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | **Upload wire format (SD29 says "multipart `file`")** | **Decided (b) by the human, 2026-10-06.** Rejected (a): `POST /api/theme/images/{slot}` takes the file as the raw request body (`Content-Type: application/octet-stream`). The server reads `request.stream()` through a bounded reader. `lib/http` gains a `rawBody: Blob` option. **(b):** add `python-multipart` (approval note under Data changes) and keep multipart. Under (b) the bounded read still has to be hand-written: Starlette's multipart parser does not cap the size of a file part. T18 adds the dependency (`pyproject.toml`, `uv.lock`) | (a) needs no dependency. It also makes AC33's "never more than 5 MB + one chunk" true by construction: one loop, one counter. (b) matches the spec text |
| PD2 | How `/settings` and home find "the current run" (SD4) when it is a draft | New `GET /api/runs/current` (admin) returns `{run_id, name, status}`: the live run, else the draft, else 404 `no_current_run`. `409 draft_exists` also carries `run_id` in its error envelope. **Confirm** (a route not listed in SD5) | Without it, a reload of `/settings` while editing a draft shows "Geen borrel". The 409 alone cannot rediscover a draft without trying to create one |
| PD3 | `run.name` for existing rows | The migration backfills `'Borrel ' \|\| run_id`, then sets `NOT NULL`. **Confirm** | The name is required (SD2). An imported run's file stem is not recoverable from the row |
| PD4 | Error codes SD5–SD30 do not name | 404 `run_not_found`, 404 `drink_not_found`, 409 `drink_removed` (PATCH/DELETE of a removed drink), 409 `run_not_live` (anchor-s0 on a draft), 409 `no_custom_theme` (`preset: custom` with none stored), 404 `asset_not_found`, 404 `key_not_found`, 404 `no_current_run` | Each is the `AppError` subclass pattern (`app/core/errors.py`), one stable code each |
| PD5 | What a live config transition broadcasts | Only `config`. Its envelope `version` is the new version. Prices that moved (a hold) reach clients on the next 1 Hz tick; the transition's `price_tick` joins the ring, so a snapshot is consistent at once | The same rule as a jump (`manipulation.py:3-5`, Phase 3 PD13). AC12 asks for exactly one `config` message |
| PD6 | The revision document and run creation | `run_config_revision.config` holds the `GET config` response body (removed drinks included, with `active: false`). `POST /api/runs` writes revision 1, author = the key label, as `import_v1` does | SD6 asks for "the full config"; one builder serves both |
| PD7 | `idle_targets` on the wire | `GET config` returns them as `drink_id`s, mapped over active drinks; a stored name with no active drink is dropped from the response. `PATCH` takes `drink_id`s; an id that is unknown or inactive is 422 naming the field | SD11 |
| PD8 | The custom-theme route | `PUT /api/theme {preset, tokens?, font?}`. `tokens` and `font` are allowed only with `preset: "custom"`, and only together. `preset: "custom"` without them uses the stored ones, or is 409 `no_custom_theme` if there are none. Tokens must be exactly `TOKEN_NAMES`, each matching SD28's hex pattern; `font` is `inter` or `garamond`. **Confirm** | SD28 names the storage and the behaviour but no route. Extending the existing route keeps one theme write path (`app/api/theme.py`) |
| PD9 | How images reach every page (SD29, D-48) | `ThemeData` gains `images: {bg, header, logo, promo}`, each `"/assets/<id>"` or `null`; `hello` and the `theme` message carry it. `/theme.css` emits `--img-<slot>: url("/assets/<id>")` for each set slot, plus `body::before{…opacity:.12}` when `bg` is set and `header{background-image:var(--img-header)}`. `ThemeProvider` sets and removes the same four properties. A `Logo` component paints `var(--img-logo, url(<bundled logo>))`, so the login page (no socket) and the shell agree on first paint. Koers adds `has-promo` and the promo tile when the store's `images.promo` is set | One mechanism for first paint and live updates, with no per-browser state (ADR 0005) |
| PD10 | `GET /assets/{asset_id}` vs Vite's `/assets/*.js` | The route path uses Starlette's int converter, `/assets/{asset_id:int}`. Vite's hashed `/assets/index-*.js` then matches no route and falls through to the SPA mount. `web/vite.config.ts` proxies `^/assets/\d+$` in dev only | Vite emits `dist/assets/`. A plain `{asset_id}` with an `int` parameter answers 422 for every bundle file instead of falling through |
| PD11 | Go-live and the hub | `hub.adopt_run(replay_window_ms)` sets the run's window and **clears the replay log**. A client that reconnects with an old `(boot_id, last_seq)` therefore gets a snapshot, never new-run ticks replayed onto an empty store. The publisher's candle book is rebuilt for the run's `candle_interval_ms`. `_Session` reads `app.state.tick_interval_ms` per message, not once at connect | SD3's "every connected client receives the new run's snapshot" also has to hold for a client mid-reconnect |
| PD12 | The close code on revocation (SD30) | 4401, Phase 3's close code for an open session that ended (`ws.py` `CLOSE_SESSION_EXPIRED`). The client already treats it as a lost session (`client.ts:33`) | SD30: "Phase 3's authentication close code" |
| PD13 | The settings composition and sibling isolation | `app/pages/SettingsPage.tsx` stays the composition root. It renders `features/settings`' sections and `features/keys`' `KeysSection` inside `features/settings`' `SettingsLayout` (with `MobileSectionNav`). `ThemeSection` moves from `features/theme` into `features/settings` (Phase 4 PD13's note); `ThemeProvider` stays in `features/theme`. `routes.tsx` passes `canEditIdle = me.role === 'admin'` into `ManipulationPage` | `eslint.config.js` boundaries forbid sibling imports; the app layer may compose |
| PD14 | Home's "age of the last message" (SD31) | `ExchangeState.lastFrameAt` (monotonic) is set by `applyMessage` from the `receivedAt` it already takes, on every applied or dropped frame | The reducer stays pure (Phase 5 PD1); no second clock |
| PD15 | The spec's Playwright flow needs an empty database | `tests/integration/realapp/serve.py --empty` seeds no run and mints only an admin key. `web/e2e/admin.spec.ts` starts its own instance in `beforeAll` through a helper factored out of `global-setup.ts`, on its own scratch database (its own advisory lock). The shared server and the Phase 4–5 specs are untouched | The shared server's v1 run is live, so go-live would be refused (`live_run_exists`), and the board specs depend on that run |
| PD16 | AC39's and SD27's lint rules | `no-restricted-syntax` bans every unary `+` (`UnaryExpression[operator='+']`) in non-test source; none exists today. `no-restricted-globals` bans `confirm`, `alert` and `prompt` | The narrowest rule that cannot be dodged by naming; `grep` finds no existing use |
| PD17 | An inactive slot through every engine step | Every per-slot value of an inactive slot is frozen: `y`, `cum_orders`, `flow_ema` and `last_order_ts`. `apply_idle`'s name lookup ranges over active slots only, so a removed drink sharing a name with a re-added one can never take its idle push. **Engine-guardian** | SD13 "its `y` freezes" and SD14. With every slot active the lookup is identical, since names are unique among active drinks |
| PD18 | A live change to `history_window_minutes` | Applies going forward: shrinking trims the ring and the hub's replay window at once; growing fills as ticks arrive, with no database reload. **Confirm** | Reloading the window from `price_tick` under the state lock would break the "one short transaction" rule |
| PD19 | Ordering of authorization and draining | `require_role` runs first, then `refuse_while_draining` (a new dependency in `app/api/deps.py`, holding `ShuttingDown`, which moves from `app/api/orders.py`). A refused role stays 401/403 while draining | One dependency per concern; the matrix test stays deterministic |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `db/migrations/versions/0009_phase_6_admin.py` | Create | `run.name`, `price_tick` source `config`, `asset`, theme custom columns and image slots | T1 |
| `app/db/models.py` | Modify | Mirror 0009 | T1 |
| `app/db/runs.py` | Modify | `create_draft_run(name=)` (T1); `all_drinks` (T5); current/draft lookup, latest params, `DraftExists` (T8); `go_live` auto-calibrate (T9); revision under `run` row lock, run/param updates (T10); drink insert/update/remove helpers (T12–T14) | T1, T5, T8, T9, T10, T12, T13, T14 |
| `app/cli/import_v1.py` | Modify | Run name from the config file stem | T1 |
| `exchange/spec.py`, `exchange/steps.py`, `exchange/advance.py` | Modify | Active mask (SD14, PD17) | T2 |
| `exchange/state.py`, `exchange/__init__.py` | Modify | `hold_quoted_prices`, `append_slot`, `cancel_jumps` | T3 |
| `app/api/deps.py` | Modify | `refuse_while_draining`, `ShuttingDown` (PD19) | T4 |
| `app/api/orders.py`, `app/api/news.py`, `app/api/market.py`, `app/api/theme.py` | Modify | Draining dependency (T4); `market.py` active-only jumps (T6); theme writes (T17, T18) | T4, T6, T17, T18 |
| `app/db/mapping.py` | Modify | `DrinkRow.removed`, mask into `MarketSpec` | T5 |
| `app/runtime/rehydrate.py` | Modify | Spec from every row, mask from `removed_at` (SD15) | T5 |
| `app/runtime/orders.py` | Modify | 422 `drink_unavailable` | T6 |
| `app/runtime/manipulation.py` | Modify | Events target active drinks only | T6 |
| `app/realtime/messages.py` | Modify | `DrinkInfo.active`, `ConfigData` (T7); `ThemeData.preset` custom (T17); `ThemeData.images` (T19) | T7, T17, T19 |
| `app/realtime/publish.py` | Modify | `config` message, active-only prices/bars (T7); book reset (T9); re-bucket (T11) | T7, T9, T11 |
| `app/runtime/holder.py` | Modify | `ConfigChanged` (T7); `adopt` (T9) | T7, T9 |
| `app/runtime/ticker.py` | Modify | `adopt_interval` re-anchor | T9 |
| `app/realtime/hub.py` | Modify | `adopt_run` (T9); connection principal, `close_key`, `connection_info` (T16) | T9, T16 |
| `app/realtime/ws.py` | Modify | Lazy `tick_interval_ms` (T9); principal into `hub.connect` (T16) | T9, T16 |
| `app/runtime/boot.py` | Modify | `app.state.publisher`, the empty holder's `on_diverged`/timeout (T9); custom theme load (T17) | T9, T17 |
| `app/runtime/golive.py` | Create | Go-live orchestration (SD3) | T9 |
| `app/api/runs.py` | Create | `POST /api/runs`, `GET /api/runs/current` (T8); `POST …/go-live` (T9) | T8, T9 |
| `app/api/config.py` | Create | `GET`/`PATCH …/config` (T10, T11); `POST …/anchor-s0` (T15) | T10, T11, T15 |
| `app/runtime/config.py` | Create | Validation (SD8), config document, draft write (T10); live transition (T11); anchor (T15) | T10, T11, T15 |
| `app/api/drinks.py` | Create | `POST`/`PATCH`/`DELETE …/drinks` | T12, T13, T14 |
| `app/runtime/drinks.py` | Create | Draft and live drink writes | T12, T13, T14 |
| `app/api/keys.py` | Create | `GET`/`POST /api/keys`, `DELETE /api/keys/{key_id}` | T16 |
| `app/api/security.py` | Modify | `issue_key(conn, role, label)` shared by the CLI and the API | T16 |
| `app/cli/keys.py` | Modify | Call `issue_key` | T16 |
| `app/db/keys.py` | Modify | Unrevoked-admin count under lock | T16 |
| `app/api/admin.py` | Modify | `GET /api/admin/connections` | T16 |
| `app/runtime/theme.py` | Modify | Custom theme, hex check (T17); image URLs and CSS (T19) | T17, T19 |
| `app/db/theme.py` | Modify | Custom columns (T17); slot pointers (T18) | T17, T18 |
| `app/db/assets.py` | Create | `asset` repository | T18 |
| `app/runtime/images.py` | Create | Magic-byte sniff, bounded reader (pure) | T18 |
| `app/api/assets.py` | Create | `GET /assets/{asset_id:int}` | T18 |
| `app/main.py` | Modify | Include runs (T8), config (T10), drinks (T12), keys (T16), assets (T18) | T8, T10, T12, T16, T18 |
| `web/vite.config.ts` | Modify | Dev proxy for uploaded assets (PD10) | T18 |
| `pyproject.toml`, `uv.lock` | Modify | Add `python-multipart` (PD1 (b)) | T18 |
| `tests/api/test_authorization_matrix.py` | Modify | A row per new route (AC43) | T8–T18 |
| `tests/meta/test_route_authorization.py` | Modify | `GET /assets/{asset_id}` public (SD29) | T18 |
| `tests/api/test_draining.py` | Create (T4), Modify | AC40, extended per route task | T4, T8–T18 |
| `tests/api/ws_fixture.py`, `web/src/features/exchange/model/__fixtures__/ws-messages.json` | Modify | Recorded frames | T7, T19 |
| `web/src/api/generated/schema.d.ts` | Modify (generated) | `scripts/gen_api_types.sh` | T7–T19 |
| `web/src/features/exchange/model/schemas.ts` | Modify | `active`, `config` (T7); `custom` (T17); `images` (T19) | T7, T17, T19 |
| `web/src/features/exchange/model/applyMessage.ts`, `.test.ts`, `selectors.ts`, `index.ts` | Modify | `config` reducer, resync trigger, `selectActiveDrinks` (T7); `lastFrameAt` (T35) | T7, T35 |
| `web/src/lib/http.ts`, `http.test.ts` | Modify | `PATCH`, `formData` (PD1 (b)) | T20 |
| `web/src/lib/format.ts`, `format.test.ts` | Modify | `parseEuroCents` | T21 |
| `web/src/components/ui/{Field,NumberField,MoneyField}.tsx` + tests/CSS | Create | SD27 primitives | T21 |
| `web/eslint.config.js`, `web/src/lint-rules.test.ts` | Modify | PD16 | T21 |
| `web/src/components/ui/{Select,Switch,Toast,MobileSectionNav}.tsx` + tests/CSS | Create | SD27, SD25 | T22 |
| `web/src/lib/useMediaQuery.ts` | Create (moved from `features/bar`) | Shared by bar and settings | T22 |
| `web/src/features/bar/useMediaQuery.ts`, `RevenueChart.tsx` | Delete / Modify | Import from `lib` | T22 |
| `web/src/lib/useEditableRecord.ts`, `.test.ts` | Create | SD27 dirty tracking, conflict | T23 |
| `web/src/features/settings/**` | Create | Layout, Borrel section, stubs (T24); one section per task (T25–T31) | T24–T31 |
| `web/src/features/theme/ThemeSection*`, `index.ts` | Delete / Modify | Moves to settings (PD13) | T24 |
| `web/src/features/keys/**` | Create | Stub (T24); `KeysSection` (T32) | T24, T32 |
| `web/src/app/pages/SettingsPage.tsx` | Modify | Composition (PD13) | T24 |
| `web/src/features/manipulation/**` | Create | Page, sections (T33); `IdleSection` (T34) | T33, T34 |
| `web/src/app/routes.tsx` | Modify | `/manipulation` (T33); `/` (T35) | T33, T35 |
| `web/src/features/home/**` | Create | Tiles, status panel | T35 |
| `web/src/features/koers/{KoersPage,PriceMarquee}.tsx` + CSS | Modify | Active drinks (T36); promo tile, `has-promo` (T19) | T36, T19 |
| `web/src/features/bar/{OrderPad,FinancialPanel,PendingOrders}.tsx`, `model/orderIntents.ts` | Modify | Removed drinks, `drink_unavailable` | T37 |
| `web/src/features/theme/ThemeProvider.tsx`, `web/src/components/ui/Logo.tsx`, `web/src/app/AppShell.tsx`, `web/src/features/auth/LoginPage.tsx` | Modify/Create | Image slots (PD9) | T19 |
| `tests/integration/realapp/serve.py`, `web/e2e/serverProcess.ts`, `web/e2e/global-setup.ts`, `web/e2e/admin.spec.ts` | Modify/Create | PD15 | T38 |
| `docs/adr/0003-*.md`, `docs/adr/0005-*.md`, `docs/design/{realtime-protocol,data-model,architecture}.md`, `docs/specs/phase-7-analytics.md`, `docs/specs/defect-register.md` | Modify | The spec's Documents list | T39 |

One new dependency: `python-multipart` (PD1 (b), approved by the human 2026-10-06; added in T18). Testing Library, Playwright, Zod and Zustand are already in
`web/package.json`; argon2, SQLAlchemy and asyncpg are already in `pyproject.toml`.

---

## Tasks

Every task leaves `./scripts/check.sh` green, with the output pasted. Branches follow
`feature/phase-6-tN-<slug>`. Single-file web runs use `pnpm --dir web exec vitest run <path>`.
Reuse, by name:
- **Server:**
  - `app/api/deps.py` (`require_role`, `Principal.label` as the revision author, `db_engine`,
    `clock_of`);
  - `app/runtime/holder.py` (`mutate`, `Outcome`, `MarketView`, `NoLiveRunError`);
  - `app/db/engine_state.py` (`compare_and_set`, `insert_tick`);
  - `app/db/codec.py` (`tick_prices`);
  - `app/db/mapping.py` (`spec_from_rows`, `params_to_json`, `cents_from_quantised`);
  - `app/db/runs.py` (`add_drink`, `DuplicateDrinkName`, `append_config_revision`, `go_live`,
    `name_key`, `LiveRunExists`, `RunNotDraft`, `RunNotReady`);
  - `app/runtime/manipulation.py` as the shape of a mutate step with its own transaction;
  - `app/api/theme.py` as the shape of a broadcast-on-hub write;
  - `app/core/errors.py` (`AppError`; the validation handler already names fields in
    `faults[].loc`).
- **Tests:**
  - `tests/api/conftest.py` (`client`, `live_client`, `live_run`, `mint_key`, `login`);
  - `tests/integration/conftest.py`;
  - `tests/api/ws_fixture.py`;
  - `tests/integration/realapp/harness.py`: urllib only, never `TestClient` or `curl` in
    real-process tests (memory note).
- **Web:**
  - `lib/http.ts` (`request`, `HttpError.details`) and `lib/format.ts` (`formatEuro`);
  - `components/ui/{Button,ConfirmDialog,StatusDot,NavMenu}.tsx`;
  - `features/exchange` (store, selectors, `applyMessage`);
  - `features/auth` (`useSession`, `RequireRole`) and `app/pages/NoAccess.tsx`;
  - `features/koers/KoersPage.tsx` for the empty state;
  - `web/e2e/fixtures.ts` (`loginAs`, `server`).

### T1 — Migration 0009 and the run name

- **Implements:** AC24 (the name), AC12 (source `config` allowed), AC34 (the `asset` table and
  slot pointers); SD2, SD7, SD28, SD29; PD3
- **Expected output:**
  - `0009_phase_6_admin.py`, revises `0008`:
    - `run.name text` is backfilled with `'Borrel ' || run_id`, then `NOT NULL`, with `CHECK
      (char_length(btrim(name)) BETWEEN 1 AND 100)`;
    - `price_tick_source_check` is dropped and recreated with `'config'` added;
    - the `asset` table: `asset_id` identity PK, `content_type` in the four types, `sha256`
      text, `data bytea`, `bytes integer` `CHECK (bytes BETWEEN 1 AND 5242880 AND bytes =
      octet_length(data))`, `created_at`;
    - the `theme` table:
      - `custom_tokens jsonb NULL`;
      - `custom_font text NULL CHECK IN ('inter','garamond')`;
      - `bg_asset_id`, `header_asset_id`, `logo_asset_id`, `promo_asset_id` (`bigint NULL`,
        FK `asset`);
      - `theme_preset_check` widened with `'custom'`;
      - `CHECK (preset <> 'custom' OR (custom_tokens IS NOT NULL AND custom_font IS NOT
        NULL))`.
  - `downgrade()` reverses every step.
  - `app/db/models.py` mirrors it.
  - `create_draft_run(conn, *, name, params, run_seed)` takes `name`. `import_v1` passes
    `args.config.stem[:100]`.
  - Every test call site of `create_draft_run` is updated mechanically (about 19 test files).
- **Verification:**
  - `uv run pytest tests/integration/test_migrations.py tests/integration/test_schema.py tests/integration/test_import_v1.py -v`:
    - the round trip (`upgrade`/`downgrade base`/`upgrade`) holds and the models match;
    - new cases: a blank name, `source='config'`, `preset='custom'` without tokens, and a
      `bytes` mismatch are each rejected;
    - an import names the run after the file stem.
  - `./scripts/check.sh`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** constraint names, column order, the test-helper shape for the
    mechanical call-site edits.
  - **Must stop and ask if:** anything would require editing migrations 0001–0008 (the
    `guard_migrations` hook), or the backfill cannot be done in the same migration.

### T2 — Engine: the active mask

- **Implements:** AC16; the engine halves of AC15 (an inactive slot takes no price move) and
  AC19 (orders on an inactive slot are refused); SD14; PD17
- **Expected output:**
  - `MarketSpec.active` is a read-only bool array, default all `True`, after `params`.
    `DrinkSpec.active: bool = True`; `from_drinks` carries it. Construction raises
    `ValueError` with no active slot.
  - `_single_step`:
    - `p_mean` and `N` range over active slots;
    - `others_avg_dev` sums active `dev` only;
    - the unstick loop skips inactive slots;
    - an inactive slot's `y` and `cum_orders` are copied through.
  - `apply_orders` leaves an inactive slot's `flow_ema` and `last_order_ts` unchanged.
  - `apply_idle`: `p_mean` over active slots; `name_to_idx` over active slots only.
  - `apply_brownian`:
    - `mean_range` over active slots;
    - the draw size stays `len(names)`;
    - `y` moves only where active.
  - `anchor_s0_to_current_y`: the mean over active slots; an inactive slot's `s0` is unchanged.
  - `schedule_jump` raises for an inactive drink. `_validated_orders` raises for a positive
    quantity on an inactive slot.
  - Every expression is unchanged when the mask is all `True`.
- **Verification:**
  - `uv run pytest tests/engine -v`. A new `tests/engine/test_mask.py` covers:
    - for random specs and states, an all-true mask gives bitwise-equal outputs to the
      unmasked call, in every step and in `anchor_s0` (compare with `np.array_equal` on the
      bytes, `.tobytes()`);
    - with one slot inactive, every per-slot value of that slot is unchanged across 200
      `advance` calls;
    - `p_mean`, `N`, `mean_range` and the anchor mean equal hand-computed values over active
      slots;
    - other drinks' Brownian draws are unchanged by deactivating a slot;
    - a renamed-duplicate idle target hits only the active slot.
  - `uv run python -m tests.engine.golden.capture --check` and `tests/engine/test_golden_replay.py` green.
  - `tests/engine/test_purity.py` green.
- **Depends on:** —
- **Autonomy note:**
  - **Engine-guardian reviews this diff.**
  - **May decide alone:** the masking idiom (`np.where`, boolean index), test names.
  - **Must stop and ask if:** any golden fixture or existing engine test changes, or an
    all-true mask cannot be made bitwise identical. That is pricing maths, a hard stop.

### T3 — Engine: hold, append, cancel

- **Implements:** AC8, AC10, AC14 (engine halves), AC18 (engine half); SD9, SD12
- **Expected output:** in `exchange/state.py`, exported from `exchange/__init__.py`:
  - `hold_quoted_prices(old_spec, new_spec, state, slots) -> EngineState`. For each index in
    `slots`, it computes `p_q` under `old_spec`, clamps it into `new_spec`'s `[p_min, p_max]`,
    quantises it on `new_spec.params.step_quant`, and refits `y` with the same `FRAC_EPS` clip
    as `retarget_y_to_hold_quantized_prices`. Every other slot's `y` is the same array value,
    bitwise. Jumps on `slots` are dropped.
  - `append_slot(new_spec, state, *, now_ms) -> EngineState`. The new last slot's `y` comes
    from `p0` exactly as `initial_state` computes it for one slot. Its `cum_orders`/`flow_ema`
    are 0 and its `last_order_ts` is `now_ms`. Every existing slot's values, the jumps and
    every counter are unchanged.
  - `cancel_jumps(state, slots) -> EngineState`.
- **Verification:** `uv run pytest tests/engine/test_lifecycle_helpers.py tests/engine -v`:
  - a property test over random bounds and steps: after `hold_quoted_prices`, the affected
    `prices_from_y(...)` `p_q` equals clamp-then-requantise of the old `p_q`, including bounds
    that are not on the grid;
  - unaffected `y.tobytes()` are equal;
  - `append_slot` then `prices_from_y` quotes `p0` for the new slot, and the prefix of every
    array is bitwise unchanged;
  - SD12's prefix-stability claim is pinned:
    `default_rng(SeedSequence([s, k])).normal(0, σ, N+1)[:N]` equals the size-`N` draw.
- **Depends on:** T2
- **Autonomy note:**
  - **Engine-guardian reviews this diff.**
  - **May decide alone:** helper names, argument order.
  - **Must stop and ask if:** the requantised clamp can land a quote outside `[p_min, p_max]`
    and the property test shows `p_q ≠ target`. How to resolve that is pricing maths.

### T4 — Draining refuses existing writes

- **Implements:** AC40 (news, jumps, events, theme, orders); SD24; PD19
- **Expected output:**
  - `app/api/deps.py: refuse_while_draining(request)` raises `ShuttingDown` (503
    `shutting_down`; the class moves from `app/api/orders.py`, code unchanged).
  - It is added to `POST /api/orders`, `POST`/`DELETE /api/news`, `POST /api/market/jumps`,
    `POST /api/market/events` and `PUT /api/theme`, after `require_role`.
  - `tests/api/test_draining.py` is parametrised over a `DRAINING_WRITES` list that later tasks
    extend.
- **Verification:** `uv run pytest tests/api/test_draining.py tests/api/test_orders.py tests/api/test_news.py tests/api/test_market.py tests/api/test_theme.py -v`:
  - with `app.state.draining = True`, an admin gets 503 `shutting_down` on each write, and
    reads still answer;
  - a display write while draining is still 403.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** dependency name, test parametrisation.
  - **Must stop and ask if:** an existing test expects a different order of 403/503.

### T5 — Persisted state covers every slot

- **Implements:** AC20 (the boot half); SD15
- **Expected output:**
  - `app/db/runs.py: all_drinks(conn, run_id)` returns every row in slot order with
    `removed_at`. `DrinkRow` gains `removed: bool`. `spec_from_rows` sets
    `DrinkSpec.active = not row.removed`.
  - `rehydrate` builds the spec and `drink_ids` from `all_drinks`. `bar_price_cents` covers
    every row.
  - `active_drinks` stays, for callers that mean "active".
  - `go_live` is unchanged in behaviour: a draft has no removed rows.
- **Verification:** `uv run pytest tests/integration/test_rehydrate.py tests/unit/test_mapping.py tests/integration/test_boot.py -v`. The new case seeds a live run whose
  `engine_state` holds keys for a row with `removed_at` set: today that is
  `StateDrinkMismatch`. Now it boots, and the removed slot is inactive with its stored values.
- **Depends on:** T1, T2
- **Autonomy note:**
  - **May decide alone:** whether `active_drinks` filters `all_drinks` or keeps its own query.
  - **Must stop and ask if:** a caller of `holder.drink_ids` would silently start acting on
    removed drinks before T6 lands. List them in the PR; T6 fixes each.

### T6 — Mask-aware orders, jumps and events

- **Implements:** AC19 (server), AC18 (event targets), AC6 (server, regression: an
  out-of-bounds target stays 422); SD13
- **Expected output:**
  - `place_order`: a line naming a removed drink is 422 `drink_unavailable` (a new
    `AppError`), checked before any price is read. Nothing is charged, written or moved. An
    unknown drink stays `invalid_request`.
  - `POST /api/market/jumps`: an inactive drink is 422 (`InvalidManipulation`).
  - `start_event` schedules jumps for active drinks only, and its `market_event.drink_ids` is
    the active set.
- **Verification:** `uv run pytest tests/integration/test_place_order.py tests/integration/test_manipulation.py tests/api/test_market.py tests/api/test_orders.py -v`:
  - with a removed drink, an order naming it is 422 `drink_unavailable`, and `order` and
    `price_tick` counts are unchanged;
  - an event skips it;
  - a jump at it is 422.
- **Depends on:** T4, T5
- **Autonomy note:**
  - **May decide alone:** error message text.
  - **Must stop and ask if:** distinguishing removed from unknown needs a query inside the
    lock. Use `spec.active` and `drink_ids`, which are in memory.

### T7 — Protocol: `active` and the `config` message

- **Implements:** AC23 (server and reducer), AC28 (the resync trigger), AC12 (the broadcast
  shape); SD18, SD19
- **Expected output:**
  - **Server messages:**
    - `DrinkInfo` gains `active: bool`.
    - A new `ConfigData {revision, run: RunInfo + name, drinks: [DrinkInfo], params}` and the
      server message type `config`.
    - `snapshot.drinks` lists every drink, with `active`. `prices`, `bars` and `tick` drinks
      cover active drinks only. `earnings` is unchanged (every drink with sales).
  - **Holder and publisher:** `holder.py` gains the domain event `ConfigChanged` (`run_id`,
    `version`, `revision`, `name`, candle interval, drinks, params). `Publisher` broadcasts it
    as `config`.
  - **Generated files:** `ws_fixture.py` records a `config` frame;
    `ws-messages.json` and `schema.d.ts` are regenerated.
  - **Web:**
    - `schemas.ts` adds `active` and the `config` envelope.
    - `applyMessage` handles an in-sequence `config` by replacing `drinks`, `params` and `run`.
      When the active `drink_id` set or `candle_interval_ms` changed, it sets
      `awaitingResync`, so the client sends one `resync_request` (`client.ts:151`).
    - `ExchangeState.drinks[*].active`, and `selectActiveDrinks` exported.
- **Verification:**
  - `uv run pytest tests/unit/test_messages.py tests/unit/test_publish.py tests/api/test_ws_fixture.py tests/api/test_state.py -v`;
  - `pnpm --dir web exec vitest run src/features/exchange`:
    - the fixture parses;
    - `config` with an unchanged active set applies without a resync;
    - with a changed set or interval, `awaitingResync` is set;
    - an out-of-sequence `config` is dropped;
    - `selectActiveDrinks`;
  - `./scripts/check.sh` (drift step).
- **Depends on:** T5
- **Autonomy note:**
  - **May decide alone:** `ConfigChanged`'s field layout, reducer helper names.
  - **Must stop and ask if:** `params` in `config` would need a different shape from the
    snapshot's. SD18 says "as in the snapshot".

### T8 — Runs: create a draft, find the current run

- **Implements:** AC24; AC7, AC43 (rows); AC40 (rows); SD2, SD4, SD33; PD2, PD6
- **Expected output:**
  - `app/api/runs.py` (router `/runs`, admin, `refuse_while_draining`):
    - **`POST /api/runs {name}`** (1–100 after trim) creates a draft. `params` come from the
      most recently created run (`ORDER BY created_at DESC, run_id DESC`), else
      `params_to_json(Params())`. It also sets:
      - `run_seed = secrets.randbits(63)`;
      - the default intervals and grace (column defaults);
      - revision 1 with `author = principal.label` (PD6).

      It refuses with 409 `live_run_exists`, or 409 `draft_exists` carrying `run_id`.
    - **`GET /api/runs/current`** (PD2).
  - Included in `app/main.py`; matrix rows and draining rows; `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_runs.py tests/integration/test_runs.py tests/api/test_authorization_matrix.py tests/meta/test_route_authorization.py tests/api/test_draining.py -v`:
  - create on an empty database copies `Params()` defaults;
  - with a prior run, it copies that run's params;
  - two creates give 409 `draft_exists` with the `run_id`;
  - with a live run, 409 `live_run_exists`;
  - a blank name is 422 naming `name`;
  - `current` returns live over draft, or 404;
  - bar and display get 403.
- **Depends on:** T1, T4, T7 (shared `schema.d.ts`)
- **Autonomy note:**
  - **May decide alone:** response model names, the query style.
  - **Must stop and ask if:** two concurrent `POST`s can both create a draft (no unique index
    covers "one draft"). Then propose a partial unique index on `status = 'draft'` as an
    additive migration rather than adding one silently.

### T9 — In-process go-live

- **Implements:** AC25, AC26, AC27; AC43, AC40 (rows); SD1, SD3; PD11
- **Expected output:**
  - `POST /api/runs/{run_id}/go-live` (admin) refuses with:
    - 409 `run_not_ready` with no active drink;
    - 409 `run_not_draft`;
    - 409 `live_run_exists`;
    - 404 `run_not_found`.
  - `app/db/runs.py: go_live` with `auto_calibrate_s0`: in the same transaction it computes
    `anchor_s0_to_current_y(spec, initial.y)`, writes each `drink.s0`, uses the anchored spec,
    and appends one revision (author = label). This replaces the refusal at `runs.py`'s
    `RunNotReady("…auto_calibrate_s0…")`. The CLI path calls it with `author="cli"`.
  - `app/runtime/golive.py`, after the commit:
    - `holder.adopt(run)` swaps view, ring and earnings under the lock, refuses with
      `LiveRunExists` if the holder is not empty, and calls `on_diverged` if the swap fails
      after the commit;
    - `ticker.adopt_interval(run.tick_interval_ms)` re-anchors;
    - `hub.adopt_run(window_ms)` clears the replay log;
    - the publisher's candle book is rebuilt;
    - `app.state.tick_interval_ms` is set;
    - a `snapshot` (and the theme catch-up) is unicast to every connection.
  - `boot.py` stores `app.state.publisher` and gives the empty holder `on_diverged` and
    `step_timeout_s`. `ws.py` reads the tick interval lazily.
- **Verification:**
  - `uv run pytest tests/api/test_go_live.py tests/integration/test_go_live_in_process.py tests/integration/test_cli_runs.py tests/integration/test_ticker.py -v`:
    - start empty, connect a WS client (`ws_fixture`), create a draft, add a drink row, and go
      live; the open socket receives a `snapshot` for the run without reconnecting;
    - fake-clock ticks advance `version` at the run's `tick_interval_ms`;
    - each 409 changes nothing (`engine_state` count 0, status `draft`);
    - with `auto_calibrate_s0`, every `drink.s0` equals the anchor and exactly one revision is
      added;
    - the CLI path still works with the app down;
  - `./scripts/check.sh`.
- **Depends on:** T8, T7 (`holder.py`, `publish.py`)
- **Autonomy note:**
  - **May decide alone:** method names, whether the snapshot fan-out is a hub method.
  - **Must stop and ask if:** the ticker cannot be re-anchored without stopping its task, or
    the advisory-lock watchdog's interval must change (it keeps the boot interval; see R12).

### T10 — Config: read and draft writes

- **Implements:** AC2 (server, empty body), AC3 (server), AC11, AC13 (draft), AC28 (422);
  AC43, AC40 (rows); SD5, SD6, SD8, SD11; PD4, PD6, PD7
- **Expected output:**
  - **Validation:** `app/runtime/config.py` defines the SD8 PATCH model: every field optional,
    `extra="forbid"`. An explicit `null` is 422 naming the field (a `model_validator` over
    `model_fields_set`). Every float must be finite, and every SD8 range holds.
    `candle_interval_s` is 5–3600 in steps of 5. `idle_*_targets` are active `drink_id`s
    (PD7).
  - **The document:** `config_document(conn, run_id)` builds the `GET` body, which is also the
    revision document.
  - **The routes** (`app/api/config.py`, admin):
    - `GET /api/runs/{run_id}/config`;
    - `PATCH /api/runs/{run_id}/config` for a **draft**:
      - `SELECT … FOR UPDATE` on `run`, merge only the present keys into `run.params`;
      - update `name` and `candle_interval_ms`;
      - append a revision only if something changed;
      - return `{revision}`.

      An empty body returns the current revision and writes nothing. An ended run is 409
      `run_ended`. A live run returns 409 until T11.
  - **The revision lock:** `append_config_revision` takes the `run` row lock before
    `max + 1` (SD6).
  - Matrix and draining rows; `schema.d.ts`.
- **Verification:** `uv run pytest tests/api/test_config.py tests/integration/test_config_draft.py tests/api/test_authorization_matrix.py tests/api/test_draining.py -v`:
  - `{}` and `{"params": {}}` give 200 with an unchanged revision count;
  - `{"params": {"eta": null}}` is 422 with `faults[].loc` naming `eta`, and nothing is
    stored;
  - `bm_sigma_y`, NaN, `decay_rho: 1.5` and `candle_interval_s: 7` are each 422 naming the
    field;
  - two concurrent PATCHes of different fields both persist, with consecutive revisions;
  - the same field gives the later value;
  - 50 concurrent PATCHes give revisions 2..51 with no gap or collision (AC13).
- **Depends on:** T9 (shared `runs.py`, `main.py`, matrix, `schema.d.ts`)
- **Autonomy note:**
  - **May decide alone:** model names, how ranges are expressed (pydantic `Field` vs
    validators).
  - **Must stop and ask if:** any SD8 range is ambiguous for a field (for example whether
    `refresh_minutes` 0.1 is inclusive).

### T11 — Config: live writes

- **Implements:** AC8 (`step_quant`), AC9 (scalars), AC10 (`step_quant` jumps), AC12, AC13
  (live), AC28 (re-bucket); SD7, SD9, SD10; PD5, PD18
- **Expected output:**
  - `PATCH config` on the live run is one `holder.mutate("config", step)`, in one transaction:
    - run row lock, params/name/candle update;
    - the revision;
    - `compare_and_set` to `version + 1`;
    - `insert_tick(source="config")`.
  - A `step_quant` change is `hold_quoted_prices` over every active slot (its jumps
    cancelled). Any other param leaves `y` untouched.
  - The outcome's view carries the new spec, `candle_interval_ms` and the tick. It emits
    `ConfigChanged`.
  - The publisher rebuilds its candle book when the interval changed. The snapshot's
    `bars_from_ring` re-buckets from the ring.
  - A `history_window_minutes` change resizes the ring and the hub's replay window going
    forward (PD18).
  - An empty body writes nothing and takes no transition.
- **Verification:** `uv run pytest tests/integration/test_config_live.py tests/api/test_config.py -v`:
  - a scalar change (`eta`, `K`, `demand_enabled`) leaves `y.tobytes()` unchanged, with
    `version + 1`, one tick of source `config`, one revision (`author` = label) and one
    `config` frame on a connected socket;
  - a `step_quant` change from 0.5 to 0.1 holds every quoted price, and cancels a running
    jump and a market event's jumps;
  - a candle change to 30 s gives a snapshot whose `bars` are 30 s buckets;
  - two concurrent live PATCHes give consecutive revisions;
  - `grep` confirms no golden scenario calls config (R15).
- **Depends on:** T10, T3
- **Autonomy note:**
  - **May decide alone:** how the ring resize is threaded (an `Outcome` field or a holder
    hook).
  - **Must stop and ask if:** the transition cannot stay "pure numpy plus one short
    transaction" under the lock (architecture.md), or a `step_quant` hold changes any golden
    test.

### T12 — Drinks: add

- **Implements:** AC4 (server defaults), AC14, AC21 (duplicate on add; re-add gets a new id),
  AC11 (resulting row), AC12; AC43, AC40 (rows); SD5, SD12, SD17
- **Expected output:**
  - `POST /api/runs/{run_id}/drinks` (`app/api/drinks.py`, admin). Absent optional fields take
    `bar_price_cents = p0_cents`, `a = 10`, `d = 0.6`, `s0 = 8`, `c = 0.4`. A `null` is 422.
    The checks are `p_min_cents ≥ 0`, `p_min < p0 < p_max`, `bar ≥ 0`, a finite coefficient
    and a name of 1–40 characters.
  - The new `slot` is `max(slot) + 1` over every row of the run, removed ones included.
  - **Draft:** insert plus revision.
  - **Live:** one `mutate("config")`. The spec is rebuilt from every row and the state is
    `append_slot(...)`. It writes a CAS at `version + 1`, a `config` tick and a revision, and
    emits `ConfigChanged`. `bar_price_cents` is extended.
  - A duplicate active `name_key` is 409 `duplicate_drink_name` (reuse `add_drink`'s
    mapping).
- **Verification:** `uv run pytest tests/api/test_drinks.py tests/integration/test_drink_lifecycle.py -v`:
  - add with blanks stores the defaults;
  - live add mid-run (after scripted orders, a running jump and a Brownian draw) leaves every
    existing drink's `y`, `cum_orders`, `flow_ema`, `last_order_ts`, jumps, `rng_counter` and
    earnings bitwise unchanged;
  - the new drink quotes `p0`;
  - "  BIER " beside an active "Bier" is 409;
  - matrix and draining rows.
- **Depends on:** T11, T3
- **Autonomy note:**
  - **May decide alone:** module split between `app/runtime/drinks.py` and
    `app/runtime/config.py`.
  - **Must stop and ask if:** the new slot's history entries cannot be represented in the ring
    (earlier ticks lack its key) without a protocol change.

### T13 — Drinks: edit

- **Implements:** AC8 (bounds), AC9 (`a/d/s0/c`, `p0`, bar price), AC10, AC11, AC21 (rename),
  AC22 (rename), AC2 (empty drink PATCH); AC43, AC40 (rows); SD5, SD9, SD11, SD17
- **Expected output:** `PATCH /api/runs/{run_id}/drinks/{drink_id}` with `PATCH config`'s
  rules. Validation is on the *resulting* row. A removed drink is 409 `drink_removed`.
  - **Draft:** update plus revision.
  - **Live:** one `mutate("config")`.
    - `p_min`/`p_max` changed: `hold_quoted_prices` on that slot, which cancels its jump.
    - Otherwise no `y` moves.
    - A rename rewrites the name in both idle-target lists in the same transaction.
    - A duplicate name is 409.
- **Verification:** `uv run pytest tests/api/test_drinks.py tests/integration/test_drink_lifecycle.py -v`:
  - a bound change holds the quote clamped and requantised, and leaves other drinks' `y`
    bitwise equal;
  - a running jump on that drink is cancelled in the same version;
  - a coefficient change leaves all `y` unchanged;
  - `{"p_min_cents": 300}` against `p0 = 250` is 422 naming `p_min_cents`, and nothing is
    stored;
  - rename "Bier" to "Pils" with "Bier" in `idle_targets` gives `["Pils"]`;
  - `{}` writes no revision.
- **Depends on:** T12
- **Autonomy note:**
  - **May decide alone:** the error message text.
  - **Must stop and ask if:** a `p0` change on a live run would require moving `y` (SD9 says
    it must not).

### T14 — Drinks: remove

- **Implements:** AC15, AC17, AC18, AC20 (restart), AC22 (removal), AC23 (server, totals);
  AC43, AC40 (rows); SD13, SD15, SD16
- **Expected output:** `DELETE /api/runs/{run_id}/drinks/{drink_id}`.
  - **Draft:** a hard delete plus revision.
  - **Live:** one `mutate("config")`:
    - `removed_at = now()`;
    - the spec is rebuilt with the slot masked;
    - `cancel_jumps` on that slot, a market event's jump included;
    - the drink is dropped from both idle lists;
    - CAS, `config` tick, revision, `ConfigChanged`.
  - Removing the last active drink is 409 `last_active_drink` and changes nothing.
- **Verification:** `uv run pytest tests/integration/test_drink_lifecycle.py tests/api/test_drinks.py -v`. The spec's scripted borrel:
  - orders on three drinks, then add D4, then remove D2:
    - other drinks' `y` bitwise unchanged across the removal;
    - D2's `order_line` rows and revenue are still in `earnings_by_drink` and in the
      snapshot's `earnings`;
    - Σ `line_total_cents` unchanged;
  - `rehydrate` on the committed database equals holder memory, slot for slot and bitwise
    (AC20);
  - D2 is re-added as a new `drink_id` (AC21);
  - removing the last active drink is 409 with no row change.
- **Depends on:** T13, T6
- **Autonomy note:**
  - **May decide alone:** test scenario lengths.
  - **Must stop and ask if:** the restart check needs a real process. Use
    `harness.spawn_app` (urllib) and stop if it is flaky; do not fall back to `TestClient`.

### T15 — Anchor s0

- **Implements:** AC16 (the anchor's mean over active drinks, end to end), AC12; AC43, AC40
  (rows); SD5, SD26
- **Expected output:** `POST /api/runs/{run_id}/anchor-s0` (admin, live only; a draft is 409
  `run_not_live`). One `mutate("config")`: `anchor_s0_to_current_y` on the masked spec,
  writing every active drink's `drink.s0`, the revision, `version + 1` and a `config` tick. No
  `y` moves.
- **Verification:** `uv run pytest tests/api/test_anchor_s0.py -v`:
  - with one drink removed, each active `s0` equals the formula with the active mean;
  - the removed drink's `s0` is unchanged;
  - `y` is bitwise unchanged;
  - draft is 409;
  - matrix and draining rows.
- **Depends on:** T14
- **Autonomy note:**
  - **May decide alone:** response shape (`{revision}`).
  - **Must stop and ask if:** SD26's "no confirmation" conflicts with any server-side check.

### T16 — Keys and connections

- **Implements:** AC36, AC37, AC38, AC41 (server half); AC43, AC40 (rows); SD30, SD31; PD12
- **Expected output:**
  - **Shared issuing:** `issue_key(conn, *, role, label) -> str` lives in
    `app/api/security.py`, moved from `app.cli.keys.create`, which now calls it. The secret is
    returned once; only the argon2 hash is stored.
  - **The key routes** (`app/api/keys.py`, admin, draining on writes):
    - `GET /api/keys` lists `{key_id, label, role, created_at, last_used_at, revoked}`, never a
      hash;
    - `POST /api/keys {role, label}` returns `{key_id, key}` once;
    - `DELETE /api/keys/{key_id}` revokes. Revoking the last unrevoked admin is 409
      `last_admin_key`, checked under `SELECT … FOR UPDATE` of the admin rows. An unknown key
      is 404 `key_not_found`.
  - **Closing sockets:** `hub.connect(socket, principal)` records `key_id`, role, label,
    `connected_at_ms` and `last_seen_ms` (updated per client frame). `hub.close_key(key_id,
    4401)` runs after the revoke commits.
  - **Connections:** `GET /api/admin/connections` (admin) returns
    `[{role, label, connected_at_ms, last_seen_ms}]`.
- **Verification:** `uv run pytest tests/api/test_keys.py tests/api/test_connections.py tests/api/test_ws_revoke.py tests/integration/test_cli_keys.py -v`:
  - create, then `SELECT secret_hash` starts `$argon2id$` and never equals the secret, and the
    list has no secret;
  - an open WS for a revoked key closes with 4401 within 1 s on the fake clock;
  - that session's next HTTP request is 401;
  - revoking the last admin is 409;
  - connections lists a connected display;
  - matrix rows;
  - the CLI tests are unchanged.
- **Depends on:** T15 (shared files: `main.py`, matrix, `schema.d.ts`), T9 (`hub.py`, `ws.py`)
- **Autonomy note:**
  - **May decide alone:** where `last_seen_ms` is stamped.
  - **Must stop and ask if:** the WS test reproduces the Phase 3 `CancelledError` flake (memory
    note). Report it; do not retry until green.

### T17 — Custom theme

- **Implements:** AC29 (server manifest), AC30 (server); AC40 (theme writes); SD28; PD8
- **Expected output:**
  - **Manifest:** `PresetName` gains `custom`. `Theme` resolves `custom` from the stored
    tokens and font (`inter` gives `_INTER`, `garamond` gives `_GARAMOND`). A
    `HEX = ^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$` check holds for every preset value too.
  - **Storage:** `set_theme` stores tokens and font.
  - **The route:** `PUT /api/theme` takes PD8's body.
  - **Messages and boot:** `ThemeData.preset` accepts `custom`; `boot._stored_theme` loads it.
  - **Web and generated files:** `schemas.ts` `PresetName` gains `custom`; `schema.d.ts` is
    regenerated.
- **Verification:** `uv run pytest tests/api/test_theme.py tests/unit/test_theme_manifest.py tests/api/test_ws_theme.py tests/integration/test_theme_repo.py -v`:
  - saving 24 tokens and `garamond` gives a `/theme.css` with all 24 values and the Garamond
    stack, and one `theme` broadcast with a higher revision;
  - `"red"` or `#12345` is 422;
  - a missing or extra token is 422;
  - `custom` with none stored is 409;
  - every preset value matches `HEX`.
- **Depends on:** T16 (shared files), T4 (`theme.py` API), T9 (`boot.py`), T7 (`messages.py`,
  `schemas.ts`)
- **Autonomy note:**
  - **May decide alone:** storage shape of `custom_tokens` (object keyed by token name).
  - **Must stop and ask if:** any preset value fails `HEX`. It would not reach `/theme.css`;
    that is a manifest question.

### T18 — Image uploads and serving

- **Implements:** AC31, AC32, AC33, AC34; AC43, AC40 (rows); SD29; PD1, PD10
- **Expected output:**
  - **Pure helpers** in `app/runtime/images.py`:
    - `sniff(prefix: bytes) -> content_type | None` for PNG, JPEG, WebP and GIF by magic
      bytes;
    - `read_limited(chunks, limit)` raises `TooLarge` as soon as the running total passes the
      limit, consuming at most one chunk beyond it.
  - **The repository:** `app/db/assets.py`.
  - **Upload:** `POST /api/theme/images/{slot}` (admin, draining):
    - the body is `multipart/form-data` with one file field `file` (PD1 (b), `python-multipart`,
      added to `pyproject.toml`/`uv.lock` in this task);
    - a `Content-Length` over 5 MB is 413 `too_large` before any read; otherwise the request
      stream passes through `read_limited` before it reaches the multipart parser, so a file
      part can never be buffered past the limit (the parser itself caps nothing);
    - `sniff` failing is 415 `unsupported_media_type`;
    - one transaction then inserts the asset (sha256, bytes), points the slot at it, deletes
      the slot's previous asset and bumps the theme revision (upserting the row if absent);
    - it then broadcasts `theme` and replaces `app.state.theme`.
  - **Removal:** `DELETE /api/theme/images/{slot}` nulls the pointer, deletes the asset and
    bumps the revision.
  - **Serving:** `GET /assets/{asset_id:int}` is public: the stored type, `nosniff`, `CSP
    default-src 'none'`, `Cache-Control: public, max-age=31536000, immutable`, or 404.
  - **Registration:** `tests/meta/test_route_authorization.py` allowlists it.
    `web/vite.config.ts` proxies it in dev (PD10).
- **Verification:** `uv run pytest tests/unit/test_images.py tests/api/test_assets.py tests/api/test_static.py tests/meta/test_route_authorization.py tests/api/test_authorization_matrix.py -v`:
  - an SVG named `.png` with `Content-Type: image/png` is 415, and the `asset` count is 0;
  - each of the four types is accepted;
  - a 6 MB multipart body with `Content-Length` is 413 with no bytes read;
  - a 6 MB chunked multipart generator without `Content-Length` is 413, and the unit test of
    `read_limited` asserts at most `limit + chunk` consumed;
  - the headers on `GET`;
  - replacing and then removing leaves `SELECT count(*) FROM asset WHERE asset_id NOT IN
    (slot pointers) = 0`;
  - `/assets/x.js` still serves the bundle file (`test_static.py`).
- **Depends on:** T17 (PD1 answered: (b))
- **Autonomy note:**
  - **May decide alone:** chunk size, error message text.
  - **Must stop and ask if:** the bounded read cannot sit in front of the multipart parser
    (i.e. AC33's "5 MB + one chunk" cannot hold), or any dependency beyond `python-multipart`
    is needed.

### T19 — Images reach every machine; koers `has-promo`

- **Implements:** AC35; the delivery half of AC30 (fonts and tokens unchanged); SD29; PD9
- **Expected output:**
  - **Server:**
    - `ThemeData.images` (`hello` and `theme` carry it);
    - `render_css` emits PD9's variables and rules;
    - `ws_fixture` and the fixture JSON are regenerated;
    - `schemas.ts` gains `images`.
  - **Web:**
    - `ThemeProvider` sets or removes `--img-*`;
    - `components/ui/Logo.tsx` replaces the `<img>` in `AppShell` and `LoginPage`;
    - koers renders the promo tile and adds the `has-promo` class to its container when
      `images.promo` is set (v1's `koers.html:76-79` grid).
- **Verification:**
  - `uv run pytest tests/api/test_theme.py tests/api/test_ws_theme.py tests/api/test_ws_fixture.py -v`: `/theme.css` with a logo and a promo contains both URLs,
    and `hello.theme.images` matches;
  - `pnpm --dir web exec vitest run src/features/theme src/features/koers src/components/ui/Logo.test.tsx`:
    - a theme with `images.promo` gives the container class `has-promo` and an
      `img[alt="Promotie"]`;
    - its removal drops both;
    - `ThemeProvider` removes `--img-logo` when it is null.
- **Depends on:** T18, T36 (`KoersPage.tsx`)
- **Autonomy note:**
  - **May decide alone:** CSS details, the `Logo` component's markup.
  - **Must stop and ask if:** the header slot has no element to paint on in the v2 shell.
    Report what v1 painted (`theme.js` `header{background-image}`).

### T20 — `lib/http`: `PATCH` and form bodies

- **Implements:** the transport halves of AC1/AC2 (`PATCH` with a dirty-only body) and AC31
  (upload); PD1
- **Expected output:** `Method` gains `PATCH`. `request` gains `formData?: FormData` (PD1 (b));
  the browser sets the multipart boundary header. `body` and `formData` are mutually exclusive
  (a type error).
- **Verification:** `pnpm --dir web exec vitest run src/lib/http.test.ts`:
  - `PATCH` sends JSON;
  - `formData` sends the form with no JSON `Content-Type` header;
  - the existing cases pass.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** option names.
  - **Must stop and ask if:** an existing caller changes behaviour.

### T21 — `Field`, `NumberField`, `MoneyField`, and the lint rules

- **Implements:** AC1, AC3 (client), AC39 (no native dialogs); SD27; PD16
- **Expected output:**
  - **Parsing:** `lib/format.ts: parseEuroCents(text) -> number | null | 'invalid'`:
    - `""` gives `null`;
    - "2,50" and "2.50" give 250;
    - "2" gives 200;
    - more than two decimals, two separators or a sign gives `'invalid'`;
    - it is exact by string parsing, never `parseFloat(x) * 100`.
  - **The fields** in `components/ui`:
    - `Field` (label, hint, error);
    - `NumberField` (controlled; `value: number | null`; empty gives `null`; no `placeholder`
      prop accepts a number; the raw string stays inside);
    - `MoneyField` (cents in and out, through `parseEuroCents`).

    An invalid entry reports `invalid` to its owner and never a number.
  - **Lint (PD16):** a unary-`+` ban, and a `confirm`/`alert`/`prompt` ban.
- **Verification:**
  - `pnpm --dir web exec vitest run src/lib/format.test.ts src/components/ui/NumberField.test.tsx src/components/ui/MoneyField.test.tsx src/lint-rules.test.ts`:
    - empty gives `null`;
    - "2,50" gives 250;
    - "2,505" is invalid;
    - an untouched field reports no change;
    - `+el.value` in a feature file is flagged;
    - `window.confirm('x')` is flagged;
  - `pnpm --dir web lint`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** component props, CSS.
  - **Must stop and ask if:** the unary-`+` ban flags existing non-test code (none today).

### T22 — `Select`, `Switch`, `Toast`, `MobileSectionNav`

- **Implements:** AC2 ("Niets te wijzigen" is shown by `Toast`); SD25, SD27
- **Expected output:**
  - Four components in `components/ui`. `MobileSectionNav` takes `[{id, label}]` and renders
    in-page links, or a `Select` at ≤ 800 px.
  - `useMediaQuery` moves from `features/bar` to `src/lib` (bar re-imports it, as Phase 5 PD14
    did for the chart theme).
- **Verification:** `pnpm --dir web exec vitest run src/components/ui src/features/bar/RevenueChart.test.tsx`:
  - a `Toast` shows its text and hides after its timeout (fake timers);
  - `Switch` toggles `aria-checked`;
  - the nav renders a select when `matchMedia` matches.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the breakpoint, the toast duration.
  - **Must stop and ask if:** moving `useMediaQuery` changes a bar test expectation.

### T23 — `useEditableRecord`

- **Implements:** AC1 (dirty-only body), AC2 (no request when clean), AC5; SD27
- **Expected output:**
  - `lib/useEditableRecord(server: T | null)` returns `{values, set(field, v), dirty, patch,
    reset, conflict, takeServer}`:
    - `patch` holds only the fields whose value differs from the server copy;
    - while not dirty, a new `server` replaces `values`;
    - while dirty, a different `server` sets `conflict` and keeps `values`;
    - `takeServer` discards the edits.
  - `save(send)` calls `send(patch)` only when `patch` is non-empty, and otherwise returns
    `'nothing'` for the caller's "Niets te wijzigen".
- **Verification:** `pnpm --dir web exec vitest run src/lib/useEditableRecord.test.ts`:
  - an untouched record gives `save` → `'nothing'` with `send` never called;
  - one edited field gives a patch with exactly that key;
  - a field edited back to its server value is not dirty;
  - a server change while clean reloads;
  - a server change while dirty sets the conflict and keeps the input, and `takeServer` loads
    the server values.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the hook's internals, the equality rule for `null`.
  - **Must stop and ask if:** it needs a library.

### T24 — Settings shell, the Borrel section, and section stubs

- **Implements:** AC24 (UI), AC25 (UI), AC39 (go-live wording); SD4, SD25; PD2, PD13
- **Expected output:**
  - `features/settings`:
    - `SettingsLayout` (sections plus `MobileSectionNav`);
    - `useCurrentRun` (`GET /api/runs/current`, refetched on a `config` or snapshot store
      change);
    - `BorrelSection`:
      - "Geen borrel" with a "Nieuwe borrel" name form, which opens the draft on 409
        `draft_exists`;
      - name and status otherwise;
      - for a draft, "Live zetten" behind `ConfirmDialog` "'{name}' live zetten?";
      - 409 codes shown in Dutch;
    - one stub file per later section (Systeemacties, Globale instellingen, Kleurenschema,
      Afbeeldingen, Drankjes beheren, Min/Max/Startprijs, Vraag/Aanbod), each "Nog niet
      beschikbaar".
  - `ThemeSection` moves here (into the Kleurenschema stub's place, still the preset picker).
  - `features/keys` holds a `KeysSection` stub.
  - `app/pages/SettingsPage.tsx` composes them.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings src/features/keys src/app`:
  - with `current` 404, "Geen borrel" and the form;
  - submit posts `{name}`;
  - 409 `draft_exists` loads that run;
  - "Live zetten" opens the dialog with the exact text, Cancel sends nothing and Confirm posts
    go-live;
  - nine sections are listed in the nav;
  - the moved `ThemeSection` tests pass.
- **Depends on:** T9, T20, T22
- **Autonomy note:**
  - **May decide alone:** layout, stub wording, file names inside the feature.
  - **Must stop and ask if:** the boundaries rule refuses the composition PD13 describes.

### T25 — Globale instellingen

- **Implements:** AC1, AC2, AC3, AC5 (this section), AC28 (UI); SD8, SD25, SD27
- **Expected output:** a form over SD8's scalar params plus `candle_interval_s`, each field a
  `NumberField` with v1's label. `useEditableRecord` is fed by `GET config` and refetched on
  `config`. Save sends `PATCH config {params: dirty}` (and `candle_interval_s` at the top
  level). It shows "Niets te wijzigen" when clean and "Serverwaarden gewijzigd — overnemen?"
  on a conflict. Server 422 faults map to their field.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/GlobalSection.test.tsx`:
  - save untouched sends nothing and shows "Niets te wijzigen";
  - editing `eta` gives the body `{params:{eta:…}}` only;
  - a cleared field blocks save;
  - a `config` dispatch while dirty shows the banner, and "Overnemen" loads the server values;
  - a 422 on `candle_interval_s` shows under that field.
- **Depends on:** T24, T11, T21, T23
- **Autonomy note:**
  - **May decide alone:** field order, hints.
  - **Must stop and ask if:** a v1 label is missing for an SD8 field.

### T26 — Drankjes beheren

- **Implements:** AC4 (UI), AC17 (UI error), AC21 (UI error), AC39 (remove wording); SD13,
  SD25
- **Expected output:**
  - An add form: name, three `MoneyField` bounds, optional bar price and `a/d/s0/c`. Blank
    optionals are omitted from the body.
  - Per active drink: rename, bar price (dirty-only `PATCH`), and "Verwijderen" behind
    `ConfirmDialog` "'{name}' verwijderen?".
  - 409 `last_active_drink` and `duplicate_drink_name` are shown in Dutch.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/DrinksSection.test.tsx`:
  - add with only name and bounds gives a body with exactly those four keys (AC4);
  - "2,50" is sent as 250;
  - Cancel on remove sends nothing; Confirm sends `DELETE`;
  - the 409s show their messages.
- **Depends on:** T24, T14, T21, T23
- **Autonomy note:**
  - **May decide alone:** the Dutch error wording for the 409s.
  - **Must stop and ask if:** the spec's wording for an error is needed and absent.

### T27 — Min/Max/Startprijs

- **Implements:** AC1, AC3, AC11 (UI) for bounds; SD25
- **Expected output:** a table of active drinks with `MoneyField`s for `p_min`, `p0` and
  `p_max`. Each row is its own `useEditableRecord`; save sends one `PATCH` per dirty row with
  only its dirty fields. A `p_min < p0 < p_max` hint is checked client-side and the server's
  422 is shown.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/BoundsSection.test.tsx`:
  - untouched sends nothing;
  - one edited `p_max` sends one `PATCH` with `{p_max_cents}`;
  - an invalid order blocks save.
- **Depends on:** T24, T13, T21, T23
- **Autonomy note:**
  - **May decide alone:** per-row vs section save button.
  - **Must stop and ask if:** —

### T28 — Vraag/Aanbod (the D-03 gate)

- **Implements:** AC1, AC2 (the D-03 gate), AC3, AC5; SD25, SD27
- **Expected output:**
  - **The gate comes first.** A failing component test is written and committed before the
    section: load a config snapshot, click save without editing, assert no request; edit one
    `a`, assert the body is exactly `{a: …}` to that drink's `PATCH`.
  - **The section:** the `demand_enabled` and `auto_calibrate_s0` switches (`PATCH config`),
    and the `a/d/s0/c` table (per-drink `PATCH`).
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/DemandSection.test.tsx`. The PR shows the gate test failing on its first commit against the stub,
  then passing.
- **Depends on:** T24, T13, T11, T21, T23
- **Autonomy note:**
  - **May decide alone:** table layout.
  - **Must stop and ask if:** the gate cannot be expressed without mocking
    `useEditableRecord`. It must run the real hook.

### T29 — Systeemacties

- **Implements:** AC39 (shutdown wording); SD26
- **Expected output:**
  - "⛔ Sluit app" opens `ConfirmDialog` "Applicatie nu afsluiten?", then calls `POST
    /api/admin/shutdown` and shows "App sluit nu af…" with every control disabled.
  - "📌 Zet huidige prijs als evenwicht" calls `POST …/anchor-s0` with no confirmation and is
    disabled for a draft.
  - No reset, no export.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/SystemSection.test.tsx`:
  - Cancel sends nothing; Confirm posts and disables every button;
  - anchor posts once.
- **Depends on:** T24, T15
- **Autonomy note:**
  - **May decide alone:** layout.
  - **Must stop and ask if:** —

### T30 — Kleurenschema editor

- **Implements:** AC29, AC30 (UI); SD28
- **Expected output:**
  - The preset picker lists all five presets (Oud Geld included) and "Eigen" when stored.
  - The editor starts from a chosen preset's tokens (from the store's `theme.tokens` when
    that preset is active, else fetched by selecting).
  - It lists **every key of `theme.tokens`**, each with a colour input and a hex text field
    validated by SD28's pattern, plus the font choice.
  - "Opslaan" sends PD8's body.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/ThemeEditor.test.tsx`:
  - the test reads `TOKEN_NAMES` from `app/runtime/theme.py` with a regex over the tuple
    literal and asserts a row per name (AC29: derived, not hard-coded);
  - an invalid hex disables save;
  - save sends 24 tokens and the font.
- **Depends on:** T24, T17
- **Autonomy note:**
  - **May decide alone:** how a non-active preset's tokens are obtained, as long as the client
    holds no preset table (Phase 4 SD6). If that is impossible without one, stop and ask (R19).
  - **Must stop and ask if:** see above.

### T31 — Afbeeldingen

- **Implements:** AC31/AC33 (UI errors), AC34 (UI), AC39 (remove wording); SD29
- **Expected output:**
  - Four slots (Achtergrond, Header, Logo, Promotie tegel), each with a preview from the
    store's `theme.images`, a file input (upload per PD1) and "Verwijderen" behind
    `ConfirmDialog` "'{slot label}' verwijderen?".
  - 413 and 415 are shown in Dutch.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/ImagesSection.test.tsx`:
  - choosing a file posts its bytes to the slot's URL;
  - Cancel on remove sends nothing;
  - the 415 message is shown.
- **Depends on:** T24, T18, T20, T19 (`images` in the store)
- **Autonomy note:**
  - **May decide alone:** the Dutch error text.
  - **Must stop and ask if:** —

### T32 — Toegangssleutels

- **Implements:** AC36 (UI), AC38 (UI), AC39 (revoke wording); SD30
- **Expected output:**
  - `features/keys/KeysSection`: a list (label, role, created, last used, Actief/Ingetrokken).
  - "Nieuwe sleutel" (role, label 1–100) shows `bb_…` once with "Kopieer" and "Wordt maar één
    keer getoond"; the value leaves component state on close.
  - "Intrekken" sits behind "'{label}' intrekken?"; `last_admin_key` is shown.
- **Verification:** `pnpm --dir web exec vitest run src/features/keys`:
  - after create, the key is shown once; after close and re-render it is absent from the DOM;
  - "Kopieer" calls `navigator.clipboard.writeText` (mocked);
  - Cancel on revoke sends nothing;
  - 409 shows the message.
- **Depends on:** T24, T16
- **Autonomy note:**
  - **May decide alone:** the date format.
  - **Must stop and ask if:** —

### T33 — Manipulation: news, market events, price jump

- **Implements:** AC6 (UI), AC39 (news delete, events), AC7 (bar sees no Idle; the page
  structure); SD20, SD21, SD22, SD23
- **Expected output:** `features/manipulation/ManipulationPage({canEditIdle})`, routed from
  `routes.tsx`. Every section re-renders from the store.
  - **📰 Nieuws:** the list, newest first; "Toevoegen" (text 1–500, a level select with Dutch
    labels, sent lowercase); "Verwijderen" behind "'{first 40}' verwijderen?".
  - **💥 Market events:**
    - "Duur (seconden)", default 30, 1–600;
    - three buttons, each behind its SD22 confirmation;
    - the status "{kind} gestart!";
    - the remaining seconds from the store's `marketEvents` and the skew.
  - **⚡ Price jump:**
    - an active-drink select;
    - "Doelprijs (€)" (`MoneyField`) with a `[p_min, p_max]` hint. The hint's bounds come from
      `GET config`, which is admin-only; a bar session shows no hint and relies on the server's
      422;
    - "Duur (seconden)", default 5, 1–1800;
    - "Start jump" is disabled until every field parses.
  - An `IdleSection` stub renders only when `canEditIdle`.
- **Verification:** `pnpm --dir web exec vitest run src/features/manipulation src/app`:
  - an empty or "abc" target leaves "Start jump" disabled with no request;
  - each event's dialog text is exact, and Cancel sends nothing;
  - news delete wording;
  - `canEditIdle=false` renders no Idle heading;
  - the drink select updates on a `config` dispatch removing a drink.
- **Depends on:** T6, T7, T21, T22
- **Autonomy note:**
  - **May decide alone:** the name and shape of a remaining-seconds selector, added to
    `features/exchange/model/selectors.ts` and exported. Do not edit `features/koers/**`:
    T36 writes koers in the same group (Out of scope: koers adopting it later).
  - **Must stop and ask if:** a hint for bar needs a new bar-readable route (that would be
    scope).

### T34 — Manipulation: Idle (admin)

- **Implements:** AC7 (admin side), AC22 (UI shows the renamed or removed list), AC1/AC2
  (section); SD11, SD20
- **Expected output:** `IdleSection`: the decay/rise minutes and strengths (`NumberField`), and
  checkboxes over active drinks for both target lists, sent as `drink_id`s. It is a dirty-only
  `PATCH config`.
- **Verification:** `pnpm --dir web exec vitest run src/features/manipulation/IdleSection.test.tsx`:
  - ticking one drink sends `{params:{idle_targets:[id]}}` only;
  - untouched sends nothing;
  - a `config` dispatch removing a drink drops its checkbox.
- **Depends on:** T33, T11, T23
- **Autonomy note:**
  - **May decide alone:** layout.
  - **Must stop and ask if:** —

### T35 — Home hub

- **Implements:** AC41; AC25 (home shows the new run); SD31; PD14
- **Expected output:**
  - `features/home/HomePage`, routed at `/`:
    - four tiles with v1's blurbs (drinks and shutdown attributed to settings);
    - a "Status" panel with `StatusDot`s for:
      - the socket: Verbonden / Verbinden… / Offline, plus the age from `lastFrameAt`;
      - the run: from `GET /api/runs/current` plus the store `quote.version` plus `/healthz`
        `last_tick_age_ms`, or "Geen actieve borrel";
      - server health: `/healthz` every 5 s;
      - connections per role: `/api/admin/connections` every 5 s.
  - With zero display connections during a live run it shows "Koersbord niet verbonden" in
    `--warn`.
  - Every fetch rejection is caught; polling stops on unmount.
  - `applyMessage` sets `lastFrameAt`.
- **Verification:** `pnpm --dir web exec vitest run src/features/home src/features/exchange/model/applyMessage.test.ts`:
  - with fetch mocked to reject, no unhandled rejection (a `process.on('unhandledRejection')`
    spy stays uncalled);
  - live run with connections `[{role:'bar'}]` shows "Koersbord niet verbonden";
  - with a display, it is gone;
  - fake timers show polling at 5 s.
- **Depends on:** T16, T8, T33 (`routes.tsx`), T7 (`applyMessage.ts`)
- **Autonomy note:**
  - **May decide alone:** layout.
  - **Must stop and ask if:** v1's tile blurbs cannot be found in `legacy/v1/static/home.html`.

### T36 — Koers shows active drinks

- **Implements:** AC23 (koers), AC42 (regression); SD18
- **Expected output:** `KoersPage` and `PriceMarquee` render `selectActiveDrinks`. A drink
  removed by `config` loses its tile without a remount of the others (keyed by `drink_id`).
- **Verification:** `pnpm --dir web exec vitest run src/features/koers`:
  - a `config` dispatch removing a drink removes one tile and keeps the other tiles' DOM
    nodes;
  - the existing `MarketEventLayer.test.tsx` "correction" case asserts the calm banner, not
    the pulsing overlay (the builder adds the assertion if missing).
- **Depends on:** T7
- **Autonomy note:**
  - **May decide alone:** —
  - **Must stop and ask if:** the correction regression fails. That is a Phase 4 defect.

### T37 — Bar: removed drinks

- **Implements:** AC19 (bar message), AC23 (bar); SD13, SD18
- **Expected output:**
  - `OrderPad` renders active drinks only.
  - `FinancialPanel` lists a removed drink with sales as "{name} (verwijderd): {qty}× — € x,xx";
    totals stay `selectTotals` (every drink).
  - `orderIntents` maps 422 `drink_unavailable` to a pending entry "{name} is niet meer
    beschikbaar".
- **Verification:** `pnpm --dir web exec vitest run src/features/bar`:
  - a `config` dispatch removing a drink removes its button;
  - the panel shows "(verwijderd)", and the total equals the sum of the store's earnings;
  - a 422 `drink_unavailable` shows the message;
  - `money.property.test.ts` stays green.
- **Depends on:** T7, T6
- **Autonomy note:**
  - **May decide alone:** the pending entry's lifetime (reuse Phase 5 PD7's 3 s).
  - **Must stop and ask if:** the money property test needs changing.

### T38 — Admin e2e from an empty database

- **Implements:** AC24, AC25, AC30, AC35, AC23, AC39, AC41 (in the browser, against the real
  server); the spec's Playwright list
- **Expected output:**
  - `serve.py --empty` (PD15).
  - `e2e/serverProcess.ts`, factored out of `global-setup.ts`.
  - `e2e/admin.spec.ts`, with its own server, logged in with the CLI-minted admin key:
    1. create a borrel;
    2. add three drinks;
    3. set params;
    4. pick a preset, then save a custom theme;
    5. upload a logo (a PNG fixture written by the test);
    6. create a display key and a bar key (read from the one-time display);
    7. go live.
  - Then:
    - a second context with the display key sees tiles, the custom `--bg` and the logo URL,
      with no reload after go-live;
    - a bar context is open; the admin removes a drink; its button disappears;
    - each destructive dialog has its cancel path;
    - `page.on('pageerror')` records nothing on `/`.
- **Verification:** `pnpm --dir web build && pnpm --dir web exec playwright test e2e/admin.spec.ts`, then `./scripts/check.sh`. Report the e2e step's total time; stop
  above 3 minutes (Phase 4 R6).
- **Depends on:** T24–T37, T19
- **Autonomy note:**
  - **May decide alone:** selectors (roles and text), test order.
  - **Must stop and ask if:** a second server cannot run beside the shared one (port, lock or
    database), or the suite passes the time budget.

### T39 — Documentation

- **Implements:** the spec's Documents list, which records the contracts that AC12, AC23, AC25,
  AC29 and AC35 rest on
- **Expected output:**
  - an ADR 0003 addendum (the single writer can adopt a run mid-process, under the state lock,
    SD3);
  - ADR 0005: "21 tokens" corrected to the manifest's 24 (SD28);
  - `realtime-protocol.md`: `config`, `active`, `images` in `theme`/`hello`, the replay-log
    clear on go-live;
  - `data-model.md`: `asset`, `run.name`, the theme columns, the `config` source;
  - `architecture.md`: the mask covers `mean_range`;
  - `phase-7-analytics.md`: create and go-live exist, reset stays in Phase 7;
  - the defect register: the D-44–D-48 rows are present (the working tree already adds them),
    each phase defect's Phase 6 evidence task is named.
- **Verification:** `./scripts/check.sh` (formatting), plus a human read of the diff.
- **Depends on:** T9, T7, T19
- **Autonomy note:** **`docs/design/` and product ADR text are a hard stop (ADR 0009).** The
  builder drafts the edits and **stops for human approval of the diff before committing**.
  Nothing else in the design docs changes.

---

## AC → task coverage

| AC | Tasks | | AC | Tasks |
|---|---|---|---|---|
| AC1 | T21, T23, T25, T27, T28, T34, T20 | | AC23 | T7, T14, T36, T37, T38 |
| AC2 | T10, T13, T22, T23, T25, T28, T34, T20 | | AC24 | T1, T8, T24, T38 |
| AC3 | T10, T12, T13, T21, T25, T27, T28 | | AC25 | T9, T24, T35, T38 |
| AC4 | T12, T26 | | AC26 | T9 |
| AC5 | T23, T25, T28 | | AC27 | T9 |
| AC6 | T6, T33 | | AC28 | T7, T10, T11, T25 |
| AC7 | T8–T18 (matrix rows), T33, T34 | | AC29 | T17, T30 |
| AC8 | T3, T11, T13 | | AC30 | T17, T19, T30, T38 |
| AC9 | T11, T13 | | AC31 | T18, T20, T31 |
| AC10 | T3, T11, T13 | | AC32 | T18 |
| AC11 | T10, T12, T13, T27 | | AC33 | T18, T31 |
| AC12 | T1, T7, T11, T12, T13, T14, T15 | | AC34 | T1, T18, T31 |
| AC13 | T10, T11 | | AC35 | T19, T38 |
| AC14 | T3, T12 | | AC36 | T16, T32 |
| AC15 | T2, T14 | | AC37 | T16 |
| AC16 | T2, T15 | | AC38 | T16, T32 |
| AC17 | T14, T26 | | AC39 | T21, T24, T26, T29, T31, T32, T33, T38 |
| AC18 | T3, T6, T14 | | AC40 | T4, T8–T18 (draining rows) |
| AC19 | T2, T6, T37 | | AC41 | T16, T35, T38 |
| AC20 | T5, T14 | | AC42 | T36 |
| AC21 | T12, T13, T26 | | AC43 | T8, T9, T10, T12, T13, T14, T15, T16, T18 |
| AC22 | T13, T14, T34 | | | |

Every AC maps to a task. Every task maps back to at least one AC. T39 maps to the contracts in
the spec's In-scope Documents list, as Phase 5's T18 did. No AC was left unmapped.

---

## Task graph

```
Group 1 (no dependencies):   T1, T2, T4, T20, T21, T22, T23
T3 ← T2                       T5 ← T1, T2
T6 ← T4, T5                   T7 ← T5
T8 ← T1, T4, T7               T36 ← T7          T37 ← T6, T7
T9 ← T7, T8                   T33 ← T6, T7, T21, T22
T10 ← T9                      T24 ← T9, T20, T22
T11 ← T3, T10                 T34 ← T11, T23, T33
T12 ← T3, T11                 T25 ← T11, T21, T23, T24
T13 ← T12                     T27, T28 ← T13 (+T11), T21, T23, T24
T14 ← T6, T13                 T26 ← T14, T21, T23, T24
T15 ← T14                     T29 ← T15, T24
T16 ← T9, T15                 T32 ← T16, T24    T35 ← T7, T8, T16, T33
T17 ← T4, T7, T9, T16         T30 ← T17, T24
T18 ← T17
T19 ← T18, T36                T31 ← T18, T19, T20, T24
T38 ← T19, T24–T37            T39 ← T7, T9, T19
```

**The server spine is a chain by necessity, not by caution:**

T1 → T5 → T7 → T8 → T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17 → T18 → T19.

Each link writes `web/src/api/generated/schema.d.ts` (the drift step forces a regeneration) and
`tests/api/test_authorization_matrix.py`, and most also write `app/db/runs.py`, `app/main.py` or
`tests/api/test_draining.py`. Several links also share `holder.py`/`publish.py` (T7, T9, T11),
`hub.py`/`ws.py` (T9, T16), and `messages.py`/`schemas.ts` (T7, T17, T19). The engine (T2, T3),
the web primitives (T20–T23) and every web feature task run beside it. Builders run one at a
time (ADR 0010 §1), so the groups give the merge order.

Shared files, ordered by dependency:
- `web/src/app/routes.tsx`: T33 → T35.
- `web/src/features/koers/KoersPage.tsx`: T36 → T19.
- `web/src/features/exchange/model/applyMessage.ts`: T7 → T35.
- `web/src/features/settings/*`: T24 creates every section file as a stub. T25–T31 each write
  only their own section file and its test.
- `web/src/features/keys/KeysSection.tsx`: T24 (stub) → T32.
- `web/src/features/manipulation/IdleSection.tsx`: T33 (stub) → T34.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T2, T4, T20, T21, T22, T23 | T1: 0009, `models.py`, `db/runs.py`, `cli/import_v1.py`, migration/schema/import tests, `create_draft_run` test call sites · T2: `exchange/{spec,steps,advance}.py`, `tests/engine/test_mask.py` · T4: `api/{deps,orders,news,market,theme}.py`, `tests/api/test_draining.py` · T20: `lib/http{,.test}.ts` · T21: `lib/format{,.test}.ts`, `components/ui/{Field,NumberField,MoneyField}*`, `eslint.config.js`, `lint-rules.test.ts` · T22: `components/ui/{Select,Switch,Toast,MobileSectionNav}*`, `lib/useMediaQuery.ts`, `features/bar/{useMediaQuery.ts,RevenueChart.tsx}` · T23: `lib/useEditableRecord{,.test}.ts` |
| 2 | T3, T5 | T3: `exchange/{state,__init__}.py`, `tests/engine/test_lifecycle_helpers.py` · T5: `db/{runs,mapping}.py`, `runtime/rehydrate.py`, rehydrate/mapping/boot tests |
| 3 | T6, T7 | T6: `runtime/{orders,manipulation}.py`, `api/market.py`, their tests · T7: `realtime/{messages,publish}.py`, `runtime/holder.py`, `ws_fixture.py`, fixture JSON, `schema.d.ts`, `exchange/model/{schemas,applyMessage,selectors}.ts`, `exchange/index.ts`, their tests |
| 4 | T8, T33, T36, T37 | T8: `api/runs.py`, `db/runs.py`, `main.py`, matrix, draining test, `schema.d.ts`, runs tests · T33: `features/manipulation/**`, `app/routes.tsx`, `exchange/model/selectors.ts`, `exchange/index.ts` · T36: `koers/{KoersPage,PriceMarquee}*`, `MarketEventLayer.test.tsx` · T37: `bar/{OrderPad,FinancialPanel,PendingOrders}*`, `bar/model/orderIntents*` |
| 5 | T9 | `api/runs.py`, `db/runs.py`, `runtime/{golive,holder,ticker,boot}.py`, `realtime/{hub,publish,ws}.py`, matrix, draining test, `schema.d.ts`, go-live tests |
| 6 | T10, T24 | T10: `api/config.py`, `runtime/config.py`, `db/runs.py`, `main.py`, matrix, draining test, `schema.d.ts`, config tests · T24: `features/settings/**` (layout, Borrel, stubs, moved `ThemeSection`), `features/theme/{ThemeSection*,index.ts}`, `features/keys/**` (stub), `app/pages/SettingsPage.tsx` |
| 7 | T11 | `api/config.py`, `runtime/config.py`, `realtime/publish.py`, config tests |
| 8 | T12, T25, T34 | T12: `api/drinks.py`, `runtime/drinks.py`, `db/runs.py`, `main.py`, matrix, draining test, `schema.d.ts`, drink tests · T25: `settings/GlobalSection*` · T34: `manipulation/IdleSection*` |
| 9 | T13 | `api/drinks.py`, `runtime/drinks.py`, `db/runs.py`, matrix, draining test, `schema.d.ts`, drink tests |
| 10 | T14, T27, T28 | T14: `api/drinks.py`, `runtime/drinks.py`, `db/runs.py`, matrix, draining test, `schema.d.ts`, `test_drink_lifecycle.py` · T27: `settings/BoundsSection*` · T28: `settings/DemandSection*` |
| 11 | T15, T26 | T15: `api/config.py`, `runtime/config.py`, matrix, draining test, `schema.d.ts`, `test_anchor_s0.py` · T26: `settings/DrinksSection*` |
| 12 | T16, T29 | T16: `api/{keys,security,admin}.py`, `cli/keys.py`, `db/keys.py`, `realtime/{hub,ws}.py`, `main.py`, matrix, draining test, `schema.d.ts`, keys/connections/revoke tests · T29: `settings/SystemSection*` |
| 13 | T17, T32, T35 | T17: `runtime/theme.py`, `db/theme.py`, `api/theme.py`, `realtime/messages.py`, `runtime/boot.py`, `exchange/model/schemas.ts`, `schema.d.ts`, theme tests · T32: `features/keys/**` · T35: `features/home/**`, `app/routes.tsx`, `exchange/model/applyMessage{,.test}.ts` |
| 14 | T18, T30 | T18: `runtime/images.py`, `db/{assets,theme}.py`, `api/{assets,theme}.py`, `main.py`, `vite.config.ts`, `pyproject.toml`, `uv.lock`, `test_route_authorization.py`, matrix, draining test, `schema.d.ts`, asset tests · T30: `settings/ThemeSection*`/`ThemeEditor*` |
| 15 | T19 | `realtime/messages.py`, `runtime/theme.py`, `ws_fixture.py`, fixture JSON, `exchange/model/schemas.ts`, `schema.d.ts`, `theme/ThemeProvider*`, `components/ui/Logo*`, `app/AppShell.tsx`, `auth/LoginPage.tsx`, `koers/KoersPage*` |
| 16 | T31, T39 | T31: `settings/ImagesSection*` · T39: the docs listed in Files |
| 17 | T38 | `realapp/serve.py`, `e2e/{serverProcess,global-setup,admin.spec}.ts` |

No two tasks in one group write the same file:
- In group 4, T33 alone writes `routes.tsx` and the exchange selectors. T36 does not touch
  `marketEvent.ts` or the exchange feature.
- In group 13, T17 writes `exchange/model/schemas.ts` and T35 writes `applyMessage.ts`, which
  are different files. T32 writes only `features/keys`.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main`, with the output pasted.
- `uv run pytest tests/engine` and `capture --check` green; engine-guardian's sign-off on T2
  and T3.
- T28's gate test history (failing, then passing).
- T38's run time.
- D-02, D-03, D-04, D-19, D-26, D-29, D-44–D-48 closed with their evidence tasks.
- The spec's manual exit check (a fresh database, configured through the UI to live on a
  separate display, then add one drink and remove another mid-borrel) is the user's step per
  the memory notes.

---

## Data changes

One migration, `0009_phase_6_admin.py` (T1). It is forward-only and additive; nothing in
0001–0008 is edited.

| Change | Columns / constraint | Backfill | Expand/contract |
|---|---|---|---|
| `run.name` | `text NOT NULL`, `CHECK (char_length(btrim(name)) BETWEEN 1 AND 100)` | `'Borrel ' \|\| run_id` (PD3), then `SET NOT NULL` in the same migration | Safe in one step: only the CLI inserts runs, and `import_v1` ships in the same image, so an old *server* in Render's overlap window never inserts a run |
| `price_tick.source` | CHECK recreated with `'config'` | none | Expand only: a value added, none removed |
| `asset` | `asset_id` identity PK, `content_type` (4 values), `sha256 text`, `data bytea`, `bytes int` (1..5 242 880, `= octet_length(data)`), `created_at` | none (new table) | Expand only |
| `theme` | `custom_tokens jsonb NULL`, `custom_font text NULL` (`inter`/`garamond`), `{bg,header,logo,promo}_asset_id bigint NULL` → `asset`; preset CHECK gains `custom`; `custom` needs tokens and font | none | Expand only; every new column is nullable, so the old image runs unchanged against it |
| `engine_state` covering removed slots (SD15) | no schema change | none: no drink has ever been removed, so every stored state already keys every row | n/a |

`downgrade()` drops the new columns and table and restores the old CHECKs. It fails loudly if a
`config` tick or a `custom` theme exists. That is correct: downgrading past live data is a
restore, not a migration. `tests/integration/test_migrations.py`'s round trip runs on an empty
database.

**Approval note: `python-multipart`. PD1 (b) chosen and approved by the human, 2026-10-06.**
- **What:** the streaming multipart parser that FastAPI's `File`/`UploadFile`/`Form` import.
- **Why not stdlib:** `email`/`cgi` cannot stream a request body (and `cgi` is removed in
  3.13).
- **Licence:** Apache-2.0.
- **Maintenance:** maintained by the Starlette/FastAPI maintainers (Kludex), with regular
  releases. It is the parser FastAPI's documentation designates.
- **Cost:** under (b), T18 still writes the bounded reader, because the parser does not cap a
  file part.


---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **The approved spec and the register edits are uncommitted** (working tree, `git status`) | The human commits them with this plan, as Phase 5 R1 was resolved |
| R2 | **PD1 (resolved: (b)).** SD29 says multipart; the parser is not installed | T18 adds `python-multipart` (approval note above). The parser caps nothing, so T18's bounded reader must sit in front of it; T18 stops if it cannot |
| R3 | **The spec's line references to v2 code have drifted:** `app/api/theme.py:260-285` is a 79-line file; `app/db/codec.py:291-330` is 151 lines | The behaviours it cites are real and were checked: `decode_state` demands an exact key set (`codec.py:101-109`); the empty holder refuses (`holder.py:325-326`); go-live refuses `auto_calibrate_s0` (`runs.py`, `go_live`). Only the numbers are stale. T39 does not chase them |
| R4 | **`/assets/{id}` collides with Vite's `/assets/*.js`** | PD10's int converter; T18's `test_static.py` asserts that the bundle still serves |
| R5 | **Mask bitwise identity.** A boolean index or `np.where` could change float results | Indexing with an all-true mask preserves order and length, so `np.mean`/`np.sum` see the same array. T2 proves it with `.tobytes()` equality plus the golden replay. Engine-guardian reviews |
| R6 | **Hold edge case:** a bound off the step grid can requantise outside `[p_min, p_max]` | T3's property test covers non-grid bounds. Disagreement is a hard stop (pricing maths), not a builder choice |
| R7 | **Go-live commits before adopting.** A failed adopt leaves the database live and memory empty | `adopt` failing calls `on_diverged` (the lost-lock exit). The restart rehydrates the committed live run, as every other divergence does (`holder.py` docstring) |
| R8 | **The server chain is the critical path** (15 links), forced by `schema.d.ts` and the matrix | Builders are serial anyway (ADR 0010). The web tasks are scheduled beside the chain, so no web task waits on more than the route it consumes |
| R9 | **The Phase 3 WS flake** (`CancelledError` on ws exit, memory note) may hit T7, T9 and T16's socket tests | Stop and report rather than retry to green (T16's autonomy note). Use `tests/api/ws_fixture.py` patterns |
| R10 | **E2E time.** T38 starts a second server (migrate, boot) | Measured and reported. Stop above 3 minutes (Phase 4 R6) |
| R11 | **Windows:** text-mode Python edits write CRLF in this LF repo; a `localhost` DSN crawls | Builders edit with the Edit tool, not text-mode Python; `.env.local` uses `127.0.0.1`; never pipe `check.sh` through `tail` (memory notes) |
| R12 | **The advisory-lock watchdog keeps the boot tick interval** after go-live | It only paces the lock check; the run default equals the boot default (1000 ms). Noted, not changed |
| R13 | **`docs/design/` and ADR text are hard stops** (T39) | T39 stops for approval. Nothing downstream depends on it |
| R14 | **Concurrent draft PATCHes could lose an update** if the params merge read outside the lock | T10 merges under `SELECT … FOR UPDATE` on `run`, and its 50-way test proves it. Live writes are serialised by the holder lock as well |
| R15 | **SD9 differs from v1 on purpose** | No golden scenario saves config (`tests/engine/golden/scenarios.py` has none). T11 asserts it with `grep` |
| R16 | **"One draft at most" has no database constraint** | T8 tests a concurrent create. If it races, the builder stops and proposes a partial unique index as an additive migration (T8's autonomy note) |
| R17 | **The ~19 test files that call `create_draft_run`** make T1 exceed the 10-file guideline | They are one-line mechanical edits. The source files are within limits; the size rule counts source lines (memory note) |
| R18 | **PD2, PD3, PD8 and PD18 are user-visible or API-surface choices** the spec did not make | Marked Confirm. Each is small to change if overruled |
| R19 | **A theme editor starting from a non-active preset** needs that preset's tokens without a client-side preset table (Phase 4 SD6) | T30's autonomy note. If no server route provides them, stop and ask. A `GET /api/theme/presets` would be a new route |
| R20 | **Size.** T7, T9, T11, T12 and T18 are the largest and may approach 400 source lines | Each autonomy note implies the standard stop-and-ask above about 400 source lines (tests excluded). T9 is the most likely to split: adopt/ticker/hub versus the route and auto-calibrate |

---

## Out of scope for this plan

Everything in the spec's Out of scope, and also:
- a partial unique index for "one draft" (unless T8 proves the race, R16);
- reloading the history window from the database on a live `history_window_minutes` increase
  (PD18);
- changing the watchdog's interval on go-live (R12);
- a bar-readable route for drink bounds (T33: the hint is admin-only);
- `GET /api/theme/presets` (R19), unless the audit asks for it;
- moving koers' market-event helper into `features/exchange` (T33 adds a selector; koers keeps
  its own until a later cleanup);
- fixing the spec's stale line numbers (R3);
- any change to `POST /api/orders` beyond `drink_unavailable`, to the grace rule, or to
  `exchange/` beyond SD9 and SD14.

---

## Audit (plan-auditor — PASS required before implementation starts)

- [ ] Every AC maps to at least one task
- [ ] Every task maps to at least one AC (no orphans)
- [ ] Each task's expected output is what we actually need
- [ ] Existing patterns reused; nothing reinvented
- [ ] No new dependency without an approval note
- [ ] Data changes additive and reversible
- [ ] Errors, empty states and permissions are tasks, not afterthoughts
- [ ] Each task reviewable in one sitting
- [ ] Verification named per task
- [ ] Nothing touches prod, secrets or infra it should not
- [ ] Every task has a Depends on and an Autonomy note
- [ ] No two tasks in one parallel group write the same file
- [x] PD1 answered by the human: (b) `python-multipart` (2026-10-06)
- [ ] PD2, PD3, PD8, PD18 confirmed or overruled
- [ ] R1 resolved: the working-tree spec and register are committed

Audited by: ______  Date: ______
