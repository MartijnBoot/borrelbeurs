# Spec: B-09 — Download the sign-up QR code

Status: Approved · Depends on: B-05 (SD6 the sign-up code and the poster link `/speler?code=<code>`,
SD14 `uqr`, SD17 the venue's own database, PD20 the link shown as text), Phase 6 (the settings
page and `ConfirmDialog`), Phase 8 (SD1 the venue at `http://192.168.8.10/`) · Fixes: no open
defect · Amends: B-05 PD20 ("Not built"), `docs/runbooks/venue.md` · Backlog:
[B-09](../backlog.md)

Line references are to `main` at `4c72851`.

## Problem

Players make a wallet at `/speler?code=<code>`, and the poster where they used to get vouchers
is where they will now find the sign-up QR code. The app shows the organizer the link and
nothing more, so the QR code on the poster comes from some outside tool, retyped by hand.

- **Admin sees the link as text only.** Under Instellingen → Wallets, the Aanmeldcode
  subsection shows `<origin>/speler?code=<code>` in a `<p>` when a code is saved, and "Aanmelden
  is gesloten." when none is (`web/src/features/wallets/WalletsSection.tsx:150-154`). The link is
  built from `window.location.origin` and the URL-encoded saved code (`:45-47`). B-05's plan
  left the QR code to "any QR maker" (PD20, `docs/plans/phase-b-05-player-wallets.md:65`, and
  out of scope at `:803`).
- **The app can already draw a QR code.** `QrCode.tsx` encodes a string with `uqr` at error
  correction `M` and a 2-module border, and draws one SVG `<rect>` per dark module, black on
  white (`web/src/features/player/QrCode.tsx:12-29`, `PlayerPage.module.css:111-118`). Only the
  player's wallet code uses it (`WalletView.tsx:44`). `jsqr`, also a dependency, decodes QR
  codes (`web/src/components/scanner/decodeQr.ts`).
- **The player page fills the code in from the link.** `SignupForm.tsx:43` reads `?code=`.
- **Changing or clearing the code breaks every printed QR code, with no warning.** "Opslaan" and
  "Wissen" save at once (`WalletsSection.tsx:96-102`, `:133-139`). The server stores the code
  trimmed (`app/api/wallets_admin.py:69-76`) and compares it trimmed and case-insensitively
  (`app/runtime/wallets.py:61`), so `borrel` and `BORREL` are the same code, and a printed QR code
  stays valid only while the saved code is the same under that comparison.
- **The address depends on where admin is open.** The venue is its own deployment with its own
  database (B-05 SD17), so a QR code made on Render signs players up on Render, and one made at
  the venue only works on the venue's network. At the venue the app runs on the laptop itself
  (`docs/runbooks/venue.md:3-34`), where admin may be opened as `http://localhost/`; a QR code of
  that address sends every phone to itself.

## Decisions

These were settled at the spec interview on 2026-10-29. Q1–Q7 were put to the owner one at a
time, each with a recommendation, and the owner chose the recommendation every time. SD8–SD10
were not asked: they are the spec writer's defaults, marked so for the owner to object to at
review. The planner must not reopen any of them.

**What the QR code says**

- **SD1 — The address admin has open (Q1).** The QR code encodes exactly the link the page
  already shows: `window.location.origin` + `/speler?code=` + the URL-encoded saved code, from
  the one function that builds the shown link. Nothing new is stored, and there is no "public
  address" setting. Posters for the venue are downloaded from the venue's admin, posters for
  Render from Render's.
- **SD2 — Never from a loopback address (Q5).** When `window.location.hostname` is `localhost`,
  ends in `.localhost`, is an IPv4 address in `127.0.0.0/8`, or is `[::1]`, both download buttons
  are disabled and the hint "Open deze pagina via het netwerkadres (bijv. http://192.168.8.10/)
  om de QR-code te downloaden." is shown under them. The preview (SD5) still shows, so the
  organizer sees what is wrong. The app does not know its LAN address; the hint only gives an
  example.
