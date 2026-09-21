# ADR 0006: Bundle every asset; no CDN at runtime

Date: 2026-09-12 · Status: Accepted

## Context

v1 has **four** runtime CDN dependencies, not one:

| Dependency | Where |
|---|---|
| Inter, from Google Fonts | `koers.html:10`, `bar.html:10`, `settings.html:10`, `manipulation.html:10`, `home.html:8` |
| EB Garamond, lazily appended | `theme.js:116-121` |
| `lightweight-charts@4`, from jsDelivr | `koers.html:11` |
| `Chart.js` + `chartjs-adapter-date-fns`, from jsDelivr | `bar.html:11-12` |

**This is a live defect, not merely a constraint on the rebuild.** At an event with no
internet today, every page silently falls back to system fonts and the bar's revenue chart
throws `Chart is not defined`.

## Decision

Everything is bundled by Vite. Fonts ship as `@fontsource` packages (Inter and EB Garamond,
latin subset, used weights only — roughly 120 kB, hashed and cached forever). No runtime
request may leave the origin.

Charting consolidates on **lightweight-charts v5** only; Chart.js is dropped. v5 rather than
the v4 the CDN serves, because v5 is tree-shakeable ESM, which matters precisely because
everything must be bundled.

## Consequences

- One charting library means one theming path. v1 hardcodes chart colours in two separate
  places (`koers.html:399-411` and `bar.html:320-321`) while everything else is themed.
- The revenue chart's cumulative series needs a small adapter: lightweight-charts requires
  strictly ascending, unique timestamps in seconds, and two sales in the same second collide.
  Chart.js tolerated duplicates. This is the one genuine cost of the migration and needs a
  unit test.
- A CI check should assert no `https://` asset references survive in built output, or this
  regresses quietly.
- Total runtime JavaScript lands around 120 kB gzipped across five dependencies: React,
  React Router, Zustand, lightweight-charts, Zod.
