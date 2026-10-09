# ADR 0005: Candle bucketing and theming move to the server

Date: 2026-09-12 · Status: Accepted

## Context

Two pieces of shared configuration live in `localStorage` in v1, which means they live
**per browser**:

- `candle_interval_s` is written by the settings page (`static/settings.html:614`) and read
  by the display page (`static/koers.html:293`). These run on different machines, so the
  setting never reaches the big screen. There are literally two definitions of "what is a
  bar".
- The entire theme — 21 CSS custom properties, the custom theme, and the uploaded
  background/header/logo/promo images — is stored and applied from `localStorage`
  (`static/theme.js`). The uploaded *file* goes to the server; the mapping from variable to
  URL does not. So the admin themes their own laptop and the big screen shows defaults.

Separately, the display page synthesises candles at 1 Hz (`koers.html:525-567`) because the
server only broadcasts every `refresh_minutes`, creating a second source of truth that
diverges from server history after a reconnect.

## Decision

1. `candle_interval_s` becomes a server parameter. **The server buckets**, and the `tick`
   message carries a real bar. `historyToOHLC()` and `tickCandles()` are both deleted.
2. Theme state — all 24 tokens of the server's manifest (`app/runtime/theme.py`; Phase 6
   SD28) plus image references — moves to the database and is
   broadcast over the WebSocket. Changing it on any machine re-themes every connected
   client instantly, without reload.
3. First paint uses a server-generated blocking stylesheet: `index.html` carries
   `<link rel="stylesheet" href="/theme.css">` and FastAPI renders that CSS from the stored
   theme. Stylesheets block first paint, so there is no flash, no extra JavaScript, and it
   works offline.

## Alternatives for the no-flash problem

| Option | Flash | Note |
|---|---|---|
| **Blocking `/theme.css` link** | none | One same-origin request. `index.html` stays a pure build artifact |
| Template a `<style>` into `index.html` | none | No extra request, but `index.html` is no longer static and a marker must survive Vite's HTML transform |
| Inline script that fetches the theme | **flashes** | `fetch` is async; impossible |
| `localStorage` (v1) | none | Per-browser — this is the bug |

## Consequences

- Client-side candle synthesis disappears, and with it the reconnect-divergence bug class.
- The tick rate rises to 1 Hz. At ~200 bytes per tick and a handful of clients this is under
  1 kB/s on a LAN — negligible, and it is what makes synthesis unnecessary.
- The theme editor becomes manifest-driven, which incidentally fixes it exposing only 13 of
  the 21 tokens (`settings.html:428-442`) — the reason custom themes look half-applied.
- Per-page `[data-theme="oudgeld"]` override blocks must be folded into the token system as
  real tokens, after which `data-theme` is a debugging attribute only.
- Fonts must be bundled rather than fetched from Google (see [ADR 0006](0006-bundle-all-assets-no-cdn.md)).