- **SD3 — Error correction `Q` and a 4-module quiet zone (Q3, Q7).** The sign-up QR code is
  encoded at `ecc: 'Q'` (about 25% damage) with `border: 4`, the standard quiet zone, so a
  poster survives beer, tape and a tight crop. The player's wallet code is unchanged (`M`,
  border 2).

**The files**

- **SD4 — PNG and SVG, two buttons (Q2).** "Download PNG" and "Download SVG". Both are made in
  the browser from the same `uqr` modules: the SVG as a standalone file, the PNG drawn on a
  `<canvas>`. No server call, no new dependency (ADR 0006).
  - **PNG:** square, opaque, white background and black modules, each module a whole number
    `k = floor(1024 / n)` of pixels for `n` modules including the quiet zone, so the image is
    `n·k` px square, at most 1024 and more than `1024 − n`. No smoothing.
  - **SVG:** a standalone document (`xmlns`, `viewBox="0 0 n n"`, `shape-rendering="crispEdges"`)
    with a white background rectangle covering the whole quiet zone and one black `<rect>` per
    dark module. No text, no script, no external reference.
  - Neither file contains anything but the QR code: no link text, no logo, no caption (Q3).
- **SD5 — A preview on the page (Q6).** When a code is saved, the Aanmeldcode subsection shows the
  QR code at about 160 CSS px, above the two buttons, so the organizer can scan it with their own
  phone before printing. It draws the same modules the files hold (SD3). With no code saved,
  there is no preview and no buttons; "Aanmelden is gesloten." stays as today.
- **SD6 — Only the saved code.** The link text, the preview and both files always use the code as
  last saved and returned by the server, never what is typed in the field and not yet saved.

**Changing the code**

- **SD7 — Confirm before printed codes break (Q4).** A confirm dialog, the existing
  `ConfirmDialog`, appears before a save only when a code is saved and the save would replace it
  with a different one or clear it:
  - "different" is the server's comparison: trimmed and case-insensitive (SD9);
  - a different code: "Aanmeldcode wijzigen? Geprinte QR-codes met '<oud>' werken dan niet
    meer.", confirm "Wijzigen";
  - clearing, by "Wissen" or by "Opslaan" with a blank field (the server treats blank as
    cleared): "Aanmelden sluiten? Geprinte QR-codes met '<oud>' werken dan niet meer.", confirm
    "Wissen";
  - cancel "Annuleren", which saves nothing and leaves the field as typed;
  - `<oud>` is the saved code.

  No dialog when no code is saved, when the new code equals the saved one under the comparison,
  or for "Wissen" with no code saved.

**Defaults, not asked**

- **SD8 — The filename names the deployment and the code.**
  `aanmelden-<host>-<code>.png` / `.svg`, with `<host>` from `window.location.host` and `<code>` the
  saved code, each character outside `[A-Za-z0-9.-]` replaced by `-`. So a venue file reads
  `aanmelden-192.168.8.10-BORREL.png`, and `Borrel 2026!` gives `Borrel-2026-`.
- **SD9 — The client's comparison is `trim()` plus `toLowerCase()`.** Python's `casefold()`
  (`app/runtime/wallets.py:61`) folds a few characters `toLowerCase()` does not (`ß` → `ss`). The
  only effect is an extra dialog for a code differing in such a character; it never misses one.
  Accepted.
- **SD10 — The labels.** "Download PNG", "Download SVG". The buttons sit with the link, under the
  preview, inside the Aanmeldcode subsection.

## In scope

- `WalletsSection.tsx`: the preview, the two download buttons, the loopback hint, and the confirm
  before a breaking save; its CSS module.
- The QR drawing: whatever change lets the sign-up preview use `Q` and border 4 while the player
  keeps `M` and border 2, and the code that turns modules into a standalone SVG and a PNG blob.
  Where that code lives is the plan's choice; the player's code must not change behaviour.
- The download itself, by a blob URL and an `<a download>`: it must work over plain HTTP (an
  insecure context), as the venue serves.
- `docs/runbooks/venue.md`: a line in "Before" to download the sign-up QR code from the venue's
  admin opened at `http://192.168.8.10/`, not from Render and not from `localhost`.
