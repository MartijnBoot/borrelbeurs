# Frontend architecture

Vite + React + TypeScript, no SSR. The built SPA is served by FastAPI from the same origin.
UI strings stay Dutch, wording preserved verbatim.

v1 is ~2,860 lines across six HTML pages with all logic inline in `<script>` blocks: four
copies of the nav, three WebSocket implementations at three quality levels, two identical
mobile drawers, and three euro formatters at three different precisions (0, 1 and 2 decimals
for the same numbers).

## Dependency budget

**Five runtime dependencies, ~120 kB gzipped:** React, React Router, Zustand,
lightweight-charts v5, Zod — plus bundled `@fontsource` files.

Explicitly rejected, each for a reason:

| Rejected | Why |
|---|---|
| TanStack Query | Its value is caching and background refetch of many keys. Here there is one key and it is *pushed*. The REST surface is commands, not queries |
| Redux Toolkit | Ceremony without payoff for one store |
| react-hook-form | These forms are uniformly "load server values, edit, save". An ~80-line `useEditableRecord` hook covers all of them. *Counterpoint: if the team does not already know RHF-free patterns, take RHF — 10 kB is not a real constraint on a LAN* |
| Chart.js | Consolidating on one chart library, see [ADR 0006](../adr/0006-bundle-all-assets-no-cdn.md) |
| Any CSS framework | The design is already expressed in CSS custom properties |

## Structure

```
web/src/
  app/            routes.tsx, AppShell.tsx, providers.tsx
  features/
    exchange/     THE core: live state, WS client, message reducer, selectors
    auth/         login form, session hook, RequireRole
    theme/        ThemeProvider, ThemeSection (preset picker); Phase 6 adds the editor.
                  The token manifest (24 tokens) is server-side, app/runtime/theme.py
    koers/  bar/  manipulation/  settings/  home/
  components/ui/  Button, Field, NumberField, Select, Switch, Marquee, NavMenu,
                  MobileSectionNav, ConfirmDialog, Toast, StatusDot
  lib/            http, ws transport, format (ONE euro formatter), useElementSize
  api/generated/  openapi-typescript output, committed
  styles/         tokens.css, base.css, keyframes.css
```

Each feature exposes one `index.ts`. Enforced with `eslint-plugin-boundaries`, which the
way-of-working calls a lint rule rather than a suggestion (§5.2). The other invariants are
core ESLint rules, with no React plugin: `no-restricted-syntax` bans `dangerouslySetInnerHTML`
and `innerHTML`/`outerHTML`/`insertAdjacentHTML`, and `no-restricted-globals` and
`no-restricted-properties` ban `localStorage`/`sessionStorage`.

**Dependency direction, which is the part that matters:** `exchange` may be imported by any
feature; `exchange` may import nothing from `features/`. Everything else is sibling-isolated.
Without that rule, "shared core" quietly becomes "everything imports everything".

Routes keep v1's paths — `/login`, `/`, `/koers`, `/bar`, `/manipulation`, `/settings` — so
QR codes, bookmarks and muscle memory survive. **Role gating comes from the server:**
`/auth/me` returns `allowed_routes`, and both `RequireRole` and `NavMenu` read that one list.
In v1 the role map is duplicated in `backend/auth.py:25-29` and again in four page scripts.

## State

One Zustand store, created once, holding connection status, the current `Quote`, drinks,
params, bars, news, market event, earnings and theme.

**One rule: the WebSocket is the only writer of live state.** A REST command returns, and the
store updates when the broadcast arrives. Pending state lives in component state. This single
rule deletes `computeLocalEarnings()` (`bar.html:192-211`) and the two-competing-revenue-
models problem outright.

Zustand over a hand-rolled Context specifically because `store.subscribe()` works **outside**
React — so a 1 Hz tick updates six charts imperatively with zero React renders.

**Message handling is a pure reducer:** `applyMessage(state, msg)`, exhaustive switch, `never`
check, no timers, no DOM, no network. It is the single highest-value unit test in the app.

## One WebSocket client owns reconnect

`features/exchange/model/client.ts`, ~150 lines. It adds two things no v1 page has:

- **Backoff jitter.** v1's curve (500 ms, ×1.7, 8 s cap) is fine, but without ±30% jitter ten
  tablets on one access point reconnect in lockstep after a wifi blip and hammer the single
  worker.
- **A 45-second liveness deadline.** If nothing arrives, force-close and reconnect. **This is
  the real failure mode at an event** — a half-open socket where `readyState === 1` forever
  and the big screen silently freezes on a stale price. No v1 page detects this. This one
  addition is worth more than the rest of the rewrite.

Polling exists only in the `offline` state and is cancelled on open, so `bar.html:369`'s bug
of never stopping its parallel poll cannot recur.

## The koers page

**Stable host, imperative feed.** Do not try to make lightweight-charts declarative. React
renders an empty `div`; the chart instance lives in a `useRef` for the tile's lifetime;
a store subscription calls `series.update()`. Ticks cause **zero** React renders for charts.
The whole `needsRebuild` teardown branch (`koers.html:437-484`) disappears as a concept.

Key on `drink.id`, not array index — v1 keys by index (`koers.html:291,477`) so any rename
tears down all six charts. Note StrictMode double-invokes mount effects in dev, so cleanup
must be idempotent and null the refs.

**The client synthesises nothing.** With a 1 Hz server tick carrying a server-bucketed bar
([ADR 0005](../adr/0005-server-side-bucketing-and-theming.md)), `tickCandles()` and
`historyToOHLC()` are both deleted, and with them the reconnect-divergence bug class. The
existing synthesis is in any case subtly broken: its SMA fast path reads `entry.ohlc`
(`koers.html:544`) which `tickCandles` never updates, so the SMA uses a stale window.

