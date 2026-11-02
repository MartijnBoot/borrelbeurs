# Spec: B-12 — Settings on separate screens per kind of work

Status: Approved · Depends on: Phase 6 (SD25 the one settings page, SD27 the form rules), B-01 (the
setting names and their (i)), B-02 (the section icons), B-03 (SD5 the noise fields), B-04
(Profielen), B-05 (SD16 the Wallets section), B-06 (SD1–SD3 the two payment settings), B-07 (SD3 the
Prijsstap confirm), B-10 (AC10 "QR-code op het scherm") · Fixes: no open defect · Amends:
`docs/design/frontend-architecture.md` (the route line and the feature list), Phase 6 SD25, B-03
SD5, B-06's placement of "Wallet verplicht" and "Rood staan tot" · Backlog: [B-12](../backlog.md)

Line references are to `main` at `e1da324`.

## Problem

`/settings` is one long page. What steers a night sits mixed in with what runs the system, and a
person who is not the owner cannot tell which is which.

- **One page, 11 sections, in v1's order.** `SettingsPage` lists Borrel, Systeemacties, Globale
  instellingen, Profielen, Kleurenschema, Afbeeldingen, Drankjes beheren, Min/Max/Startprijs,
  Vraag/Aanbod, Toegangssleutels and Wallets in that order
  (`web/src/app/pages/SettingsPage.tsx:24-52`; Phase 6 SD25). Finding one means scrolling or the
  section select (`web/src/components/ui/MobileSectionNav.tsx:20-42`).
- **Settings that belong together sit apart.** "Wallet verplicht" and "Rood staan tot" are in
  Globale instellingen (`web/src/features/settings/GlobalSection.tsx:206-223`), while the other
  wallet settings are in Wallets (`web/src/features/wallets/WalletsSection.tsx:189-322`).
  Prijsstap is in Globale instellingen (`GlobalSection.tsx:44-55`), while the bounds it constrains
  (B-07) are in Min/Max/Startprijs. Vraag/Aanbod's two switches and its per-drink table are one
  section (`DemandSection.tsx`), though one is engine tuning and the other is a per-drink value.
- **Globale instellingen is 18 fields in one grid** (`GlobalSection.tsx:192-224`), with no groups,
  and the five noise fields are always shown, switch on or off (B-03 SD5).
- **One role opens all of it.** `ROLE_ROUTES["admin"]` lists `/settings` as one route
  (`app/api/security.py:125-130`), so nothing on the server can tell the game-setup screens from
  the engine's. B-13 (an organiser role) needs exactly that split.
- **The menu and the home tile describe the old page.** The header menu lists `/settings` as
  "Instellingen" (`web/src/components/ui/NavMenu.tsx:17`) and the home tile reads "Globale
  instellingen, grenzen, vraag/aanbod, drankjes, afsluiten." (`web/src/features/home/HomePage.tsx:31-34`).
- **Two tick boxes remain.** "QR-code op het scherm" (`WalletsSection.tsx:208-216`) and Idle's
  per-drink lists on `/manipulation` (`web/src/features/manipulation/IdleSection.tsx:151-160`)
  are `<input type="checkbox">`; everything else on/off already uses `Switch`
  (`web/src/components/ui/Switch.tsx`).

## Decisions

These were settled at the spec interview on 2026-11-02. Q1–Q11 were put to the owner one at a time,
each with a recommendation; the owner chose the recommendation every time (Q3, with one change:
the Vraag/Aanbod switches go to Beheer and its table to Spelopzet). SD11–SD17 were not asked: they
are the spec writer's defaults, marked so for the owner to object to at review. The planner must
not reopen any of them.

**The screens**

- **SD1 — Each screen has its own address (Q1).** `/settings` becomes the landing page (SD2) and
  three screens are added: `/settings/spel` (Spelopzet), `/settings/wallets` (Mensen en wallets)
  and `/settings/beheer` (Beheer). All four are in `ROLE_ROUTES["admin"]`, so the server's list
  keeps deciding the menu, `RequireRole` and the reload fallback (`SPA_ROUTES`,
  `app/main.py:112-114`). Other roles' lists do not change. This amends
  `docs/design/frontend-architecture.md:64` ("Routes keep v1's paths"): the six v1 paths stay and
  three are added under `/settings`. The owner approved the amendment at this interview.