- An "Amended by B-09" note on B-05 PD20 in `docs/plans/phase-b-05-player-wallets.md`.
- Tests: web unit and e2e over an insecure, non-loopback origin.

## Out of scope

- Any server change: no route, no setting, no migration. `app/`, `db/` and `exchange/` are
  untouched.
- A new dependency: `uqr` draws the code, `jsqr` is only used by tests (both already approved in
  B-05).
- A poster, print page, caption, logo, colours, or text in the image (backlog "Not this").
- A "public address" setting or any way to make a QR code for another deployment than the one
  open (SD1).
- Knowing or showing the venue's LAN address.
- Other sizes, resolutions, PDF, or a size picker.
- Remembering which codes were printed, or keeping an old code valid after a change.
- A QR code on the koers screen: that is B-10.
- Any QR code other than sign-up.
- Changing the player's wallet QR code.
- The sign-up flow itself, the code's rules (40 characters, trimmed, case-insensitive), or the
  "Aanmeldcode" texts that exist today.
- The pricing engine (`exchange/`), the golden fixtures and anything that feeds them.

## Acceptance criteria

**The preview and the buttons — SD5, SD6, SD10**

- **AC1.** When a sign-up code is saved, the Aanmeldcode subsection shall show the link as today,
  a QR-code preview, and the buttons "Download PNG" and "Download SVG".
- **AC2.** When no sign-up code is saved, the subsection shall show "Aanmelden is gesloten." and
  no preview and no download buttons.
- **AC3.** When the admin types in the code field without saving, the link text, the preview and
  both downloads shall still encode the saved code. When the save succeeds, they shall encode
  the newly saved code as returned by the server.

**What the code encodes — SD1, SD3**

