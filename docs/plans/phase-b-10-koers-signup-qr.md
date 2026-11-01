# Plan: B-10 — Sign-up QR code on the koers screen

Spec: [docs/specs/phase-b-10-koers-signup-qr.md](../specs/phase-b-10-koers-signup-qr.md) (`Status: Approved`; the owner approved it in the `/plan b-10` session on 2026-11-01, SD9–SD12 included) · Status: **Audited — owner accepted 2026-11-01 (plan-auditor FAIL on F1–F3, fixed in the plan; see Audit)**
Design: `docs/design/realtime-protocol.md` and `docs/design/data-model.md` change, as the spec's "In scope" says the owner approved at the interview (T9). Nothing else in `docs/design/` changes.
ADRs honoured:
- 0004, 0002: Postgres stays the only store; the one new column is additive and reversible. The pricing engine and the golden fixtures are not touched (AC21).
- 0006: everything stays bundled and same-origin. The QR code is drawn in the browser by `uqr`, with no request.
- 0003: the server stays the single writer. The `signup` message is a broadcast with `version: null`, like `theme`; it never touches `MarketHolder`.

No ADR is reversed. No new dependency: `uqr` and `jsqr` are already in `web/package.json` (approved in B-05's plan).
Backlog: [B-10](../backlog.md) · Fixes: no open defect · Amends: B-05 "only admin sees the code" (T9), B-09 SD1's address rule for the screen only (SD2)

Line references are to `main` at `7188d24`.

---

## Approach

**Copy `theme`, change as little as possible.** `theme` is the one message that already reaches
every screen with or without a live run, and survives reconnects (`app/api/theme.py:157-176`
`_publish`, `app/realtime/ws.py:152-156` `send_theme`, `web/src/features/exchange/model/applyMessage.ts`
the `theme` branch). `signup` follows it step for step:
- **Server state:** `app.state.signup`, loaded at boot (as `app.state.theme`, `boot.py:197`),
  replaced after each save. A reconnecting screen is answered from memory, so a restart shows the
  stored state (AC8), and `ws.py`'s "no await between connect and replay" rule is not disturbed.
- **Server send:** the settings route broadcasts it, `ws.py` sends it as a unicast after the
  `theme` catch-up in the same two places `theme` is (handshake and `resync_request`).
- **Client:** a `signup` field in `ExchangeState`, written by the reducer outside the seq rule,
  taking its `seq` only when it is next in line and no resync is pending — the exact shape of
  `applyFrame`'s `theme` branch (`applyMessage.ts:163-170`).

**One decision rule, written once, tested as a table.** SD6 and SD2 (switch, code, address, loopback)
become one pure function in `features/koers/signupBlock.ts`. The component only renders what it
returns, so AC2, AC3 and AC13 are a table test, not a component maze. It reuses B-09's
`signupLink` and `isLoopbackHost`. Those live in `features/wallets/`, and features are
sibling-isolated (`web/eslint.config.js:123-136`), so they move to `components/qr/` (next to
`QrSvg`) and the wallets file re-exports them. B-09's code and tests then change nothing (AC22).

**The layout is a band, not an overlay.** Today the two marquees are direct children of
`.page`. They move into a flex row with the block at its left, so "marquees fill the width to its
right" and "nothing is covered" hold by construction, and the grid below just gets shorter
(`.container` is `flex: 1; min-height: 0`). The block sits above the crash/bubble glow in z-order,
so the glow cannot tint the code (AC14).

**Rejected:**
- Reading the sign-up code over HTTP from the koers page. A display key is refused by the admin
  route, and the spec chose a realtime message (SD3).
- Reading the DB for every WebSocket connect. That puts an `await` into the handshake and can
  race a broadcast; the in-memory copy is the `theme` pattern.
- Putting the address in the message as a full link. SD3 fixes `{show_on_screen, signup_code, public_url}`;
  the client builds the link with B-09's `signupLink`, so the file naming and encoding stay in one place.
- Role-filtering the message (SD4 says no).

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. The rest follow from the
spec or the code.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | The environment variable's name (SD1) | `Settings.public_url: str \| None` with `validation_alias="BB_PUBLIC_URL"`. Without the alias pydantic would read `PUBLIC_URL` (fields map to their upper-case name, `config.py:57-`), and the venue's `.env` already says `BB_PUBLIC_URL`. A `field_validator(mode="before")` maps an empty or blank string to `None` (as `_empty_export_dir_is_none`, `config.py:159-163`), because compose will pass `BB_PUBLIC_URL: ${BB_PUBLIC_URL:-}`. A second validator parses with `urlsplit`: scheme `http`/`https`, a host, no userinfo, path `""` or `"/"`, no query or fragment; it stores `scheme://netloc` with no trailing slash. A bad value is a `ValueError`, so `_describe` names `BB_PUBLIC_URL` in the `ConfigError`. **Confirm** | AC1 names `BB_PUBLIC_URL` and the compose file already uses that name. The alias keeps one name end to end. Rejecting userinfo is mine: the link goes onto a screen, and `http://user:pw@host` must not. |
| PD2 | Where the screen's state lives and how a save publishes it | `SignupData(show_on_screen: StrictBool, signup_code: StrictStr \| None, public_url: StrictStr \| None)` in `app/realtime/messages.py`, with `signup_data(row, public_url)` beside `theme_data`. `boot.py` sets `app.state.signup` from `wallets.get_settings` and `settings.public_url`. `put_wallet_settings` stores, sets `app.state.signup`, and calls `hub.broadcast(Envelope(type="signup", seq=0, run_id=holder.run_id, version=None, …))`, as `api/theme.py:_publish` does. The store and the publish happen under one `asyncio.Lock` (`app.state.signup_lock`, made at boot), so two racing saves leave memory and broadcast in the order they committed. | Two admin saves racing is unlikely, but `wallet_settings` has no revision like `theme` has (`_publish` compares revisions). A lock is three lines and removes the doubt. |
| PD3 | `show_signup_on_screen` in the admin body | A required `StrictBool` on `WalletSettingsData`, no default, so `PUT` is a full replace like its other fields. A non-boolean is 422 (AC9). The DB column is `boolean NOT NULL DEFAULT false`. `WalletSettingsRow` gets `show_signup_on_screen: bool = False` as its last field, so positional constructions in existing tests still work. **Confirm** | A default on the body would silently turn the screen off for any client that does not send it. The only client is the web build shipped with this change. |
| PD4 | When the broadcast goes out | After **every** successful `PUT /api/admin/wallet-settings`, even a retention-periods-only save. | AC4: "when admin saves the wallet settings". The message is the whole state, so an unchanged repeat is harmless. |
| PD5 | The client's state | `ExchangeState.signup: SignupData \| null`, `null` until the first message. It is kept by `applyHello` (also on a new `boot_id`), `applyRunClosed` and `applySnapshot`. The two builders at `applyMessage.ts:222-236` (`applyHello`) and `:238-251` (`applyRunClosed`) rebuild from `initialState` and would otherwise drop it. The catch-up that follows every handshake replaces it. | SD6 (the block shows after a close) and AC19 (a dropped socket keeps the last state). The two `initialState` rebuilds are the trap. |
| PD6 | Where B-09's link helpers live | New `web/src/components/qr/signupLink.ts` holds `signupLink`, `SIGNUP_QR`, `isLoopbackHost` and `pageAddress`, moved as written. `features/wallets/signupQr.ts` keeps `signupFileName` and re-exports the four, so `WalletsSection.tsx`, `signupQr.test.ts` and `WalletsSection.test.tsx` need no edit. | The boundaries rule forbids koers importing wallets. A re-export keeps B-09's tests unchanged (AC22). |
| PD7 | The visibility rule | `features/koers/signupBlock.ts`: `signupBlockLink(signup: SignupData \| null, origin: string, hostname: string): string \| null`. `null` unless `signup?.show_on_screen` and a non-blank `signup_code`; `base = signup.public_url ?? (isLoopbackHost(hostname) ? null : origin)`; then `signupLink(base, signup_code)`. | AC2, AC3, AC13 in one function. `signup.public_url` wins even at `localhost` (AC2). |
| PD8 | Layout and stacking (SD7, SD9) | In `KoersPage.tsx` a `.band` row holds `<SignupBlock/>` then a `.marquees` column (`flex: 1; min-width: 0`) holding the two marquees. The band is rendered only if the block or the marquees are. `SignupBlock` is a white card: the QR, `QrSvg` with `SIGNUP_QR` (`Q`, 4), `width: max(96px, 14vh)`, over the caption "Meld je aan". The card is `position: relative; z-index: 150`, above the glow (`keyframes.css:12`, z 100) and below the banner (z 200). `@media (max-width: 700px) { display: none }`, the page's own phone breakpoint (`KoersPage.module.css:290`). **Confirm** | The glow is a fixed overlay with an inset shadow about 70 px deep (`keyframes.css:8-34`). Under it a code in the corner would be tinted; "unobstructed" (AC14) reads as above the glow. The alternative reading, "tinted but scannable", is the audit's to choose. |
| PD9 | Which spec does the e2e live in | New `web/e2e/signup-koers.spec.ts` on the shared server, serial, at `http://signup.test:<port>` with the same `--host-resolver-rules` as `signup-qr.spec.ts`. It starts and ends with the switch off and the code cleared, over the API. | `signup-qr.spec.ts` (B-09) must keep asserting what it asserts (AC22). Other specs on the shared server render `/koers`; a switch left on would change their layout. **Confirm** |
| PD11 | Go-live | `signup` is not sent at go-live (`golive.py:74-93` sends `snapshot` and `theme` to connected clients). `applySnapshot` keeps `signup`, so there is no gap. T9's protocol text must not claim a go-live catch-up for `signup`. | A screen keeps its state; no handshake happens. |
| PD10 | The generated types | `GET`/`PUT` carry the new field through `web/src/api/generated/schema.d.ts`, regenerated by the drift step's own command (`./scripts/gen_api_types.sh`, then `git diff --exit-code -- web/src/api/generated`, `check.sh:167-170`). The WebSocket message is not in OpenAPI, so `signup` is mirrored by hand in `schemas.ts`, like every message. | AC7. |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `app/core/config.py` | Modify | `public_url` and its validators (PD1) | T1 |
| `tests/unit/test_config.py` | Modify | AC1 cases; its `ENV_VARS`/field-list test made alias-aware (F2) | T1 |
| `.env.example` (root) | Modify | `BB_PUBLIC_URL` as a **commented-out** line, like `EXPORT_DIR` | T1 |
| `deploy/venue/compose.yml` | Modify | `BB_PUBLIC_URL: ${BB_PUBLIC_URL:-}` into the app's `environment` | T1 |
| `db/migrations/versions/0016_signup_on_screen.py` | Create | `wallet_settings.show_signup_on_screen` | T2 |
| `app/db/models.py` | Modify | the column on `WalletSettings` | T2 |
| `app/db/wallets.py` | Modify | `WalletSettingsRow` field, `get_settings`, `put_settings` | T2 |
| `app/api/wallets_admin.py` | Modify | body field (T2); `_publish` and lock (T3) | T2, T3 |
| `tests/api/test_wallets_admin.py` | Modify | AC9: default, round trip, 422, draining | T2 |
| `tests/api/test_draining.py` | Modify | the PUT body gains the field | T2 |
| `tests/integration/test_migrations.py` and/or a new `test_migration_0016.py` | Modify/Create | AC9: up, down, default false; head revision lists | T2 |
| `tests/meta/test_guard_migrations_hook.py` | Modify | pins `0015_short_keys.py` as the head (`:158-166`, `:229-238`); the head becomes `0016`, `0015` is now blocked | T2 |
| `tests/integration/test_schema.py` | Modify | column list of `wallet_settings`, if it pins them | T2 |
| `web/src/api/generated/schema.d.ts` | Modify (generated) | AC7/PD10 | T2 |
| `web/src/features/wallets/api.ts` | Modify | `WalletSettings` Zod gains the field | T2 |
| `web/src/app/pages/SettingsPage.test.tsx`, `web/src/features/wallets/WalletsSection.test.tsx` | Modify | mocked settings gain the field so `tsc` holds | T2 |
| `app/realtime/messages.py` | Modify | `SignupData`, `"signup"` type, model map, union, `signup_data()` | T3 |
| `app/runtime/boot.py` | Modify | `app.state.signup`, `app.state.signup_lock` | T3 |
| `app/realtime/ws.py` | Modify | `send_signup`, in the handshake and the `resync_request` path | T3 |
| `tests/unit/test_messages.py` | Modify | AC7: closed model, round trip | T3 |
| `tests/api/test_ws.py`, `tests/api/test_ws_theme.py` and any other API test that reads `/ws` frames by position | Modify | one more `signup` read per handshake and per `resync_request` reply; no assertion removed (F1) | T3 |
| `tests/api/test_ws_signup.py` | Create | AC4, AC5; `seq` unmoved | T3 |
| `tests/integration/test_signup_restart.py` | Create | AC8 (pattern: `test_wallets_restart.py`) | T3 |
| `tests/api/ws_fixture.py` | Modify | record a `signup` frame | T4 |
| `web/src/features/exchange/model/__fixtures__/ws-messages.json` | Modify (recorded) | AC7 | T4 |
| `web/src/features/exchange/model/schemas.ts` | Modify | `SignupData`, the envelope | T4 |
| `web/src/features/exchange/model/applyMessage.ts` | Modify | `signup` state, reducer, PD5 | T4 |
| `web/src/features/exchange/model/selectors.ts`, `web/src/features/exchange/index.ts` | Modify | `selectSignup`, exports | T4 |
| `web/src/features/exchange/model/{schemas,applyMessage}.test.ts` | Modify | AC6, AC7, AC19 | T4 |
| `web/src/components/qr/signupLink.ts` | Create | moved helpers (PD6) | T5 |
| `web/src/features/wallets/signupQr.ts` | Modify | re-export instead of define | T5 |
| `web/src/features/koers/signupBlock.ts` + `.test.ts` | Create | PD7 and its table test | T5 |
| `web/src/features/koers/SignupBlock.tsx` + `.module.css` | Create | the card (PD8) | T6 |
| `web/src/features/koers/KoersPage.tsx`, `KoersPage.module.css`, `KoersPage.test.tsx` | Modify | the band; AC11–AC14, AC17 | T6 |
| `web/src/features/wallets/WalletsSection.tsx`, `.test.tsx` | Modify | the checkbox (AC10) | T7 |
| `web/e2e/signup-koers.spec.ts` | Create | the spec's e2e steps, AC15, AC16, AC20 | T8 |
| `docs/design/realtime-protocol.md`, `docs/design/data-model.md` | Modify | the message and the column (AC23) | T9 |
| `docs/runbooks/venue.md`, `docs/specs/phase-b-05-player-wallets.md` | Modify | `BB_PUBLIC_URL` and the switch; the B-05 note | T9 |

Nothing under `exchange/` or `tests/engine/golden/fixtures/` changes, and no dependency is added
(AC21). `db/migrations/versions/` gets exactly one new file.

---

## Tasks

### T1 — `public_url` in the settings and the venue compose file

- **Implements:** AC1
- **Expected output:**
  - `Settings.public_url` as PD1 describes, with a comment in `config.py`'s style.
  - `tests/unit/test_config.py:502-512` builds its field list from `Settings.model_fields` upper-cased, which
    would give `PUBLIC_URL`. It becomes alias-aware (`(field.validation_alias or name).upper()`), `ENV_VARS`
    gains `BB_PUBLIC_URL` (so `_isolated` clears it, `:55-56`), and the root `.env.example` documents it as a
    commented-out line (`# BB_PUBLIC_URL=http://192.168.8.10`), never a set value: `setup.sh` copies that file
    to `.env.local`, which the gate sources.
  - `deploy/venue/compose.yml`'s `app.environment` passes `BB_PUBLIC_URL: ${BB_PUBLIC_URL:-}`.
    `.env.example` already carries the variable (`deploy/venue/.env.example:17`).
  - `tests/unit/test_config.py` gains cases:
    - `http://192.168.8.10/` gives `http://192.168.8.10`; `https://borrelbeurs.onrender.com`
      and `http://192.168.8.10:8080/` keep their form (port kept);
    - unset and `""` and `"  "` give `None` and boot succeeds;
    - `192.168.8.10`, `ftp://x`, `http://`, `http://h/path`, `http://h/?q=1`, `http://h/#f` and
      `http://u:p@h/` each raise `ConfigError`, and the message names `BB_PUBLIC_URL` and does not
      echo a password.
- **Verification:** `uv run pytest tests/unit/test_config.py tests/meta` and `uv run mypy app`. If a
  test pins the venue compose file's environment (grep `compose.yml` under `tests/`), run it too.
- **Depends on:** —
- **Autonomy note:**
  - **The builder decides:** the exact `urlsplit` checks, message wording, test layout.
  - **Stop and ask if:** pydantic's alias would need `populate_by_name` and that breaks an existing
    `Settings(...)` call; any second module would have to read the environment.

### T2 — The switch: column, repository and admin routes

- **Implements:** AC9 (server and typed client halves)
- **Expected output:**
  - Migration `0016`: `wallet_settings.show_signup_on_screen boolean NOT NULL DEFAULT false`
    (`server_default`), `min_code_revision = "unchanged"` with the docstring's reason: expand-only;
    an older image's upsert never names the column and its insert takes the default.
    `downgrade()` drops the column. It is the only new file under `db/migrations/versions/`.
  - `models.py`, `WalletSettingsRow`, `get_settings` and `put_settings` carry the field.
  - `WalletSettingsData` gains `show_signup_on_screen: StrictBool` (PD3); `_settings` and the PUT
    build the row from it.
  - The generated `schema.d.ts` is regenerated; `web/src/features/wallets/api.ts`'s Zod and the two
    web tests' mocked bodies carry the field so `tsc -b` holds. No UI yet.
  - `tests/meta/test_guard_migrations_hook.py` moves its head and allowed file to `0016_*.py`; this edit is
    expected and exempt from the stop condition below.
  - Tests: GET on a fresh database is `show_signup_on_screen: false` (the existing exact-body test
    at `test_wallets_admin.py:394-399` changes); a PUT round trip stores and returns `true`; `"yes"`,
    `1` and `null` are 422; a missing field is 422; draining is 503 and writes nothing (extend the
    existing case at `:464-479`); the migration goes up and down with the default `false` for an
    existing row; `_settings_body` and `test_draining.py`'s body gain the field.
- **Verification:** `uv run pytest tests/unit tests/meta`, then `uv run pytest tests/api/test_wallets_admin.py tests/api/test_draining.py tests/api/test_authorization_matrix.py`,
  then `uv run pytest tests/integration -k "migration or schema"`, run separately with `.env.local` sourced
  (MEMORY: api and integration are not run in one pytest). Then `pnpm -C web exec tsc -b` and
  `pnpm -C web exec vitest run src/features/wallets src/app/pages/SettingsPage.test.tsx`. The drift
  step: `./scripts/gen_api_types.sh`, then `git diff --exit-code -- web/src/api/generated`.
- **Depends on:** —
- **Autonomy note:**
  - **The builder decides:** the migration's file slug, how it is tested next to `test_migration_0015.py`.
  - **Stop and ask if:** an existing test other than `test_guard_migrations_hook.py` needs more than the field added to its body; the `check.sh`
    drift step wants anything but regenerating `schema.d.ts`.

### T3 — The `signup` message on the server

- **Implements:** AC4, AC5, AC7 (closed model), AC8
- **Expected output:**
  - `messages.py`: `SignupData` (a `_Closed` model, PD2), `"signup"` in `ServerMessageType`,
    `SERVER_MESSAGE_MODELS` and `ServerData`, and `signup_data(row, public_url)`. The module docstring
    gains a paragraph for `signup` beside `theme`'s.
  - `boot.py`: after `app.state.theme`, `app.state.signup` is built from `wallets.get_settings` and
    `settings.public_url`, and `app.state.signup_lock = asyncio.Lock()`.
  - `wallets_admin.py`: `put_wallet_settings` takes the lock; stores; sets `app.state.signup`;
    `hub.broadcast` with `version=None`, `run_id=holder.run_id` (PD2, PD4); returns the settings as
    today. Admin-only and draining behaviour unchanged.
  - `ws.py`: `send_signup()` is a unicast with `version=None`, built as `send_theme` is, and called
    right after `send_theme()` in `run()` (`ws.py:252`) and in `handle()` for `resync_request`
    (`ws.py:203`). The module docstring's "The theme" paragraph gains the sentence for `signup`.
  - `golive.py` is **not** changed (PD11): go-live sends no handshake and a screen keeps its `signup` state.
  - Existing tests that read frames by position gain one `signup` read per handshake and per
    `resync_request` reply and nothing else: `test_ws.py` (`:128-134`, `:173`, `:192`, `:210`, `:280-285`) and
    `test_ws_theme.py` (`:74-80`, `:119-123`) at least. No assertion is removed.
  - Tests set or delete `BB_PUBLIC_URL` explicitly with monkeypatch, since the API app reads `get_settings()` from
    the process environment (`tests/api/conftest.py:71-79`) (F4).
  - Tests:
    - `test_messages.py`: an unknown field is refused; `Envelope` with `type="signup"` validates
      only `SignupData`; `null` code and `null` URL are accepted.
    - `test_ws_signup.py`: with and without a live run (`client` and `live_client` fixtures, as
      `test_ws_theme.py`), one save gives each connected socket of all four roles exactly one `signup`
      frame with the stored values, `version` null (AC4, SD4). A fresh connect, a replay after
      `hello {boot_id, last_seq}`, a snapshot and a `resync_request` each end in a `signup` unicast
      carrying the current `seq` and not moving it (AC5). A save with only the periods changed
      broadcasts (PD4). A draining refusal broadcasts nothing.
    - `test_signup_restart.py`: save a code and the switch; build a fresh `create_app` on the same
      database; a new socket's catch-up holds the stored values (AC8).
- **Verification:** `uv run pytest tests/unit/test_messages.py tests/unit/test_hub.py`, then
  `uv run pytest tests/api/test_ws_signup.py tests/api/test_ws_theme.py tests/api/test_ws.py tests/api/test_ws_revoke.py tests/api/test_close.py tests/api/test_go_live.py tests/api/test_config.py tests/api/test_drinks.py tests/api/test_connections.py tests/api/test_standby.py tests/api/test_authorization_matrix.py tests/api/test_wallets_admin.py`,
  then `uv run pytest tests/integration/test_signup_restart.py`, each run separately (MEMORY).
  `uv run mypy app tests` and `uv run ruff check`.
- **Depends on:** T1 (`public_url`), T2 (the column and `wallets_admin.py`, which both tasks write)
- **Autonomy note:**
  - **The builder decides:** `_publish`'s name and place, whether the lock is created in `boot.py`
    or in a tiny holder class, test structure.
  - **Stop and ask if:** any existing WebSocket test breaks because of the extra unicast (only if a test needs more than one extra `signup` read per handshake or resync reply; one extra read is expected, never hide it); the hub's `seq` or resync
    metadata would have to change; the engine (`exchange/`) or `MarketHolder` would have to be touched.

### T4 — The message on the client: recorded fixture, Zod, reducer

- **Implements:** AC6, AC7 (types, fixture, Zod), AC19 (state kept)
- **Expected output:**
  - `tests/api/ws_fixture.py` records one `signup` frame from the real app, the handshake catch-up, with a
    non-default state (switch on, a code, a URL). The recorder sets `BB_PUBLIC_URL` inside an env context like
    `_database_env` and seeds the `wallet_settings` row in `_seed`; it does **not** PUT mid-session, since a
    broadcast would move `seq` for every later frame (F4). Then and `python -m tests.api.ws_fixture --write` rewrites
    `ws-messages.json`; `--check` is clean. The recorder consumes frames by kind, so the extra
    handshake frame must not shift the existing steps.
  - `schemas.ts`: `SignupData` (`z.strictObject`), `envelope('signup', SignupData)`, the exported type.
  - `applyMessage.ts`: `signup: SignupData | null` in the state and `initialState`; `applyFrame`
    gains a `signup` branch shaped like `theme`'s, minus the revision rule: the latest message always
    wins (AC6), it never sets `awaitingResync`, and it takes its `seq` only when
    `!awaitingResync && message.seq === state.seq + 1`. The `applyBroadcast` switch lists `signup`
    with the other handled-before-seq types so `never` still holds. PD5: `applyHello` (new boot) and
    `applyRunClosed` carry `signup` over; the header comment gets the paragraph.
  - `selectors.ts` and `index.ts` export `selectSignup`.
  - Tests:
    - `schemas.test.ts`: the recorded `signup` frame parses; a stray field fails.
    - `applyMessage.test.ts`: a `signup` with a `seq` far ahead applies and does not set
      `awaitingResync`; during a resync it applies and the seq is not taken; in line it takes its
      seq; out of order, the later message received wins whatever its `seq`; a `hello` with a new
      `boot_id`, a `run_closed` and a `snapshot` each leave `signup` as it was; it is `null` before
      the first message.
- **Verification:** `uv run python -m tests.api.ws_fixture --check` and
  `uv run pytest tests/api/test_ws_fixture.py`; `pnpm -C web exec vitest run src/features/exchange`;
  `pnpm -C web exec tsc -b` and `pnpm -C web lint`.
- **Depends on:** T3
- **Autonomy note:**
  - **The builder decides:** the fixture key name.
  - **Stop and ask if:** recording changes any existing frame in the fixture (a diff beyond the added
    frame means the handshake order moved); a consumer of `ServerMessage` outside `exchange/` needs
    an edit.

### T5 — The shared link helpers and the visibility rule

- **Implements:** AC2, AC3, AC13 (the rule)
- **Expected output:**
  - `components/qr/signupLink.ts` holds `signupLink`, `SIGNUP_QR`, `isLoopbackHost` and `pageAddress`, moved
    verbatim (PD6; `pageAddress` is B-09's test seam, F5). `features/wallets/signupQr.ts` re-exports them and keeps `signupFileName`. `signupQr.test.ts`, `WalletsSection.tsx` and its test are not edited.
  - `features/koers/signupBlock.ts` with `signupBlockLink` (PD7).
  - `signupBlock.test.ts` is a table:
    - the full cross of `show_on_screen` (2) × code (`null`, `''`, `'  '`, `BORREL`) × `public_url`
      (`null`, `http://192.168.8.10`) × page (`http://localhost`, `http://127.0.0.1:4173`,
      `http://[::1]`, `http://signup.test:4173`, `https://borrelbeurs.onrender.com`), with each
      result stated;
    - `public_url` wins at `localhost` (AC2);
    - no `public_url` at a loopback host is `null` (AC3);
    - a `null` signup state is `null`;
    - the link equals `public_url + '/speler?code=' + encodeURIComponent(code)` for an awkward code
      `a b&c#é`.
- **Verification:** `pnpm -C web exec vitest run src/features/koers/signupBlock.test.ts src/features/wallets src/components/qr`
  (B-09's tests pass unchanged), `pnpm -C web lint` (the boundaries rule), `pnpm -C web exec tsc -b`.
- **Depends on:** T4 (the `SignupData` type)
- **Autonomy note:**
  - **The builder decides:** the file name of the moved module within `components/qr/`, test layout.
  - **Stop and ask if:** a B-09 test needs any edit to keep passing (AC22).

### T6 — The block on the koers page

- **Implements:** AC11, AC12, AC13, AC14, AC17 (jsdom halves; geometry and the phone width are T8)
- **Expected output:**
  - `SignupBlock.tsx` reads `selectSignup`, calls `signupBlockLink(signup, origin, hostname)` with `pageAddress()` and renders nothing for `null`. Otherwise it draws
    `encode(link, SIGNUP_QR).data` through `QrSvg` (`label="Aanmeld-QR-code"`) over the caption
    "Meld je aan" (SD10), nothing else (no code text, no link text). The matrix is recomputed from the
    link alone, so there is no stale copy (AC18).
  - `KoersPage.tsx`: the band of PD8. `KoersPage.module.css`: `.band`, `.marquees`; `SignupBlock.module.css`:
    the white card, `width: max(96px, 14vh)` for the QR, `z-index: 150`, the ≤700 px rule, black on
    white whatever the theme (as `PlayerPage.module.css:111-118`).
  - Tests in `KoersPage.test.tsx` (its `dispatch` helper feeds `signup` messages; the jsdom origin is
    loopback, so the address comes from mocking `pageAddress`, as `WalletsSection.test.tsx:14-22` does):
    - the block appears for switch+code+address and not otherwise, and takes no space (no `.band`
      when neither block nor marquees render, and no padding or gap when only the hidden block would be in it, F9) (AC13);
    - with `public_url` it shows at a loopback page (AC2 on the page);
    - rasterise the `QrSvg` rects as B-09's tests do and decode with `jsqr`: the result equals the
      link; the rects equal `encode(link, { ecc: 'Q', border: 4 }).data`; the caption is exactly
      "Meld je aan" (AC12);
    - no live run and a closed run (`run_closed` dispatched) still show it; a `market_event` crash
      and bubble leave it in the DOM (AC14);
    - a second `signup` with another code redraws, a clear or switch off removes it (AC18 on the store);
    - the same render for the admin role as for display: the page does not read the role (AC17).
- **Verification:** `pnpm -C web exec vitest run src/features/koers`, `pnpm -C web lint`,
  `pnpm -C web exec tsc -b`, `pnpm -C web build`.
- **Depends on:** T4, T5
- **Autonomy note:**
  - **The builder decides:** the card's padding and caption size, whether the 96 px floor is on the
    QR or the card, how the test mocks `pageAddress`.
  - **Stop and ask if:** `PriceMarquee`/`NewsMarquee` need a code change to live in a narrower
    container (the audit found `Marquee.tsx` measures nothing, so none is expected); an
    existing `KoersPage` test needs more than an added `signup` state.

### T7 — The checkbox in Wallets

- **Implements:** AC10
- **Expected output:** In `WalletsSection.tsx`'s Aanmeldcode subsection a checkbox labelled
  "QR-code op het scherm", reflecting `settings.show_signup_on_screen`. Toggling it calls the
  existing `save({ ...settings, show_signup_on_screen: checked }, …)` and goes through no confirm
  (`breaksPrinted` is about the code only). It is disabled while `busy`. The existing code
  change/clear confirm is untouched. A save failure shows the section's existing alert text.
  Tests: it shows the stored value; toggling sends one PUT with the flag flipped and every other
  field as stored; no dialog opens; changing and clearing the code still ask (the B-09 tests stay
  green unchanged); a failed PUT shows `NETWORK`.
- **Verification:** `pnpm -C web exec vitest run src/features/wallets`, `pnpm -C web lint`,
  `pnpm -C web exec tsc -b`.
- **Depends on:** T2
- **Autonomy note:**
  - **The builder decides:** the checkbox's markup (reuse `Field`/the section's styles), its place in
    the subsection.
  - **Stop and ask if:** the label would need to differ from the spec's text; saving the switch
    would have to send the code field's unsaved text.

### T8 — The Playwright story and the geometry

- **Implements:** AC11–AC20 end to end (AC15, AC16 and AC20 are only checked here), AC3 on a real page
- **Expected output:** `web/e2e/signup-koers.spec.ts` (PD9), serial, shared server, `signup.test`
  mapped to 127.0.0.1 as in `signup-qr.spec.ts`. Helpers for the API reset (as that file's
  `closeSignup`). Steps follow the spec's Verification:
  1. Display key opens `/koers`: no block.
  2. Admin saves `BORREL` over the API: still none (switch off). Turn the switch on (through the
     Wallets checkbox, a second admin page): the display shows the block with no reload; its decoded
     link (screenshot of the SVG → pixels → `jsqr`, or the SVG rects) is
     `http://signup.test:<port>/speler?code=BORREL`; `isSecureContext` is false and no page error
     was raised (AC20).
  3. Save `ANDERS` (confirm "Wijzigen"): the code changes without reload; the decoded link opens the
     player page with `ANDERS` in the code field.
  4. A crash from Manipulation (or the mocked socket of `frames.ts`): the block stays, its rect is
     inside the viewport and does not intersect the banner (AC14); decode it during the glow.
  5. Reload the display: the block is there at once (AC5). Clear the code: it goes (AC18).
  6. Drop the socket as `offline.spec.ts` does (`routeWebSocket` close): the block stays; on
     reconnect it matches the server (AC19).
  7. Geometry (AC16): at 1920×1080 and 1280×720, with and without a promo image, the block's rect
     intersects none of the marquee rects, tile rects or the banner, and the marquees' right edge
     equals the band's right edge (`.page` has no padding); the QR is at least 96 px.
  8. At 700×900 the block is not in the DOM's layout (`display: none`, AC15).
  9. At `http://127.0.0.1:<port>` (loopback, no `public_url`): no block even with the switch on (AC3).
  The reset (switch off, code cleared) runs in `afterAll`, so a failed step cannot leave the switch on for later specs.
- **Verification:** `pnpm -C web build`, then `pnpm -C web exec playwright test e2e/signup-koers.spec.ts`
  (compose `db` up), then the whole `pnpm -C web e2e` so the shared server's other specs are shown
  unaffected; `pnpm -C web lint`.
- **Depends on:** T6, T7
- **Autonomy note:**
  - **The builder decides:** helper structure, how the QR is decoded in the browser (rects vs pixels),
    timeouts, how a crash is started.
  - **Stop and ask if:** `serverProcess.ts` passes `BB_PUBLIC_URL` from the developer's environment
    into the shared server (it would change step 9); the spec would need its own `serve.py`; another
    spec's `/koers` layout assertion fails because of the band.

### T9 — The design docs, the runbook and the B-05 note

- **Implements:** AC23
- **Expected output:**
  - `docs/design/realtime-protocol.md`: a `signup` row in "Server to client" beside `theme`
    (`{show_on_screen, signup_code, public_url}`, broadcast `version: null` on every settings save
    with or without a live run, catch-up unicast after replay or snapshot and every `resync_request`
    snapshot, to every role), and a bullet under "How the client applies `seq`": outside the seq rule,
    never starts or waits on a resync, the latest wins, kept across a new boot and a `run_closed`.
  - `docs/design/data-model.md`: `show_signup_on_screen` in the `wallet_settings` row's description
    (boolean, default false).
  - `docs/runbooks/venue.md`: next to the `BB_PUBLIC_URL` lines (`:13`, `:33`), one line that the app
    now uses it for the screen's QR code, so it must be the address phones reach, and the step to turn
    "QR-code op het scherm" on in Instellingen → Wallets → Aanmeldcode.
  - `docs/specs/phase-b-05-player-wallets.md`: a note on "only admin sees the sign-up code" pointing
    at B-10 SD3/SD4 (the code is now also on the screen and so visible to every role's socket).
- **Verification:** `grep -n "signup" docs/design/realtime-protocol.md`,
  `grep -n "show_signup_on_screen" docs/design/data-model.md`,
  `grep -n "QR-code op het scherm" docs/runbooks/venue.md` and
  `grep -n "B-10" docs/specs/phase-b-05-player-wallets.md` each print a line. No formatter covers `docs/`.
- **Depends on:** —
- **Autonomy note:**
  - **The builder decides:** wording and the exact place in each file.
  - **Stop and ask if:** a docs change would go beyond the two named design files and those lines, or
    would reverse an ADR.

### T10 — The closing check

- **Implements:** AC21, AC22
- **Expected output:** evidence only, no file changes:
  - `git diff --stat main -- exchange tests/engine/golden/fixtures` is empty;
  - `git diff main -- web/package.json pyproject.toml` shows no dependency change;
  - `git diff --stat main -- db/migrations/versions` lists exactly `0016_*.py`;
  - `git diff main -- web/src/features/wallets/signupQr.test.ts web/src/features/player/QrCode.test.tsx web/e2e/signup-qr.spec.ts`
    is empty, and B-09's tests pass (AC22);
  - `./scripts/check.sh` is green at 13/13, output pasted. This is the phase's one full gate
    (MEMORY: gate only at phase end). Never pipe it through `tail` (MEMORY).
- **Verification:** the commands above, with their output.
- **Depends on:** T8, T9
- **Autonomy note:**
  - **The builder decides:** nothing beyond running the commands.
  - **Stop and ask if:** any of the diffs is non-empty or `check.sh` fails in a step this change did
    not touch. The golden tests and `engine-guardian` are not required (spec, Verification).

---

## AC coverage

| AC | Tasks |
|---|---|
| AC1 | T1 |
| AC2 | T5, T6 |
| AC3 | T5, T8 |
| AC4 | T3 |
| AC5 | T3, T8 |
| AC6 | T4 |
| AC7 | T2 (generated types), T3 (closed model), T4 (fixture, Zod) |
| AC8 | T3 |
| AC9 | T2 |
| AC10 | T7 |
| AC11 | T6, T8 |
| AC12 | T6, T8 |
| AC13 | T5, T6 |
| AC14 | T6, T8 |
| AC15 | T8 |
| AC16 | T8 (plus the owner's visual check) |
| AC17 | T6, T8 |
| AC18 | T4, T6, T8 |
| AC19 | T4, T8 |
| AC20 | T8 |
| AC21 | T10 |
| AC22 | T5, T10 |
| AC23 | T9 |

Every task implements at least one AC. T10 is AC21 and AC22's evidence.

---

## Task graph

```
T1 ─────────┐
            ├── T3 ── T4 ── T5 ── T6 ──┐
T2 ─────────┤                          ├── T8 ── T10
            └── T7 ────────────────────┘          │
T9 ───────────────────────────────────────────────┘
```

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T2, T9 | T1: `app/core/config.py`, `tests/unit/test_config.py`, `deploy/venue/compose.yml` · T2: migration `0016`, `app/db/{models,wallets}.py`, `app/api/wallets_admin.py`, wallet and migration tests, `schema.d.ts`, `web/src/features/wallets/api.ts` and two web test fixtures · T9: the four docs |
| G2 | T3, T7 | T3: `app/realtime/{messages,ws}.py`, `app/runtime/boot.py`, `app/api/wallets_admin.py`, new tests · T7: `web/src/features/wallets/WalletsSection.{tsx,test.tsx}` |
| G3 | T4 | `tests/api/ws_fixture.py`, the fixture JSON, `web/src/features/exchange/**` |
| G4 | T5 | `web/src/components/qr/signupLink.ts`, `web/src/features/wallets/signupQr.ts`, `web/src/features/koers/signupBlock.{ts,test.ts}` |
| G5 | T6 | `web/src/features/koers/{KoersPage.*,SignupBlock.*}` |
| G6 | T8 | `web/e2e/signup-koers.spec.ts` |
| G7 | T10 | none (evidence only) |

No two tasks in one group write the same file. `wallets_admin.py` is written by T2 and T3, which is
why T3 depends on T2; T3 also needs T1's `public_url`. T7 touches only `WalletsSection`, which no
other task edits, and needs only T2's typed body, so it sits in G2 beside T3.

---

## Data changes

One additive migration, `0016`: `wallet_settings.show_signup_on_screen boolean NOT NULL DEFAULT false`.
- **Backfill:** none needed. The server default gives the existing row `false`, so a deploy changes
  nothing on any screen until the switch is turned on (SD5).
- **Expand-only:** an older image never names the column. Its upsert (`set_=values` of three
  columns) leaves it alone, and its insert takes the default. So `min_code_revision` is `unchanged`.
- **Reversible:** `downgrade()` drops the column. A switch that was on is lost, which is the
  consequence of downgrading, not of this migration.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | The extra handshake unicast could shift frame order in existing WebSocket tests and in the recorder (`ws_fixture.py` consumes by kind and may read past frames). | T3 and T4 stop-and-ask: a test is adjusted only to expect one more `signup` frame. T4 checks that `--write` changes only the added frame. |
| R2 | `applyHello` and `applyRunClosed` rebuild the state from `initialState`; if `signup` is not carried over, the block flashes off on every reconnect to a new boot or after a close, against SD6 and AC19. | PD5 names both; T4 has one test per path. |
| R3 | The marquees animate with the Web Animations API (`Marquee.tsx`) and may measure their width once; the block appearing after mount shrinks their container. | T6's stop-and-ask: check `Marquee.tsx` before building. T8 step 7 shows the marquees' edges with the block present. |
| R4 | The crash/bubble glow (z 100, `keyframes.css:8`) would tint a code in the corner. | PD8 puts the block at z 150. T8 step 4 decodes it during a crash. If the owner prefers the other reading, only the z-index changes. |
| R5 | vitest's jsdom origin is `http://localhost:3000`, a loopback host, so every `KoersPage` test would see "no address". | T6: stub `location` (or the docblock URL option). Both are the builder's; `signupBlock.ts` takes `origin` and `hostname` as arguments, so its table needs no stub. |
| R6 | CSS media queries do not run in jsdom (vitest identity-maps CSS modules), so AC15 and AC16 cannot be proven in unit tests. | They are in T8 (real Chromium, measured rects), plus the spec's own owner visual check. |
| R7 | `wallet_settings` has no revision, so two racing saves could leave memory and the stored row apart. | PD2's lock; the single-process advisory lock (CLAUDE.md `go-live` note) means one process owns it. |
| R8 | A developer with `BB_PUBLIC_URL` in their shell could change the shared e2e server's behaviour (T8 step 9). | T8 stop-and-ask: read `serverProcess.ts`'s env first. |
| R9 | `docs/design/frontend-architecture.md` describes the exchange store's fields and the koers page; after this it is slightly out of date. | `docs/design/` is the owner's, and the spec names only two design files. Not edited here (as B-09 R2). If the owner wants a line, it is one sentence added at audit. |
| R10 | SD2 says the screen's link may use `public_url`, so the QR code can differ from the one admin sees in the Wallets section (that one uses the page's address). A printed poster and the screen then point at the same host only if `BB_PUBLIC_URL` is right. | The runbook line in T9, and the spec's manual exit check at the venue. |

---

## Out of scope for this plan

- Everything in the spec's Out of scope: an admin setting for the public address, other QR codes, a
  poster, other sizes or places, code text on the screen, role-filtering the message, changes to the
  sign-up flow or B-09's downloads.
- `exchange/` and the golden fixtures.
- `docs/design/frontend-architecture.md` (R9).
- Setting `BB_PUBLIC_URL` on Render, or any Render setting. Render sets nothing (SD1).

---

## Uncertain

- **PD1, the alias.** The spec says "read from `BB_PUBLIC_URL`", and the app today reads names with no
  prefix. I chose an alias, not a compose rename (`PUBLIC_URL: ${BB_PUBLIC_URL}`). Both give the same
  behaviour; the alias makes AC1's wording literal. Confirm.
- **PD3, a required body field.** It makes an old-shape PUT a 422. Confirm that is wanted over a
  `= False` default.
- **PD8, "unobstructed".** I read it as above the glow. Confirm or overrule.
- **R1 (the recorder) and R3 (the marquees):** checked by the audit. `until` skips other frame types, and `Marquee.tsx` measures nothing.
- **PD1, PD3, PD8, PD9:** confirmed by the audit.

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

plan-auditor (agent), 2026-11-01: **FAIL** on three Required findings, all fixed in this plan:
- F1: the extra `signup` frame breaks position-reading WebSocket tests; T3 now names them and widens its verification.
- F2: `test_config.py`'s field list would give `PUBLIC_URL`, not `BB_PUBLIC_URL`; T1 makes it alias-aware and documents the root `.env.example` as a commented line.
- F3: `test_guard_migrations_hook.py` pins `0015` as the head; T2 updates it.

Also folded in: F4 (tests and recorder pin `BB_PUBLIC_URL`; the recorder seeds, no mid-session PUT), F5 (`pageAddress` moves to `components/qr`), F6 (PD11, go-live), F7 (band edge, `afterAll` reset), F8 (stale references), F9 (no band padding). F10 accepted. The auditor confirmed PD1, PD3, PD8 and PD9.

Audited by: MartijnBoot (owner), accepting the plan-auditor's report and ticking every line on request  Date: 2026-11-01