- **SD2 — `/settings` is a landing page (Q2).** It shows one tile per screen the session's
  `allowed_routes` contains: the screen's name, one line of what is in it, and a link. It has no
  settings of its own. It shows no sections, so an old `/settings#borrel` link opens the landing
  page and scrolls nowhere (SD14).
- **SD3 — What is on each screen (Q3, Q4).**
  - **Spelopzet** (`/settings/spel`): Borrel, Profielen, Drankjes beheren, Prijzen (SD4),
    Vraag/Aanbod (the a/d/s0/c table, only while Verwachte verkoop meetellen is on; otherwise one
    line, "Vraag/Aanbod staat uit. Zet het aan onder Beheer."), Kleurenschema, Afbeeldingen. The
    line is plain text with no link: an organiser (B-13) cannot open Beheer.
  - **Mensen en wallets** (`/settings/wallets`): Betalen ("Wallet verplicht", "Rood staan tot"),
    then Wallets, unchanged (Aanmeldcode, "QR-code op het scherm", Bewaartermijnen, Totalen, Alle
    wallets).
  - **Beheer** (`/settings/beheer`): Globale instellingen (SD5), Vraag/Aanbod (its two switches,
    "Verwachte verkoop meetellen" and "Evenwicht zetten bij live zetten"), Toegangssleutels,
    Systeemacties.
  - Min/Max/Startprijs stays under Spelopzet. Whether the organiser may change it is B-13's call.
- **SD4 — Prijsstap moves to Spelopzet (Q5).** A "Prijzen" section holds Prijsstap and the
  Min/Max/Startprijs table. Prijsstap keeps everything B-07 gave it: the `ConfirmDialog` listing the
  bounds that move, "Annuleren" sending nothing, and the `bounds_collision` message under the field.
  It is still saved through `PATCH /api/runs/{id}/config` `params.step_quant`.