- **AC4.** When the preview or either downloaded file is decoded, the result shall equal the link
  shown on the page, `window.location.origin + '/speler?code=' + encodeURIComponent(<saved
  code>)`, including for a code with spaces, `&`, `#` and a non-ASCII character. *(Decoded with
  `jsqr` from the PNG's pixels and from the SVG rendered to pixels.)*
- **AC5.** The preview and both files shall be encoded at error correction `Q` with a 4-module
  quiet zone, and shall hold the same modules. The player's wallet QR code shall stay at `M` with
  a 2-module border. *(Regression: `QrCode.test.tsx` unchanged in what it asserts.)*

**The files — SD4, SD8**

- **AC6.** When "Download PNG" is pressed, the system shall download an opaque square PNG with
  white light modules and black dark modules, each module `floor(1024 / n)` pixels with no
  intermediate colours, at most 1024 px square.
- **AC7.** When "Download SVG" is pressed, the system shall download a standalone SVG with
  `xmlns`, `viewBox="0 0 n n"`, `shape-rendering="crispEdges"`, a white rectangle covering the
  whole `n × n` area, and one black `<rect>` per dark module. It shall contain no `<text>`,
  `<script>`, `<image>`, `href` or any URL other than the SVG namespace.
- **AC8.** The downloaded file shall be named `aanmelden-<host>-<code>.png` or `.svg`, with every
  character outside `[A-Za-z0-9.-]` in the host and in the code replaced by `-`.
- **AC9.** When either button is pressed in a page served over plain HTTP from a non-loopback
  host, the download shall complete and nothing shall throw. *(e2e at `http://signup.test:<port>`,
  where `isSecureContext` is false, as `web/e2e/payments.spec.ts:32-50`.)*

**Loopback — SD2**

- **AC10.** When the admin page is open at a hostname of `localhost`, `*.localhost`, `127.x.x.x`
  or `[::1]`, both download buttons shall be disabled and the hint "Open deze pagina via het
  netwerkadres (bijv. http://192.168.8.10/) om de QR-code te downloaden." shall be shown; the
  preview shall still show. At any other hostname there shall be no hint and the buttons shall be
  enabled.

**Changing the code — SD7, SD9**

- **AC11.** When a code is saved and the admin saves a code that differs from it after trimming
  and lower-casing, the system shall first show "Aanmeldcode wijzigen? Geprinte QR-codes met
  '<oud>' werken dan niet meer." with "Wijzigen" and "Annuleren", and save only on "Wijzigen".
- **AC12.** When a code is saved and the admin presses "Wissen", or "Opslaan" with a blank or
  whitespace-only field, the system shall first show "Aanmelden sluiten? Geprinte QR-codes met
  '<oud>' werken dan niet meer." with "Wissen" and "Annuleren", and save only on "Wissen".
- **AC13.** When "Annuleren" is pressed in either dialog, the system shall send no request, keep
  the saved code, preview and link unchanged, and leave the field's typed text in place.
- **AC14.** When no code is saved, or the new code equals the saved one after trimming and
  lower-casing (`borrel` over `BORREL`, ` BORREL `), the system shall save at once with no dialog.
  *(Regression of today's immediate save.)*

**Boundaries**

- **AC15.** The diff shall touch nothing under `app/`, `db/`, `exchange/` or
  `tests/engine/golden/fixtures/`, and shall add no entry to `web/package.json`'s dependencies.
- **AC16.** `docs/runbooks/venue.md` shall say to download the sign-up QR code from the venue's
  admin at its network address, and B-05 PD20 shall carry an "Amended by B-09" note pointing
  here.

## Verification

- **Web (vitest):**
  - `WalletsSection.test.tsx`: preview and buttons with a saved code, none without (AC1, AC2);
    typed-but-unsaved text does not change the preview, a save does (AC3); every dialog path, its
    wording, confirm and cancel, and the no-dialog cases including a case-only change (AC11–AC14);
    the loopback hostnames and a normal one (AC10).
  - The file builders: decode the PNG's pixels and the SVG, rendered to pixels, with `jsqr` and
    compare to the link for awkward codes (AC4); `Q` and border 4 against `uqr`'s own output,
    the same modules in preview and files (AC5); the PNG's size, opacity and two colours (AC6);
    the SVG's attributes, background and forbidden elements (AC7); the filename sanitising
    (AC8).
  - `QrCode.test.tsx` still passing as it is (AC5).
- **e2e (Playwright), at an insecure origin** (`http://signup.test:<port>`, mapped to loopback by
  `--host-resolver-rules`):
  1. Log in as admin and open Instellingen → Wallets: "Aanmelden is gesloten.", no buttons (AC2).
  2. Save code `BORREL`: preview and buttons appear (AC1).
  3. Press "Download PNG" and "Download SVG": both downloads complete with the SD8 names (AC8, AC9).
     Decode the PNG with `jsqr`: it is `http://signup.test:<port>/speler?code=BORREL` (AC4).
  4. Open that decoded link in a new context: the player page's code field holds `BORREL`.
  5. Save `borrel`: no dialog (AC14). Save `ANDERS`: the change dialog, "Annuleren" keeps
     `borrel` (AC13); again, "Wijzigen" saves it and the preview changes (AC11).
  6. "Wissen": the closing dialog; "Wissen" closes sign-up and the buttons go (AC12, AC2).
- **Docs:** the venue runbook line and the PD20 note are present (AC16).
- **The gate:** `./scripts/check.sh`, 13/13, output pasted. `git diff --stat main` shows nothing
  under `app/`, `db/`, `exchange/` and no dependency added (AC15), so `golden_linux.sh` and
  `engine-guardian` are not required.
- **Manual exit check (the owner's):**
  - on Render, download the PNG, put it on a printed page, and sign up by scanning it with an
    iPhone and an Android phone;
  - download both files from admin on a phone (iOS Safari and Android Chrome), and confirm they
    save or open as an image;
  - at the next venue bundle, open admin at `http://192.168.8.10/`, download the QR code, and scan
    it from a phone on the venue network; open admin at `http://localhost/` on the laptop and see
    the buttons disabled with the hint.

## Exit condition

An organizer downloads the sign-up QR code as PNG or SVG from the Wallets settings of the
deployment the players will use, scans it straight onto the player page with the code filled in,
and is warned before any change to the code that would make printed QR codes stop working.
