# Plan: Phase 4 — React shell, theme, auth and the display board

Spec: [docs/specs/phase-4-web-koers.md](../specs/phase-4-web-koers.md) · Status: Audited — PASS (2026-10-04)
Design: [frontend-architecture.md](../design/frontend-architecture.md), [realtime-protocol.md](../design/realtime-protocol.md), [data-model.md](../design/data-model.md), [architecture.md](../design/architecture.md)
ADRs honoured: 0003 (single writer owns time — SD30 note added), 0004 (Postgres only), 0005 (server-side theme, blocking `/theme.css`), 0006 (bundle everything, lightweight-charts v5), 0009/0010 (hard stops: new dependency, data model, wire protocol, `docs/design/`)
Fixes: D-13, D-14, D-17, D-25 · Client half of D-15

---

## Approach

Two halves that meet at one contract. **Server first, small:** a pure token manifest
(`app/runtime/theme.py`, T1), a one-row `theme` table (T2), a `theme` message plus `hello.theme`
(T3), then the HTTP surface (`GET /theme.css`, `PUT /api/theme`, T4) and the WebSocket wiring
(T5). Theme writes never touch `MarketHolder`: `mutate` refuses with no live run
(`app/runtime/holder.py:325`), and SD9 forbids the engine lock anyway. A `PUT` therefore commits
in its own transaction, updates an in-memory current theme on `app.state`, and calls
`hub.broadcast` directly. The hub is the one broadcast handle that does not depend on a run
(`app/realtime/hub.py:138`). **Client second, bottom-up along the design's seams:** the pure
pieces first (formatter, HTTP wrapper, Zod schemas checked against a fixture recorded from the
real server, then `applyMessage`, the SMA and skew estimation), all in Vitest under the `node`
environment. Next the WS state machine on fake timers. Then the shell (components, auth,
routes), theme application, the chart host against a mocked `lightweight-charts`, and finally
the board. Every live update flows WS → `applyMessage` → Zustand store → imperative
`series.update` through a store subscription. Ticks cause zero React renders
(`frontend-architecture.md:88-104`). The gate grows three steps in order: generated-types drift
(T11), build plus the built-output reference check (T22), and Playwright against the real
process on the compose database (T23).

Rejected:
- **Routing theme writes through `MarketHolder.mutate`:** it refuses with no run (AC5), and SD9
  forbids the engine lock.
- **A client-side preset table**, which `frontend-architecture.md:34` places in
  `features/theme/` but SD6 overrules.
- **`eslint-plugin-react` for `react/no-danger`:** it is a dependency SD25 does not list, and core
  `no-restricted-syntax` on `JSXAttribute[name.name="dangerouslySetInnerHTML"]` does the same job
  with no new package (PD9).
- **Seeding several real servers for the board's shape cases** (nine drinks, an XSS name, a
  suppressed market-event end, no live run). Playwright's `page.routeWebSocket` injects frames
  shaped by T12's recorded fixture against one real server, and the real-server tests keep what
  only a real server can prove: login, offline load, theme propagation and recovery (PD14).
- **Synthesising candles client-side, or any client interval.** SD3 forbids it.
- **Pixel-diff regression.** The design rejects it.

---

## Decisions this plan makes

