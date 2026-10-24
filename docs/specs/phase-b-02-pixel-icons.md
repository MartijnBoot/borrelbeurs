# Spec: B-02 — Own pixel icons instead of emoji

Status: Approved · Depends on: Phase 4, Phase 5, Phase 6, B-01 (PR #19: it renamed the 33
market controls without emoji and left the headings to this item, B-01 SD6) · Fixes: no open
defect · Backlog: [B-02](../backlog.md)

Line references are to the B-01 tip (`84eff7c`), which this item builds on.

## Problem

Every page outside the koers board uses emoji as icons, and the board itself uses font-drawn
symbols. Each device draws them with its own emoji font, so the same heading looks different
on the admin laptop, an Android bar phone, an iPhone and the big screen. And none of it is
BorrelBeurs's own.

**16 emoji, in 21 places:**

- `/settings`: the eight section names "🧹 Systeemacties", "⚙️ Globale instellingen",
  "🎨 Kleurenschema", "🖼️ Afbeeldingen", "🥤 Drankjes beheren", "🔒 Min/Max/Startprijs",
  "📈 Vraag/Aanbod" and "🔑 Toegangssleutels" (`web/src/app/pages/SettingsPage.tsx:23-39`). Each
  name appears three times: as the section's `<h2>` (`web/src/features/settings/SettingsLayout.tsx:30`),
  as a sidebar link, and as an option in the narrow-screen "Sectie" select
  (`web/src/components/ui/MobileSectionNav.tsx:21-32`).
- `/manipulation`: the section titles "📰 Nieuws", "💥 Market events", "⚡ Price jump" and
  "⏳ Idle" (`web/src/features/manipulation/ManipulationPage.tsx:20-30`).
- `/bar`: "🍺 Bar — Bestellen" (`web/src/features/bar/BarPage.tsx:24`) and
  "💶 Financieel overzicht" (`web/src/features/bar/FinancialPanel.tsx:23`).
- Buttons: "💾 Opslaan instellingen" (`web/src/features/settings/GlobalSection.tsx:124`),
  "💾 Opslaan schakelaars" and "💾 Opslaan coëfficiënten"
  (`web/src/features/settings/DemandSection.tsx:156`, `:210`), "💾 Opslaan idle"
  (`web/src/features/manipulation/IdleSection.tsx:166`), and "⛔ Sluit app"
  (`web/src/features/settings/SystemSection.tsx:75`).

**4 font-drawn symbols:**

- The koers banners "⚠ MARKTCRASH" and "▲ PRIJSBUBBEL"
  (`web/src/features/koers/MarketEventLayer.tsx:17-18`). Many phones and TVs draw ⚠ as a
  colour emoji.
- ▲ / ▼ before every price change on the board tiles and in the price marquee
  (`web/src/lib/format.ts:34`, used by `web/src/features/koers/Tile.tsx:35` and
  `web/src/features/koers/PriceMarquee.tsx:23`).
- ▾ on the Menu button (`web/src/components/ui/NavMenu.tsx:54`).

**No tab icon.** `web/index.html` links no favicon, and `SpaStaticFiles` answers
`/favicon.ico` with a 404 (`app/main.py:106-111`). Every browser tab shows the browser's
blank default.

Nothing else on screen has emoji: not the server's texts, the analytics pages or login, and
not v1's drink names or news (`tests/fixtures/v1/`, checked). The (i) on B-01's info buttons is
the letter `i` (`web/src/components/ui/InfoButton.tsx:85`), not an emoji.

## Decisions

Settled at the spec interview (2026-10-24). Each was put to the owner one at a time with a
recommendation. The owner chose the recommendation for all of them except SD3 and SD7, where
they chose an alternative. The planner must not reopen any of them.

- **SD1 — The build draws the icons in code.** Each icon is a pixel grid written as text in
  the repository (one string per row, one character per pixel: `#` on, `.` off) and drawn as
  an inline SVG. Nobody hand-draws PNGs. No icon pack, no download, no new dependency: the
  icons ship in the bundle like everything else (ADR 0006).
- **SD2 — One colour, the colour of the surrounding text.** An "on" pixel is `currentColor`.
  An icon in a heading is the heading's colour, a button's icon is the button's text colour,
  and a banner's icon is the banner's colour. So icons follow every preset and the custom
  theme, and re-colour live when the theme changes. No new theme token: ADR 0005's token set
  (24 tokens, Phase 6 SD28) stays as it is. The favicon is the one exception (SD8).
