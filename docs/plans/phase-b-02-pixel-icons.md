# Plan: B-02 — Own pixel icons instead of emoji

Spec: [docs/specs/phase-b-02-pixel-icons.md](../specs/phase-b-02-pixel-icons.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-24)**
Design: [frontend-architecture.md](../design/frontend-architecture.md) ("Structure": `components/ui/`, `lib/`, per-feature `index.ts`, `eslint-plugin-boundaries`; "Testing": no pixel-diff tests, `:217-221`)
ADRs honoured: 0006 (the icons are code in the bundle, the favicon a same-origin static file, no new dependency), 0005 (no new theme token; icons are `currentColor`). Nothing in an ADR is reversed.
Backlog: [B-02](../backlog.md) · Fixes: no open defect · Builds on: the B-01 stack (`84eff7c`, PR #19)

---

## Approach

**One JSON file of grids, drawn by one component, checked by two languages.** The 21 grids
live in `web/src/components/ui/pixelIcons.json`, one array of row strings per icon, keyed by
motif (`broom`, `gear`, …, `favicon`). `components/ui/PixelIcon.tsx` turns a grid into an
inline SVG: one `<path>` built from each row's runs of `#`, `viewBox` the grid's size,
`fill="currentColor"`, `shape-rendering="crispEdges"`, 1em tall, `aria-hidden` unless it is
given a `label` (only rise and fall are, SD11). Every spot in SD4 renders `<PixelIcon name=…/>`
next to its plain name, with the gap made by CSS rather than a space character, so each
heading's `textContent` and accessible name are exactly the plain name. The contact sheet
(SD9) and the favicon (SD8) are made by one stdlib Python script,
`scripts/pixel_icons.py`. It reads the same JSON and imports the five presets straight from
`app/runtime/theme.py`. The approval is a real hard stop (T3), and every task that puts an
icon on a page depends on it. An emoji scan in Vitest (T14) closes the item.

Rejected:
- **A TypeScript grid module.** The script that writes the contact sheet and the favicon
  would then have to run TypeScript. `web/` has no `tsx`, `ts-node` or `vite-node`, and CI's
  Node 22 (`.nvmrc`) may not strip types without a flag. JSON is read natively by both Vitest
  and Python. This is B-01's precedent (PD1, `explanations.json`, read by
  `tests/unit/test_setting_explanations_text.py:18-19` and by Vitest).