PD1 is a hard stop before T8 is built. PD2–PD4, PD7, PD8, PD15 and PD17 touch a named contract
(spec wording, the data model, the wire protocol or a user-visible string), so the audit must
confirm them.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | SD25's dependencies | One task, T8, adds the runtime deps `react-router`, `zustand`, `lightweight-charts@^5`, `zod`, `@fontsource/inter`, `@fontsource/eb-garamond`, and the dev deps `openapi-typescript`, `@testing-library/react`, **`@testing-library/dom`**, `jsdom`, `@playwright/test`. Approval notes are under Files. **It stops for explicit human approval before `pnpm add`** | ADR 0009/0010 make a new dependency a hard stop. `@testing-library/dom` is **not in SD25**: it is a required peer of `@testing-library/react` ≥ 16, and without it RTL does not install. It needs its own yes |
| PD2 | Token count | The manifest has **24** tokens: v1's 22 per preset (`theme.js:4-62`, counted per preset) minus `--up`/`--down`, plus `--candle-up`, `--candle-down`, `--tile-rising`, `--tile-falling`. **Confirm at the audit.** SD6's "23" is arithmetic from a miscount (v1 has 22, not 21) | SD6's rule (split, values as given) is unambiguous. Only its count is wrong. The builder ports the values; T1's test pins the count at 24 |
| PD3 | Theme payload | `ThemeData{preset: Literal[5 keys], revision: int ≥ 0, tokens: dict[str, str] (24 entries, keys from the manifest), font_family: str}`. `font_family` is the CSS stack: `"'EB Garamond', Georgia, serif"` for Oud Geld, `"Inter, system-ui, sans-serif"` otherwise. `revision` 0 means "no row, Blauw fallback". **Confirm at the audit**: `font_family` is a field SD9 does not name | AC3 says "tokens **and font**" without reload, and SD6 says the client holds no preset table. The server must therefore send the font, and a field is cleaner than a 25th "token" that is not a colour |
| PD4 | Singleton row | `theme.id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1)`, alongside SD5's `preset`, `revision`, `updated_at`. **Confirm at the audit**: `id` is a column SD5 does not list | The ORM needs a primary key (`app/db/models.py` is declarative), and the CHECK makes "a single row" a database fact rather than a convention. The alternative, a unique index on `((true))` without a mapped PK, fights the declarative style |
| PD5 | Where the current theme lives in the process | `app.state.theme: ThemeData`, loaded in `start_runtime` (`app/runtime/boot.py`) after migrate, **with or without a live run**. It is replaced after a successful `PUT` commit only if the committed revision is higher (two racing PUTs converge, as SD9 requires). `hello`, `/theme.css` and the catch-up unicast (PD7) read it | One read per boot, not per connect. `/theme.css` and `hello` agree by construction |
| PD6 | A non-run broadcast and the hub's resync metadata | The theme envelope carries `run_id = holder.run_id` (`None` with no run) and `version = None`. `Hub.broadcast` updates `_run_id`/`_version` **only when `envelope.version is not None`** | Today every broadcast overwrites them (`hub.py:142`), so a theme broadcast would make every later `resync` carry `version: null`. The one-line guard is tested in `tests/unit/test_hub.py` |
| PD7 | Theme catch-up after a snapshot | After the handshake's replay or snapshot, and after every `resync_request` snapshot, the session **unicasts a `theme` message** with the current theme (current `seq`, not incremented, as `snapshot` does). The client ignores it when `revision` is not higher (AC7). **Confirm at the audit**: this is a wire-protocol addition beyond SD9 | Three windows lose a theme otherwise. (a) `hello` is sent before `hub.connect` (`ws.py:192-204`), so a broadcast in between reaches nobody. (b) A gap repaired by `resync_request` restores state from a `snapshot`, which has no theme. (c) Overflow resync, the same. AC6 covers a reconnect, but (b) and (c) break "converges on the last write" silently |
| PD8 | History-mode fallback | The `/` mount becomes `SpaStaticFiles(StaticFiles)`: on a 404 for a `GET` whose path is exactly one of the **SPA routes** (`/login` plus the union of `ROLE_ROUTES`, imported from `app/api/security.py`, not copied), it serves `index.html`. Every other unknown path stays a plain 404, which keeps `main.py`'s `/probe` comment true. **Confirm at the audit**: the spec says "SPA fallback unchanged", but there is none (`app/main.py:178-186`). Without one, a reload of `/koers` or a `/login?next=` redirect 404s against a real Vite build | It stays inside the already-public mount, so no new route enters `PUBLIC_ROUTES`. The route list is the server's existing table, so there is no second copy |
| PD9 | SD27 lint without new packages | `boundaries/element-types`: `features/exchange` imports nothing from `features/*`; other features import only `exchange` among features. `no-restricted-syntax` covers `dangerouslySetInnerHTML` and `innerHTML`/`outerHTML`/`insertAdjacentHTML` assignment. `no-restricted-globals` and `no-restricted-properties` cover `localStorage`, `sessionStorage`, `window.localStorage` and `window.sessionStorage`. Each rule has a self-test running ESLint's Node API on a failing and a passing snippet | `react/no-danger` would need `eslint-plugin-react`, which is not in SD25. The core rule enforces the same thing. The `innerHTML` ban goes past `no-danger` and is D-25's actual sink |
| PD10 | AC20's "handshake rejected (1008)" in a browser | A pre-accept rejection reaches the browser as an HTTP 403 on the upgrade, which the `WebSocket` API reports as close **1006**, indistinguishable from a network failure. The client treats it as `offline`; SD17's first poll fires **immediately** on entering `offline` and gets 401, which follows SD12. The client also handles 1008 and 4401 directly for the cases where they are visible. Playwright proves the path (T23: cookie cleared, then socket killed, then the browser lands on `/login?next=/koers`) | The browser hides the code. Spec SD12/SD17 already route a poll 401 to login, so no new behaviour is invented |
| PD11 | SD18's server timestamp | `pong.data.server_ts_ms` (`messages.py:170`). The envelope `ts_ms` is ignored for skew | The pong's own field is the documented one (`realtime-protocol.md:73`) |
| PD12 | Error typing | `lib/http.ts` parses failures with one Zod schema for `{error: {code, message, …}}`. Generated OpenAPI types are used for success bodies only (`Me`, `Snapshot`, `ThemeData`) | FastAPI documents `HTTPValidationError{detail}`, but the app returns its own envelope (`app/core/errors.py:76-98`), and `AppError` statuses are not in the schema. Trusting the generated error types would type-check against a shape the server never sends |
| PD13 | Where `/settings` is composed | `features/theme` exports `ThemeSection`. `app/pages/SettingsPage.tsx` (app layer) renders it above the "Nog niet beschikbaar" placeholder. Phase 6 creates `features/settings` and moves the composition | Sibling isolation (`frontend-architecture.md:46-47`): a `features/settings` cannot import `features/theme`. The app layer may import features |
| PD14 | E2E shape | A Python launcher, `tests/integration/realapp/serve.py`, reuses `harness.py` (`seed_live_run`, `mint_key`, `spawn_app`, `free_port`). It creates and migrates a scratch database on the compose server, seeds v1's 6-drink run, mints display, bar and admin keys, starts `python -m app.main`, and writes `{base_url, keys}` to a JSON file **under the OS temp dir**. That file is never in the repo (`tests/meta/test_repo_hygiene.py` bans key literals). Playwright's `globalSetup` spawns the launcher and `globalTeardown` stops it. Shape cases (9 drinks, XSS name, market event with end suppressed, no live run, `correction`) use `page.routeWebSocket` with frames built from T12's fixture | One real server keeps the gate under about 90 s and the advisory lock uncontended. The injected frames are the recorded server shapes, so they cannot drift (SD26) |
| PD15 | lightweight-charts attribution | Keep v5's default `attributionLogo`. v1 hid TradingView's link (`koers.html:94`). **Confirm at the audit** | The Apache-2.0 NOTICE asks for attribution. It is an anchor, not a request, so AC1 (zero non-origin *requests*) holds. If T22's check flags its `href` string as a reference, the builder stops and asks rather than allowlisting |
| PD16 | `web/src/lib/` versus CLAUDE.md "There is no `lib/`" | That rule is about the Python tree. `web/src/lib/` already exists (`config.ts`) and is the design's (`frontend-architecture.md:39`). No change to CLAUDE.md | Saying so here so the auditor does not trip on it |
| PD17 | Dutch strings the spec does not fix | Login failure: v1's **"Ongeldige toegangscode."** (`legacy/v1/static/login.html:69`), shown for both 401 and an unknown key, so existence is not revealed (AC21). Network failure: v1's **"Verbindingsfout. Probeer opnieuw."** (`:74`). 429: **"Te veel pogingen. Probeer het over een minuut opnieuw."** (new). Placeholder, no access, banner and empty state: the spec's own strings. **Confirm the 429 string at the audit** | Ported verbatim where v1 has a string, per `frontend-architecture.md:3-4` |
| PD18 | Generating the API types | `scripts/gen_api_types.sh` runs `uv run python -c` to dump `create_app().openapi()` (callable with no environment, as the analyst ran it) to a temp file, then `pnpm --dir web exec openapi-typescript <tmp> -o web/src/api/generated/schema.d.ts`. The gate runs it and then `git diff --exit-code -- web/src/api/generated` | SD3/SD26: in-process, not over HTTP. One script, used by both developers and the gate |
| PD19 | The WS fixture | `tests/api/ws_fixture.py` drives a `TestClient` session on the `FakeClock` with a seeded 3-drink run. It records one frame of every server type (`hello`, `snapshot`, `tick`, `order`, `market_event` start/end, `news`, `theme`, `pong`, `resync`, `error`) and normalises `boot_id` to a constant. `--write` regenerates `web/src/features/exchange/model/__fixtures__/ws-messages.json`, and the test `tests/api/test_ws_fixture.py` fails on any difference. This mirrors `tests.engine.golden.capture --check/--write` | Either side drifting fails the gate (SD26). The pattern is already in the repo |

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `app/runtime/theme.py`, `tests/unit/test_theme_manifest.py` | Create (T1) | Token manifest, presets, fonts, `resolve`, `render_css` (SD5–SD7) |
| `db/migrations/versions/0008_theme.py`, `app/db/models.py`, `app/db/theme.py`, `tests/integration/test_schema.py`, `tests/integration/test_theme_repo.py` | Create / Modify (T2) | `theme` table, repository |
| `app/realtime/messages.py`, `app/realtime/hub.py`, `tests/unit/test_messages.py`, `tests/unit/test_hub.py` | Modify (T3) | `ThemeData`, `theme` type, `Hello.theme`, PD6 |
| `app/api/theme.py`, `app/runtime/boot.py`, `app/main.py`, `tests/meta/test_route_authorization.py`, `tests/api/test_authorization_matrix.py`, `tests/api/test_theme.py` | Create / Modify (T4) | `GET /theme.css`, `PUT /api/theme`, PD5 |
| `app/realtime/ws.py`, `tests/api/test_ws_theme.py` | Modify / Create (T5) | `hello.theme`, PD7 catch-up |
| `app/main.py`, `tests/api/test_static.py` | Modify (T6) | PD8 |
| `app/runtime/ticker.py`, `tests/integration/test_ticker.py`, `docs/adr/0003-single-writer-owns-time.md` | Modify (T7) | SD29–SD31 |
| `web/package.json`, `web/pnpm-lock.yaml`, `web/vite.config.ts` | Modify (T8) | PD1; the Vitest `test` block |
| `web/eslint.config.js`, `web/src/lint-rules.test.ts` | Modify / Create (T9) | SD27, PD9 |
| `web/src/lib/format.ts`, `web/src/lib/format.test.ts`, `web/src/lib/http.ts`, `web/src/lib/http.test.ts` | Create (T10) | SD22, PD12, the 401 half of SD12 |
| `scripts/gen_api_types.sh`, `web/src/api/generated/schema.d.ts`, `web/src/api/generated/.gitkeep`, `scripts/check.sh` | Create / Modify / Delete (T11) | PD18, the drift step |
| `tests/api/ws_fixture.py`, `tests/api/test_ws_fixture.py`, `web/src/features/exchange/model/__fixtures__/ws-messages.json`, `web/src/features/exchange/model/schemas.ts`, `web/src/features/exchange/model/schemas.test.ts` | Create (T12) | PD19, SD26 |
| `web/src/features/exchange/{index.ts, model/applyMessage.ts, model/applyMessage.test.ts, model/store.ts, model/selectors.ts, model/sma.ts, model/sma.test.ts}` | Create (T13) | Reducer, store, SMA |
| `web/src/features/exchange/{index.ts, model/client.ts, model/client.test.ts, model/skew.ts, model/skew.test.ts, model/backoff.ts}` | Create / Modify (T14) | WS state machine |
| `web/src/components/ui/{Button.tsx, NavMenu.tsx, NavMenu.test.tsx, StatusDot.tsx}`, `web/src/app/AppShell.tsx`, `web/src/app/pages/{Placeholder.tsx, NoAccess.tsx}`, `web/src/assets/logo.png` | Create (T15) | Shell components |
| `web/src/features/auth/{index.ts, LoginPage.tsx, useSession.ts, RequireRole.tsx, auth.test.tsx}`, `web/src/app/routes.tsx`, `web/src/app/App.tsx`, `web/src/main.tsx` | Create / Modify / Delete (T16) | Auth, routing |
| `web/src/features/theme/{index.ts, ThemeProvider.tsx, ThemeProvider.test.tsx}`, `web/src/app/providers.tsx`, `web/src/app/AppShell.tsx`, `web/index.html`, `web/src/main.tsx`, `web/src/styles/base.css` | Create / Modify (T17) | Theme application, fonts, connection banner |
| `web/src/features/theme/{index.ts, ThemeSection.tsx, ThemeSection.test.tsx}`, `web/src/app/pages/SettingsPage.tsx`, `web/src/app/routes.tsx` | Create / Modify (T18) | Preset picker (SD10, PD13) |
| `web/src/features/koers/ui/{DrinkChart.tsx, DrinkChart.test.tsx, chartOptions.ts}` | Create (T19) | Chart host |
| `web/src/features/koers/{index.ts, KoersPage.tsx, KoersPage.module.css, Tile.tsx, Tile.test.tsx, HeaderClock.tsx}`, `web/src/app/routes.tsx` | Create / Modify (T20) | The board |
| `web/src/components/ui/{Marquee.tsx, Marquee.test.tsx}`, `web/src/features/koers/{PriceMarquee.tsx, NewsMarquee.tsx, MarketEventLayer.tsx, MarketEventLayer.test.tsx, KoersPage.tsx}`, `web/src/styles/keyframes.css` | Create / Modify (T21) | Marquees, market events |
| `scripts/check_built_assets.py`, `tests/unit/test_check_built_assets.py`, `scripts/check.sh` | Create / Modify (T22) | AC2, the build step |
| `tests/integration/realapp/serve.py`, `web/playwright.config.ts`, `web/e2e/{global-setup.ts, global-teardown.ts, fixtures.ts, auth.spec.ts}`, `web/package.json`, `web/.gitignore`, `scripts/check.sh`, `scripts/setup.sh`, `.github/workflows/ci.yml` | Create / Modify (T23) | SD28, PD14 |
| `web/e2e/{board.spec.ts, offline.spec.ts, frames.ts}` | Create (T24) | Board e2e |
| `web/e2e/theme.spec.ts` | Create (T25) | Theme e2e |
| `docs/design/{realtime-protocol,data-model,frontend-architecture}.md`, `docs/specs/phase-3-api-realtime.md` | Modify (T26) | In-scope doc updates |

### New dependencies (approval notes, PD1)

Versions are resolved at install. The builder pins the major version with `^`.

