# Spec: Phase 4 — React shell, theme, auth and the display board

Status: Approved · Depends on: Phase 3 · Fixes: D-13, D-14, D-17, D-25

## Problem

The display board is the most complex page in v1 (`legacy/v1/static/koers.html`, 754 lines)
and the most valuable: candle charts per drink, an SMA line, two marquees, market-event
overlays and a viewport-locked layout. It is also where the offline and shared-config defects
bite:

- **Four runtime CDN dependencies** (D-13): Inter from Google Fonts (`koers.html:10`, and
  `bar.html`, `settings.html`, `manipulation.html`, `home.html`), EB Garamond appended lazily
  (`theme.js:116-121`), `lightweight-charts@4` from jsDelivr (`koers.html:11`), Chart.js
  (`bar.html:11-12`). At an event without internet, fonts fall back and charts fail.
- **Theme and candle interval live in `localStorage`** (D-14): the theme is applied per
  browser (`theme.js`, `applyTheme` writes `localStorage.setItem('theme', …)`), and the
  candle interval is read per browser (`koers.html:293`, `getCandleIntervalMs`). The admin
  themes their laptop; the big screen shows defaults.
- **No WebSocket liveness check** (D-17): a half-open socket keeps `readyState === 1` and the
  big screen freezes silently on a stale price. v1's ping (`koers.html:718`) never checks for
  a reply.
- **Drink names interpolated into `innerHTML`** (D-25, `koers.html:462`).
- The client synthesises candles at 1 Hz (`koers.html:525-567`, `setInterval(tickCandles,
  1000)` at `:567`) and its SMA fast path reads a stale `entry.ohlc` (`koers.html:543-545`).
- Chart colours are hardcoded (`koers.html:399-411`) except `--sma-line`, which is read once
  at creation (`koers.html:413`), so a theme change leaves the chart in the old colours.
- The marquee's phase preservation uses wall-clock `performance.now() % duration`
  (`koers.html:653-664`), which drifts from the animation's own timeline after any hover
  pause (`koers.html:48`).

Phase 3 delivered the server half: server-bucketed bars (SD25, `run.candle_interval_ms`),
`t_end_ms` on market events (D-15), the `seq`/`boot_id` replay protocol, and
`/api/auth/me` returning `allowed_routes` (SD2). There is no theme table, no theme endpoint,
no `theme` message and no frontend beyond the Phase 0 shell (`web/src/App.tsx`).

The display page is **read-only**, which is why it comes before the order path: it validates
auth, the protocol, theming, charts and reconnect with no risk of charging anyone.

## Decisions

Settled at the spec interview (2026-10-04). SD1–SD4 were answered by the human; SD5 onward
were delegated ("choose the recommended option") and record the recommendation taken. The
planner must not reopen them; the human may overrule any at spec approval.

**Theme**

- **SD1 — Phase 4 builds the theme's server side and a preset picker; no editor.** A `theme`
  table (own migration), `GET /theme.css`, admin-only `PUT /api/theme`, the `theme` WS
  message, and an admin-only picker for v1's five presets — Oud Geld, Blauw, Groen, Paars,
  Rood (`theme.js:72-77`). The custom ("Eigen") theme, the token editor and image uploads are
  Phase 6.
- **SD2 — No theme images in Phase 4.** The theme is the colour tokens plus the preset name.
  The board always uses the single-board layout and the bundled default logo (v1's
  `legacy/v1/static/logo/logo_medium.png`, copied into `web/`, served from the origin). The
  four image slots (`--bg-image`, `--header-image`, `--logo-url`, `--promo-image`,
  `theme.js:185-209`), the `has-promo` layout (`koers.html:76`) and the `asset` table are
  Phase 6. Adding them later is an additive change to the theme schema.
