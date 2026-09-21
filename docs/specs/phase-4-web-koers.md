# Spec: Phase 4 — React shell, theme, auth and the display board

Status: Draft · Depends on: Phase 3 · Fixes: D-13, D-14, D-17, D-25

## Problem

The display board is the most complex page in v1 (754 lines) and the most valuable: candle
charts per drink, an SMA line, two marquees, market-event overlays, and a viewport-locked
layout. It is also where the offline defects bite — at an event with no internet, fonts fall
back and the theme never leaves the admin's laptop.

The display page is **read-only**, which is why it comes before the order path: it validates
auth, the protocol, theming, charts and reconnect with no risk of charging anyone.

## In scope

- Vite + React + TypeScript app; routes, `AppShell`, `RequireRole` from server-supplied
  `allowed_routes`.
- The shared core: Zustand store, `applyMessage` reducer, the one WebSocket client.
- `components/ui` primitives, including the nav duplicated four times in v1.
- Server-driven theming, including `/theme.css` for first paint.
- Login page and the koers board.
- Bundled fonts and charting; no CDN.

## Out of scope

- Bar, manipulation and settings pages (Phases 5–6).
- The theme *editor* (Phase 6); this phase consumes the theme, it does not edit it.

## Acceptance criteria

**Offline and assets**

- **AC1.** While the machine has no internet access, the system shall render every page with
  the correct fonts and a working chart. *(D-13)*
- **AC2.** When the production bundle is built, no asset reference shall point outside the
  origin. A CI check shall fail otherwise. *(D-13)*

**Theming**

- **AC3.** When an admin changes the theme on one machine, every connected client shall
  re-theme **without reload**. *(D-14)*
- **AC4.** When a page is loaded with JavaScript disabled or not yet executed, the themed
  background shall already be applied — no flash of default theme. *(ADR 0005)*
- **AC5.** When the candle interval is changed on the server, the display shall use it.
  *(D-14)*

**Realtime**

- **AC6.** While the WebSocket is open but no message has arrived for 45 seconds, the system
  shall force-close and reconnect. *(D-17)*
- **AC7.** When reconnecting, the system shall apply jittered exponential backoff.
- **AC8.** When the connection is lost, the system shall show a Dutch connection banner and
  start polling; when it reopens, polling shall stop.
- **AC9.** When a `snapshot` arrives, the system shall replace bar data wholesale, so client
  and server history cannot diverge.
- **AC10.** When a message sequence gap is detected, the system shall request a resync.

**Board**

- **AC11.** At 1920×1080 the board shall fit one viewport and shall not scroll.
- **AC12.** At ≤700 px portrait the board shall become one scrollable column; at ≤700 px
  landscape, two columns.
- **AC13.** When a price rises, the tile shall pulse **red**; when it falls, **green**. The
  candles shall use conventional green-up. *(deliberate inversion)*
- **AC14.** When the theme changes, chart colours shall update without the chart being torn
  down and recreated.
- **AC15.** When a tick arrives, the chart series shall be updated in place — no `remove`,
  no `setData`.
- **AC16.** When a market event is active, the system shall run its own countdown from
  `t_end_ms` and clear the overlay when it expires, without waiting for a broadcast. *(D-15)*
- **AC17.** When a drink name contains HTML metacharacters, the system shall render it as
  text. *(D-25)*
- **AC18.** When the marquee content updates, the scroll position shall not visibly jump.

## Verification

- Playwright: viewport fit assertion (`scrollHeight <= clientHeight`); responsive column
  counts; theme propagation across two browser contexts; the no-flash test (block the JS
  bundle, assert the themed background); offline banner and resync.
- Vitest: the reducer, the bars module, the SMA, the formatter, the WS state machine with
  fake timers.
- Chart tests against a mocked `lightweight-charts`, asserting no teardown on data update.
- **Manual:** disconnect the machine from the network entirely and load every page.

## Exit condition

The big screen works end to end against the new API, offline, and re-themes live from
another machine.
