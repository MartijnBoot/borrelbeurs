# Plan: B-09 — Download the sign-up QR code

Spec: [docs/specs/phase-b-09-signup-qr.md](../specs/phase-b-09-signup-qr.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-29)**
Design: no change to `docs/design/` (R2).
ADRs honoured:
- 0006: everything bundled, nothing leaves the origin. Both files are made in the browser from `uqr`'s matrix. No server call, no CDN.
- 0004, 0002, 0012: `app/`, `db/` and `exchange/` are not touched (AC15).

No ADR is reversed. No new dependency: `uqr` 0.1.3 and `jsqr` 1.4.0 are already in `web/package.json` (approved in B-05's plan, § Dependency approval).
Backlog: [B-09](../backlog.md) · Fixes: no open defect · Amends: B-05 PD20, `docs/runbooks/venue.md` (T5)

Line references are to `main` at `4c72851`.

---

## Approach

**One shared QR module, used by two features.** Features are sibling-isolated
(`web/eslint.config.js:123-136`), so the wallets section cannot import the player's
`QrCode.tsx`. The drawing moves into a new shared folder, `web/src/components/qr/`, next to
`components/scanner/`, which already holds the shared camera and decoder (B-06 SD12). It holds
two files:
- **`QrSvg.tsx`** draws a module matrix as SVG `<rect>`s. Its markup and attributes are
  today's `QrCode.tsx:15-27`.
- **`qrFiles.ts`** turns the same matrix into a standalone SVG string, an RGBA pixel raster, a
  PNG `Blob` and a download.

The player's `QrCode` keeps its name, props and `encode(token, { ecc: 'M', border: 2 })`. It
draws through `QrSvg`, so `QrCode.test.tsx` passes unchanged (AC5).

The sign-up preview and both files are built from **one** `encode(link, { ecc: 'Q', border: 4 })`
matrix, memoised on the saved code, so "the same modules" (AC5) holds by construction and is
also tested.

**The PNG is a pure pixel raster first, then a canvas.** `qrPixels(modules)` returns the
`{ data, width, height }` shape that `decodeQr.ts` already uses (its `Frame`). Each module
becomes a `k × k` block, `k = floor(1024 / n)`, opaque white or black. `pngBlob` puts exactly
those pixels on a canvas with `putImageData` and calls `toBlob('image/png')`. PNG is lossless,
so the file holds the raster's pixels, and no scaling or smoothing step exists.

The raster is the part jsdom can test: jsdom has no canvas, and vitest runs jsdom
(`web/vite.config.ts:24-26`). So AC4 and AC6 are tested on the raster with `jsqr`, and the real
PNG is checked once in Playwright.

**The confirm and the download are two separate slices.** The confirm is a regression-sensitive
change to today's immediate save, and it needs no QR code. It is built first and in parallel
with the QR module, then the preview and buttons go on top.

**Rejected:**
- Drawing the PNG with `fillRect` at scale. That adds a second path from modules to pixels, and
  it cannot be checked in jsdom.
- A `canvas` npm package for tests. That would be a new dependency.
- Encoding the SVG through `XMLSerializer` of the preview's DOM. That would tie the file to
  React's output and its `class` attribute.
- A new Playwright spec with its own `serve.py`. That costs a server boot against B-11's gate
  budget, and the shared server is enough (PD7).

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. The rest follow from the
spec or the code.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | Where the shared drawing lives | **New folder `web/src/components/qr/`:**<br>• `QrSvg.tsx`: `QrSvg({ modules, className, label })`, `role="img"`, `aria-label={label}`, `viewBox`, `shapeRendering="crispEdges"`, one `<rect fill="#000">` per dark module, as `QrCode.tsx:15-27`;<br>• `qrFiles.ts`: `type Modules = readonly (readonly boolean[])[]`, `svgDocument(modules)`, `qrPixels(modules, max = 1024)`, `pngBlob(modules)`, `saveFile(blob, name)`.<br>`features/player/QrCode.tsx` becomes `encode` plus `<QrSvg … label="QR-code" className={styles.qr} />`. | The boundaries rule forbids feature-to-feature imports. `components/` is where shared UI already lives (`components/scanner/`). One drawing path means the player and sign-up codes cannot drift. |
| PD2 | The SVG file (SD4, AC7) | Built as a string from numbers only, no user text:<br>• `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 n n" shape-rendering="crispEdges">`;<br>• `<rect width="n" height="n" fill="#fff"/>`;<br>• one `<rect x y width="1" height="1" fill="#000"/>` per dark module;<br>• then `</svg>`.<br>No XML declaration is needed. `Blob` type `image/svg+xml`. | The link never enters the file, so nothing needs escaping, and AC7's "no other URL" holds trivially. It is a string, not an HTML sink, so the `htmlSinks` lint rule is not involved. |
| PD3 | The PNG (SD4, AC6) | `qrPixels`:<br>• `k = Math.floor(max / n)`, size `n·k`;<br>• RGBA with alpha 255 everywhere, `0,0,0` for dark and `255,255,255` for light.<br>`pngBlob`:<br>• a `document.createElement('canvas')` of that size, `getContext('2d')`, `putImageData(new ImageData(data, w, h), 0, 0)`, `toBlob(…, 'image/png')`;<br>• a missing context or a `null` blob rejects. | `putImageData` writes pixels as given: no smoothing, no antialiasing. The same raster is what the tests decode. |
| PD4 | The download over plain HTTP (AC9) | `saveFile`:<br>• `URL.createObjectURL(blob)`;<br>• a detached `<a href download={name}>`, `.click()`;<br>• `URL.revokeObjectURL` in a `setTimeout(…, 0)`.<br>No File System Access API, no `navigator.share`, no clipboard: all three are secure-context only or absent at the venue. | Blob URLs and `download` work in insecure contexts. The analytics export already downloads through an `<a download>` (`ExportPanel.tsx:140`), though of a server URL; no blob URL exists in `web/src` yet. |
| PD5 | The sign-up helpers | New `web/src/features/wallets/signupQr.ts`:<br>• `signupLink(origin, code)`, moved from `WalletsSection.tsx:45-47`, which then calls it;<br>• `SIGNUP_QR = { ecc: 'Q', border: 4 } as const`;<br>• `signupFileName(host, code, ext)`: `aanmelden-${safe(host)}-${safe(code)}.${ext}`, with `safe = s.replace(/[^A-Za-z0-9.-]/gu, '-')`;<br>• `isLoopbackHost(hostname)`: `localhost`, `*.localhost`, `/^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/`, `[::1]`.<br>The `u` flag makes one dash per character (SD8, "each character"), not one per UTF-16 half. A host with a port, `signup.test:4173`, gives `signup.test-4173`. **Confirm** | SD8 and SD2 to the letter. `URL.hostname` keeps an IPv6 host's brackets, so `[::1]` is the string to match. |
| PD6 | The code comparison (SD7, SD9) | New `web/src/features/wallets/signupCode.ts`:<br>• `breaksPrinted(saved, next): 'change' \| 'clear' \| null`;<br>• `null` when `saved === null`;<br>• `'clear'` when `next === null` or `next.trim() === ''`;<br>• `'change'` when `next.trim().toLowerCase() !== saved.trim().toLowerCase()`;<br>• otherwise `null`.<br>`saveCode` asks it first. A non-null answer opens a second `ConfirmDialog` holding the pending `signup_code`. "Wijzigen" or "Wissen" saves it, and "Annuleren" clears the pending state only. The wallet-delete dialog stays as it is. | One pure function carries every AC11–AC14 branch, so a table test can cover them all. Cancel touches neither `code` nor `settings`, so the typed text and the preview stay (AC13). |
| PD7 | The Playwright spec (AC9) | New `web/e2e/signup-qr.spec.ts` on the **shared** server (`fixtures.ts` `server()`). Chromium gets `--host-resolver-rules=MAP signup.test 127.0.0.1`, as `payments.spec.ts:49`. Pages run at `http://signup.test:<port>`.<br>Starting state: no other spec on the shared server sets a sign-up code, and the shared server seeds none. The spec still starts by clearing the code over the API, so it does not depend on that. It ends with sign-up closed.<br>Decoding the downloaded PNG:<br>• the bytes go into `page.evaluate` as base64;<br>• there, `createImageBitmap`, then `OffscreenCanvas`, then `getImageData`;<br>• the pixels come back to Node and go to `jsqr`.<br>The same pixels give AC6's opaque and two-colour check. **Confirm** | No server boot is added against B-11's gate budget. jsqr is already a dependency, and the browser is the PNG decoder, so no PNG library is needed. |
| PD8 | Where the page reads its address | `WalletsSection` reads `window.location.origin`, `.host` and `.hostname` once per render, through one small exported `pageAddress()` in `signupQr.ts`. vitest's jsdom origin is `http://localhost:3000`, a loopback host, so `WalletsSection.test.tsx` sets a non-loopback address with `vi.spyOn` on that module, or with vitest's per-file jsdom URL if that works. The existing assertions compare against the same source, so they keep holding. | Without it, every existing test would run in "loopback" mode with the buttons disabled. |
| PD9 | A failed PNG (errors are tasks) | If `pngBlob` rejects, the subsection's existing `role="alert"` paragraph shows "Downloaden lukt niet. Probeer opnieuw." and nothing throws. The SVG path cannot fail short of an exception in `saveFile`, which goes to the same text. **Confirm**: the spec fixes no text for this. | AC9 says "nothing shall throw". The wording follows the section's `NETWORK` text. |
| PD10 | Preview size and label (SD5) | `.qr` in `WalletsSection.module.css`: `display: block; width: 160px; height: 160px; background: #fff`, black on white whatever the theme, as `PlayerPage.module.css:111-118`. `label="Aanmeld-QR-code"`. Order inside the subsection: the form, the link `<p>`, the preview, a `.row` with "Download PNG" and "Download SVG" (`type="button"`), the hint `<p className={styles.muted}>` (loopback only), then the alert. **Confirm** | SD5 says "about 160 CSS px". A label distinct from the player's lets tests and screen readers tell the two apart. |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `web/src/components/qr/QrSvg.tsx` | Create | The matrix as SVG `<rect>`s (PD1) | T1 |
| `web/src/components/qr/qrFiles.ts` | Create | `svgDocument`, `qrPixels`, `pngBlob`, `saveFile` (PD2–PD4) | T1 |
| `web/src/components/qr/qrFiles.test.ts` | Create | AC4, AC6, AC7 on the builders, with `jsqr` | T1 |
| `web/src/features/player/QrCode.tsx` | Modify | Draw through `QrSvg`, same `M`/2 and props | T1 |
| `web/src/features/wallets/signupCode.ts` | Create | `breaksPrinted` (PD6) | T2 |
| `web/src/features/wallets/signupCode.test.ts` | Create | AC11, AC12 and AC14 as a table | T2 |
| `web/src/features/wallets/WalletsSection.tsx` | Modify | T2: the confirm · T3: preview, buttons, hint, download | T2, T3 |
| `web/src/features/wallets/WalletsSection.test.tsx` | Modify | T2: dialog paths · T3: preview, buttons, loopback, saved-only | T2, T3 |
| `web/src/features/wallets/signupQr.ts` | Create | `signupLink`, `SIGNUP_QR`, `signupFileName`, `isLoopbackHost`, `pageAddress` (PD5, PD8) | T3 |
| `web/src/features/wallets/signupQr.test.ts` | Create | AC8 sanitising, AC10 host list | T3 |
| `web/src/features/wallets/WalletsSection.module.css` | Modify | `.qr` (PD10) | T3 |
| `web/e2e/signup-qr.spec.ts` | Create | The spec's e2e steps 1–6 at an insecure origin, plus loopback | T4 |
| `docs/runbooks/venue.md` | Modify | The "Before" line (AC16) | T5 |
| `docs/plans/phase-b-05-player-wallets.md` | Modify | "Amended by B-09" on PD20 (AC16) | T5 |

`QrCode.test.tsx` is **not** modified (AC5). Nothing under `app/`, `db/`, `exchange/`,
`tests/`, `docs/design/` or `web/package.json` changes.

---

## Tasks

### T1 — The shared QR drawing and its two files

- **Implements:** AC4 (the builders), AC5 (`Q`/4 against `uqr`, the player unchanged), AC6, AC7
- **Expected output:**
  - `web/src/components/qr/` holds `QrSvg.tsx` and `qrFiles.ts` as PD1–PD4 describe.
  - `features/player/QrCode.tsx` keeps its name, export, props and `memo`, and draws through
    `QrSvg`. The player page renders exactly as before.
  - `qrFiles.test.ts` (`// @vitest-environment jsdom`) holds these tests:
    - **Decoding (AC4).** For links whose codes are `BORREL`, `a b&c#é` and a 40-character
      code, under `http://192.168.8.10` and `https://borrelbeurs.onrender.com`, it does three
      things. It decodes `qrPixels(encode(link, Q/4))` with `jsqr`. It renders
      `svgDocument(…)` to pixels with a test-side rasteriser: `DOMParser`, the white
      background rect first, then each black `rect` filled into an RGBA buffer at `k` px per
      unit. It decodes that buffer too. Both results must equal `link`.
    - **The same modules (AC5).** The dark cells of the pixel raster (sampled at each block's
      centre), the black `rect`s of the SVG and the `rect`s of a rendered `<QrSvg>` all equal
      `encode(link, { ecc: 'Q', border: 4 }).data`. Their size is `n` with the quiet zone: the
      outermost 4 rows and columns are light.
    - **The PNG raster (AC6).** `width === height === n·k`, with `k = floor(1024 / n)`, so
      `≤ 1024` and `> 1024 − n`. Every alpha is 255. The only colours are `0,0,0` and
      `255,255,255`. Each `k × k` block is uniform.
    - **The SVG text (AC7).** It has `xmlns`, `viewBox="0 0 n n"` and `shape-rendering="crispEdges"`.
      The first `rect` is white, at `0,0` and `n × n`. The number of black `rect`s equals the
      number of dark modules. It has no `<text`, `<script`, `<image`, `href`, and no `http`
      other than the namespace.
    - **`pngBlob`.** It is tested with a stubbed `HTMLCanvasElement.prototype.getContext` and
      `toBlob`, which receive exactly `qrPixels`' data and size and the type `image/png`. A
      `null` from `toBlob` rejects.
    - **`saveFile`.** It is tested with a stubbed `URL.createObjectURL`: an anchor with
      `download === name` is clicked, and the URL is revoked afterwards.
- **Verification:** `pnpm -C web exec vitest run src/components/qr src/features/player`. That
  includes `QrCode.test.tsx` unchanged and green. Also `pnpm -C web lint` and
  `pnpm -C web exec tsc -b`.
- **Depends on:** —
- **Autonomy note:**
  - **The builder decides:** internal helper names; the test-side SVG rasteriser's shape;
    whether `QrSvg` takes `className` or a `size`; test structure.
  - **Stop and ask if:** `QrCode.test.tsx` would need any edit; a canvas or PNG package seems
    needed; `uqr`'s `encode` output has no quiet zone at `border: 4`, or differs from the
    matrix shape assumed here.

### T2 — Confirm before printed codes break

- **Implements:** AC11, AC12, AC13, AC14
- **Expected output:**
  - `signupCode.ts` holds `breaksPrinted` (PD6).
  - In `WalletsSection.tsx`, `saveCode` asks `breaksPrinted(settings.signup_code, signupCode)`
    first:
    - `null` saves at once, as today;
    - otherwise a pending `{ signupCode, kind }` opens a second `ConfirmDialog`.
  - The dialog texts:
    - change: "Aanmeldcode wijzigen? Geprinte QR-codes met '<oud>' werken dan niet meer.",
      confirm "Wijzigen";
    - clear: "Aanmelden sluiten? Geprinte QR-codes met '<oud>' werken dan niet meer.", confirm
      "Wissen";
    - cancel "Annuleren";
    - `<oud>` is `settings.signup_code` as stored.
  - Cancel only clears the pending state. Confirm clears it and calls the existing `save`.
  - Tests:
    - `signupCode.test.ts` is a table over:
      - saved `null` with `'X'`, `''` and `null`;
      - saved `BORREL` with `'borrel'`, `' BORREL '`, `'ANDERS'`, `''`, `'   '` and `null`;
      - saved `Straße` with `'STRASSE'`, which gives `'change'`, SD9's accepted extra dialog.
    - `WalletsSection.test.tsx` gains:
      - a change shows the exact text and buttons, and "Wijzigen" sends one PUT with the new
        code (AC11);
      - "Wissen", and "Opslaan" over a whitespace-only field, show the closing text, and
        "Wissen" sends `null` (AC12);
      - "Annuleren" in either dialog sends no PUT, and the link text, the stored code and the
        field's typed value are unchanged (AC13);
      - `borrel` over `Borrel2026`'s stand-in `BORREL`, the same code with spaces, no code
        saved, and "Wissen" with none saved all PUT at once with no dialog (AC14).
    - The existing tests at `WalletsSection.test.tsx:93-109` change saved data ("Nieuw" over
      `Borrel2026`, "Wissen" over `Borrel2026`), so they now pass through the dialog. Each gets
      one confirm click, and the rest of each assertion stays as it is.
- **Verification:** `pnpm -C web exec vitest run src/features/wallets` and `pnpm -C web lint`.
- **Depends on:** —
- **Autonomy note:**
  - **The builder decides:** state names; one or two `ConfirmDialog` instances, as long as only
    one is ever open.
  - **Stop and ask if:** a text differs from the spec's; the server's reply would make the
    dialog show for a save the server treats as the same code; an existing test would need
    more than an added confirm click.

### T3 — The preview, the two downloads, and the loopback hint

- **Implements:** AC1, AC2, AC3, AC4 (on the page), AC5 (the preview), AC8, AC10
- **Expected output:**
  - `signupQr.ts` holds what PD5 and PD8 describe, and `WalletsSection.tsx`'s local
    `signupLink` is gone in favour of it.
  - With `settings.signup_code !== null`:
    - `modules = useMemo(() => encode(signupLink(origin, saved), SIGNUP_QR).data, [origin, saved])`;
    - the subsection shows the link `<p>`, then `<QrSvg modules label="Aanmeld-QR-code" className={styles.qr}>`,
      then "Download PNG" and "Download SVG";
    - PNG is `pngBlob(modules)` and SVG is `new Blob([svgDocument(modules)], { type: 'image/svg+xml' })`;
    - each is passed to `saveFile(…, signupFileName(host, saved, ext))`;
    - a failure shows PD9's text in the alert.
  - With `isLoopbackHost(hostname)`: both buttons are `disabled`, and the hint is shown under
    them: "Open deze pagina via het netwerkadres (bijv. http://192.168.8.10/) om de QR-code te
    downloaden." The preview still shows.
  - With no code saved: "Aanmelden is gesloten." and no preview or buttons, as today.
  - Tests:
    - `signupQr.test.ts`:
      - AC8: `('192.168.8.10', 'BORREL')`, `('signup.test:4173', 'Borrel 2026!')`, `'é'` and an
        astral character, which each give one `-`;
      - AC10: `localhost`, `app.localhost`, `127.0.0.1`, `127.255.0.9` and `[::1]` are true;
        `192.168.8.10`, `localhost.example`, `128.0.0.1`, `borrelbeurs.onrender.com` and
        `[::2]` are false;
      - `signupLink` with an awkward code.
    - `WalletsSection.test.tsx`, at a non-loopback address (PD8), gains:
      - preview plus both enabled buttons with a code (AC1), none without (AC2);
      - typing without saving leaves the preview's `rect`s unchanged, and a save, through T2's
        dialog, changes them to the reply's code (AC3);
      - the preview, rasterised in the test and decoded with `jsqr`, equals the shown link
        text, including for `a b&c#é` (AC4);
      - its `rect`s equal `encode(link, SIGNUP_QR)` (AC5);
      - pressing each button calls `saveFile` with the SD8 name: `qrFiles` is mocked or spied;
      - a rejected `pngBlob` shows the alert;
      - at `localhost` the buttons are disabled and the hint is present, and at a LAN host
        neither is (AC10).
- **Verification:** `pnpm -C web exec vitest run src/features/wallets src/components/qr`,
  `pnpm -C web lint`, `pnpm -C web exec tsc -b` and `pnpm -C web build`.
- **Depends on:** T1 (`QrSvg`, `qrFiles`), T2 (the same `WalletsSection.tsx`, and AC3's save
  goes through the dialog)
- **Autonomy note:**
  - **The builder decides:** layout and CSS details within PD10; how the test fixes the page
    address (PD8); whether the buttons' handlers live inline or in a helper.
  - **Stop and ask if:** the preview would encode anything but the saved code; a label or hint
    text differs from SD2 or SD10; an existing assertion would have to be weakened.

### T4 — The Playwright story at an insecure origin

- **Implements:** AC9, and end to end AC1, AC2, AC4, AC6, AC8, AC10, AC11, AC12, AC13, AC14
- **Expected output:** `web/e2e/signup-qr.spec.ts` (PD7), serial. The steps below are the
  spec's, numbered as in its Verification:
  1. Over the API, clear the sign-up code. As admin at `http://signup.test:<port>/settings`,
     assert `isSecureContext === false`, and in Wallets see "Aanmelden is gesloten." and no
     download buttons (AC2).
  2. Save `BORREL`: the link, the preview (`img` "Aanmeld-QR-code") and both buttons appear
     (AC1).
  3. Press each download button with `page.waitForEvent('download')`:
     - `suggestedFilename()` is `aanmelden-signup.test-<port>-BORREL.png` or `.svg` (AC8), and
       no page error was raised (AC9);
     - the PNG's pixels are decoded as PD7 describes and equal
       `http://signup.test:<port>/speler?code=BORREL` (AC4); they are square, at most 1024,
       alpha 255 and two colours only (AC6);
     - the SVG text starts with `<svg xmlns=` and has no `<script` or `href`.
  4. Open the decoded link in a new context: the player page's code field holds `BORREL`.
  5. Save `borrel`: no dialog appears and the link becomes `…?code=borrel` (AC14). Save
     `ANDERS`: the change dialog appears, and "Annuleren" keeps the `borrel` link (AC13). Save
     it again: "Wijzigen" saves it and the preview changes (AC11).
  6. "Wissen": the closing dialog appears. "Wissen" closes sign-up and the buttons go (AC12,
     AC2).
  7. Open the same page at the loopback base URL (`127.0.0.1`): the preview shows, both buttons
     are disabled, and the hint is visible (AC10).
- **Verification:**
  - `pnpm -C web build`, then
    `pnpm -C web exec playwright test e2e/signup-qr.spec.ts`; the compose `db` must be up;
  - then the whole `pnpm -C web e2e`, so the shared server's other specs are shown unaffected;
  - `pnpm -C web lint` (e2e is linted).
- **Depends on:** T3
- **Autonomy note:**
  - **The builder decides:** the helpers, reusing `fixtures.ts` and the `section()` pattern
    from `wallets.spec.ts`; how the bytes cross into `page.evaluate`; timeouts.
  - **Stop and ask if:** the shared server already has a code that another spec relies on;
    the spec would need its own `serve.py`; `--host-resolver-rules` cannot be combined with
    the shared server's login.

### T5 — The runbook line and the PD20 note

- **Implements:** AC16
- **Expected output:**
  - **`docs/runbooks/venue.md`.** "Before: the router" gains a step after step 3. With the
    laptop on the router and `start.cmd` running, log in as admin at `http://192.168.8.10/`,
    not on Render and not at `http://localhost/` (the buttons are disabled there). Under
    Instellingen → Wallets → Aanmeldcode, save the code and press "Download PNG". Print it,
    and check that a phone on the venue Wi-Fi opens the player page with the code filled in.
    The step also warns that changing or clearing the code later breaks printed QR codes.
  - **`docs/plans/phase-b-05-player-wallets.md`.** PD20's row keeps its text and gains
    "*Amended by B-09:* the Wallets section draws the QR code and downloads it as PNG or SVG
    ([spec](../specs/phase-b-09-signup-qr.md))". The out-of-scope line at `:803` gets the same
    pointer. This follows B-08 PD11's note style.
- **Verification:** `grep -n "Download PNG" docs/runbooks/venue.md` and
  `grep -n "Amended by B-09" docs/plans/phase-b-05-player-wallets.md` each print a line. No
  formatter covers `docs/` (`check.sh` formats Python and `web/` only).
- **Depends on:** —
- **Autonomy note:**
  - **The builder decides:** the runbook step's wording and number.
  - **Stop and ask if:** the runbook's existing step 3, the router-address QR, seems to
    contradict the new step. It does not as planned: they are two different QR codes.

### T6 — The closing check

- **Implements:** AC15
- **Expected output:** evidence only, no file changes:
  - `git diff --stat main -- app db exchange tests/engine/golden/fixtures` is empty;
  - `git diff main -- web/package.json` is empty;
  - `./scripts/check.sh` is green at 13/13, with its output pasted. This is the phase's one
    full gate (MEMORY: gate only at phase end).
- **Verification:** the commands above, with their output.
- **Depends on:** T4, T5
- **Autonomy note:**
  - **The builder decides:** nothing beyond running the commands.
  - **Stop and ask if:** any of the diffs is non-empty, or `check.sh` fails in a step this
    phase did not touch. The golden tests and `engine-guardian` are not required (AC15, the
    spec's Verification).

---

## AC coverage

| AC | Tasks |
|---|---|
| AC1 | T3, T4 |
| AC2 | T3, T4 |
| AC3 | T3 |
| AC4 | T1, T3, T4 |
| AC5 | T1, T3 |
| AC6 | T1, T4 |
| AC7 | T1, T4 |
| AC8 | T3, T4 |
| AC9 | T4 |
| AC10 | T3, T4 |
| AC11 | T2, T4 |
| AC12 | T2, T4 |
| AC13 | T2, T4 |
| AC14 | T2, T4 |
| AC15 | T6 |
| AC16 | T5 |

Every task implements at least one AC. T6 is AC15's evidence.

---

## Task graph

```
T1 ──┐
     ├── T3 ── T4 ──┐
T2 ──┘              ├── T6
T5 ─────────────────┘
```

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T2, T5 | T1: `web/src/components/qr/{QrSvg.tsx,qrFiles.ts,qrFiles.test.ts}`, `web/src/features/player/QrCode.tsx` · T2: `web/src/features/wallets/{signupCode.ts,signupCode.test.ts,WalletsSection.tsx,WalletsSection.test.tsx}` · T5: `docs/runbooks/venue.md`, `docs/plans/phase-b-05-player-wallets.md` |
| G2 | T3 | `web/src/features/wallets/{signupQr.ts,signupQr.test.ts,WalletsSection.tsx,WalletsSection.test.tsx,WalletsSection.module.css}` |
| G3 | T4 | `web/e2e/signup-qr.spec.ts` |
| G4 | T6 | none (evidence only) |

No two tasks in one group write the same file. T2 and T3 share `WalletsSection{.tsx,.test.tsx}`,
which is why T3 depends on T2.

---

## Data changes

None. No migration, no setting, no route (spec, Out of scope).

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | jsdom has no canvas, so the real PNG encoder is never run in vitest. | The pixels are a pure function, tested and decoded (T1). `pngBlob` only hands them to `putImageData`, and its stubbed test checks that handover. T4 decodes the real downloaded PNG in Chromium. |
| R2 | `docs/design/frontend-architecture.md` lists `components/ui/` and `components/scanner/` and calls `uqr` "the player page's QR code". After B-09 there is also `components/qr/`, and the admin page uses `uqr`. The doc becomes incomplete, not wrong. | Changing `docs/design/` is an owner's hard stop, so no task edits it. Recommendation: leave it. B-05's plan listed the same doc's stale parts as out of scope. If the owner wants the line, it is one sentence, added with approval at audit. |
| R3 | iOS Safari's handling of `<a download>` on a blob URL: it may open a preview rather than save. | It is in the spec's manual exit check (iOS Safari, Android Chrome). Opening the image is acceptable there ("save or open as an image"). |
| R4 | The shared e2e server is used by every other spec. A sign-up code left set could change another spec's view of `/settings`. | T4 clears the code first and ends with it cleared (step 6). Step 7 saves nothing. T4 runs the whole e2e suite. |
| R5 | vitest's jsdom origin, `http://localhost:3000`, is loopback, so without care every Wallets test sees disabled buttons. | PD8: one `pageAddress()` the test controls. The existing link assertions use the same source. |
| R6 | `uqr`'s `border` might not produce light rows exactly as assumed, or the matrix might include extra padding. | T1 asserts the outer four rows and columns are light and the size matches. If not, T1 stops (autonomy note). |
| R7 | An astral-plane character in the code passes through `encodeURIComponent` as four `%XX` bytes, which is fine for the link. Without the `u` flag the filename would get two dashes. | PD5's `u` flag; the case is tested in T3. |

---

## Out of scope for this plan

- Everything in the spec's Out of scope: any server change, a poster or caption, a public-address
  setting, other sizes, the koers-screen QR code (B-10), and the player's wallet QR code beyond
  the refactor that keeps it identical.
- Editing `docs/design/frontend-architecture.md` (R2).
- Adding `src/components/qr/` to `walletCode.provenance.test.ts`'s scan. The module draws and
  downloads only and never makes a key. That scan is about `crypto.randomUUID` in pages that
  post with idempotency keys.
- Committing the spec and the backlog change. They are uncommitted on `docs/phase-b-09-spec`,
  and this is the owner's branch choice before `/build`, not a task.

---

## Uncertain

- **PD7, the shared server.** I found no sign-up seed in `tests/integration/realapp/`, and no
  shared-server spec touches wallet settings. The alternative, an own `serve.py`, is safe but
  costs a boot against B-11's 12-minute gate bar. Confirm.
- **PD8, how the test fixes the address.** I am not certain vitest honours a per-file jsdom URL
  comment in this version. A spied `pageAddress()` always works, so the builder chooses.
- **PD9's text.** The spec has no failure text for a download. "Downloaden lukt niet. Probeer
  opnieuw." is mine. Confirm or replace.
- **PD10's label, "Aanmeld-QR-code".** The spec does not name the preview's accessible name.
  Confirm.
- **R2.** The owner may want the design doc's two lines updated. That is the owner's call;
  the default is no change.

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

The owner ticked every line without changes. The **Confirm** rows stand as written: PD5, PD7
(the shared e2e server), PD9 ("Downloaden lukt niet. Probeer opnieuw.") and PD10
("Aanmeld-QR-code"). R2 stands: `docs/design/` is not edited. The one audit correction is
PD4's precedent: `ExportPanel` downloads a server URL, not a blob.

Audited by: MartijnBoot (owner, /audit)  Date: 2026-10-29