| Package | What it does | Why not the platform / stdlib | Licence | Maintenance |
|---|---|---|---|---|
| `react-router` (runtime) | Client routes, `RequireRole` wrapping, `?next=` | The History API alone means hand-writing matching, nested layouts and navigation state | MIT | Remix/Shopify. Active, v7 line, the de-facto React router |
| `zustand` (runtime) | The one store, subscribable outside React (zero-render ticks) | `useSyncExternalStore` plus a hand-rolled store would be the same 1 kB with no tests | MIT | pmndrs. Active, about 1 kB |
| `lightweight-charts@^5` (runtime) | Candle and line series | Canvas charts by hand are a project of their own. ADR 0006 names it | Apache-2.0 (NOTICE asks for attribution, PD15) | TradingView. Active, v5 is tree-shakeable ESM |
| `zod` (runtime) | Validates every WS frame and HTTP body at the boundary | The no-untyped-boundary rule (`CLAUDE.md`). The platform has no runtime schema validation | MIT | colinhacks. Active, widely used |
| `@fontsource/inter`, `@fontsource/eb-garamond` (runtime, CSS and fonts only) | Self-hosted fonts, latin subset (D-13) | The alternative is committing `.woff2` files by hand with no update path | Package MIT, fonts OFL-1.1 | Fontsource org. Active |
| `openapi-typescript` (dev) | TS types from `create_app().openapi()` (SD26) | No stdlib equivalent. Hand-written types drift | MIT | openapi-ts org. Active |
| `@testing-library/react` (dev) | Component tests (`NavMenu`, `RequireRole`, `ThemeSection`, `Tile`) | React's test utils were removed from React 19 | MIT | testing-library org. Active |
| **`@testing-library/dom` (dev, not in SD25)** | Required peer of `@testing-library/react` ≥ 16 | It cannot be avoided if RTL is used | MIT | Same org |
| `jsdom` (dev) | DOM for Vitest component tests (per-file `@vitest-environment jsdom`, default stays `node`) | Node has no DOM | MIT | jsdom org. Active |
| `@playwright/test` (dev) | E2E in the gate (SD28). Chromium only, installed by `playwright install chromium` | No alternative that can block requests and route WebSockets | Apache-2.0 | Microsoft. Active |

Not added: `eslint-plugin-react` (PD9), `@testing-library/user-event` (`fireEvent` is enough),
`@testing-library/jest-dom`, any CSS framework, TanStack Query (rejected by the design).

---

## Tasks

Every task leaves `./scripts/check.sh` green. Branches follow `feature/phase-4-tN-<slug>`.
Integration and API tests reuse Phase 2/3's fixtures (`tests/integration/conftest.py`,
`tests/api/conftest.py`: `client`, `live_client`, `mint_key`, `login`, `advance`, `FakeClock`).
Nothing touches `exchange/`. `engine-guardian` runs on T7, because it changes when the ticker
ends events. Reuse, by name:
- `app/api/security.py` (`ROLE_ROUTES`, `require_role`, `OriginGuard`), `app/api/deps.py`, and
  `app/core/errors.py` (`AppError`)
- `app/db/keys.py` as the repository shape
- `app/realtime/hub.py` (`broadcast`, `unicast`) and `app/realtime/messages.py` (`_Closed`,
  `Envelope`)
- `tests/integration/realapp/harness.py`
- v1's `theme.js`/`koers.html` as the port source, read only

The web tests use per-file `// @vitest-environment jsdom` only where a DOM is needed.

### T1 — Token manifest, pure

- **Implements:** SD5 (Blauw fallback), SD6, SD7; AC9 and AC10 (server halves); PD2, PD3
- **Expected output:** `app/runtime/theme.py`:
  - `TOKEN_NAMES: Final[tuple[str, ...]]`, the 24 names in v1's order with the split four in place of `--up`/`--down`.
  - `PRESETS: Final[Mapping[PresetName, Preset]]` with the five keys `oudgeld`, `blauw`, `groen`, `paars`, `rood`, Dutch labels (`Oud Geld`, `Blauw`, `Groen`, `Paars`, `Rood`), swatches (`THEME_META`, `theme.js:72-77`), token values ported **verbatim** from `theme.js`, and `font_family` per PD3.
  - The split mapping: `--candle-up = up`, `--candle-down = down`, `--tile-rising = down`, `--tile-falling = up`.
  - `DEFAULT_PRESET = "blauw"`.
  - `resolve(preset, revision) -> ThemeData`.
  - `render_css(theme) -> str`, which emits `:root{…24 tokens…}` and `body{background:var(--bg);color:var(--text);font-family:…}`.
  - No I/O, no clock.
- **Verification:** `uv run pytest tests/unit/test_theme_manifest.py -v`:
  - exactly 24 tokens per preset, and every preset has the same key set;
  - a table test of every value against `legacy/v1/static/theme.js`, parsed in the test with a regex, so a transcription error fails;
  - the split mapping per preset;
  - the font per preset;
  - `render_css` contains every token, and the `body` rule is present;
  - an unknown preset raises.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** type names and the CSS formatting.
  - **Must stop and ask if:** the count is not 24 (PD2), or a v1 value seems wrong. Port it anyway; do not "fix" colours.

### T2 — The `theme` table

- **Implements:** SD5; AC8 (the "stored theme unchanged" half), AC9 (no row); PD4
- **Expected output:**
  - `db/migrations/versions/0008_theme.py` (`down_revision = "0007"`) creates `theme(id SMALLINT PK DEFAULT 1 CHECK id = 1, preset TEXT NOT NULL CHECK IN (five keys), revision INTEGER NOT NULL CHECK revision >= 1, updated_at timestamptz NOT NULL DEFAULT now())`, with a full `downgrade()`.
  - `app/db/models.py` gets `Theme`.
  - `app/db/theme.py` holds:
    - `ThemeRow` (frozen dataclass);
    - `get_theme(conn) -> ThemeRow | None`;
    - `set_theme(conn, preset) -> ThemeRow`, one `INSERT … ON CONFLICT (id) DO UPDATE SET preset = excluded.preset, revision = theme.revision + 1, updated_at = now() RETURNING …`, so a first write is revision 1 and each write after adds 1, atomically.
  - The caller owns the transaction (the `app/db/keys.py` contract).
- **Verification:**
  - `uv run pytest tests/integration/test_migrations.py tests/integration/test_schema.py tests/integration/test_theme_repo.py -v`:
    - the round trip;
    - `PHASE_4_TABLES = {"theme"}` added to the exact-set test;
    - a second row and an unknown preset are rejected;
    - two sequential writes give revisions 1 and 2;
    - `get_theme` on an empty table is `None`.
  - `uv run pytest tests/meta/test_migration_scaffolding.py`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** constraint names.
  - **Must stop and ask about:** any column beyond PD4's four. That is the data model, a hard stop.
  - Never edit 0001–0007.

### T3 — `theme` message, `hello.theme`, hub guard

- **Implements:** SD9 (models); AC6 and AC9 (hello half); PD3, PD6
- **Expected output:** in `app/realtime/messages.py`:
  - `ThemeData(_Closed)` per PD3, with `tokens` validated to exactly `TOKEN_NAMES`;
  - `"theme"` added to `ServerMessageType`, `SERVER_MESSAGE_MODELS` and `ServerData`;
  - `Hello.theme: ThemeData`.

  In `app/realtime/hub.py`, `broadcast` updates `_run_id`/`_version` only when `envelope.version is not None` (PD6). `app/realtime/ws.py` is **not** touched here. Its `hello` construction gets the field in T5, so this task changes `Hello` with a temporary `resolve(DEFAULT_PRESET, 0)` default only if the existing tests need it to stay green; T5 removes that default.
- **Verification:**
  - `uv run pytest tests/unit/test_messages.py tests/unit/test_hub.py -v`:
    - an envelope `type="theme"` with `ThemeData` round-trips, and a wrong data model is rejected;
    - extra or missing tokens are rejected;
    - after a `tick` broadcast and then a theme broadcast, `resync_frame()` still carries the tick's `run_id`/`version`.
  - `uv run pytest tests/api/test_ws.py`, which still passes.
- **Depends on:** T1
- **Autonomy note:**
  - **May decide alone:** validator placement.
  - **Must stop and ask about:** any field on `ThemeData` beyond PD3, or changing another message.

### T4 — `GET /theme.css` and `PUT /api/theme`

- **Implements:** SD5, SD8, SD9 (write and broadcast); AC8, AC9 (CSS), AC10 (CSS), AC5 (server broadcast with no run); PD5
- **Expected output:** `app/api/theme.py` with two routers.

  `theme_css_router`, no prefix:
  - `GET /theme.css` returns `render_css(app.state.theme)`.
  - `media_type="text/css"`, `Cache-Control: no-cache`, `ETag: "theme-<revision>"`.
  - 304 on a matching `If-None-Match`.

  `theme_router` under `/api`:
  - `PUT /api/theme` takes `{preset}` (`extra="forbid"`) and requires `require_role("admin")`.
  - An unknown preset gives 422 `invalid_request` through the existing handler.
  - It runs `set_theme` in `engine.begin()`, updates `app.state.theme` if the revision is higher, broadcasts `theme` via `app.state.hub` (`run_id = holder.run_id`, `version=None`), and returns `ThemeData` (200).

  Elsewhere:
  - `start_runtime` (`app/runtime/boot.py`) loads `app.state.theme` after migrate (Blauw, revision 0, when there is no row).
  - `app/main.py` includes both routers, the CSS router before the SPA mount.
  - `PUBLIC_ROUTES` gains `("GET", "/theme.css")`, and its exact-equality test is updated. SD8 is the human's authorisation, cited in the test's docstring.
  - The authorization matrix gains `PUT /api/theme → admin`, and `_status` sends a valid body for PUT.
- **Verification:** `uv run pytest tests/api/test_theme.py tests/api/test_authorization_matrix.py tests/meta/test_route_authorization.py tests/api/test_static.py -v`.

  `test_theme.py` covers:
  - **AC9:** a fresh database serves Blauw's `--bg` and Inter.
  - **AC8:** display → 403 and bar → 403. `{"preset":"eigen"}` → 422, and the stored row is unchanged in each case.
  - **AC10:** after a PUT of `oudgeld`, the CSS has the EB Garamond stack.
  - **ETag and 304.**
  - A cross-origin PUT → 403 (`OriginGuard`).
  - **AC5:** with no live run, a PUT is followed by exactly one `theme` broadcast in `hub`'s log, observed through a test hub or a WS client.
  - A PUT never takes `holder.lock`: hold the lock from the test and assert the PUT still completes.
- **Depends on:** T1, T2, T3
- **Autonomy note:**
  - **May decide alone:** router names and the ETag format.
  - **Must stop and ask about:** caching beyond `no-cache` plus ETag, or adding any other public route.

### T5 — Theme over the WebSocket

- **Implements:** SD9; AC5, AC6, AC9 (hello); PD7
- **Expected output:** in `app/realtime/ws.py`:
  - `hello` carries `app.state.theme`, with or without a live run.
  - After the handshake's replay or snapshot, and after every `resync_request` snapshot, the session unicasts `theme` with the current theme (PD7).
  - T3's temporary default on `Hello.theme`, if any, is removed.