- **SD5 — One global theme, not per run.** The `theme` table holds a single row: `preset`,
  `revision` (integer, +1 per write), `updated_at`. It survives across runs. With no row, the
  server serves **Blauw** — v1's fallback (`theme.js`, `THEMES[name] || THEMES.blauw`).
  `PUT /api/theme` takes `{preset}` and accepts only the five preset names (422 otherwise).
- **SD6 — The token manifest lives server-side, once.** A Python module defines the token
  names and the five presets' values, ported verbatim from `theme.js`. `/theme.css` renders
  from it; the `theme` message carries the resolved tokens, so the client holds no preset
  table of its own. v1's `--up`/`--down` are **split** per
  [frontend-architecture.md](../design/frontend-architecture.md) "The koers page":
  `--candle-up`/`--candle-down` take v1's `--up`/`--down` values; `--tile-rising`/
  `--tile-falling` take v1's `--down`/`--up` values (rising is bad news for the drinker, so
  red). The manifest therefore has 23 tokens; Phase 6's "all 21 tokens" (its AC11, D-19) reads
  as "every token in the manifest".
- **SD7 — The font is part of the preset.** Oud Geld uses EB Garamond (`theme.js`, the
  `oudgeld` font override); the others use Inter. `/theme.css` sets `font-family` on `body`
  accordingly. Both families are bundled via `@fontsource` (latin subset, used weights only).
- **SD8 — `/theme.css` is public and uncached-by-default.** It is added to Phase 3 SD4's
  public allowlist (the login page must paint themed too; the tokens are not secret). It is
  served with `Cache-Control: no-cache` and an `ETag` derived from `revision`, so a reload
  revalidates cheaply. `index.html` links it as a blocking stylesheet before any script
  (ADR 0005).
- **SD9 — The theme travels in `hello` and in a `theme` broadcast.** `hello` gains `theme`
  (preset, revision, tokens) — `hello` is sent on every connect, with or without a live run,
  so a reconnecting client always catches up. A successful `PUT /api/theme` commits, then
  broadcasts `theme` (takes the next `seq`, enters the replay log) whether or not a run is
  live. The client applies a theme only if its `revision` is higher than the one it holds, so
  two concurrent admin writes converge on the last committed one. Theme writes do not take the
  engine state lock.
- **SD10 — The picker lives on `/settings`.** `/settings` (admin only) renders a "Thema"
  section with the five presets as swatches, the current one marked. The rest of `/settings`
  is the SD4 placeholder until Phase 6, which extends the same page.

**Candles**

- **SD3 — The client has no candle interval.** The board draws the server's bars as they
  arrive: `snapshot.bars` once, then `tick`'s current bar per drink via `series.update`.
  Nothing in the client stores, reads or computes an interval, and no code in the web bundle
  touches `localStorage` or `sessionStorage`. Changing the interval during a run (rebucketing
  plus a fresh `snapshot`) is a config change and belongs to Phase 6.
- **SD11 — The SMA is computed client-side over bar closes, window 5** (`koers.html:385`,
  `SMA_WINDOW = 5`), from the bars the server sent — never from a synthesised candle.

**Routes and shell**

- **SD4 — Unbuilt routes render a placeholder.** Every route in `allowed_routes` that Phase 4
  does not build renders "Nog niet beschikbaar" inside the `AppShell`, nav included. After
  login each role lands on its first allowed route per Phase 3 SD2 (display → `/koers`, bar →
  `/bar`, admin → `/`). Phase 3 SD2's route map is unchanged; Phases 5–6 replace placeholders.
- **SD12 — Session loss goes to login.** A 401 from any request, a WS handshake rejected with
  1008, or a WS close with 4401 (session expired, Phase 3 AC25) sends the browser to
  `/login?next=<current route>`. After login, `next` is honoured if it is in
  `allowed_routes`, else the role's landing route.
- **SD13 — `NavMenu` and `RequireRole` read only `allowed_routes`.** No role→route table
  exists in the client. A route not in the list renders a Dutch "Geen toegang" page, not a
  redirect loop.