- **Keeping each replaced emoji next to its grid in the JSON** (for the sheet's "beside the
  emoji it replaces"). That puts emoji under `web/src/`, and SD12's scan would fail on it. The
  name → (spot, replaced character, spot colour) table lives in the Python script, which
  SD12 does not scan.
- **A Python emoji scan in `tests/meta/`.** The stdlib has no `Extended_Pictographic`:
  `unicodedata` lacks the property, `re` has no `\p{}`, and `regex` is not installed. B-01's
  `category == "So"` check (`test_setting_explanations_text.py:141-146`) is not the same set.
  V8 supports `/\p{Extended_Pictographic}/u` natively, so the scan is a Vitest following
  `features/exchange/model/quote.provenance.test.ts` (`import.meta.glob` `?raw`, `path:line`
  messages, an anti-vacuity count, planted forgeries).
- **An SVG favicon.** It is the obvious match for the icons, but Safari's support for SVG
  favicons is recent, and the exit check includes an iPhone. A 64×64 PNG (each grid pixel
  4×4) is supported everywhere. It downscales exactly to 32 and 16, so it stays crisp.
- **A favicon built by a Vite plugin, or a hashed asset referenced from `index.html`.** A
  plugin is code nobody here maintains. A hashed asset gets a different URL in dev and in the
  build, and Vite may inline a small one as `data:`, which would leave nothing for AC12 to
  `GET`. `web/public/favicon.png` is served at `/favicon.png` by Vite in dev and copied to the
  `dist/` root at build. `SpaStaticFiles` already serves root files
  (`tests/api/test_static.py:192-204` pins `/favicon.svg`).
- **Python rendering the sheet's SVGs while TS renders the app's.** It is two renderers, but
  both are 10-line run-length loops, and each is tested cell-exact against the grid (T1, T2).
  A drift would then fail a test rather than mislead the owner.

---

## Decisions this plan makes

Rows marked **Confirm** are readings of the spec that the audit confirms or overrules. The
owner confirmed all four (PD5, PD6, PD8, PD13) as written at the audit on 2026-10-24; see
§ Audit.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | Grid file and keys | `web/src/components/ui/pixelIcons.json`: `{ "<motif>": ["<row>", …] }`, 21 keys. The 16×16 keys are `broom gear palette picture cup padlock chart key newspaper burst bolt hourglass beer banknote warning arrowUp`. The 8×8 keys are `stop rise fall chevronDown`. Plus `favicon`. The size is the row count; there is no separate size field to disagree with | Python and Vitest both read it; keys name the motif (SD10), not the spot |
| PD2 | The component | `PixelIcon({ name, label?, className? })`, where `name: Exclude<keyof typeof grids, 'favicon'>`. It renders `<svg viewBox="0 0 N N" width="1em" height="1em" fill="currentColor" shape-rendering="crispEdges" focusable="false">` with one `<path d=…>` made of `M{x} {y}h{w}v1h-{w}z` per run of `#`. Without `label`: `aria-hidden="true"`. With `label`: `role="img" aria-label={label}`. It has no size or scale prop (AC2) and no `<title>`, so it adds no text node | AC4, AC8, SD11; JSX only, no `innerHTML` (eslint `no-restricted-syntax`) |
| PD3 | The gap between icon and name | CSS (`margin-inline` or flex `gap`), never a space character. So `h2.textContent === 'Systeemacties'` | The existing `textContent` assertions (`SettingsPage.test.tsx:54`, `ManipulationPage.test.tsx:334`, `Tile.test.tsx:56-59`) keep working with the plain names |
| PD4 | Where the settings icon is declared | `SettingsSection` (`features/settings/SettingsLayout.tsx:10-14`) and `MobileSectionNav`'s `Section` (`components/ui/MobileSectionNav.tsx:11-14`) each gain `icon?: PixelIconName`. The `<h2>` and the sidebar `<a>` render it before `label`; the `Select` keeps `label` only. Borrel has no `icon` | SD4, In scope ("`SettingsSection` gains an icon next to its plain-text `label`") |
| PD5 | The crash and bubble banners' accessible name | The banner keeps `role="status"` and gains `aria-label={text}` ("MARKTCRASH", "PRIJSBUBBEL", "Terug naar start"). Its content becomes `<PixelIcon/>` + the word. **Confirm** | `status` takes no name from its content: `dom-accessibility-api`'s `allowsNameFromContent` excludes it, so AC8's "status MARKTCRASH" needs a label. The live region still announces the content, which is the same word |
| PD6 | AC6 on the banners | The banners keep `color: #fff` (`styles/keyframes.css:52-58`). Their icons are `currentColor`, so they stay white under every preset, exactly like the banner's text. AC6 is proved on a settings heading, as the spec's Verification says. **Confirm** | SD2: "a banner's icon is the banner's colour". Recolouring the banner would be a change the spec does not ask for |
| PD7 | The price change | In `lib/format.ts`, `deltaText(prev, cur): string` is replaced by `deltaParts(prev, cur): { direction: 'rise' \| 'fall' \| null; text: string }`. `text` is `€ 0,30 (12,0%)`, the fall `€ -0,30 (-12,0%)`, the unchanged `—`, and the zero previous price `€ 0,05 (0,0%)` with `rise`. `features/koers/DeltaIcon.tsx` renders `rise`→`<PixelIcon name="rise" label="stijgt"/>` and `fall`→`<PixelIcon name="fall" label="daalt"/>`. `Tile` and `PriceMarquee` use both. `MarqueePart` (`components/ui/Marquee.tsx:19-22`) gains `icon?: ReactNode`, rendered before `{part.text}` in the same span. `text` stays a text node (Phase 4 AC32) | AC9; In scope ("`deltaText` stops returning the symbol"). The marquee is the only other renderer of the delta |
| PD8 | The favicon's two colours (SD8) with a `#`/`.` grid (AC1) | The `favicon` grid draws **the glass and its outline** as `#`. An on pixel with any of its 8 neighbours off, or outside the grid, is outline (`#070b16`). Every other on pixel is fill (`#60a5fa`). Off pixels are transparent. **Confirm** | SD8: "its grid is its own 16×16 drawing (the glass plus its outline)". AC1 allows only `#` and `.`, so the outline has to be derived. 8-neighbour gives a closed ring at diagonal corners. The owner sees the result in the sheet (SD9) |
| PD9 | Favicon file | `web/public/favicon.png`, 64×64 RGBA, written by `python -m scripts.pixel_icons favicon`, committed. `web/index.html` gets `<link rel="icon" type="image/png" href="/favicon.png" />`. A pytest regenerates it in memory and requires byte equality with the committed file | AC12; drift between grid and file fails the gate (stdlib `zlib`, fixed level, so the output is deterministic) |
| PD10 | Contact sheet | `python -m scripts.pixel_icons sheet` writes `.dev/pixel-icons.html` (`.dev/` is gitignored, `.gitignore:54`; `dev.ps1` keeps its logs there). It has one block per preset (`oudgeld blauw groen paars rood`) with that preset's `--bg` background. Each icon is shown at 1×, 2× and 4× (N, 2N, 4N CSS px) in the colour of its spot, beside the character it replaces: `--text` for headings, sidebar and "Sluit app"; `--accent` for the Menu chevron; `--muted` for rise and fall; `#fff` on the banner's own background for crash and bubble. The favicon is shown at 1×, 2× and 4× on `#ffffff` and on `#202124` | AC3, SD9 |
| PD11 | Running the script | `uv run python -m scripts.pixel_icons {sheet,favicon} [--out PATH]`, run as a module so that `app.runtime.theme` imports. Stdlib only, like `scripts/check_built_assets.py`; tested from `tests/unit/` (`from scripts.pixel_icons import …`, as `tests/unit/test_check_built_assets.py:18`) | Existing script conventions |
| PD12 | The emoji scan's reach | It scans every text file under `web/src/` and `web/e2e/` and `web/index.html`, with extensions `.ts .tsx .css .json .html`. It fails on any other extension found there unless that extension is on a named binary list (`.png`). One failure per hit, as `path:line: U+XXXX`. The scan file writes the banned characters only as `\u{…}` escapes | SD12, AC14; a new file type cannot silently escape the scan |
| PD13 | SD13's notes beyond its list | The B-01 SD6 note also names B-01 **AC8** ("Every section heading shall be unchanged", `phase-b-01-settings-explained.md:486`), which contradicts B-02 as directly as SD6 does. The Phase 4 note covers SD21 **and SD22** (`phase-4-web-koers.md:146-147`, "Tile contents otherwise port `koers.html` verbatim"), because B-02 replaces the tile's ▲/▼. **Confirm** | A note on SD6 alone leaves AC8 reading as broken. AC16 requires the listed notes and forbids none extra |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `web/src/components/ui/pixelIcons.json` | Create | The 21 grids (PD1) | T1 (redraws in T3) |
| `web/src/components/ui/PixelIcon.tsx`, `PixelIcon.module.css`, `PixelIcon.test.tsx` | Create | The component (PD2); the grid checks (AC1, AC2, AC4) | T1 |
| `scripts/pixel_icons.py` | Create | `sheet` and `favicon` (PD8–PD11) | T2 |
| `tests/unit/test_pixel_icons.py` | Create | Sheet contents, path cells, favicon pixels and PNG; drift case added in T12 | T2, T12 |
| `docs/plans/phase-b-02-pixel-icons.md` | Modify | § Contact-sheet approval (AC15) | T3 |
| `tests/api/test_news.py`, `tests/api/test_drinks.py` | Modify | Emoji kept as typed (AC11) | T4 |
| `web/src/features/settings/SettingsLayout.tsx`, `settings.module.css` | Modify | `icon?` on `SettingsSection`; icon in `<h2>` | T5 |
| `web/src/components/ui/MobileSectionNav.tsx`, `MobileSectionNav.module.css` | Modify | `icon?` on `Section`; icon in the link; select untouched | T5 |
| `web/src/app/pages/SettingsPage.tsx`, `SettingsPage.test.tsx` | Modify | Plain labels + icons; tests on plain names | T5 |
| `web/src/components/ui/FormControls.test.tsx` | Modify | `MobileSectionNav` cases (`:130-165`) | T5 |
| `web/e2e/admin.spec.ts` | Modify | `section(…)` names (T5); "Opslaan instellingen" (`:124`, T8) | T5, T8 |
| `web/e2e/analytics.spec.ts`, `web/e2e/offline.spec.ts` | Modify | Section and heading names | T5 |
| `web/src/features/manipulation/ManipulationPage.tsx`, `ManipulationPage.module.css`, `ManipulationPage.test.tsx` | Modify | Four titles with icons | T6 |
| `web/src/features/manipulation/NewsSection.tsx`, `MarketEventsSection.tsx`, `PriceJumpSection.tsx` | Modify | Docblock line 2 only | T6 |
| `web/src/features/bar/BarPage.tsx`, `BarPage.module.css`, `FinancialPanel.tsx`, `FinancialPanel.module.css`, `BarPage.test.tsx`, `FinancialPanel.test.tsx` | Modify | Two headings with icons | T7 |
| `web/src/features/auth/auth.test.tsx`, `web/e2e/auth.spec.ts`, `web/e2e/bar.spec.ts` | Modify | Bar heading names | T7 |
| `web/src/features/settings/GlobalSection.tsx`, `DemandSection.tsx`, `SystemSection.tsx` (+ their `.test.tsx`) | Modify | Opslaan text only; "Sluit app" + `stop`; docblocks | T8 |
| `web/src/features/manipulation/IdleSection.tsx`, `IdleSection.test.tsx` | Modify | "Opslaan idle"; docblocks | T8 |
| `web/src/features/koers/MarketEventLayer.tsx`, `MarketEventLayer.test.tsx`, `web/e2e/board.spec.ts` | Modify | Banners (PD5, PD6) | T9 |
| `web/src/lib/format.ts`, `format.test.ts` | Modify | `deltaParts` (PD7) | T10 |
| `web/src/features/koers/DeltaIcon.tsx` | Create | Rise and fall with their names | T10 |
| `web/src/features/koers/Tile.tsx`, `Tile.test.tsx`, `PriceMarquee.tsx`, `KoersPage.module.css` | Modify | Delta rendering | T10 |
| `web/src/components/ui/Marquee.tsx`, `Marquee.test.tsx` | Modify | `MarqueePart.icon?` | T10 |
| `web/src/components/ui/NavMenu.tsx`, `NavMenu.module.css`, `NavMenu.test.tsx` | Modify | "Menu" + `chevronDown` | T11 |
| `web/public/favicon.png` | Create | Generated (PD9) | T12 |
| `web/index.html` | Modify | `<link rel="icon">` | T12 |
| `web/e2e/icons.spec.ts` | Create | Favicon (T12); AC5, AC6, AC10 (T13) | T12, T13 |
| `web/e2e/fixtures.ts`, `web/e2e/theme.spec.ts` | Modify | Move `storeTheme` (`theme.spec.ts:28-39`) to the shared fixtures, for reuse | T13 |
| `web/src/noEmoji.test.ts` | Create | SD12 scan (PD12) | T14 |
| `web/src/features/keys/KeysSection.tsx`, `KeysSection.test.tsx`; `web/src/features/settings/BoundsSection.tsx`, `BoundsSection.test.tsx`, `DrinksSection.tsx`, `DrinksSection.test.tsx`, `ImagesSection.tsx`, `ImagesSection.test.tsx`, `ThemeSection.tsx` | Modify | Docblock line 2 only (the hits no other task touches) | T14 |
| `docs/specs/phase-4-web-koers.md`, `phase-5-bar-orders.md`, `phase-6-admin.md`, `phase-b-01-settings-explained.md` | Modify | "Superseded in part by B-02" notes (SD13, PD13) | T15 |
| `docs/backlog.md` | Modify | B-02 status | T15 |

Not touched: `exchange/`, `app/`, `db/`, `web/src/api/generated/`, `docs/design/`,
`web/src/assets/logo.png`, `components/ui/Logo.*`, and the logo upload slot.

---

## Tasks

### T1 — The 21 grids and `PixelIcon`

- **Implements:** AC1, AC2, AC4; AC8's `aria-hidden` (component level)
- **Expected output:**
  - `pixelIcons.json` with the 21 keys of PD1, each drawn as SD10's motif. There are 16 of
    16×16, 4 of 8×8, and `favicon` as 16×16 with its outline as `#` per PD8. The 8×8 grids
    are drawn from scratch, not by thinning a 16×16.
  - `PixelIcon.tsx` per PD2, with the CSS module for `vertical-align` and `flex: none`.
    Export `type PixelIconName`.
  - `PixelIcon.test.tsx` (jsdom):
    - the JSON has exactly these 21 keys; 16 have 16 rows, 4 have 8, `favicon` has 16;
    - every row is as long as the row count, matches `/^[#.]+$/`, and every grid has a `#`
      (AC1);
    - for every non-favicon grid, the rendered path's runs cover exactly the grid's `#`
      cells, no more and no fewer (AC2: what is drawn is the grid itself);
    - the attributes `viewBox="0 0 N N"`, `fill="currentColor"`,
      `shape-rendering="crispEdges"`, `height="1em"` (AC4);
    - `aria-hidden="true"` by default; `role="img"` and the given name with `label`;
    - no `<title>`, `<image>`, `<use>` or `href` anywhere in the SVG (AC4: no file request).
  - Not placed on any page (AC15).
- **Verification:** `pnpm --dir web exec vitest run src/components/ui/PixelIcon.test.tsx`; `pnpm --dir web lint`; `pnpm --dir web exec tsc -b`.
- **Depends on:** —
- **Autonomy note:** The builder draws the motifs, choosing the drawing within SD10's motif
  and the run-length encoding. The owner judges the drawings in T3, so do not polish them
  past "clearly the motif". Stop and ask if a motif cannot be read at 8×8 or 16×16. The JSON
  is ~320 lines of drawing; that is the task's substance, not overrun. If Prettier reflows a
  grid onto one line, keep Prettier's output and say so in the commit.

### T2 — The contact sheet and favicon script

- **Implements:** AC3; the favicon pixels for AC12 (generator side)
- **Expected output:**
  - `scripts/pixel_icons.py` (stdlib plus `app.runtime.theme`):
    - `load_grids()` validates the JSON's shape (raises on a bad grid);
    - `svg(grid, px)` uses the same run encoding as PD2;
    - `favicon_rgba(grid)` follows PD8;
    - `encode_png(rgba, scale=4)` uses `zlib`, `struct` and `binascii.crc32`;
    - `main(argv)` takes the subcommands `sheet` (default out `.dev/pixel-icons.html`) and
      `favicon` (default out `web/public/favicon.png`).
  - The sheet follows PD10:
    - the preset tokens come from the function `render_css` uses to expand a preset
      (`app/runtime/theme.py:310-336`), not a copy;
    - the spot table (name → spot label, replaced character, spot colour) lives in this
      script, emoji and all.
  - `tests/unit/test_pixel_icons.py`:
    - `svg()` covers exactly the `#` cells;
    - `favicon_rgba`: a hand-made 5×5 grid gives fill, outline and transparent where PD8
      says;
    - `encode_png` round-trips. The test parses the IHDR and inflates the IDAT with `zlib`.
      The result is 64×64, and its pixels equal `favicon_rgba` scaled 4×;
    - `sheet`:
      - it writes exactly one file at the given path;
      - the file holds every non-favicon grid × 5 presets × 3 scales, plus the favicon on 2
        backgrounds × 3 scales;
      - each preset's `--bg` appears;
      - the default path is not under `web/dist` (AC3).
  - Run `uv run python -m scripts.pixel_icons sheet` and leave `.dev/pixel-icons.html` for
    the owner.
- **Verification:** `uv run pytest tests/unit/test_pixel_icons.py`; `uv run ruff check scripts tests/unit/test_pixel_icons.py`; `uv run ruff format --check scripts tests/unit`.
- **Depends on:** T1
- **Autonomy note:** Layout, styling and the function names of the sheet are the builder's.
  Stop and ask if importing `app.runtime.theme` needs the environment, a database or a
  config file. The fallback would be parsing `theme.py` as `ThemeEditor.test.tsx:12-16`
  does, and that is a choice for the owner. Do not write `web/public/favicon.png` yet;
  that is T12, after the drawings are approved.

### T3 — Contact-sheet approval (SD9) — **hard stop, owner**

- **Implements:** AC15
- **Expected output:**
  - The build **stops** after T2 and tells the owner the absolute path of
    `.dev/pixel-icons.html`.
  - The owner either says "go" or lists icons to redraw. For a redraw, the builder edits
    only the named grids in `pixelIcons.json`, re-runs T1's test and `sheet`, and stops
    again.
  - On "go", the builder fills § Contact-sheet approval below with the date, each round's
    answer, and the grids redrawn, and commits it with any redraws:
    `docs(phase-b-02): T3 — contact sheet approved`.
- **Verification:** § Contact-sheet approval holds a dated "go" from the owner;
  `pnpm --dir web exec vitest run src/components/ui/PixelIcon.test.tsx` and
  `uv run pytest tests/unit/test_pixel_icons.py` green on the approved grids.
- **Depends on:** T2
- **Autonomy note:** **Stop. This is the owner's, not a step to note and carry on past**
  (`.claude/commands/build.md:53-55` does not apply: T5–T13 depend on it). The builder may
  not approve, may not read silence as approval, and may not redraw an icon the owner did not
  name. A changed motif (SD10 allows it at this stop) is a redraw like any other.

### T4 — Typed text keeps its emoji (SD6)

- **Implements:** AC11
- **Expected output:**
  - In `tests/api/test_news.py`, posting `{"level": "info", "text": "Happy hour 🎉"}`
    returns that exact text, stores it in the row (`_rows()`, `:35-47`), and returns it from
    `GET /api/news`.
  - In `tests/api/test_drinks.py`, creating a drink named `"Bier 🍺"` stores it and lists it
    unchanged.
  - These pin behaviour that exists today, so they pass on first run. Say so in the commit.
    No product code changes.
- **Verification:** `uv run pytest tests/api/test_news.py tests/api/test_drinks.py` (needs the compose `db`).
- **Depends on:** —
- **Autonomy note:** Test names and placement are the builder's. **If either fails, stop and
  ask**: emoji would then be refused today, and SD6 forbids new validation, so the fix is the
  owner's call.

### T5 — `/settings`: section headings and sidebar links

- **Implements:** AC7, AC8 (settings rows of SD4; the "Sectie" select and Borrel as text only)
- **Expected output:**
  - PD4 is in place.
  - `SettingsPage.tsx:23-39`: the plain labels, with `icon`s `broom`, `gear`, `palette`,
    `picture`, `cup`, `padlock`, `chart` and `key`; Borrel has no icon.
  - `SettingsPage.test.tsx`:
    - `SECTIONS` holds the plain names;
    - each `<h2>` and sidebar link contains exactly one `svg[aria-hidden="true"]` before
      the name, except Borrel, which has none;
    - every `<option>` of "Sectie" holds only text;
    - the `region` names are plain.
  - `FormControls.test.tsx:130-165`: a section with `icon` shows it in the link, not in the
    `<option>`.
  - e2e: every `section(page, '…')` in `admin.spec.ts` (except `:124`, which is T8's) and in
    `analytics.spec.ts`, plus `offline.spec.ts:58`, use the plain names.
- **Verification:** `pnpm --dir web exec vitest run src/app/pages/SettingsPage.test.tsx src/components/ui/FormControls.test.tsx`; `pnpm --dir web exec playwright test admin analytics offline` (needs the compose `db` and a `pnpm --dir web build`).
- **Depends on:** T3
- **Autonomy note:** CSS for the icon gap and alignment is the builder's (PD3). Stop and ask
  before changing any section's wording, order or `id`.

### T6 — `/manipulation`: four section titles

- **Implements:** AC7, AC8 (manipulation rows of SD4)
- **Expected output:**
  - The local `Section` (`ManipulationPage.tsx:38-45`) gains `icon: PixelIconName`. The
    titles are "Nieuws" with `newspaper`, "Market events" with `burst`, "Price jump" with
    `bolt`, and "Idle" with `hourglass`.
  - The docblocks at `ManipulationPage.tsx:2-3`, `NewsSection.tsx:2`,
    `MarketEventsSection.tsx:2` and `PriceJumpSection.tsx:2` are rewritten without emoji.
  - `ManipulationPage.test.tsx`:
    - `:112`, `:124-131`, the `describe` titles, `:317-320` and `:335-338` use the plain
      names;
    - each `<h2>` holds one `aria-hidden` svg.
- **Verification:** `pnpm --dir web exec vitest run src/features/manipulation/ManipulationPage.test.tsx`.
- **Depends on:** T3
- **Autonomy note:** "Market events" and "Price jump" stay English (spec Out of scope). The
  builder must not touch `IdleSection.*`, which is T8's.

### T7 — `/bar`: two headings

- **Implements:** AC7, AC8 (bar rows of SD4)
- **Expected output:**
  - `BarPage.tsx:24`: `<h1>` = `beer` + "Bar — Bestellen".
  - `FinancialPanel.tsx:23`: `<h2>` = `banknote` + "Financieel overzicht".
  - The docblocks at `BarPage.tsx:2,4` are rewritten.
  - The tests:
    - `BarPage.test.tsx:69,77,85,96,106`, `FinancialPanel.test.tsx:90` and
      `auth.test.tsx:199` use the plain names;
    - the negative assertions `BarPage.test.tsx:72,102` and `auth.test.tsx:207` use the
      plain names too, so they stay meaningful and do not pass vacuously.
  - e2e: `auth.spec.ts:54` and `bar.spec.ts:224` use the plain names.
- **Verification:** `pnpm --dir web exec vitest run src/features/bar src/features/auth/auth.test.tsx`; `pnpm --dir web exec playwright test auth bar`.
- **Depends on:** T3
- **Autonomy note:** Alignment CSS is the builder's. "Bestellingen" (`BarPage.tsx:35`) gets
  no icon (SD4).

### T8 — Buttons: the four "Opslaan …" and "Sluit app"

- **Implements:** AC7 (Opslaan text only; "Sluit app" with `stop`), AC8
- **Expected output:**
  - The button text becomes "Opslaan instellingen" (`GlobalSection.tsx:124`), "Opslaan
    schakelaars" and "Opslaan coëfficiënten" (`DemandSection.tsx:156,210`), and "Opslaan
    idle" (`IdleSection.tsx:166`).
  - `SystemSection.tsx:75` becomes `<PixelIcon name="stop"/>` + "Sluit app".
  - The docblocks at `GlobalSection.tsx:2`, `DemandSection.tsx:2`, `SystemSection.tsx:2,4`
    and `IdleSection.tsx:2,9` are rewritten.
  - The tests:
    - `GlobalSection.test.tsx:97`, `DemandSection.test.tsx:96,137,146`,
      `IdleSection.test.tsx:117,127,165,186` and `SystemSection.test.tsx:55,63` use the
      plain names;
    - their line-2 comments are rewritten;
    - `SystemSection.test.tsx` adds: the button's name is exactly "Sluit app", and it holds
      one `aria-hidden` svg. Each "Opslaan …" button holds no svg.
  - e2e: `admin.spec.ts:124` becomes "Opslaan instellingen".
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/GlobalSection.test.tsx src/features/settings/DemandSection.test.tsx src/features/settings/SystemSection.test.tsx src/features/manipulation/IdleSection.test.tsx`; `pnpm --dir web exec playwright test admin`.
- **Depends on:** T3, T5 (both write `admin.spec.ts`)
- **Autonomy note:** `Button` (`components/ui/Button.tsx`) gets no icon prop. The icon is a
  child, aligned by `PixelIcon`'s CSS. Stop and ask before changing `Button`'s API.

### T9 — Koers banners

- **Implements:** AC7, AC8 (banner rows of SD4), PD5, PD6
- **Expected output:**
  - `MarketEventLayer.tsx:16-20` maps each kind to `{ icon?, text }`: `crash` →
    `warning` + "MARKTCRASH", `bubble` → `arrowUp` + "PRIJSBUBBEL", `correction` → "Terug
    naar start" with no icon.
  - The banner `<div role="status" aria-label={text}>`, so the `textContent` is the word
    alone.
  - The docblock at `:6-7` is rewritten. `keyframes.css` is unchanged.
  - `MarketEventLayer.test.tsx`:
    - `:82,90` assert the `textContent` "MARKTCRASH" and "PRIJSBUBBEL";
    - each has one `aria-hidden` svg;
    - `getByRole('status', { name: 'MARKTCRASH' })` resolves;
    - correction has no svg.
  - `board.spec.ts:160` uses `toHaveText('MARKTCRASH')`.
- **Verification:** `pnpm --dir web exec vitest run src/features/koers/MarketEventLayer.test.tsx`; `pnpm --dir web exec playwright test board`.
- **Depends on:** T3
- **Autonomy note:** If the audit overrules PD5 or PD6, follow its ruling. Otherwise stop and
  ask before changing a banner's colour, size or animation.

### T10 — Price change on tiles and marquee

- **Implements:** AC9; AC7 and AC8 for the rise/fall row
- **Expected output:**
  - PD7: `deltaParts` replaces `deltaText` (the only callers are `Tile.tsx:35` and
    `PriceMarquee.tsx:23`). `DeltaIcon.tsx` is added, and `MarqueePart.icon?` is rendered
    before the text.
  - The tile's change shows `DeltaIcon` + text. Each marquee item's change part carries
    `icon: <DeltaIcon …/>`.
  - The module docblock at `format.ts:2` and the comment at `:30` are updated.
  - The tests:
    - `format.test.ts:30-46`: rise, fall, unchanged and zero-previous give the direction and
      text of PD7;
    - `Tile.test.tsx:56-59`: the change's `textContent` is `€ 0,30 (12,0%)`, and an
      `img` named "stijgt" sits before it. The fall gives "daalt"; unchanged gives "—" with
      no img;
    - `Marquee.test.tsx`: a part with `icon` renders it before the text, and the text is
      still a text node (the AC32 case still passes).
  - `NewsMarquee` is unchanged.
- **Verification:** `pnpm --dir web exec vitest run src/lib/format.test.ts src/features/koers/Tile.test.tsx src/components/ui/Marquee.test.tsx`; `pnpm --dir web exec playwright test board`.
- **Depends on:** T3
- **Autonomy note:** The names `deltaParts` and `DeltaIcon` may change if the builder finds
  better ones; the shape of PD7 may not. The icon takes `.change`'s `--muted` (SD2, the
  surrounding text's colour). Do not switch it to `--up` or `--down`. Do not touch
  `MarketEventLayer.test.tsx` (T9's). If its name-count cases (`:165-171`) break, stop and
  ask.

### T11 — The Menu button

- **Implements:** AC7, AC8 (Menu row of SD4)
- **Expected output:**
  - `NavMenu.tsx:54` becomes `Menu<PixelIcon name="chevronDown"/>`, with the icon after the
    word and the gap from CSS.
  - `NavMenu.test.tsx`: the button's name is exactly "Menu" (`{ name: 'Menu' }`, exact), and
    one `aria-hidden` svg comes after the text node.
- **Verification:** `pnpm --dir web exec vitest run src/components/ui/NavMenu.test.tsx`.
- **Depends on:** T3
- **Autonomy note:** The colour stays `--accent` (`NavMenu.module.css:14`), which is the
  button's text colour. The builder may adjust `gap` only.

### T12 — The favicon

- **Implements:** AC12; AC13 (the logo is untouched)
- **Expected output:**
  - `uv run python -m scripts.pixel_icons favicon` writes `web/public/favicon.png` from the
    approved grid. `web/index.html` gains `<link rel="icon" type="image/png" href="/favicon.png" />`.
  - `tests/unit/test_pixel_icons.py` gains the drift case: the committed file equals
    `encode_png(favicon_rgba(grid))` byte for byte.
  - New `web/e2e/icons.spec.ts`:
    - `GET /favicon.png` on the built app is 200, with `content-type` `image/png` and same
      origin;
    - the `<link rel="icon">` href resolves to it.
  - Dev server (not in the gate, PD9): with `pnpm --dir web dev` running, fetch
    `http://127.0.0.1:5173/favicon.png` with `urllib` and get 200 with `image/png`. Paste
    the output in the commit body.
- **Verification:** `uv run pytest tests/unit/test_pixel_icons.py`; `pnpm --dir web build && uv run python scripts/check_built_assets.py web/dist`; `pnpm --dir web exec playwright test icons`; the dev-server `urllib` check above; `git diff --stat -- web/src/assets web/src/components/ui/Logo.tsx web/src/components/ui/Logo.module.css` is empty.
- **Depends on:** T3
- **Autonomy note:** The favicon's colours are fixed by SD8. The builder must not make it
  follow the theme, add a server route, or add a manifest (spec Out of scope). The browser's
  automatic `/favicon.ico` request stays a 404; leave it.

### T13 — Whole pages: height, colour, no emoji (Playwright)

- **Implements:** AC5, AC6, AC10
- **Expected output:**
  - `storeTheme` moves from `theme.spec.ts:28-39` to `e2e/fixtures.ts`; `theme.spec.ts`
    imports it.
  - `icons.spec.ts` gains:
    - **AC5:** the icon's `getBoundingClientRect().height` is within 1 px of
      `getComputedStyle(container).fontSize` on:
      - the "Systeemacties" heading on `/settings`;
      - the "Bar — Bestellen" heading on `/bar`;
      - the crash banner at 1920×1080, started as `board.spec.ts` starts one;
      - a tile's rise icon at 360×800, after a price moves, as `board.spec.ts` causes one.
    - **AC6:** on `/settings` under `blauw`, switch to "Oud Geld" via Kleurenschema (as
      `theme.spec.ts:84` does). Without a reload, the "Globale instellingen" icon's path's
      computed `fill` equals the heading's computed `color`, equals oudgeld `--text`
      (`#e8dfc0`), and differs from its value before the switch. Then save a custom
      `--text` and check the icon follows it. `afterAll` restores `blauw`.
    - **AC10:** for each of the five presets (`storeTheme`), visit `/`, `/bar`, `/settings`,
      `/manipulation`, `/analytics` and `/login`, each as its role. In each page's
      `document.body.innerText` and in every `aria-label`, `title`, `alt` and `placeholder`,
      no character matches SD12's set. The seed data is v1's, which has no emoji
      (spec Problem).
- **Verification:** `pnpm --dir web exec playwright test icons theme` (after `pnpm --dir web build`).
- **Depends on:** T5, T6, T7, T8, T9, T10, T11, T12
- **Autonomy note:** Helpers and waits are the builder's; reuse `board.spec.ts`'s way of
  starting an event and moving a price rather than writing a new one. If the AC10 loop adds
  more than ~60 s to the e2e run, stop and ask before cutting presets.

### T14 — The emoji scan (SD12)

- **Implements:** AC14
- **Expected output:**
  - `web/src/noEmoji.test.ts` per PD12, after the pattern of `quote.provenance.test.ts`. It
    has an anti-vacuity count (at least the number of files that exist) and planted strings
    that must hit (⚠, ▲, ▼, ▾, a U+FE0F sequence, 🍺) and miss (€, →, ×, …), all written as
    escapes.
  - The remaining hits are docblock line 2 in `KeysSection.tsx`, `KeysSection.test.tsx`,
    `BoundsSection.tsx`, `BoundsSection.test.tsx`, `DrinksSection.tsx`,
    `DrinksSection.test.tsx`, `ImagesSection.tsx`, `ImagesSection.test.tsx` and
    `ThemeSection.tsx`. They are rewritten with the plain names.
  - The scan is then green over the whole tree.
  - Shown to bite: add one `⚠` to a component, run it red with `path:line` in the message,
    remove it, and run it green. Paste both runs in the commit body.
- **Verification:** `pnpm --dir web exec vitest run src/noEmoji.test.ts` (red with the planted ⚠, green without); `./scripts/check.sh`.
- **Depends on:** T5, T6, T7, T8, T9, T10, T11, T13
- **Autonomy note:** If the scan finds a hit outside the files listed in this plan, fix it
  only if it is the app's own text, a test or a comment. If it is text a person typed (a
  fixture), stop and ask.

### T15 — Older specs, backlog, and the item's end

- **Implements:** AC16, AC17; AC13 (regression evidence)
- **Expected output:**
  - A note in B-01's style (`phase-6-admin.md:199-203`: an indented blockquote starting
    `**Superseded in part by B-02**` with a link to this item's spec) on each of:
    - Phase 4 SD21 (`phase-4-web-koers.md:139-145`), also naming SD22's ▲/▼ (PD13);
    - Phase 5 SD18 (`phase-5-bar-orders.md:192-195`);
    - Phase 6 SD20 (`:300-305`), SD25 (`:336-349`), SD26 (`:350-359`, "Sluit app") and
      SD30 (`:431`);
    - B-01 SD6 (`phase-b-01-settings-explained.md:79-83`), also naming its AC8 (PD13).
  - The texts in those specs are left as the record.
  - `docs/backlog.md`: B-02 → `built → docs/plans/phase-b-02-pixel-icons.md (spec: docs/specs/phase-b-02-pixel-icons.md)`, as B-01 was.
- **Verification:**
  - `grep -c "Superseded in part by B-02"` gives 1 in `phase-4-web-koers.md`, 1 in
    `phase-5-bar-orders.md`, 4 in `phase-6-admin.md` and 1 in
    `phase-b-01-settings-explained.md`;
  - `git diff --stat <T1's base>..HEAD -- docs/design exchange web/src/api/generated db/migrations app`
    is empty (AC16, AC17);
  - `./scripts/check.sh`, green, output pasted. It covers AC13 through `Logo.test.tsx`,
    `ImagesSection.test.tsx`, `admin.spec.ts:138-149,182` and `tests/api/test_assets.py`.
- **Depends on:** T4, T14
- **Autonomy note:** Note wording is the builder's, in the B-01 note's register; it must not
  restate what the spec now says. Run the manual exit check with the owner (spec
  Verification: the admin laptop, an Android phone and an iPhone; the tab icon). It is a
  human step, and the item is not done without it.

---

## Contact-sheet approval (SD9, AC15)

T3 fills this in. No icon is placed on a page (T5–T13) before it holds a "go".

| Round | Date | Owner's answer | Grids redrawn |
|---|---|---|---|
| — | — | — | — |

---

## Task graph

```
T1 ── T2 ── T3 (owner) ─┬─ T5 ── T8 ─┐
                        ├─ T6 ───────┤
                        ├─ T7 ───────┤
                        ├─ T9 ───────┼── T13 ── T14 ──┐
                        ├─ T10 ──────┤                ├── T15
                        ├─ T11 ──────┤                │
                        └─ T12 ──────┘                │
T4 ───────────────────────────────────────────────────┘
```

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T4 | `components/ui/pixelIcons.json`, `PixelIcon.*` · `tests/api/test_news.py`, `test_drinks.py` |
| G2 | T2 | `scripts/pixel_icons.py`, `tests/unit/test_pixel_icons.py` |
| G3 | T3 (owner) | `pixelIcons.json` (redraws only), this plan |
| G4 | T5, T6, T7, T9, T10, T11, T12 | settings layout/nav/page and `admin`/`analytics`/`offline` specs · manipulation page and three docblocks · bar, `auth.test.tsx`, `auth`/`bar` specs · `MarketEventLayer.*`, `board.spec.ts` · `format.*`, `DeltaIcon`, `Tile.*`, `PriceMarquee`, `Marquee.*`, `KoersPage.module.css` · `NavMenu.*` · `web/public/favicon.png`, `index.html`, `test_pixel_icons.py`, `icons.spec.ts` |
| G5 | T8 | Global/Demand/System/Idle sections and tests, `admin.spec.ts` |
| G6 | T13 | `icons.spec.ts`, `fixtures.ts`, `theme.spec.ts` |
| G7 | T14 | `noEmoji.test.ts`, nine docblock lines |
| G8 | T15 | four specs, `backlog.md` |

No two tasks in one group write the same file. `admin.spec.ts` is written by T5 and then T8,
so T8 depends on T5. `icons.spec.ts` is created by T12 and extended by T13.
`test_pixel_icons.py` is written by T2 and then T12, which T3 orders. `board.spec.ts` is
written only by T9. T10 only runs it.

---

## Data changes

None. No migration, no API change, and no stored data is touched. `web/src/api/generated/`
stays as it is (AC17).

---

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| `/build` notes an owner step and carries on (`build.md:53-55`), so icons reach pages unapproved | T3 is a hard stop in its Autonomy note, and T5–T13 all depend on it |
| Python (sheet) and TS (app) draw a grid differently, so the owner approves something the app does not show | Both renderers are tested to cover exactly the grid's `#` cells (T1, T2) |
| AC12's "with the dev server running" has no harness: e2e serves only the built `web/dist` (`playwright.config.ts:1-7`) | `web/public/` is Vite's documented dev-and-build path. T12 checks the dev server by command and pastes the result; the gate pins the built app |
| SVG favicon support on iPhone Safari | PNG chosen (PD9); the manual exit check includes an iPhone |
| PD5 (the banner's `aria-label`), PD6 (banner icons stay white) and PD8 (outline derived from the grid) are readings | Marked **Confirm**; the audit rules |
| The spec counts "16 emoji, in 21 places"; the code has 19 places (8 + 4 + 2 + 4 + 1) plus 4 symbols. "21" is the grid count | No behaviour depends on it; every place is a task (Files table). The spec is not edited |
| B-01 AC8 and Phase 4 SD22 contradict B-02 but are not in SD13 | PD13 (Confirm): covered inside the listed notes |
| `frontend-architecture.md:4` ("wording preserved verbatim") and its `components/ui` list (`:37-38`, already missing B-01's `InfoButton`) go further out of date | SD13 forbids changing `docs/design/`; recorded here only |
| Each marquee row is rendered twice with neither copy hidden (`PriceMarquee.tsx:35`), so "stijgt"/"daalt" are read twice per drink, as names and prices already are | Pre-existing; out of scope |
| An 8×8 icon at 14 px has uneven pixel columns | Accepted by SD5 |
| The negative assertions (`BarPage.test.tsx:72,102`, `auth.test.tsx:207`) would pass vacuously if left on the old string | T7 rewrites them to the plain names; T14's scan forbids the old strings |
| Prettier may reflow a grid's rows | T1's autonomy note: keep Prettier's output; the test checks content, not layout |
| The AC10 loop (5 presets × 6 routes) slows e2e | T13 stops and asks above ~60 s |
| The spec, the backlog edit and this plan are uncommitted on `docs/phase-b-02-spec` | Commit them before `/build b-02`, so T1's branch carries the approved spec and plan |

---

## Out of scope for this plan

- Recolouring the crash and bubble banners for the theme (PD6). Their `#fff` is v1's.
- Colouring the rise and fall icons `--up`/`--down`. They take the change text's `--muted`
  (SD2).
- A `/favicon.ico` file or route, a manifest, or home-screen icons (spec Out of scope).
- Hiding the marquee's second copy from assistive tech (pre-existing).
- Marking B-01's own gaps, Phase 6 SD22 (`:314`) and SD26's "📌" (`:354`), as superseded.
  B-01 renamed those; noted here for B-01's owner.
- Adding a "built" status to the backlog template (`backlog.md:31`); B-01 already uses it.
- Everything in the spec's Out of scope.

---

## AC → task traceability

| AC | Tasks |
|---|---|
| AC1 | T1 |
| AC2 | T1 |
| AC3 | T2 |
| AC4 | T1 |
| AC5 | T13 |
| AC6 | T13 (`currentColor` from T1) |
| AC7 | T5, T6, T7, T8, T9, T10, T11 |
| AC8 | T5, T6, T7, T8, T9, T10, T11 (`aria-hidden` from T1) |
| AC9 | T10 |
| AC10 | T13 |
| AC11 | T4 |
| AC12 | T2 (pixels), T12 |
| AC13 | T12, T15 |
| AC14 | T14 |
| AC15 | T3 |
| AC16 | T15 |
| AC17 | T15 |

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible (none: no migration, no API change)
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Rulings at the audit (owner, 2026-10-24):

- **PD5 confirmed.** The banners keep `role="status"` and gain `aria-label={text}`.
- **PD6 confirmed, as an accepted exception to AC6.** The crash and bubble banner icons stay
  `#fff` like the banner text and do not follow the theme. AC6 is proved on a settings heading
  (T13). The spec is not amended.
- **PD8 confirmed.** The favicon outline is derived from the grid (8-neighbour); the owner
  judges the result at T3.
- **PD13 confirmed.** The B-01 SD6 note also names B-01 AC8; the Phase 4 SD21 note also names
  SD22.
- **AC12's dev-server half** is accepted as a manual `urllib` check pasted in T12's commit; the
  gate pins the built app only.
- Noted, not changed: T5 and T14 sit at the ~10-file limit (T14's are nine one-line docblock
  edits); AC3's test counts icons × presets × scales but not the replaced character beside
  each, which the owner sees at T3.

Audited by: Martijn Boot (owner), walked through by Claude  Date: 2026-10-24