- **Verification:** `uv run pytest tests/api/test_ws_theme.py tests/api/test_ws.py -v`:
  - **AC9:** `hello.theme.preset == "blauw"` on an empty table.
  - **AC5:** with no live run, a connected client receives `theme` after an admin PUT.
  - **AC6:** connect, record `boot_id`/`last_seq`, disconnect, PUT, reconnect with `hello{boot_id, last_seq}`. The replay contains the `theme` frame, and the client holds the new revision.
  - **PD7:** a `resync_request` is answered by `snapshot` and then `theme`.
  - Two racing PUTs give two broadcasts with increasing revisions.
- **Depends on:** T4
- **Autonomy note:**
  - **May decide alone:** the helper layout in `ws.py`.
  - **Must stop and ask if:** PD7 was not confirmed at the audit. In that case implement SD9 only and report windows (a)–(c) as open.

### T6 — History-mode fallback for SPA routes

- **Implements:** AC20 (`/login?next=` lands on a page), AC21–AC23 (a reload of any role route renders the app); PD8
- **Expected output:**
  - `SpaStaticFiles(StaticFiles)` in `app/main.py` (or `app/api/static.py` if `main.py` grows past readability).
  - On a 404 for a GET of a path in `SPA_ROUTES = {"/login"} | {r for routes in ROLE_ROUTES.values() for r in routes}`, it serves `index.html`.
  - Every other unknown path keeps a plain 404.
  - The comment at `main.py:178-184` is rewritten to say what is served and why.
- **Verification:** `uv run pytest tests/api/test_static.py -v`:
  - with a tmp `dist` holding **only** `index.html` (the real Vite shape), `/login`, `/koers` and `/settings` each return 200 with `index.html`;
  - `/probe`, `/koers/x` and `/api/nope` return 404, and `/api/nope` is still JSON;
  - `/assets/x.js` is served when it exists.
- **Depends on:** T4 (shares `app/main.py`)
- **Autonomy note:**
  - **May decide alone:** the class's location.
  - **Must stop and ask if:** PD8 was not confirmed.
  - Do not add the SPA paths as FastAPI routes. That would enter the public allowlist.

### T7 — Ticker carry-overs