**Realtime client**

- **SD14 — Liveness by client ping.** With no live run the ticker sends nothing (Phase 3
  SD16), so ticks alone cannot prove liveness. The client sends `ping` every 15 s; **any**
  inbound frame resets a 45 s deadline; on expiry the client force-closes and reconnects.
- **SD15 — Backoff.** v1's curve — 500 ms initial, ×1.7, 8 s cap — with ±30 % uniform jitter
  on every delay. Reset to the initial delay on a successful open.
- **SD16 — Reconnect sends `hello {boot_id, last_seq}`.** The server replays or snapshots
  (Phase 3). A `hello` with a different `boot_id` than the client holds discards all live
  state; the following `snapshot` rebuilds it.
- **SD17 — Polling only while not open.** In the `offline` state the client polls
  `GET /api/state` every 5 s and applies the result as a `snapshot`. Polling stops on open. A
  409 `no_live_run` shows the empty state; a 401 follows SD12.
- **SD18 — Clock skew.** Each `pong` gives a sample `offset = ts_ms − (sent + received) / 2`;
  the client keeps the sample with the smallest round trip among the last 8. Until the first
  `pong`, the offset is `hello.ts_ms − received`. Countdowns and the header clock use
  `Date.now() + offset`.
- **SD19 — Connection banner wording.** Offline: "Verbinding verbroken — opnieuw verbinden…".
  It disappears on open. (New string; v1 koers has no banner.)

**Board**

- **SD20 — Empty state.** With no live run (`hello.run_id` null, or 409 from polling), the
  board shows "Geen actieve borrel" in the themed shell — header, nav and theme still work.