**Chart colours become theme tokens** via `applyOptions` on a `[tokens]` effect. v1 hardcodes
them (`koers.html:399-411`) while reading only `--sma-line` from CSS, and only once at
creation — so changing theme leaves the SMA line the old colour until reload. The same hole
exists in the bar chart (`bar.html:320-321`).

**Name the colour inversion.** `.tile.up` is red and `.tile.down` is green deliberately: a
rising drink price is bad news for the drinker. The candlesticks use conventional green-up.
Both currently overload `--up`/`--down` (`theme.js:9`), which is exactly why it reads as a
bug. Split into `--tile-rising`/`--tile-falling` and `--candle-up`/`--candle-down`. Keep the
legend verbatim: *"Tegels pulseren bij stijging (rood) of daling (groen)."*

Layout ports as CSS Modules nearly verbatim: viewport-locked 3-column grid,
`grid-auto-rows:1fr`, `clamp()` sizing, the ≤700 px and ≤700 px-landscape breakpoints, and
`has-promo` switching the container to `1fr clamp(180px,22%,360px)`.

## Marquees

React's reconciliation does not restart a CSS animation on a text change, so for the common
case — prices updating — the innerHTML/`animationDelay` trick (`koers.html:654-664`) is simply
unnecessary.

**The v1 trick is also subtly wrong.** It computes elapsed as `performance.now() % duration`
(`koers.html:657`), which is wall-clock rather than the animation's own timeline. The marquee
pauses on hover (`koers.html:48`), so after any hover the two diverge permanently and the next
state update produces exactly the jump the code was written to prevent.

Phase preservation is needed **only** when the item *count* changes, and should use the Web
Animations API `currentTime`, which *is* the animation's timeline. Market-event speed-up
becomes `animation.updatePlaybackRate(2.5)` rather than a `!important` duration class swap.

## The bar order path

Keep the anti-flicker buffering — it exists for a good reason, so prices do not change
mid-tap — but reframe it as a **display hold** rather than a state fork, and make the
invariant structural:

```ts
type Quote = { readonly version: number; readonly prices: readonly number[]; readonly at: number };
```

You cannot obtain a price without the version that belongs to it, because they are the same
object. That is what makes the bug impossible — not a code comment. The buffer holds a
reference to a `Quote`, never to two separate fields.

Force-promote the held quote on order success, on 409, on reconnect, and on manual refresh.
Show a subtle age indicator so the hold reads as deliberate rather than as a frozen screen.

Optimistic update is **UI only**: a local `pendingOrders` list gives instant feedback. Revenue
is never computed locally; the server is authoritative. See
[ADR 0008](../adr/0008-honour-the-quoted-price.md) for the server-side policy.

## Forms

The v1 defect: inputs use `placeholder=` instead of `value=` (`settings.html:668-671`), and
`+"" === 0` which is not `NaN` (`:678-680`), so clicking save without editing **zeroes
a/d/s0/c for every drink**. Same pattern in add-drink (`:701,712-715`).

Four structural defences, in order of importance:

1. **No raw `<input type="number">` in feature code.** `NumberField` is controlled, has no
   prop that accepts a number as a placeholder, and maps empty to `null` — never `0`.
   TypeScript then forces every call site to decide what `null` means.
2. **Parse, never coerce.** The raw string never escapes the component. Lint-ban bare `+x` on
   form values.
3. **Send only dirty fields (PATCH).** v1 sends every field every time. This alone would have
   prevented the incident.
4. **Zod at the boundary**, per way-of-working §5.3.

**A trap a naive React rewrite walks straight into:** v1's `settings.html:783` assigns
incoming WebSocket state but never re-renders, so a half-typed form is *accidentally*
protected. In React the same broadcast would wipe it every 60 seconds. Rule: reset from the
server only when the form is not dirty; otherwise show a non-blocking
"Serverwaarden gewijzigd — overnemen?" affordance.

Destructive actions use `ConfirmDialog`, not native `confirm`/`alert` (`settings.html:734,
750, 759, 763`), preserving the Dutch strings "Reset spel?", "Applicatie nu afsluiten?",
"'X' verwijderen?". XSS disappears for free because React escapes by default; add the
`react/no-danger` lint rule so the inconsistent escaping at `settings.html:633` and
`manipulation.html:383-386` cannot come back.

## Testing

| Layer | Scope |
|---|---|
| **Unit** (Vitest, node) | `applyMessage` reducer; bars module; SMA; the single euro formatter; the hold buffer; the WS state machine with fake timers; Zod schemas — *empty string maps to `null`, never `0`*, written first as the failing regression test |
| **Property** | Over thousands of random interleavings of tick arrivals and taps, assert `request.price_version === displayedQuote.version`. This is the money bug; it deserves more than an example test |
| **Component** (Testing Library) | `NumberField`; `NavMenu` across three roles; `ConfirmDialog` focus trap; `OrderPad` 409 handling; **settings forms: load, click save without editing, assert the request body is empty** |
| **Charts** | Mock `lightweight-charts` and assert the calls: `setData` once on bootstrap, `update` per tick, `applyOptions` on theme change, `remove` on unmount — and crucially **no `remove` on a data update** |
| **Playwright** (~8) | See [../specs/](../specs/) per phase |

**Deliberately not done: pixel-diff visual regression.** This UI is dark, animated,
`clamp()`-sized and font-dependent; the diffs will be flaky and the suite will be disabled
within two weeks. Assert *structural* properties instead — no-scroll, column count, class
presence, animation `currentTime`. Publish screenshots as CI artifacts for human review, not
as assertions.