- **Implements:** SD29, SD30, SD31; AC36, AC37
- **Expected output:**
  - **SD29:** in `app/runtime/ticker.py`, `_iterate` ends due events against the tick's **actual** stamp, `max(grid_ms, last_commit_wall_ms)` as computed in `_tick_step`. The step makes that stamp available to the caller (for example `Outcome.result` carries `(version, stamp_ms)`, or the ticker keeps `_last_stamp_ms`), and `_end_due_events(stamp_ms)` receives it.
  - **SD30:** `_tick_step` gets a docstring stating the freeze (a wall clock stepping back by less than the 30 s budget holds stamps at the last commit's time until the grid passes it, for at most the budget).
  - **SD30:** ADR 0003 gains the same note under "Why bounded catch-up" (after `:48-52`). This is authorised by the spec's In scope and does not reverse the decision.
  - **SD31:** the existing test gains the price assertion.
- **Verification:** `uv run pytest tests/integration/test_ticker.py -v`:
  - **AC36:** a new test in the shape of `test_an_event_ending_within_the_next_interval_ends_on_that_slot` (`:292-327`). A jump pulls the actual stamp ahead of the grid, and an event whose `t_end_ms` lies between the grid stamp and the actual stamp ends on that tick, not the next.
  - **AC37:** in `test_a_tick_is_never_stamped_before_the_commit_it_follows` (`:214-236`), the jumped drink's `p_q` on the following tick row equals the jump row's.

  Then `uv run pytest tests/engine` (golden green) and the `engine-guardian` review.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** how the stamp is threaded out of the step.
  - **Must stop and ask if:** AC37's equality does not hold. That is a pricing finding, not a test to loosen.

### T8 — Web dependencies and Vitest config

- **Implements:** SD25; PD1. It enables AC1–AC35 (client side)
- **Expected output:**
  - `pnpm --dir web add react-router zustand lightweight-charts@^5 zod @fontsource/inter @fontsource/eb-garamond`.
  - `pnpm --dir web add -D openapi-typescript @testing-library/react @testing-library/dom jsdom @playwright/test`.
  - `pnpm-lock.yaml` regenerated.
  - A `test` block in `vite.config.ts` (`environment: "node"`, `include: ["src/**/*.test.{ts,tsx}"]`, `restoreMocks: true`), typed via `vitest/config`.
  - The PR body carries the approval notes.
- **Verification:**
  - `pnpm --dir web install --frozen-lockfile`.
  - `pnpm --dir web exec tsc -b`.
  - `pnpm --dir web run test --run`.
  - `./scripts/check.sh`.
- **Depends on:** —
- **Autonomy note:**
  - **Must stop and ask before `pnpm add`.** Each package needs explicit approval, `@testing-library/dom` especially (not in SD25).
  - Also stop if a package's licence differs from the table.

### T9 — Lint invariants

- **Implements:** SD27; AC12 (storage ban), AC32 (no HTML sinks); PD9
- **Expected output:** `web/eslint.config.js` with:
  - the `boundaries/element-types` rules: `features/exchange` imports no `features/*`, and other features import only `features/exchange` among features (sibling-isolated);
  - the HTML-sink `no-restricted-syntax` selectors;
  - the storage `no-restricted-globals`/`-properties`.

  `web/src/lint-rules.test.ts` uses `new ESLint({ overrideConfigFile })` and `lintText` on one violating and one clean snippet per rule, with fake `filePath`s under `src/features/...`.
- **Verification:**
  - `pnpm --dir web run test --run src/lint-rules.test.ts`.
  - `pnpm --dir web lint`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** selector details and the test file's location, as long as `pnpm test` runs it.
  - **Must stop and ask about:** adding an ESLint plugin.

### T10 — Formatter and HTTP wrapper

- **Implements:** SD22; AC20 (401 half), AC26 (tile text); PD12
- **Expected output:**
  - `lib/format.ts`: `formatEuro(cents)` → `"€ 2,50"`, `nl-NL`, two decimals, from integer cents, the one euro formatter; `formatPercent(x)`, one decimal.
  - `deltaText(prev, cur)` ports `koers.html:646-652`: `—` when unchanged, otherwise `▲`/`▼` plus the amount plus `(x,x%)`, using the formatters above.
  - `lib/http.ts`: `request(method, path, {body, schema})`. It sends JSON, parses the body with the given Zod schema, and parses failures with one `ErrorEnvelope` schema into `HttpError{status, code}`.
  - A 401 calls a registered `onUnauthenticated()` hook, which T16 wires to navigation.
- **Verification:** `pnpm --dir web run test --run src/lib`:
  - formatter table: 0, 5, 250, 1000, 123456 cents, and negatives for deltas;
  - `http` with a stubbed `fetch`: success parse, error-envelope parse, 401 calls the hook exactly once, and a malformed body is a typed error rather than `any`.
- **Depends on:** T8
- **Autonomy note:**
  - **May decide alone:** function names.
  - **Must stop and ask about:** any formatting differing from SD22.

### T11 — Generated API types and the drift step

- **Implements:** SD26 (OpenAPI half); it enables AC8 (client) and AC21 (`Me`); PD18
- **Expected output:**
  - `scripts/gen_api_types.sh` as PD18 describes.
  - A committed `web/src/api/generated/schema.d.ts`, with `.gitkeep` removed.
  - `scripts/check.sh` gains a step "web api types drift" after `web tsc -b`, `TOTAL` is updated, and the gate's header docstring lists it.
  - The script excludes the generated file from Prettier and ESLint if they object (`web/.prettierignore`); the builder adds that line.
- **Verification:**
  - `./scripts/gen_api_types.sh && git diff --exit-code -- web/src/api/generated`.
  - A deliberate local edit to a response model makes the gate step fail. Report it, then revert.
  - `./scripts/check.sh`.
- **Depends on:** T4, T8
- **Autonomy note:**
  - **May decide alone:** the script's shell details and the temp path.
  - **Must stop and ask about:** dumping the schema over HTTP, or committing the JSON schema itself.

### T12 — WS schemas and the recorded fixture

- **Implements:** SD26 (WS half); it enables AC17–AC19 and AC7 on real shapes; PD19
- **Expected output:**
  - `tests/api/ws_fixture.py` (`python -m tests.api.ws_fixture --check|--write`) and `tests/api/test_ws_fixture.py`, which calls the check.
  - The committed `ws-messages.json`, with one frame per server type.
  - `features/exchange/model/schemas.ts`: Zod schemas for the envelope and every server message, as a discriminated union on `type`, plus the client messages.
  - `schemas.test.ts` parses every fixture frame and asserts each server type in the schema union appears in the fixture.
- **Verification:**
  - `uv run pytest tests/api/test_ws_fixture.py -v`.
  - `pnpm --dir web run test --run src/features/exchange/model/schemas.test.ts`.
  - Drift proof, both directions, reported then reverted: add a field to `TickData` locally and the Python check fails; remove a field from the Zod schema and Vitest fails.
- **Depends on:** T5, T8
- **Autonomy note:**
  - **May decide alone:** the recording script's internals and the normalisation of non-deterministic fields (`boot_id` only; `ts_ms` is deterministic on `FakeClock`).
  - **Must stop and ask about:** normalising anything else.

### T13 — Exchange store, `applyMessage`, SMA

- **Implements:** AC7, AC17, AC18 (apply half), AC19, AC35; SD11, SD16 (state half), SD23
- **Expected output:** `features/exchange/model/applyMessage.ts`, a pure `(state, msg) → state` with an exhaustive `switch` and a `never` check, no timers, DOM or network. It does the following:
  - **`hello`:** a different `boot_id` clears live state (AC19); `run_id` null sets `empty`; the theme is applied only if its revision is higher (AC7).
  - **`snapshot`:** replaces drinks, prices, bars, news and market events wholesale, and sets `seq`. It does not mark pulses (AC17, SD23).
  - **Broadcasts:**
    - `seq === held + 1` → apply;
    - `seq > held + 1` → set `awaitingResync`, which the client reads to send `resync_request`, and apply nothing until a `snapshot` (AC18);
    - `seq === held` → only unicast types (`hello`, `snapshot`, `pong`, `error`, `theme`, per PD7).
  - **`tick`/`order`:** update prices and the current bar per drink (bars keyed by bucket time; replace the last bar if its time matches, otherwise append), and record the previous displayed `price_cents` for pulse direction (SD23).
  - **`market_event`:** start or end. A late end is a no-op.
  - **`theme`:** revision rule.

  Also:
  - `store.ts`: one Zustand store (`createStore`, usable outside React) holding status, `boot_id`, `seq`, theme, skew offset, drinks, prices, bars, news, market events and `empty`.
  - `selectors.ts`.
  - `sma.ts`: `smaSeries(bars, 5)` over closes (SD11).
  - `index.ts`: the feature's public surface.
- **Verification:** `pnpm --dir web run test --run src/features/exchange/model`. Fixture frames from T12 are the inputs:
  - every message type;
  - a gap, then a snapshot clearing `awaitingResync`;
  - a boot change;
  - theme revision equal, lower and higher;
  - pulse direction for up, down, unchanged, and snapshot (no pulse);
  - SMA against a hand-computed table, including fewer than 5 bars (no point) and a tick replacing the last bar's close.
- **Depends on:** T12
- **Autonomy note:**
  - **May decide alone:** state shape and selector names.
  - **Must stop and ask about:** synthesising or rebucketing a bar (SD3), or applying anything during `awaitingResync`.

### T14 — The WebSocket client

- **Implements:** AC13, AC14, AC15, AC16 (client half), AC18 (send), AC20 (WS half); SD14–SD18; PD10, PD11
- **Expected output:** `features/exchange/model/client.ts` (about 150 lines, per the design) is a state machine `connecting → open → offline` with injected `WebSocket` factory, timers, `random()`, `now()` and `fetchState()`. It does the following:
  - **On open:** sends `hello{boot_id, last_seq}`, starts `ping` every 15 s, arms a 45 s deadline that **any** inbound frame resets, stops polling, and resets the backoff.
  - **Deadline expiry:** `close()` and reconnect.
  - **On close:**
    - 4401 or 1008 → `onSessionLost`;
    - otherwise go `offline`, poll `GET /api/state` immediately and then every 5 s, applying the result as a `snapshot`;
    - a poll 409 means the empty state, and a poll 401 → `onSessionLost` (PD10);
    - schedule a reconnect via `backoff.ts` (`500 × 1.7ⁿ`, capped at 8000, × uniform[0.7, 1.3]).
  - **During the run:** `awaitingResync` sends `resync_request` once.

  `skew.ts` keeps the last 8 samples, `offset = server_ts_ms − (sent + received)/2`, takes the minimum round trip, and falls back to `hello.ts_ms − received` before the first pong (PD11).
- **Verification:** `pnpm --dir web run test --run src/features/exchange/model/client.test.ts src/features/exchange/model/skew.test.ts`, on fake timers with a fake socket:
  - **AC13:** no frame for 45 s means close and reconnect; a frame at 44 s means no close.
  - **AC14:** pings at 15, 30 and 45 s.
  - **AC15:** with `random` stubbed at 0, 0.5 and 1, each delay sits in [0.7×, 1.3×] of the curve, the cap is 8 s, and the backoff resets after open.
  - **AC16 (client half):** polling starts on close, runs every 5 s, and stops on open.
  - **AC18:** a gap sends exactly one `resync_request`.
  - **AC20:** 4401 and 1008 call `onSessionLost`, and a poll 401 does too.
  - **Skew:** min-RTT selection and the fallback.
- **Depends on:** T10, T13
- **Autonomy note:**
  - **May decide alone:** internal structure and the event names.
  - **Must stop and ask about:** changing any SD14/SD15/SD17 constant.

### T15 — Shell components

- **Implements:** AC22 (nav), AC23 (placeholder); SD4, SD13
- **Expected output:**
  - **`components/ui/NavMenu.tsx`:** renders exactly the `allowed_routes` it is given, with Dutch labels: `/` → Home, `/koers` → Live koersbord, `/bar` → Bar, `/manipulation` → Spel mechanica, `/settings` → Instellingen. These are v1's labels (`koers.html:248-258`). It also has an "Uitloggen" item that calls a passed handler. Label lookup is presentation only, **not** a role table.
  - **`Button.tsx`** and **`StatusDot.tsx`**.
  - **`app/AppShell.tsx`:** the header with the logo, the nav, and a slot for the banner (T17).
  - **`app/pages/Placeholder.tsx`** ("Nog niet beschikbaar") and **`NoAccess.tsx`** ("Geen toegang").
  - **`assets/logo.png`:** v1's `logo_medium.png`, copied byte-for-byte and imported (hashed by Vite).
- **Verification:** `pnpm --dir web run test --run src/components/ui/NavMenu.test.tsx`:
  - for each of the three roles' `allowed_routes` (from Phase 3 SD2), the links are exactly those routes;
  - a route missing from the label map still renders its path, so it is never dropped silently.
- **Depends on:** T8
- **Autonomy note:**
  - **May decide alone:** markup and CSS-module structure.
  - **Must stop and ask about:** new user-facing strings beyond v1's labels and the spec's.

### T16 — Auth and routing

- **Implements:** AC20, AC21, AC22 (no access), AC23; SD4, SD12, SD13; PD17
- **Expected output:**
  - **`features/auth`:** `useSession()` (`GET /api/auth/me`, generated `Me` type) and `RequireRole(route)`, which renders `NoAccess` when the route is not in `allowed_routes`, never a redirect.
  - **`LoginPage`:** posts `{key}`. On success it navigates to `next` if it is in `allowed_routes`, otherwise to `allowed_routes[0]`. On failure it shows PD17's strings.
  - **`app/routes.tsx`:** `/login`, then every route in Phase 3 SD2's map, rendered as `Placeholder` inside `AppShell` for now (`/koers` and `/settings` are replaced in T18/T20). Unknown → `NoAccess`.
  - **`onSessionLost`/`onUnauthenticated`:** navigate to `/login?next=<current path>`.
  - **Wiring:** `App.tsx` is removed (its Phase 0 docstring says so), and `main.tsx` mounts the router in `StrictMode`.
- **Verification:** `pnpm --dir web run test --run src/features/auth`, with `fetch` stubbed and a `MemoryRouter`:
  - **AC21:** login per role lands on `/koers`, `/bar` and `/` respectively. A 401 shows "Ongeldige toegangscode." and a 429 shows PD17's string.
  - **AC20:** `next` is honoured when allowed and ignored when not.
  - **AC22:** display on `/settings` sees "Geen toegang".
  - **AC23:** bar on `/bar` sees "Nog niet beschikbaar" inside the shell.
- **Depends on:** T10, T11, T15
- **Autonomy note:**
  - **May decide alone:** the router API style (data router or `<Routes>`).
  - **Must stop and ask about:** any role-to-route mapping in the client (SD13).

### T17 — Theme application, fonts, connection banner

- **Implements:** AC3 and AC5 (client apply), AC4, AC6 (client), AC7 (DOM), AC10, AC16 (banner); SD7, SD8, SD19
- **Expected output:**
  - **`web/index.html`:** `<link rel="stylesheet" href="/theme.css">` before any script. Vite dev serves `/theme.css` through a dev-server proxy to `:8000` that the builder adds in `vite.config.ts` **only if** needed for `pnpm dev`. Note: `vite.config.ts` is T8's; this task is ordered after it.
  - **`main.tsx`:** imports `@fontsource/inter/latin-{400,600,800}.css` and `@fontsource/eb-garamond/latin-{400,500,600,700}.css` (v1's weights).
  - **`features/theme/ThemeProvider`:** subscribes to the store's theme and, on a higher revision, sets each token with `document.documentElement.style.setProperty` and sets `document.body.style.fontFamily`.
  - **`app/providers.tsx`:** after a session exists, starts T14's client once (idempotent under StrictMode), wires `onSessionLost`, and renders `ThemeProvider`.
  - **`AppShell`:** shows SD19's banner "Verbinding verbroken — opnieuw verbinden…" while the status is `offline`.
  - **`styles/base.css`:** uses tokens (`var(--bg)`, `var(--text)`) and drops `color-scheme: light dark`, which fights the theme.
- **Verification:** `pnpm --dir web run test --run src/features/theme`, with jsdom:
  - applying a `theme` message sets all 24 properties;
  - a lower revision changes nothing;
  - Oud Geld sets the EB Garamond stack;
  - the banner appears and disappears with status.

  End-to-end evidence comes in T25 and T24.
- **Depends on:** T14, T16
- **Autonomy note:**
  - **May decide alone:** the provider structure.
  - **Must stop and ask about:** any client-side default theme or preset data (SD6).

### T18 — Preset picker on `/settings`

- **Implements:** AC3 (the admin action), AC8 (the client shows a 403/422 failure); SD10; PD13
- **Expected output:**
  - `features/theme/ThemeSection.tsx`: a "Thema" heading and the five presets as buttons labelled `Oud Geld`, `Blauw`, `Groen`, `Paars` and `Rood`, with the current preset (from the store's theme) marked.
  - The key → label pairs are **UI strings**, not token values, so they do not break SD6. Colour swatches would need preset colours the client does not hold (`ThemeData` carries only the active preset). That is Risks R3's default (a). If the audit picks R3(b), this task renders swatches from the catalogue endpoint instead.
  - Selecting a preset calls `PUT /api/theme`. On failure it shows a Dutch error (the `HttpError` message), and nothing changes locally until the broadcast arrives (the WS is the only writer, `frontend-architecture.md:59`).
  - `app/pages/SettingsPage.tsx` composes `ThemeSection` and the placeholder, and `routes.tsx` routes `/settings` to it.
- **Verification:** `pnpm --dir web run test --run src/features/theme/ThemeSection.test.tsx`:
  - five options, with the current one marked;
  - clicking sends the right `PUT` body;
  - a 403 response shows the error and leaves the marked preset unchanged.
- **Depends on:** T17
- **Autonomy note:**
  - **May decide alone:** layout.
  - **Must stop and ask about:** swatches with colours (R3), and any editor feature (Phase 6).

### T19 — Chart host

- **Implements:** AC11, AC12 (draws server bars), AC27, AC28, AC29, AC35 (SMA series); SD3, SD11
- **Expected output:** `features/koers/ui/DrinkChart.tsx({drinkId})` renders one empty `div`. On mount it does the following:
  - `createChart` with `autoSize`, `handleScroll: false`, `handleScale: false`, crosshair hidden, and `timeScale{timeVisible: true, secondsVisible: false}` (ported from `koers.html:396-425`, v5 API: `chart.addSeries(CandlestickSeries, …)` and `chart.addSeries(LineSeries, …)`);
  - `setData` from the store's bars and their SMA;
  - a store subscription that calls `series.update` for the drink's last bar and SMA point on `tick`/`order`, and `setData` **only** when the store's snapshot generation changes;
  - a `[tokens]` effect calling `applyOptions` with `--candle-up`/`--candle-down` (candles), `--sma-line`, `--grid`, `--muted` (text) and `--input-bg` (background), from `chartOptions.ts`.

  Unmount removes the chart once and nulls the refs, so a double cleanup is a no-op. The component is keyed by `drink_id` at the call site.
- **Verification:** `pnpm --dir web run test --run src/features/koers/ui/DrinkChart.test.tsx`, with `vi.mock('lightweight-charts')` and jsdom:
  - **AC27:** one `setData` per series on mount and on a new snapshot; `update` per tick; never `setData` on a tick.
  - **AC11:** `applyOptions` on a theme change, with no `remove` and no `createChart`.
  - **AC28:** `remove` exactly once under `<StrictMode>` mount-unmount-mount-unmount, and the refs are null after.
  - **AC29:** reordering or renaming drinks in a parent list creates no chart for an unchanged `drink_id`.
  - **AC12:** bars 30 000 ms apart are passed through unchanged (times in seconds per the library, values equal).
  - **AC35:** the SMA points equal `sma.ts` over the same bars.
- **Depends on:** T8, T13
- **Autonomy note:**
  - **May decide alone:** option details not listed.
  - **Must stop and ask if:** v5 lacks an API used here, or the attribution logo cannot stay (PD15).

### T20 — The board

- **Implements:** AC12, AC24, AC25, AC26, AC32 (tiles), AC34; SD20, SD22, SD23
- **Expected output:**
  - **`features/koers/KoersPage.tsx`:** the empty state "Geen actieve borrel" when `empty`; otherwise a tile grid, `HeaderClock` (skew-corrected `HH:MM:SS`, 500 ms) and the legend "Tegels pulseren bij stijging (rood) of daling (groen)." verbatim.
  - **`KoersPage.module.css`:** ports `koers.html:20-35, 73-94, 121-133` (viewport lock, 3-column grid, `grid-auto-rows: 1fr`, `clamp()` sizes, ≤700 px portrait at 1 column scrolling, ≤700 px landscape at 2 columns), with hardcoded rgba replaced by tokens. The pulse uses `--tile-rising`/`--tile-falling`.
  - **`Tile.tsx`:** name as a **text node**, `formatEuro(price_cents)`, `deltaText`, and `DrinkChart` keyed by `drink_id`. The pulse class is set from SD23's direction and cleared on animation end.
  - **Routing:** `routes.tsx` routes `/koers` to it.
- **Verification:** `pnpm --dir web run test --run src/features/koers/Tile.test.tsx`, with jsdom:
  - **AC32:** a name `<img src=x onerror=alert(1)>` renders as text, and `container.querySelector('img')` is null.
  - **AC26:** rising adds the rising class, falling adds the falling class, and a snapshot adds neither.
  - **AC34:** the empty state renders inside `AppShell`; a later snapshot shows tiles with no remount of the page.

  Layout (AC24/AC25) is proved in T24.
- **Depends on:** T17, T18 (shares `routes.tsx`), T19
- **Autonomy note:**
  - **May decide alone:** CSS structure and how the pulse animation is reset.
  - **Must stop and ask about:** any string other than the spec's, or a layout change beyond v1's breakpoints.

### T21 — Marquees and market events

- **Implements:** AC30 (client), AC31, AC32 (marquee text), AC33; SD21, SD24
- **Expected output:**
  - **`components/ui/Marquee.tsx({items, playbackRate})`:** children are text nodes only. It runs one WAAPI `element.animate` (ports `scroll`/`scroll-news` from `koers.html:37-50`) and pauses on hover (SD24). Content changing with the same count keeps the animation as-is. A count change re-creates the keyframes and restores `currentTime` from the previous animation, never from `performance.now()`. `playbackRate` changes call `updatePlaybackRate`.
  - **`PriceMarquee`** shows name, price and delta per drink, duplicated for a seamless loop. **`NewsMarquee`** shows level badge, time and text, with "Geen nieuws" when empty.
  - **`MarketEventLayer`:**
    - `crash`: overlay, banner "⚠ MARKTCRASH", tile shake, news rate 2.5;
    - `bubble`: overlay, banner "▲ PRIJSBUBBEL", tile pulse, news rate 2.5;
    - `correction`: a static banner "Terug naar start", with no overlay and no animation.
  - The layer ends the event locally at `t_end_ms` using `Date.now() + offset` (a timer set from the skew-corrected remaining time, re-armed when the offset changes). A later `end` is a no-op.
  - **`styles/keyframes.css`** ports `koers.html:135-200`.
  - **`KoersPage.tsx`** composes the marquees and the layer.
- **Verification:** `pnpm --dir web run test --run src/components/ui/Marquee.test.tsx src/features/koers/MarketEventLayer.test.tsx`, with jsdom and a stubbed `Element.prototype.animate` that records `currentTime`/`updatePlaybackRate`:
  - **AC33:** same count, so no new animation and `currentTime` unchanged; different count, so `currentTime` carried over; crash or bubble, so rate 2.5, and back to 1 at the end.
  - **AC31:** each kind's DOM, with `correction` having no overlay element and no animation class.
  - **AC30:** with the offset at +300 000 ms and fake timers, the event ends within 1.5 s of `t_end_ms` on server time and no broadcast is needed.
  - **AC32:** an HTML-metacharacter news text is a text node.
- **Depends on:** T20
- **Autonomy note:**
  - **May decide alone:** the keyframe port's details.
  - **Must stop and ask about:** an animation for `correction` (the defect register forbids it).

### T22 — Build step and the built-output reference check

- **Implements:** AC2; D-13 gate half
- **Expected output:**
  - `scripts/check_built_assets.py <dist>` fails on any absolute URL with a host (`http://`, `https://`, `//host`) in a **reference position**:
    - HTML `src`, `href`, `srcset` and `<link>`;
    - CSS `url(…)` and `@import`;
    - JS `import(…)`, `import … from`, `new URL(…)`, `fetch(…)`, `importScripts`, `new Worker`;
    - `.webmanifest` icons.
  - Bare string constants such as the SVG/XLink/MathML namespace URIs React carries are not references.
  - `tests/unit/test_check_built_assets.py` covers a fixture `dist` per position that must fail, plus the namespace strings and a `href` inside an inert JS string that must pass.
  - `scripts/check.sh` gains "web build" (`pnpm --dir web build`) and "built output references" steps after the drift step.
- **Verification:**
  - `uv run pytest tests/unit/test_check_built_assets.py -v`.
  - `./scripts/check.sh`, whose output shows both steps passing on the real bundle.
- **Depends on:** T11 (shares `scripts/check.sh`)
- **Autonomy note:**
  - **May decide alone:** the parsing approach (regex per file type is fine).
  - **Must stop and ask if:** the real bundle fails, rather than adding an allowlist entry. That includes lightweight-charts' attribution link (PD15).

### T23 — E2E harness, gate step, auth journeys

- **Implements:** SD28; AC20, AC21, AC22, AC23 (real browser); PD10, PD14
- **Expected output:**
  - **`tests/integration/realapp/serve.py`:** reuses `harness.py` per PD14. It reads `DATABASE_URL` for the server (memory: use `127.0.0.1`, not `localhost`), creates `borrelbeurs_e2e_<pid>`, and drops it on exit.
  - **Playwright:** `web/playwright.config.ts` runs Chromium only, with `workers: 1`, screenshots on failure into `test-results/` (gitignored), and global setup and teardown spawning and stopping `serve.py`. `web/e2e/fixtures.ts` provides `loginAs(role)`.
  - **`auth.spec.ts` covers:**
    - **AC21:** each role's landing route, and a wrong key showing "Ongeldige toegangscode.";
    - **AC22:** the nav lists exactly the allowed routes for each role, and display at `/settings` sees "Geen toegang";
    - **AC23:** the placeholder for bar at `/bar`;
    - **AC20/PD10:** clear cookies while on `/koers`, force a socket close via `routeWebSocket`, and the browser reaches `/login?next=%2Fkoers`; logging in returns to `/koers`.
  - **Gate, setup and CI:**
    - `web/package.json` gets `"e2e": "playwright test"`.
    - `scripts/check.sh` gets an "e2e" step after the built-output check (it needs the compose `db`, as the integration step does).
    - `scripts/setup.sh` runs `pnpm --dir web exec playwright install chromium`.
    - `.github/workflows/ci.yml` installs Chromium with deps before `check.sh`.
- **Verification:**
  - `pnpm --dir web exec playwright test e2e/auth.spec.ts`.
  - `./scripts/check.sh`, with the step count and the e2e step's timing reported.
- **Depends on:** T16, T18, T22
- **Autonomy note:**
  - **May decide alone:** the launcher's internals and timeouts.
  - **Must stop and ask about:** committing any key or keys file, using `curl`/`TestClient` in the launcher, a gate run above 3 minutes for the e2e step, or a CI change beyond the browser install.

### T24 — Board e2e

- **Implements:** AC1, AC16, AC24, AC25, AC30, AC32, AC34 (real browser)
- **Expected output:**
  - **`offline.spec.ts`:** with `context.route('**', …)` aborting every non-origin request and counting them, each of `/login`, `/koers`, `/settings` and a placeholder page gives:
    - zero non-origin requests;
    - `document.fonts.check('16px Inter')`, or `EB Garamond` under Oud Geld, true;
    - a `canvas` inside every tile on `/koers` (AC1).

    It also severs the socket with `routeWebSocket`: the banner appears, `/api/state` is requested at a 5 s cadence, and after reconnect the banner is gone and polling stops (AC16).
  - **`board.spec.ts`:** uses frames from `web/e2e/frames.ts`, built from T12's fixture, through `routeWebSocket`:
    - at 1920×1080 with 6 and with 9 drinks, `scrollHeight <= clientHeight` (AC24);
    - at 390×844, 1 column that scrolls; at 844×390, 2 columns (AC25);
    - an XSS drink name and news text are literal, no `img` exists, and no dialog fired (AC32);
    - `hello` with `run_id: null` shows "Geen actieve borrel", then a snapshot shows tiles with no navigation (AC34);
    - with `page.clock` set 5 minutes off and the `end` frame suppressed, the crash banner disappears within 1.5 s of `t_end_ms` (AC30).
- **Verification:** `pnpm --dir web exec playwright test e2e/offline.spec.ts e2e/board.spec.ts`. Screenshots of each viewport are attached as artifacts, not diffed.
- **Depends on:** T21, T23
- **Autonomy note:**
  - **May decide alone:** viewport sizes within the ACs' bounds, and the frame builders.
  - **Must stop and ask if:** an AC can only pass with a looser bound.

### T25 — Theme e2e

- **Implements:** AC3, AC4, AC10 (real browser); AC5 is proved in T5
- **Expected output:** `theme.spec.ts`:
  - **AC3:** two contexts, admin on `/settings` and display on `/koers`. Admin picks Rood, and within 2 s display's `getComputedStyle(body).backgroundColor` equals Rood's `--bg`, with no navigation (the `framenavigated` count is unchanged).
  - **AC10:** picking Oud Geld makes display's body font `EB Garamond`, and `document.fonts.check` is true.
  - **AC4:** with `**/assets/*.js` aborted, `/koers`'s body background equals the stored theme's `--bg`.
  - The test resets the theme to Blauw in `afterAll`.
- **Verification:** `pnpm --dir web exec playwright test e2e/theme.spec.ts`.
- **Depends on:** T18, T23
- **Autonomy note:**
  - **May decide alone:** the colour comparison helper (hex to `rgb()`).
  - **Must stop and ask about:** a propagation bound looser than 2 s.

### T26 — Documentation

- **Implements:** In scope "Document updates"; PD2, PD3, PD7, PD8 as recorded decisions
- **Expected output:**
  - **`realtime-protocol.md`:** the `theme` row (24 tokens, preset, revision, `font_family`, no images), `hello.theme` (and `boot_id`, which the row omits today), PD7's catch-up unicast, and the client's seq rule.
  - **`data-model.md`:** the `theme` row rewritten to PD4's single row.
  - **`frontend-architecture.md`:** the manifest is server-side (`app/runtime/theme.py`) with 24 tokens; `features/theme` holds `ThemeProvider` and `ThemeSection`; lint via core rules (PD9).
  - **`docs/specs/phase-3-api-realtime.md` SD4:** the allowlist names `GET /theme.css` (Phase 4 SD8).
- **Verification:**
  - `rg -n "21 tokens|21 CSS" docs/design` returns nothing.
  - `rg -n "theme.css" docs/specs/phase-3-api-realtime.md` returns a match.
  - `./scripts/check.sh` still passes (docs only).
- **Depends on:** T5, T6
- **Autonomy note:**
  - **May decide alone:** wording.
  - **Must stop and ask about:** editing ADR 0005 or the Phase 6 spec's "21 tokens". They are not in this spec's In scope (R7).

---

## Task graph

```
T1, T2, T7, T8, T9                      (no dependencies)
T3 ← T1          T10 ← T8          T15 ← T8
T4 ← T1, T2, T3
T5 ← T4          T6 ← T4           T11 ← T4, T8
T12 ← T5, T8     T16 ← T10, T11, T15     T22 ← T11     T26 ← T5, T6
T13 ← T12
T14 ← T10, T13   T19 ← T8, T13
T17 ← T14, T16
T18 ← T17
T20 ← T17, T18, T19                     T23 ← T16, T18, T22
T21 ← T20                               T25 ← T18, T23
T24 ← T21, T23
```

Critical path: T1 → T3 → T4 → T5 → T12 → T13 → T14 → T17 → T18 → T20 → T21 → T24.

Shared files are ordered by dependency:
- `app/main.py`: T4 → T6.
- `scripts/check.sh`: T11 → T22 → T23.
- `web/package.json`: T8 → T23.
- `web/src/app/routes.tsx`: T16 → T18 → T20.
- `web/src/app/AppShell.tsx`: T15 → T17.
- `web/src/main.tsx`: T16 → T17.
- `features/exchange/index.ts`: T13 → T14.
- `features/theme/index.ts`: T17 → T18.
- `features/koers/KoersPage.tsx`: T20 → T21.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T2, T7, T8, T9 | T1: `app/runtime/theme.py`, `tests/unit/test_theme_manifest.py` · T2: `db/migrations/versions/0008_theme.py`, `app/db/models.py`, `app/db/theme.py`, `tests/integration/test_schema.py`, `tests/integration/test_theme_repo.py` · T7: `app/runtime/ticker.py`, `tests/integration/test_ticker.py`, `docs/adr/0003-…md` · T8: `web/package.json`, `web/pnpm-lock.yaml`, `web/vite.config.ts` · T9: `web/eslint.config.js`, `web/src/lint-rules.test.ts` |
| 2 | T3, T10, T15 | T3: `app/realtime/messages.py`, `app/realtime/hub.py`, `tests/unit/test_messages.py`, `tests/unit/test_hub.py` · T10: `web/src/lib/{format,http}{,.test}.ts` · T15: `web/src/components/ui/*`, `web/src/app/AppShell.tsx`, `web/src/app/pages/{Placeholder,NoAccess}.tsx`, `web/src/assets/logo.png` |
| 3 | T4 | `app/api/theme.py`, `app/runtime/boot.py`, `app/main.py`, `tests/meta/test_route_authorization.py`, `tests/api/test_authorization_matrix.py`, `tests/api/test_theme.py` |
| 4 | T5, T6, T11 | T5: `app/realtime/ws.py`, `tests/api/test_ws_theme.py` · T6: `app/main.py`, `tests/api/test_static.py` · T11: `scripts/gen_api_types.sh`, `web/src/api/generated/*`, `web/.prettierignore`, `scripts/check.sh` |
| 5 | T12, T16, T22, T26 | T12: `tests/api/ws_fixture.py`, `tests/api/test_ws_fixture.py`, `web/src/features/exchange/model/{schemas,schemas.test}.ts`, `…/__fixtures__/ws-messages.json` · T16: `web/src/features/auth/*`, `web/src/app/routes.tsx`, `web/src/app/App.tsx`, `web/src/main.tsx` · T22: `scripts/check_built_assets.py`, `tests/unit/test_check_built_assets.py`, `scripts/check.sh` · T26: `docs/design/*.md`, `docs/specs/phase-3-api-realtime.md` |
| 6 | T13 | `web/src/features/exchange/{index.ts, model/applyMessage*, model/store.ts, model/selectors.ts, model/sma*}` |
| 7 | T14, T19 | T14: `web/src/features/exchange/{index.ts, model/client*, model/skew*, model/backoff.ts}` · T19: `web/src/features/koers/ui/*` |
| 8 | T17 | `web/src/features/theme/{index.ts, ThemeProvider*}`, `web/src/app/providers.tsx`, `web/src/app/AppShell.tsx`, `web/index.html`, `web/src/main.tsx`, `web/src/styles/base.css`, `web/vite.config.ts` (dev proxy, only if needed) |
| 9 | T18 | `web/src/features/theme/{index.ts, ThemeSection*}`, `web/src/app/pages/SettingsPage.tsx`, `web/src/app/routes.tsx` |
| 10 | T20, T23 | T20: `web/src/features/koers/{index.ts, KoersPage.tsx, KoersPage.module.css, Tile*, HeaderClock.tsx}`, `web/src/app/routes.tsx` · T23: `tests/integration/realapp/serve.py`, `web/playwright.config.ts`, `web/e2e/{global-setup,global-teardown,fixtures,auth.spec}.ts`, `web/package.json`, `web/.gitignore`, `scripts/check.sh`, `scripts/setup.sh`, `.github/workflows/ci.yml` |
| 11 | T21, T25 | T21: `web/src/components/ui/Marquee*`, `web/src/features/koers/{PriceMarquee,NewsMarquee,MarketEventLayer*,KoersPage}.tsx`, `web/src/styles/keyframes.css` · T25: `web/e2e/theme.spec.ts` |
| 12 | T24 | `web/e2e/{offline.spec,board.spec,frames}.ts` |

No two tasks in one group write the same file. Builders run one at a time (ADR 0010 §1), so
the groups give the merge order.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main` and in CI, with the output pasted, including the drift, build, references and e2e steps.
- `uv run pytest tests/engine` green, so the golden fixtures are untouched.
- D-13, D-14, D-17 and D-25 are closed, each with its evidence: T22 and T24 (D-13), T9, T17 and T25 (D-14), T14 and T24 (D-17), T9, T20, T21 and T24 (D-25).
- The spec's manual exit check (two machines offline, a third admin switches the preset, a pulled network recovers) is the user's step per the memory notes.

---

## Data changes

One forward-only migration, chained from `0007`.

| Revision | Change | Constraints |
|---|---|---|
| `0008_theme` | `theme(id, preset, revision, updated_at)` | `id` SMALLINT PK, default 1, `CHECK (id = 1)` (PD4); `preset` `CHECK IN (5 keys)`; `revision INTEGER NOT NULL CHECK ≥ 1`; `updated_at timestamptz NOT NULL DEFAULT now()` |

- **Additive:** a new, empty table, and no existing row changes. No row means Blauw at revision 0 (SD5), so there is no backfill.
- **Reversible:** `downgrade()` drops the table, and T2's round trip exercises it.
- `tests/integration/conftest.py` truncates every `Base.metadata` table per test, so `theme` is included automatically.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **PD1 is a hard stop**, and it includes `@testing-library/dom`, which SD25 does not list. Until T8 is approved, every web task after T9 is blocked | Server tasks T1–T7 and T9 need none of it. T8 is small and goes first in the web chain |
| R2 | **Spec defects the plan corrects** (PD2's 24 tokens, PD8's missing fallback) count under ADR 0009 as "spec ambiguity that changes user-visible behaviour" | Both are marked "confirm at the audit". If the human prefers to amend the spec text, it is a two-line edit to SD6 and In scope, the human's file |
| R3 | **Swatches without a client preset table.** SD10 says "swatches". SD6 forbids client preset data, and `ThemeData` carries only the active preset. T18 therefore renders labelled buttons, not colour swatches | Options: (a) accept labelled buttons now; Phase 6's editor can add a `GET /api/theme/presets` catalogue. (b) Add a read-only catalogue endpoint in T4 (a new route, a matrix row and generated types; about 40 lines). **The audit picks.** The plan defaults to (a) because it adds no surface |
| R4 | **Oud Geld's rising tiles turn red** (SD6's split: `--tile-rising` = v1 `--down`, #b34a3a), where v1's Oud Geld override showed rising green (`koers.html:207-214`), contradicting its own legend | Spec-intended: SD6 and the legend agree. Noted so nobody files it as a regression. v1's other `[data-theme="oudgeld"]` overrides (`koers.html:202-231`) are not ported; the tokens carry the theme (ADR 0005 consequence) |
| R5 | **The Phase 3 tip `59a8f57` never had a completed gate run** (memory) | The first task's gate run (T1, T2 or T7) is the first evidence. If it fails in `db/session`, the lock or `runtime/holder\|boot\|ticker`, suspect `59a8f57` before Phase 4 work, and stop and report |
| R6 | **E2E on Windows:** a `localhost` DSN crawls over `::1`, and Playwright adds about 60–90 s to the gate | `serve.py` uses whatever `DATABASE_URL` says, and the memory note says use `127.0.0.1`. T23 reports the step's timing and stops above 3 minutes. Never pipe `check.sh` through `tail` |
| R7 | "21 tokens" survives in ADR 0005 (`:14, :27`) and Phase 6 AC11, which the spec's doc list does not cover | T26 does not edit them (a product ADR and another spec). Listed for the human; SD6 already reads Phase 6 AC11 as "every token in the manifest" |
| R8 | **PD7 changes the wire protocol.** If it is rejected, windows (a)–(c) can leave a client on a stale theme until its next reconnect | T5's autonomy note handles both outcomes. The fallback is SD9 alone, and the gap is documented in `realtime-protocol.md` |
| R9 | **lightweight-charts v5 API.** The plan assumes `addSeries(CandlestickSeries)`, `attributionLogo` and `autoSize`, from the analyst's memory of v5, not checked against the package | T19 stops if an API is missing. T8's install makes `index.d.ts` available to check first |
| R10 | AC1's font check under `context.route` blocking: a bundled font file must be **requested** before `document.fonts.check` is true, and `font-display` may delay it | T24 waits on `document.fonts.ready` before checking. Fontsource CSS uses `font-display: swap`, which is fine, since the check runs after `ready` |
| R11 | **jsdom has no Web Animations API or canvas**, so marquee and chart tests mock both. A mock can pass while the real API differs | T24 exercises the real board in Chromium (canvas per tile; the marquee runs). AC33's `currentTime` preservation is proved only in Vitest against the mock; if the auditor wants it in Playwright too, T24 adds a step |
| R12 | `PUT /api/theme` broadcasting outside the holder means a theme frame can interleave between two run broadcasts | Harmless by design: `seq` is the hub's, assigned in `broadcast`, so ordering stays total. PD6 keeps resync metadata correct. T4 asserts the lock is never taken |
| R13 | **The gate now needs a browser and a built bundle.** `setup.sh` and CI both change (T23), and a fresh clone without `playwright install` fails the e2e step with a cryptic error | `setup.sh` installs Chromium (idempotent). T23 has `check.sh` print the install command if the browser is missing |
| R14 | `/settings` is admin-only, but the theme reaches display and bar clients only through the WS. If the WS client is started only on `/koers`, other pages would not re-theme | T17 starts the client app-wide in `providers.tsx` for every authenticated session, so AC3 holds on every page |
| R15 | T7 changes when market events end (one tick earlier in the jump case) | `engine-guardian` reviews T7. Golden fixtures are engine-only and unaffected. AC36 is the spec's intent |

---

## Out of scope for this plan

- Everything in the spec's Out of scope:
  - the bar page and the order path;
  - manipulation and the rest of settings;
  - the home hub;
  - the Eigen theme, the editor, images, `asset`, `has-promo`;
  - changing `candle_interval_ms`, and the `config` message;
  - the key UI, and closing sockets on revoke;
  - analytics;
  - Docker, Render, proxies;
  - a service worker, fullscreen, wake lock;
  - pixel diffs.
- `Cache-Control: immutable` on hashed assets and `no-store` on `index.html` (`architecture.md:219-220`). No AC needs it; Phase 8.
- A preset catalogue endpoint, unless the audit picks R3(b).
- Porting v1's `[data-theme="oudgeld"]` per-element overrides (R4).
- Editing ADR 0005 or the Phase 6 spec (R7), `docs/plans/manual-checklist.md`, `rebuild-route.md`'s stale concurrency line, or the spec's Status header. Those are the human's files.
- Any change under `exchange/`, `legacy/v1/` or `tests/engine/v1_reference/`.

---

## Audit (plan-auditor — PASS required before implementation starts)

Human audit decisions (2026-10-04), all confirmed as the plan states them:
- **PD1** approved: all eleven dependencies, including `@testing-library/dom`. T8 still stops
  for a go-ahead immediately before `pnpm add`.
- **PD2** confirmed: 24 tokens (v1 has 22 per preset; SD6's "23" is a miscount).
- **PD3** confirmed: `ThemeData.font_family`.
- **PD4** confirmed: `theme.id SMALLINT PK DEFAULT 1 CHECK (id = 1)`.
- **PD7** confirmed: `theme` catch-up unicast after every handshake/resync snapshot.
- **PD8** confirmed: `SpaStaticFiles` history fallback for SPA routes only.
- **PD15** confirmed: keep lightweight-charts' default attribution logo.
- **PD17** confirmed: 429 string "Te veel pogingen. Probeer het over een minuut opnieuw."
- **R3** → option (a): labelled preset buttons, no catalogue endpoint in Phase 4.

Audit notes, accepted as-is: T17's blocking `<link>` (AC4) is proved only end-to-end in T25;
AC33 is proved only against a mocked WAAPI (R11); T23 is at the size limit (about 10 files).

- [x] Every AC maps to at least one task:
  - AC1 → T22, T24
  - AC2 → T22
  - AC3 → T17, T18, T25
  - AC4 → T17, T25
  - AC5 → T4, T5, T17
  - AC6 → T3, T5, T17
  - AC7 → T13, T17
  - AC8 → T2, T4, T18
  - AC9 → T1, T3, T4, T5
  - AC10 → T1, T4, T17, T25
  - AC11 → T19
  - AC12 → T9, T19, T20
  - AC13 → T14
  - AC14 → T14
  - AC15 → T14
  - AC16 → T14, T17, T24
  - AC17 → T13
  - AC18 → T13, T14
  - AC19 → T13
  - AC20 → T6, T10, T14, T16, T23
  - AC21 → T6, T16, T23
  - AC22 → T15, T16, T23
  - AC23 → T15, T16, T23
  - AC24 → T20, T24
  - AC25 → T20, T24
  - AC26 → T10, T20
  - AC27 → T19
  - AC28 → T19
  - AC29 → T19
  - AC30 → T21, T24
  - AC31 → T21
  - AC32 → T9, T20, T21, T24
  - AC33 → T21
  - AC34 → T20, T24
  - AC35 → T13, T19
  - AC36 → T7
  - AC37 → T7
- [x] Every task maps to at least one AC. T8 (SD25), T11 (SD26) and T12 (SD26) enable ACs rather than prove them alone. T26 implements In scope "Document updates"
- [x] PD1 approved (dependencies, hard stop, including `@testing-library/dom`). PD2, PD3, PD4, PD7, PD8, PD15 and PD17 (the 429 string) confirmed. R3 option chosen
- [x] Existing patterns reused, nothing reinvented:
  - `ROLE_ROUTES` (PD8);
  - `require_role` / `OriginGuard`;
  - the `keys.py` repository shape;
  - `hub.broadcast`;
  - `realapp/harness.py`;
  - the golden `--check/--write` pattern (PD19);
  - one euro formatter;
  - one Zod error schema
- [x] No new dependency without an approval note: eleven, under Files, gated by T8
- [x] Data changes additive and reversible (T2 round trip)
- [x] Errors, empty states and permissions are tasks:
  - no live run (T5, T20, T24);
  - 401/1008/4401 (T14, T16, T23);
  - 403/422 (T4, T18);
  - "Geen toegang" and "Nog niet beschikbaar" (T15, T16);
  - offline (T14, T17, T24)
- [x] Each task reviewable in one sitting. Largest: T23 (about 10 files), T13, T14
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not. Scratch databases only; keys minted at runtime into the OS temp dir; the CI change is limited to the browser install
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audited by: MartijnBoot (human audit, /audit 4)  Date: 2026-10-04