- **SD21 — Market events render per kind, from `t_start_ms`/`t_end_ms`.** `crash`: overlay,
  banner "⚠ MARKTCRASH", tile shake, news marquee ×2.5 (`koers.html:135-200, 583-587`).
  `bubble`: overlay, banner "▲ PRIJSBUBBEL", tile pulse (`koers.html:588-592`). `correction`
  (v1's "mid"): a calm, non-animated banner "Terug naar start" — no overlay, no pulse (defect
  register, "Deliberately not treated as defects"; this satisfies Phase 6's AC17 early). The
  client ends the event at `t_end_ms` on the skew-corrected clock; a late `market_event end`
  is a no-op.
- **SD22 — One euro formatter.** `nl-NL`, two decimals, "€ 2,50". Percentages one decimal.
  Tile contents otherwise port `koers.html` verbatim.
- **SD23 — Pulse direction compares the displayed price.** A tile pulses `rising` when its
  `price_cents` goes up from the previous value the client displayed, `falling` when down, and
  not at all on a snapshot that replaces state. Candles use `chart_price_cents`. Both price
  changes from `tick` and from `order` messages count.
- **SD24 — Not ported:** fullscreen and wake-lock APIs (v1 has neither), the earnings
  aggregates on the board (v1 koers does not show them), and hover-pause on marquees is kept.

**Tooling and dependencies**

- **SD25 — Runtime dependencies are the design's five plus fonts:** `react-router`,
  `zustand`, `lightweight-charts` v5, `zod`, `@fontsource/inter`, `@fontsource/eb-garamond`
  (React is already present). Dev dependencies: `openapi-typescript`,
  `@testing-library/react`, `jsdom`, `@playwright/test`. All are named in
  [frontend-architecture.md](../design/frontend-architecture.md) and ADR 0006; the plan still
  justifies each per `CLAUDE.md` (why not stdlib, licence, maintenance). No other dependency.
- **SD26 — Types are generated and checked for drift.** `openapi-typescript` generates
  `web/src/api/generated/` from `create_app().openapi()` in-process (Phase 3 SD3), committed.
  The check regenerates and fails on diff. A WS message fixture recorded from the real server
  by a Python test is committed and parsed by the client's Zod schemas in Vitest; either side
  drifting fails the gate.
- **SD27 — Lint rules carry the invariants:** `eslint-plugin-boundaries` per the design
  ("`exchange` may be imported by any feature; `exchange` imports nothing from
  `features/`"), `react/no-danger`, and a ban on `localStorage`/`sessionStorage`.
- **SD28 — Playwright joins the gate.** `scripts/check.sh` gains an e2e step after the
  integration step: build the web bundle, start the real app on the compose `db` with a seeded
  live run and display/admin keys, run the Playwright suite (Chromium), stop the app.

**Carried over from Phase 3** (engine-guardian follow-ups, `docs/plans/manual-checklist.md`)

- **SD29** — End due market events against the tick's actual stamp, not the grid stamp
  (`app/runtime/ticker.py`, `_iterate` → `_end_due_events`); today an event can end one tick
  late, which SD21's local countdown would expose as a visible mismatch.
- **SD30** — Document the freeze: a wall clock stepping back by less than the catch-up budget
  (30 s) holds tick stamps at the last commit's time until the grid passes it, so prices
  freeze for at most the budget. Say so in the `_tick_step` docstring and ADR 0003.
- **SD31** — In `test_a_tick_is_never_stamped_before_the_commit_it_follows`, also assert the
  jumped drink's price after the tick equals the price on the jump row.

## In scope

- Vite + React + TypeScript app in `web/`, structured per
  [frontend-architecture.md](../design/frontend-architecture.md): `app/` (routes, `AppShell`,
  providers), `features/exchange` (store, `applyMessage`, the WS client, selectors),
  `features/auth` (login, session hook, `RequireRole`), `features/theme` (`ThemeProvider`,
  picker), `features/koers`, `components/ui` (`NavMenu`, `Marquee`, `StatusDot`, `Button`,
  and what the board needs), `lib/` (http, format), `styles/`.
- Routes: `/login`, `/koers`, the `/settings` theme section, placeholders for every other
  route in `allowed_routes`, "Geen toegang".
- Server: `theme` table + migration, the token manifest, `GET /theme.css`, `PUT /api/theme`
  (admin), `theme` in `hello`, the `theme` broadcast, SPA fallback unchanged.
- Bundled fonts (Inter, EB Garamond) and the default logo; lightweight-charts v5 bundled.
- The no-external-reference check on the built output, in the gate.
- Generated API types, the WS fixture drift check, lint rules SD27.
- Playwright in the gate (SD28).
- The three Phase 3 carry-overs (SD29–SD31).
- Document updates: `realtime-protocol.md` (`theme` message, `hello.theme`),
  `data-model.md` (`theme` table), `frontend-architecture.md` (23-token manifest), ADR 0003
  (SD30), Phase 3 SD4's public allowlist (`/theme.css`).

## Out of scope

- Bar page and order path (Phase 5; D-05). Manipulation and the rest of settings (Phase 6).
- The home hub and its connection-health strip (Phase 6; D-26). `/` is a placeholder.
- The custom ("Eigen") theme, the token editor, image slots, uploads, the `asset` table, the
  `has-promo` layout (Phase 6; D-19, D-29).
- Changing `candle_interval_ms` or any other run config during a run; the `config` message
  (Phase 6).
- Key management UI, closing sockets on key revocation (Phase 6).
- Analytics, `GET /api/history`, earnings on the board (Phase 7).
- Docker image, Render, offline cookie profile, proxy headers (Phase 8).
- Service worker, PWA install, fullscreen, wake lock.
- Pixel-diff visual regression (rejected in the design); screenshots are CI artifacts only.
- i18n beyond Dutch UI strings.
- Any change to pricing behaviour. Golden fixtures stay green.

## Acceptance criteria

**Offline and assets — D-13**

- **AC1.** While every request to a non-origin host is blocked, when each Phase 4 page
  (`/login`, `/koers`, `/settings`, a placeholder) is loaded, the system shall make zero
  non-origin requests, shall report the theme's font as loaded
  (`document.fonts.check`), and shall render a chart canvas on every board tile. *(D-13)*
- **AC2.** When the production bundle is built, the gate shall fail if any file in the built
  output references an absolute URL with a host (`http://`, `https://`, `//`) in an asset,
  stylesheet, font, script or import position. *(D-13)*

**Theming — D-14**

- **AC3.** When an admin selects a preset in one browser, every other connected client shall
  apply the new tokens and font within 2 s **without reload**. *(D-14)*
- **AC4.** When a page is loaded with its JavaScript bundle blocked, the body's computed
  background shall already be the stored theme's `--bg`. *(ADR 0005)*
- **AC5.** When the theme changes while no run is live, connected clients shall still
  re-theme. *(SD9)*
- **AC6.** When a client reconnects after missing a `theme` broadcast, it shall hold the
  current theme after the reconnect. *(SD9)*
- **AC7.** When a `theme` message arrives with a `revision` not higher than the one held, the
  client shall ignore it.
- **AC8.** When `PUT /api/theme` is called by a display or bar session, the system shall
  return 403; with an unknown preset name, 422; and the stored theme shall be unchanged.
- **AC9.** When no theme has ever been stored, `/theme.css` and `hello` shall carry Blauw.
- **AC10.** When the Oud Geld preset is active, the body font shall be EB Garamond; otherwise
  Inter.
- **AC11.** When the theme changes, chart colours (candles, SMA, grid, text) shall update via
  `applyOptions`, without the chart being removed and recreated.
- **AC12.** When a run's `candle_interval_ms` is 30 000, the board shall draw 30-second bars
  exactly as the server sent them, and no code in the web bundle shall read or write
  `localStorage` or `sessionStorage` (lint-enforced, SD27). *(D-14)*

**Realtime — D-17**

- **AC13.** While the WebSocket is open but no frame has arrived for 45 s, the client shall
  force-close and reconnect. *(D-17)*
- **AC14.** While the WebSocket is open, the client shall send `ping` every 15 s, so an idle
  server with no live run does not trip AC13.
- **AC15.** When reconnecting, the client shall wait per SD15: 500 ms × 1.7ⁿ capped at 8 s,
  each delay jittered uniformly within ±30 %.
- **AC16.** When the connection is lost, the system shall show SD19's banner and poll
  `GET /api/state` every 5 s; when the socket reopens, polling shall stop and the banner
  disappear.
- **AC17.** When a `snapshot` arrives, the client shall replace drinks, prices, bars, news and
  market events wholesale.
- **AC18.** When a broadcast arrives whose `seq` is not the previous `seq + 1`, the client
  shall send `resync_request` and apply nothing until the `snapshot` arrives.
- **AC19.** When the server restarts (new `boot_id`), the client shall discard its live state
  and rebuild it from the snapshot.
- **AC20.** When the session expires (4401), the handshake is rejected (1008), or any request
  returns 401, the browser shall go to `/login?next=…`, and after login return to `next` if
  allowed.

**Auth and shell**

- **AC21.** When a key is submitted on `/login`, the system shall log in and land on the
  role's first allowed route; on failure it shall show a Dutch error and not reveal whether
  the key exists.
- **AC22.** For each of display, bar and admin, the nav shall list exactly `allowed_routes`,
  and navigating to a route outside it shall show "Geen toegang".
- **AC23.** When a role opens an allowed route Phase 4 has not built, the system shall show
  "Nog niet beschikbaar" inside the shell.

**Board**

- **AC24.** At 1920×1080 with six drinks and with nine, the board shall fit one viewport
  (`scrollHeight <= clientHeight`) and shall not scroll.
- **AC25.** At ≤700 px portrait the board shall be one scrollable column; at ≤700 px
  landscape, two columns.
- **AC26.** When a drink's displayed price rises, its tile shall pulse with `--tile-rising`;
  when it falls, with `--tile-falling`; candles shall use `--candle-up`/`--candle-down`. The
  legend shall read "Tegels pulseren bij stijging (rood) of daling (groen)." verbatim.
- **AC27.** When a `tick` or `order` arrives, chart series shall be updated with `update`
  only — no `setData`, no `remove`. `setData` happens only on a snapshot.
- **AC28.** When a tile unmounts (including StrictMode's double mount), its chart shall be
  removed exactly once and its refs nulled.
- **AC29.** When drink names change order or a name changes, charts shall be keyed by
  `drink_id` and no other drink's chart shall be recreated.
- **AC30.** When a market event is active, the client shall end it at `t_end_ms` on the
  skew-corrected clock without waiting for a broadcast — within 1.5 s of server time, even
  with the client's clock 5 minutes off. *(client half of D-15)*
- **AC31.** When a `crash`, `bubble` or `correction` is active, the board shall render SD21's
  treatment for that kind; `correction` shall have no overlay and no animation.
- **AC32.** When a drink name or news text contains HTML metacharacters
  (`<img src=x onerror=alert(1)>`), the system shall render it as literal text and create no
  element from it. *(D-25)*
- **AC33.** When marquee content changes without changing its item count, the animation's
  `currentTime` shall not jump; when the count changes, `currentTime` shall be preserved via
  the Web Animations API. During `crash`/`bubble` the news marquee's playback rate shall be
  2.5.
- **AC34.** With no live run, the board shall show "Geen actieve borrel" inside the themed
  shell, and shall show the board without reload once a run is live and a snapshot arrives.
- **AC35.** The SMA line shall equal the mean of the last five bar closes the server sent,
  for every bar.

**Carried over from Phase 3**

- **AC36.** When a tick's actual stamp passes a market event's `t_end_ms`, that tick shall end
  the event, even when the grid stamp has not. *(SD29)*
- **AC37.** In the existing never-stamped-before-commit test, the jumped drink's price after
  the tick shall equal the price on the jump row. *(SD31)*

## Verification

- **Playwright (in the gate, SD28):** login per role and the nav (AC21–23); the no-network
  load of every page with non-origin requests aborted and counted (AC1); the no-flash test
  with the JS bundle blocked (AC4); theme propagation across two browser contexts, the exit
  check (AC3, AC10); viewport fit and column counts at three sizes (AC24–25); kill the socket
  server-side and assert banner, polling and recovery (AC16); a market event that ends with
  the end broadcast suppressed (AC30); an XSS drink name (AC32).
- **Vitest:** `applyMessage` exhaustively, including seq gap and boot change (AC17–19); the
  WS state machine with fake timers — liveness, ping, backoff bounds, polling start/stop
  (AC13–16); skew estimation; the SMA (AC35); the formatter; theme revision ordering (AC7);
  Zod parsing of the recorded WS fixture (SD26).
- **Chart tests** against a mocked `lightweight-charts`: `setData` once per snapshot,
  `update` per tick, `applyOptions` on theme change, `remove` exactly once on unmount, never
  on a data update (AC11, AC27–29).
- **Python:** `/theme.css` and `PUT /api/theme` authorization and validation (AC8–9);
  `theme` in `hello`, broadcast with and without a live run, replayed after a gap (AC5–6); the
  meta test still passes with `/theme.css` on the public allowlist; the ticker carry-overs
  (AC36–37).
- **Gate:** the built-output external-reference check (AC2); lint (SD27); generated-types
  drift (SD26).
- **Manual (exit check):** with the network cable out and wifi off, open `/koers` on two
  machines against the laptop, switch the preset on a third admin session, watch both
  re-theme; pull the board machine's network for a minute and watch it recover.

## Exit condition

The big screen works end to end against the new API with no internet, survives a dropped
connection on its own, and re-themes live when an admin picks a preset on another machine.