- **SD3 — Two grid sizes: 16×16 for headings and banners, 8×8 for small inline spots.**
  (Owner's choice over "16×16 everywhere".) An 8×8 icon is drawn as its own grid, never a
  scaled-down 16×16.
- **SD4 — Placement.** This table is the source of truth:

  | Spot | Today | Becomes |
  |---|---|---|
  | 8 `/settings` section headings and sidebar links | 🧹 ⚙️ 🎨 🖼️ 🥤 🔒 📈 🔑 | 16×16 icon + name |
  | The "Sectie" select on a narrow screen | the same emoji | name only: a native `<option>` holds text only |
  | 4 `/manipulation` section titles | 📰 💥 ⚡ ⏳ | 16×16 icon + name |
  | 2 `/bar` headings | 🍺 💶 | 16×16 icon + name |
  | Koers crash banner | ⚠ MARKTCRASH | 16×16 icon + "MARKTCRASH" |
  | Koers bubble banner | ▲ PRIJSBUBBEL | 16×16 icon + "PRIJSBUBBEL" |
  | Koers correction banner | Terug naar start | unchanged, no icon |
  | 4 "Opslaan …" buttons | 💾 | name only, no icon |
  | "Sluit app" | ⛔ | 8×8 icon + name |
  | Price change on tiles and marquee | ▲ / ▼ | 8×8 rise / fall icon + amount |
  | Menu button | ▾ | "Menu" + 8×8 icon |

  The "Borrel" section has no emoji today and gets no icon. The rest of each name stays
  exactly as it is: "🧹 Systeemacties" becomes "Systeemacties", "🍺 Bar — Bestellen" becomes
  "Bar — Bestellen". A price change of zero stays "—".
- **SD5 — Icons scale with their text.** An icon is 1em tall, as tall as the text beside it,
  at every screen size, including the `clamp()`-sized board. Edges are crisp, never blurred
  or anti-aliased. At in-between sizes some pixel columns come out one screen pixel wider than
  others. That's accepted.
- **SD6 — Text people type keeps its emoji.** News messages, drink names, key labels and run
  names are stored and shown exactly as typed. No new validation. This item covers the app's
  own text only.
- **SD7 — The logo stays; the app gains a favicon.** (Owner's choice over "neither".) The
  default logo (`web/src/assets/logo.png`) and the logo upload slot (Phase 6 SD29) are
  unchanged.
- **SD8 — The favicon is fixed and two-coloured.** It's the Bar heading's beer glass, filled
  with the default preset's `--accent` (`#60a5fa`, preset `blauw`, `app/runtime/theme.py:170-180`),
  with a one-pixel outline in that preset's `--bg` (`#070b16`) so it shows on both light and
  dark tab bars. Every other pixel is transparent. It doesn't follow the theme: it's a static
  file from the build, served from the app's own origin. Its grid is its own 16×16 drawing
  (the glass plus its outline), kept next to the other grids.
- **SD9 — The owner approves the look before any icon reaches a page.** The first task draws
  all 21 grids (SD10) and adds a script that writes a contact sheet: one HTML file, not part
  of the app and not in `web/dist`. It shows every icon at 1×, 2× and 4×, on each of the five
  presets (`oudgeld`, `blauw`, `groen`, `paars`, `rood`), beside the emoji or symbol it
  replaces. The favicon is shown on a light and a dark background. **The build then stops** (a
  hard stop). The owner either says "go" or lists icons to redraw. Wiring starts only after
  the go. The script stays, so a later redraw can be re-checked the same way.
- **SD10 — The motifs.** Each one shows what its emoji showed. The owner may change any of
  them at SD9's stop.

  | Size | Spot | Motif |
  |---|---|---|
  | 16×16 | Systeemacties | broom |
  | 16×16 | Globale instellingen | gear |
  | 16×16 | Kleurenschema | paint palette |
  | 16×16 | Afbeeldingen | framed picture: mountain and sun |
  | 16×16 | Drankjes beheren | cup with a straw |
  | 16×16 | Min/Max/Startprijs | padlock |
  | 16×16 | Vraag/Aanbod | rising line chart |
  | 16×16 | Toegangssleutels | key |
  | 16×16 | Nieuws | folded newspaper |
  | 16×16 | Market events | explosion burst |
  | 16×16 | Price jump | lightning bolt |
  | 16×16 | Idle | hourglass |
  | 16×16 | Bar — Bestellen | beer glass with foam |
  | 16×16 | Financieel overzicht | banknote |
  | 16×16 | Crash banner | warning triangle with "!" |
  | 16×16 | Bubble banner | up arrow |
  | 8×8 | Sluit app | stop sign (octagon) |
  | 8×8 | Price rise | up triangle |
  | 8×8 | Price fall | down triangle |
  | 8×8 | Menu | down chevron |
  | 16×16 | Favicon | the beer glass, with outline (SD8) |

  So there are 21 grids: 16 at 16×16, 4 at 8×8, and the favicon.
- **SD11 — Accessible names don't change in meaning.** An icon next to a word is decorative
  (`aria-hidden`). The heading, link, button or banner keeps the plain name as its accessible
  name ("Systeemacties", "Sluit app", "Menu", "MARKTCRASH"). The rise and fall icons stand in
  for a word, so they carry one: "stijgt" and "daalt".
- **SD12 — A test keeps emoji out.** It fails on any emoji (Unicode `Extended_Pictographic`),
  any variation selector U+FE0F, or any of ▲ ▼ ▾ ⚠ (U+25B2, U+25BC, U+25BE, U+26A0) in a
  file under `web/src/`, `web/e2e/` or in `web/index.html`. That includes tests and comments,
  so a docblock that quotes an old heading is updated too. `app/runtime/config.py:29` quotes
  v1's button text and stays as it is; the server's code is not scanned.
- **SD13 — Older specs get a note, not a rewrite.** They stay as the record, like B-01's note
  on Phase 6 SD8. The notes go on Phase 4 SD21 (the banner texts), Phase 5 SD18 (the bar
  headings), Phase 6 SD20, SD25, SD26 and SD30 (the section names and "⛔ Sluit app"), and
  B-01 SD6 ("the headings keep their emoji"). `docs/design/` is not changed.

## In scope

- **Web:**
  - the 21 grids and one component that draws a grid as an inline SVG: `viewBox` the grid's
    size, `fill="currentColor"`, `shape-rendering="crispEdges"`, 1em tall (SD1, SD2, SD5);
  - the icons placed per SD4: the settings headings and sidebar links (`SettingsSection` gains
    an icon next to its plain-text `label`, and the select keeps using the label), the
    manipulation section titles, the two bar headings, the two koers banners, "Sluit app", the
    tile and marquee price change (`deltaText` stops returning the symbol; the sign becomes an
    icon), and the Menu button;
  - the emoji removed from the four "Opslaan …" buttons;
  - the favicon file(s) and the `<link rel="icon">` in `web/index.html`, served from the root
    by the existing `SpaStaticFiles` (SD8);
  - every unit test, component test and e2e selector that names an old heading, button or
    banner (`SettingsPage.test.tsx`, `ManipulationPage.test.tsx`, `BarPage.test.tsx`,
    `format.test.ts`, `MarketEventLayer.test.tsx`, `web/e2e/admin.spec.ts`,
    `web/e2e/analytics.spec.ts`, `web/e2e/board.spec.ts`, …), and docblocks that quote them.
- **Tools:** the contact-sheet script (SD9). It writes outside `web/dist`, to a gitignored
  path.
- **Tests:** SD12's emoji scan; the grid check (AC1, AC2).
- **Documents:** SD13's notes, and B-02's backlog status.

## Out of scope

- Redrawing or replacing the logo, or changing the logo upload slot (SD7).
- A theme-following favicon, a favicon route on the server, or an app manifest / home-screen
  icon (SD8).
- Colour icons, or icons in more than one colour (SD2); new theme tokens (ADR 0005).
- Icons anywhere SD4 doesn't list: the Borrel section, the "Opslaan …" buttons, the
  correction banner, the analytics pages, login, the nav menu's entries, form fields, the
  (i) buttons, the theme editor.
- An icon inside the "Sectie" select (SD4).
- Refusing or stripping emoji from news, drink names, key labels or run names (SD6).
- Changing any wording besides dropping the emoji (B-01 owns the setting names). The English
  section titles "Market events" and "Price jump" stay.
- Pixel-diff screenshot tests (rejected in `docs/design/frontend-architecture.md:217`).
- An icon font, sprite sheet download, or any third-party icon set or dependency (SD1).
- Whole-pixel snapping of icon sizes (SD5).
- The server, the database, the API, the engine. `exchange/` is untouched.

## Acceptance criteria

**The grids — SD1, SD3, SD10**

- **AC1.** The system shall hold exactly the 21 grids of SD10: 16 of 16×16, 4 of 8×8, and the
  favicon of 16×16. Every grid shall have exactly as many rows as columns, each row the grid's
  width, made only of `#` and `.`, with at least one `#`.
- **AC2.** Every 8×8 grid shall be its own drawing. No code shall derive an 8×8 icon by
  scaling a 16×16 one.
- **AC3.** When the contact-sheet script runs, it shall write one HTML file outside
  `web/dist`. The file shall show every grid at 1×, 2× and 4× on each of the five presets
  beside the emoji or symbol it replaces, and the favicon on a light and a dark background.
  It shall not be part of the built app.

**Drawing — SD2, SD5**

- **AC4.** Each icon shall render as an inline SVG with a `viewBox` of its grid size,
  `fill="currentColor"` and `shape-rendering="crispEdges"`, 1em tall. It shall request no
  file and no font.
- **AC5.** When an icon is shown, its rendered height shall equal the computed font size of
  its container, to within 1 px, on the settings heading, the bar heading, the crash banner
  at 1920×1080, and the tile's price change at 360 px wide.
- **AC6.** When the theme changes (another preset, or a custom `--text` saved), every icon on
  an open page shall take the new colour without a reload (ADR 0005).

**Placement — SD4, SD11**

- **AC7.** Each spot in SD4's table shall show exactly what its "Becomes" column says: the
  named icon before the name, or after it for the Menu button. The "Sectie" select, the four
  "Opslaan …" buttons, the Borrel section and the correction banner shall show text only.
- **AC8.** Each heading, sidebar link, button and banner in SD4 shall have the plain name as
  its accessible name, e.g. heading "Systeemacties", button "Sluit app", button "Menu",
  status "MARKTCRASH". The icon next to the name shall be `aria-hidden`.
- **AC9.** When a price rises, the tile and the marquee shall show the rise icon, with
  accessible name "stijgt", before the amount and percentage. When it falls, they shall show
  the fall icon ("daalt"). When it doesn't change, they shall show "—", as today. The amount
  and percentage text shall be unchanged.
- **AC10.** On every route (`/`, `/bar`, `/settings`, `/manipulation`, `/analytics`,
  `/login`), with any built-in preset, the rendered page shall contain no emoji or symbol from
  SD12's set, except in text a person typed (SD6).

**Typed text — SD6**

- **AC11.** When a news message or drink name containing an emoji is saved, the system shall
  store and show it unchanged.

**Favicon — SD7, SD8**

- **AC12.** `web/index.html` shall link a favicon. `GET` on that path shall return 200 with an
  image content type from the app's own origin, with the dev server running and from the
  built app. The image shall be the favicon grid in `#60a5fa` with a `#070b16` outline,
  transparent elsewhere, and shall not change with the theme.
- **AC13.** The logo and the logo upload slot shall behave exactly as before.

**Guards — SD9, SD12, SD13**

- **AC14.** When any file under `web/src/` or `web/e2e/`, or `web/index.html`, contains an
  `Extended_Pictographic` code point, U+FE0F, or one of ▲ ▼ ▾ ⚠, a test in the gate shall fail
  and name the file and line.
- **AC15.** No icon shall be placed on a page before the owner has approved the contact sheet
  (SD9). The approval shall be recorded in the plan.
- **AC16.** The specs listed in SD13 shall each carry a "superseded in part by B-02" note.
  `docs/design/` shall be unchanged.
- **AC17.** `exchange/`, the API types and the database migrations shall be unchanged by this
  item.

## Verification

- **Contact-sheet stop (SD9):** the first task ends with the sheet written and the build
  stopped. The owner opens it, approves or lists redraws, and the plan records the go.
- **Vitest / component tests:**
  - every grid square, sized, `#`/`.` only, non-empty; 21 of them, 16 + 4 + 1 (AC1);
  - the icon component's SVG attributes and `aria-hidden` (AC4, AC8);
  - each spot of SD4 renders its icon or none, with the plain accessible name (AC7, AC8);
  - `deltaText`'s replacement: rise, fall and zero, with "stijgt"/"daalt" and the unchanged
    amount text (AC9);
  - the old label tests, rewritten to the plain names, still pass on the same behaviour.
- **The emoji scan (AC14):** shown to fail by temporarily adding one ⚠ to a component, then
  passing again once it's removed.
- **Playwright (in the gate):**
  - icon height equals font size ±1 px on `/settings`, `/bar`, the crash banner at
    1920×1080, and a tile at 360 px (AC5);
  - switch the preset from `blauw` to `oudgeld` on `/settings` and check that a heading icon's
    computed colour follows without a reload (AC6);
  - every route scanned for SD12's characters in its rendered text (AC10);
  - `GET` on the favicon path returns 200 with an image type (AC12);
  - the existing admin, bar, board and offline specs pass with the new selectors.
- **API (pytest):** a news message with "🎉" saved and read back unchanged (AC11); this pins
  behaviour that exists today.
- **The gate:** `./scripts/check.sh` green. `exchange/` is untouched, so
  `golden_linux.sh` isn't needed. If a diff touches `exchange/` anyway, that's a defect in
  the diff.
- **Manual (exit check):** on the admin laptop, an Android phone and an iPhone, open
  `/settings`, `/manipulation`, `/bar` and the board with a crash running. Each icon is the
  same pixel drawing on all three devices, sharp, in the text's colour. The BorrelBeurs tab
  shows the beer-glass favicon.

## Exit condition

No page draws an emoji or font symbol of its own any more. Every spot in SD4 shows the
owner-approved BorrelBeurs pixel icon in the theme's text colour, the same on every device,
and a test fails if an emoji comes back.