- **SD5 — Globale instellingen: groups, one form (Q6).** It keeps one form and one "Opslaan
  instellingen", with the groups as headings: **Hoe bestellingen de prijs bewegen** (Beweging per
  bestelling, Drukdrempel, Concurrentie tussen drankjes, Trek naar gemiddelde prijs, Nawerking van
  bestellingen, Geheugen van bestellingen, Ritme stille drankjes), **Willekeurige ruis** (SD6) and
  **Koersbord** (Grafiekgeschiedenis, Kaarsbreedte). It no longer holds Prijsstap or the two
  payment settings. Saving still sends only the changed fields and nothing when clean ("Niets te
  wijzigen"); the conflict prompt "Serverwaarden gewijzigd — overnemen?" stays one prompt.
- **SD6 — The noise fields hide while the switch is off (Q7).** Under the "Willekeurige ruis"
  switch the five fields show only while it is on. Turning it off discards nothing: edits made to
  the hidden fields stay in the form and are sent by the next save. A hidden field that is empty
  or invalid blocks the save, with a message that names the field and says the noise switch must
  be on to fix it. This amends B-03 SD5 ("switching the noise off disables none of them").
- **SD7 — Switches (Q8).** Every on/off is a `Switch`; no `<input type="checkbox">` is left in
  `web/src`. The `Switch` changes its layout: the label on the left, the switch at the right end
  of a fixed-width row, the (i) right after the label, so the switches of a screen line up in one
  column. The switch itself keeps its size (2.25 × 1.25 rem). The converted places are "QR-code op
  het scherm" and, on `/manipulation`, the two per-drink lists of Idle, which become a wrapping
  grid of such rows, one per drink. The page `/manipulation` stays as it is otherwise, and "Spel
  mechanica" stays its own menu item.
- **SD8 — Navigation inside a screen (Q9).** A screen keeps `SettingsLayout` and
  `MobileSectionNav` for its own sections: in-page links on a wide screen, one select on a narrow
  one. A screen with a single section shows no section navigation. Every screen shows a
  "← Instellingen" link at the top that goes to the landing page. There is no tab bar across
  screens.
- **SD9 — Unsaved edits are not dropped silently (Q10).** When a screen holds a form whose typed
  values differ from what is stored and the person tries to leave it (the "← Instellingen" link,
  the header menu, a link on the landing, the browser's back button), a `ConfirmDialog` asks
  "Niet-opgeslagen wijzigingen weggooien?" with "Weggooien" and "Blijven". "Blijven" keeps the
  screen and every typed value. A reload or a closed tab gets the browser's own prompt. A clean
  screen leaves without a dialog.
- **SD10 — The landing page shows the run (Q11).** One status line above the tiles, from the same
  current-run source as the Borrel section: "Borrel: <naam> (live)", "Borrel: <naam> (concept)"
  or "Geen actieve borrel". When the run cannot be fetched: "Borrel: onbekend". The tiles work
  in every case.

**Defaults, not asked**

- **SD11 — The menu stays as it is (default).** The header menu lists "Instellingen" once, for
  `/settings`; the three screen addresses are in `allowed_routes` but `NavMenu` does not list
  them. A person reaches a screen through the landing page.
- **SD12 — Names and order (default).** Screen names as in SD3. On Spelopzet: Borrel, Profielen,
  Drankjes beheren, Prijzen, Vraag/Aanbod, Kleurenschema, Afbeeldingen. On Beheer: Globale
  instellingen, Vraag/Aanbod, Toegangssleutels, Systeemacties last (the one that stops the app).
  Each section keeps its B-02 pixel icon; Prijzen takes Min/Max/Startprijs's `padlock`. The
  Betalen section has no icon.
- **SD13 — The API does not change (default).** "Wallet verplicht", "Rood staan tot" and Prijsstap
  move on screen only. `PATCH /api/runs/{id}/config`, `GET`/`PUT /api/admin/wallet-settings` and
  every other endpoint keep their bodies, their roles and their errors. Betalen is its own form
  with its own "Opslaan" and sends only the changed run columns at the top level (never under
  `params`), as `GlobalSection` does today.
- **SD14 — Old links (default).** `/settings#<section>` is not translated. It opens the landing
  page. Bookmarks to `/settings` itself keep working.
- **SD15 — The texts (default).** Tiles: Spelopzet "Borrel, profielen, drankjes, prijzen,
  vraag/aanbod, kleuren, afbeeldingen."; Mensen en wallets "Betalen, aanmeldcode, bewaartermijnen,
  alle wallets."; Beheer "Globale instellingen, vraag/aanbod, toegangssleutels, systeemacties."
  The home tile's line becomes "Spelopzet, wallets en beheer." The setting names and their
  explanations (B-01) do not change.
- **SD16 — The demand table follows the switch live (default).** Turning "Verwachte verkoop
  meetellen" on or off in Beheer reaches an open Spelopzet through the `config` message, without a
  reload. If it goes off while the table has unsaved edits, the table goes with them; unlike the
  noise fields (SD6) they are not kept, and SD9 does not count them.
- **SD17 — Only admin opens the new addresses (default).** `ROLE_ROUTES` gives the three addresses
  to `admin` only. Nothing is added for `bar`, `kassa` or `display`. Which of them a future
  organiser or the kassa key may open is B-13's.

**For the planner (a constraint, not a decision to reopen)**

- **SD18 — The router.** The app mounts `BrowserRouter` (`web/src/main.tsx:17`), which does not
  support `useBlocker`. SD9 needs a way to stop a navigation that covers links, the menu and the
  back button. The plan shall say how (a data router, or something smaller) and what it costs.
  A new dependency is a hard stop.

## In scope

- `app/api/security.py`: the three addresses in `ROLE_ROUTES["admin"]` (SD1); `SPA_ROUTES`
  follows from it.
- The landing page, the three screens and their routes in `web/src/app/routes.tsx`; the
  composition in `web/src/app/pages/` (SD1–SD3, SD12).
- `GlobalSection` split into the Beheer form (SD5, SD6) and Prijsstap into Prijzen (SD4); the
  Betalen section (SD13); `DemandSection` split into the two switches and the table (SD3, SD16).
- `Switch`'s new layout (SD7); the checkbox in `WalletsSection` and the two lists in `IdleSection`
  become switches.
- The "← Instellingen" link, the single-section rule of `SettingsLayout` (SD8), the leave guard
  (SD9, SD18), the status line (SD10), `NavMenu` (SD11), the home tile (SD15).
- `docs/design/frontend-architecture.md` (the route line at `:64`, the feature list at `:44`),
  a note on Phase 6 SD25 and B-03 SD5 in their specs, and B-06's placement of the two wallet
  settings. The owner approved the design amendment at this interview.
- Tests: pytest (role table, SPA routes, auth `allowed_routes`), vitest, and the existing e2e specs
  moved to the new addresses.

## Out of scope

- A new role, a change to who may call what, or any server check beyond the route list — B-13.
- A new setting, a renamed setting, a changed explanation or default, or a changed range.
- The pricing engine (`exchange/`), the golden fixtures and anything that feeds them.
- A migration, a new endpoint, a changed request or response body.
- Moving Spel mechanica's other sections, or the page `/manipulation` itself.
- A tab bar or submenu across screens, translating old `#section` links, remembering the last
  screen visited.
- Per-group save buttons in Globale instellingen.
- A new narrow-screen pattern: the existing select stays.
- Reordering what is inside a section (Wallets' subsections, the Drankjes table, the Profielen list).
- A new dependency.

## Acceptance criteria

**Addresses and the menu — SD1, SD11, SD17**

- **AC1.** When an admin key logs in, `allowed_routes` shall contain `/settings`,
  `/settings/spel`, `/settings/wallets` and `/settings/beheer`; for `display`, `bar` and `kassa`
  it shall be exactly what it was.
- **AC2.** When any of the four addresses is requested directly (a reload) and no file matches,
  the server shall serve `index.html`; any other path under `/settings/` shall stay a plain 404.
- **AC3.** When a display, bar or kassa session opens `/settings/beheer`, `/settings/spel` or
  `/settings/wallets`, the page shall show "Geen toegang" and the address shall not change.
- **AC4.** When the header menu is open, it shall list "Instellingen" once, for `/settings`, and
  none of the three screen addresses.

**The landing page — SD2, SD10, SD14, SD15**

- **AC5.** When `/settings` is open, the page shall show one tile for each of the three screens
  the session's `allowed_routes` contains, each with the screen's name, its line from SD15 and a
  link to its address, and shall show no settings.
- **AC6.** When the current run is live, a draft, absent or cannot be fetched, the status line
  shall read "Borrel: <naam> (live)", "Borrel: <naam> (concept)", "Geen actieve borrel" or
  "Borrel: onbekend"; in every case the tiles shall work.
- **AC7.** When `/settings#borrel` is opened, the system shall show the landing page and scroll
  nowhere.

**What is where — SD3, SD4, SD5, SD12, SD13**

- **AC8.** When `/settings/spel` is open, it shall show the sections Borrel, Profielen, Drankjes
  beheren, Prijzen, Vraag/Aanbod, Kleurenschema, Afbeeldingen, in that order, each with the icon
  it has today (Prijzen: `padlock`), and nothing else.
- **AC9.** When `/settings/wallets` is open, it shall show Betalen and then Wallets, and nothing
  else. When `/settings/beheer` is open, it shall show Globale instellingen, Vraag/Aanbod,
  Toegangssleutels and Systeemacties, in that order, and nothing else.
- **AC10.** The set of settings reachable across the three screens shall equal the set reachable
  on the old page: every field and control of the 11 old sections shall appear on exactly one
  screen, with the same label. *(A test lists them from the old `SettingsPage` test and
  `explanations.json`.)*
- **AC11.** The setting names and (i) explanations shall be byte-identical to `main`
  (`web/src/features/settings/explanations.json` unchanged), and each (i) shall still sit on the
  same setting.

**Globale instellingen — SD5, SD6**

- **AC12.** When Beheer is open, Globale instellingen shall show three groups, "Hoe bestellingen
  de prijs bewegen" with its 7 fields, "Willekeurige ruis" and "Koersbord" with its 2 fields, one
  "Opslaan instellingen", and neither Prijsstap nor "Wallet verplicht" nor "Rood staan tot".
- **AC13.** When the form is saved, it shall send only the changed fields, `params` for the
  engine values and `candle_interval_s` at the top level, exactly as today; when nothing changed
  it shall send no request and show "Niets te wijzigen"; when the server's values change while
  the form is dirty it shall keep the input and offer "Overnemen" once.
- **AC14.** While "Willekeurige ruis" is off, the five noise fields shall not be shown; while on,
  they shall be. When the switch is turned off after a field was edited, the next save shall
  still send that edit. When a hidden field is empty or invalid, the save shall send nothing and
  the message shall name the field and say the switch must be on.

**Prijzen, Betalen and Vraag/Aanbod — SD4, SD13, SD16**

- **AC15.** When a new Prijsstap would move a bound, saving shall open the confirm that lists the
  moves; "Annuleren" shall send nothing and keep the input; "Opslaan" shall send. A
  `bounds_collision` shall show its message under Prijsstap. *(B-07's AC for this, on its new
  screen.)*
- **AC16.** When Betalen is saved, it shall send only the changed run columns
  (`wallet_required`, `credit_limit_cents`) at the top level of `PATCH /api/runs/{id}/config`,
  never under `params`; nothing changed sends no request; a 422 shows under the field it names.
- **AC17.** When Beheer's Vraag/Aanbod is saved, it shall send only the switch that changed, as
  today. When Spelopzet's Vraag/Aanbod is open with "Verwachte verkoop meetellen" on, it shall
  show the a/d/s0/c table with today's behaviour (a save with nothing edited sends nothing; an
  empty cell blocks the save, D-03's gate); with it off, it shall show only "Vraag/Aanbod staat
  uit. Zet het aan onder Beheer." and no link.
- **AC18.** When "Verwachte verkoop meetellen" is changed in Beheer while Spelopzet is open in
  another session, Spelopzet shall show or hide the table without a reload. If the table goes
  while it holds unsaved edits, those edits shall be gone and leaving shall not warn for them.

**Switches — SD7**

- **AC19.** `web/src` shall contain no `<input type="checkbox">`; every on/off control shall have
  `role="switch"` and `aria-checked`, be reachable and toggled by the keyboard (Space, Enter),
  and be named by its label, with its (i) outside that name.
- **AC20.** A switch shall show its label on the left and its track at the right end of a
  fixed-width row, with the (i) after the label; the tracks of the switches in one section shall
  share the same x position at 1280 px. Idle's per-drink lists shall be one such row per drink.
- **AC21.** When a drink's switch in Idle's "Verlagen" or "Verhogen" list is toggled, the saved
  `idle_targets` / `idle_rise_targets` shall be exactly what the checkbox produced; a save with
  nothing changed shall send nothing. When "QR-code op het scherm" is toggled, it shall save at
  once and ask no confirmation (B-10 AC10).

**Navigation and leaving — SD8, SD9, SD18**

- **AC22.** Each screen shall show "← Instellingen" at the top, going to `/settings`. A screen
  with more than one section shall show `MobileSectionNav` (links on a wide screen, the select at
  800 px or less); Mensen en wallets has two sections and Spelopzet and Beheer more.
- **AC23.** When a form on the screen has typed values that differ from what is stored and the
  person leaves by the "← Instellingen" link, the header menu or the browser's back button, the
  system shall ask "Niet-opgeslagen wijzigingen weggooien?". "Blijven" shall keep the screen and
  every typed value; "Weggooien" shall leave.
- **AC24.** When the screen has no such form, or its forms were saved, the system shall leave
  without a dialog. When a reload or tab close is attempted with unsaved edits, the browser's
  prompt shall be requested.
- **AC25.** At 375 px width, the landing's tiles shall stack in one column and no settings
  screen shall scroll sideways, except the a/d/s0/c table inside its own box (B-01 AC6).

**Boundaries — SD13**

- **AC26.** The diff shall touch nothing under `exchange/`, `tests/engine/golden/fixtures/` or
  `db/migrations/versions/`, shall add no dependency (`web/package.json`, `pyproject.toml`), and
  shall change no endpoint, request body or response model: the API-types drift step shall pass
  with no change to the generated types.
- **AC27.** `docs/design/frontend-architecture.md`, the specs of Phase 6 (SD25), B-03 (SD5) and B-06
  (the two settings' placement), the home tile's text and the web e2e specs that open `/settings`
  shall carry the changes named under "In scope".

## Verification

- **Python (pytest):** `tests/unit/test_security.py` (the admin list, the others unchanged, AC1),
  `tests/api/test_auth.py` (`allowed_routes` per role, AC1) and `tests/api/test_static.py`
  (`SPA_ROUTES`, the reload of the four addresses, `/settings/x` a 404, AC2).
- **Web (vitest):** the route table and `RequireRole` per role (AC1, AC3); `NavMenu` (AC4); the
  landing: tiles per role, the four status lines, `#borrel` (AC5–AC7); each screen's sections in
  order, icons and absences (AC8, AC9); a coverage test that every control of the old page is on
  exactly one screen and that `explanations.json` is unchanged (AC10, AC11); `GlobalSection`
  groups, save body, clean save, conflict, the hidden noise fields and the blocked hidden fields
  (AC12–AC14); Prijsstap's confirm (AC15); Betalen's body and 422 (AC16); both Vraag/Aanbod parts
  and the live show/hide (AC17, AC18); a source scan for `type="checkbox"` and a `Switch` test
  for role, keyboard, name and layout (AC19, AC20); Idle's lists and the save body (AC21); the
  section navigation and back link (AC22); the leave guard for each way out, with a clean and a
  dirty screen (AC23, AC24).
- **e2e (Playwright), with the existing settings specs moved to the new addresses:**
  1. Log in as admin, open `/settings`: three tiles, the status line, and "Instellingen" once in
     the menu (AC4–AC6).
  2. Beheer: change Drukdrempel, tap "← Instellingen": the dialog appears; "Blijven" keeps the
     value; save; leave without a dialog (AC23, AC24).
  3. Beheer: switch Willekeurige ruis off and on and watch the five fields go and come (AC14).
  4. Turn "Verwachte verkoop meetellen" off in Beheer: Spelopzet shows the note. Turn it on: the
     table is there, and saving without an edit sends nothing (AC17).
  5. Spelopzet: set a Prijsstap that moves a bound; the confirm lists it; "Opslaan" stores it
     (AC15).
  6. Mensen en wallets: toggle "Wallet verplicht" and set "Rood staan tot", save, and see them in
     the bar (AC16).
  7. `/manipulation`: toggle a drink in Idle's list and save (AC21).
  8. As a display key open `/settings/beheer`: "Geen toegang" (AC3). At 375 px the tiles stack
     and no screen scrolls sideways (AC25).
- **Visual check (the owner's):** screenshots of the landing and the three screens at 1280 px
  and 375 px, and of a section of switches, to judge that the pages carry less clutter (AC20).
- **The gate:** `./scripts/check.sh`, 13/13, output pasted. `git diff --stat main` shows nothing
  under `exchange/`, so `golden_linux.sh` and `engine-guardian` are not required (AC26).
- **Manual exit check (the owner's):** on a phone, open `/settings`, set a Prijsstap and a
  "Rood staan tot" and change the noise, with a half-typed field left while tapping back.

## Exit condition

The owner's partner can open Instellingen, find the screen for the job (the night, the wallets or
the system), change a setting there and never lose a half-typed value by leaving, and every setting
of the old page is on exactly one of the new screens.
