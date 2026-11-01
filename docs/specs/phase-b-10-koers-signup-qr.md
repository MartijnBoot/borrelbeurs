# Spec: B-10 — Sign-up QR code on the koers screen

Status: Approved · Depends on: B-09 (SD1–SD5 the sign-up QR code, its loopback rule, `signupLink`,
`QrSvg`), B-05 (SD6 the sign-up code, SD17 the venue's own database), Phase 3 (the realtime
protocol, SD27 `seq`), Phase 4 (the koers screen, SD9 `theme` as the pattern), Phase 8 (SD1 the
venue at `http://192.168.8.10/`) · Fixes: no open defect · Amends: B-05 "only admin sees the
sign-up code", `docs/design/realtime-protocol.md`, `docs/design/data-model.md`
(`wallet_settings`), `docs/runbooks/venue.md` · Backlog: [B-10](../backlog.md)

Line references are to `main` at `7188d24`.

## Problem

People in the room who have not signed up have to find the poster first, while the big screen
everyone is already looking at could show them how.

- **The koers screen shows no sign-up.** `KoersPage` renders the price marquee, the news marquee,
  the board and the promo tile (`web/src/features/koers/KoersPage.tsx:34-69`). Nothing on it
  mentions wallets.
- **A display key cannot read the sign-up code.** The code is served only by
  `GET /api/admin/wallet-settings`, admin only (`app/api/wallets_admin.py:127-129`). The
  WebSocket every screen uses is open to all four roles (`app/realtime/ws.py:81-97`) but carries
  no wallet data.
- **The theme is the pattern that already works.** `theme` is broadcast on change, with or
  without a live run, and re-sent as a unicast after every handshake (`ws.py:152-156`, `:252`;
  `docs/design/realtime-protocol.md:56`, `:83-86`).
- **The app does not know its own public address.** `BB_PUBLIC_URL` exists only in the venue's
  `.env` (`deploy/venue/.env.example:17`) and `start.cmd` prints it (`start.cmd:65`); the app
  container is not given it (`deploy/venue/compose.yml:53-59`) and `Settings` has no field for
  it (`app/core/config.py:57-`). At the venue the laptop drives the TV over HDMI, so the koers
  screen is open at `http://localhost/`; B-09 SD1's rule, "the address the page is open at",
  would put `localhost` in the QR code and send every phone to itself.
- **The screen has no room for it.** The two marquees are about 40 px tall each
  (`web/src/components/ui/Marquee.module.css:11-16`) and disappear when there is no live run
  (`KoersPage.tsx:36-41`). A crash or bubble pulses a glow about 70 px in from every edge
  (`web/src/styles/keyframes.css:25-34`).
- **B-09 already draws the QR code in the browser.** `uqr` at error correction `Q` and a
  4-module quiet zone, `signupLink(origin, code)` and `isLoopbackHost` (`web/src/features/wallets/signupQr.ts`),
  and `QrSvg` (`web/src/components/qr/QrSvg.tsx`). It needs no secure context.

## Decisions

These were settled at the spec interview on 2026-11-01. Q1–Q7 were put to the owner one at a
time, each with a recommendation; the owner chose the recommendation every time (Q1: the laptop
drives the TV over HDMI, which ruled out the screen's own address at the venue). SD9–SD12 were
not asked: they are the spec writer's defaults, marked so for the owner to object to at review.
The planner must not reopen any of them.

**The address**

- **SD1 — `BB_PUBLIC_URL` becomes an optional setting (Q1, Q2).** `app/core/config.py` gains an
  optional `public_url`, read from `BB_PUBLIC_URL`, validated as an absolute `http` or `https`
  URL with a host and no path beyond `/`, query or fragment, and stored without a trailing
  slash. `deploy/venue/compose.yml` passes it to the app. Unset is valid: Render sets nothing.
  Config is still the only module that reads the environment.
- **SD2 — Which address the screen's link uses (Q2).** The link is
  `<base>/speler?code=<encodeURIComponent(code)>`, built by B-09's `signupLink`, where `<base>`
  is the server's `public_url` when set, else `window.location.origin`. With no `public_url`
  and a loopback hostname (B-09 SD2's rule), there is no usable address and the block is
  hidden (SD6). Admin's own QR code and downloads (B-09) are unchanged: they keep using the
  address admin is open at.

**Getting it to the screen**

- **SD3 — A `signup` realtime message (Q3).** Added to `docs/design/realtime-protocol.md` as a
  server-to-client message, next to `theme`:
  `{show_on_screen: bool, signup_code: string | null, public_url: string | null}`, the whole
  state, replacing what the client holds. It is broadcast with `version: null` whenever the
  sign-up code or the switch (SD5) is saved, whether or not a run is live, and sent as a
  catch-up unicast after every handshake replay or snapshot and every `resync_request`
  snapshot, as `theme` is. The client applies it outside the seq rule, never starts or waits
  on a resync, and the latest one wins. It carries no prices; the hub's resync metadata is
  untouched.
- **SD4 — Every socket receives it.** The code is already on a poster and now on the screen, so
  it is not a secret from display keys. The server does not filter by role; bar, kassa and
  admin clients receive it and only the koers page uses it.

**When and what**

- **SD5 — A switch, off by default (Q4).** `wallet_settings` gains `show_signup_on_screen`
  (boolean, default false, a new migration). `GET`/`PUT /api/admin/wallet-settings` carry it.
  The Wallets settings show it as a checkbox "QR-code op het scherm" in the Aanmeldcode
  subsection. Toggling it needs no confirm: nothing printed breaks. Changing or clearing the
  code keeps B-09 SD7's confirm. Existing deployments change nothing until it is turned on.
- **SD6 — The visibility rule (Q6, Q7).** The block shows when, and only when, the switch is on,
  a sign-up code is set, and an address is known (SD2). It does not depend on a live run, a
  closed run or a market event: it shows with no run and after a close, and stays up through
  a crash, bubble or correction. Clearing the code, turning the switch off or losing the
  address removes it at once.
- **SD7 — Layout: a block at the top left, beside the marquees (Q5).** A white square card with
  the QR code (error correction `Q`, 4-module quiet zone, black on white, as B-09 SD3) and the
  caption "Meld je aan" under it, at the left of the band that holds the marquees. The
  marquees keep their order and fill the width to the right of it. The block is a square of
  about 14% of the viewport height, at least 96 px, so the band grows from about 80 px to
  about 150 px at 1080p and the tiles lose that much height. With no marquees (no live run) the
  block sits alone at the top left. Nothing covers a price, a tile or a market event's banner.
- **SD8 — It follows changes live.** A new code, the switch or a clear reaches a connected
  screen without a reload, and a screen that reconnects shows the current state, never an old
  one. The QR code is drawn from the last `signup` message received, only.
- **SD9 — Not on a phone-sized screen (default).** At a viewport 700 px wide or less, the
  koers page's existing phone layout, the block is not shown: a phone does not scan itself.
- **SD10 — The caption (default).** "Meld je aan". No code text, no link text, no logo.
- **SD11 — The block is the same on every koers page (default).** Admin opening `/koers` sees
  what the display sees.
- **SD12 — Plain HTTP, no network (default).** The drawing is in the browser with `uqr`, with no
  secure-context API and no request of its own. With the WebSocket down the screen keeps the
  last state it had (the existing connection banner shows); on reconnect SD3's catch-up
  replaces it.

## In scope

- `app/core/config.py`: `public_url` (SD1); `deploy/venue/compose.yml` passes `BB_PUBLIC_URL`.
- `wallet_settings`: `show_signup_on_screen`, its migration, its repository and runtime code,
  and the admin routes' body (SD5); the generated API types.
- The `signup` message (SD3): model in `app/realtime/messages.py`, broadcast on a settings save,
  catch-up in `ws.py`, the client store and its Zod half, the recorded fixture.
- `docs/design/realtime-protocol.md` and `docs/design/data-model.md`: the message and the
  column. The owner approved both at this interview.
- The koers page: the block, its CSS, the layout change (SD7); `WalletsSection.tsx`: the checkbox.
- `docs/runbooks/venue.md`: a line on `BB_PUBLIC_URL` and the switch. A note on B-05's "only
  admin sees the code" in `docs/specs/phase-b-05-player-wallets.md`.
- Tests: pytest (config, API, WebSocket, migration), web unit, and e2e over an insecure,
  non-loopback origin.

## Out of scope

- A "public address" setting in admin or the database (SD1 chose the environment).
- Any QR code other than sign-up; a QR code for the wallet or the kassa.
- A poster, a print layout, text or logo in the QR code, other sizes, or a size setting.
- Hiding the block during market events, or only while a run is live (SD6).
- A different place for the block, or letting the organizer move or resize it.
- Showing the code or link as text on the screen.
- Role-filtering the `signup` message (SD4).
- Changing the sign-up flow, the code's rules, the player page, or B-09's downloads.
- Knowing or showing the venue's LAN address beyond `BB_PUBLIC_URL`.
- The pricing engine (`exchange/`), the golden fixtures and anything that feeds them.

## Acceptance criteria

**The address — SD1, SD2**

- **AC1.** When `BB_PUBLIC_URL` is `http://192.168.8.10/`, the system shall hold `public_url`
  `http://192.168.8.10`. When it is unset, `public_url` shall be null and boot succeeds. When it
  is not an absolute `http` or `https` URL, or has a path, query or fragment, boot shall fail
  with a `ConfigError`.
- **AC2.** When `public_url` is set, the link in the screen's QR code shall be
  `public_url + '/speler?code=' + encodeURIComponent(<code>)`, whatever address the koers page
  is open at, including `http://localhost/`. When it is unset, the link shall use the page's
  `window.location.origin`.
- **AC3.** When `public_url` is unset and the koers page is open at `localhost`, `*.localhost`,
  `127.x.x.x` or `[::1]`, the system shall show no block.

**The message — SD3, SD4, SD8**

- **AC4.** When admin saves the wallet settings, the system shall broadcast one `signup` message
  `{show_on_screen, signup_code, public_url}` with the stored values, with `version: null`, with
  or without a live run, to every connected socket of every role.
- **AC5.** When a client connects, replays after a `hello`, receives a snapshot, or sends a
  `resync_request`, the system shall also send it the current `signup` message as a unicast
  that does not move `seq`.
- **AC6.** When a `signup` message arrives with any `seq`, the client shall apply it without
  starting or waiting on a resync, and shall hold the latest one received.
- **AC7.** The `signup` model shall be closed (`extra="forbid"`); the generated types and the
  recorded fixture, parsed through Zod, shall include it, and the API-types drift step shall
  pass.
- **AC8.** When the server restarts, a screen that reconnects shall receive the stored state,
  not the state from before the restart.

**The switch — SD5**

- **AC9.** `GET /api/admin/wallet-settings` shall return `show_signup_on_screen`, false on a
  deployment that never set it; `PUT` shall store it and return it. A non-boolean shall be 422.
  Writes shall refuse while draining as today.
- **AC10.** The Aanmeldcode subsection shall show a checkbox "QR-code op het scherm" that saves
  the switch with the existing wallet settings and asks no confirmation. Changing or clearing the
  code shall still ask B-09's confirmation.

**The block — SD6, SD7, SD9, SD10, SD11**

- **AC11.** When the switch is on, a code is set and an address is known, the koers page shall
  show the block at the top left, left of the marquees, holding a QR code and the caption
  "Meld je aan".
- **AC12.** When the QR code is decoded, the result shall equal the link of AC2. It shall be
  drawn black on white at error correction `Q` with a 4-module quiet zone, from the same
  function B-09's preview uses, and shall be at least 96 px square.
- **AC13.** When the switch is off, or no code is set, or no address is known (AC3), the page
  shall show no block and no space for one.
- **AC14.** When there is no live run, or the run is closed, the block shall show alone at the top
  left. During a crash, bubble and correction it shall stay shown and unobstructed.
- **AC15.** At a viewport 700 px wide or less, the block shall not be shown.
- **AC16.** The block shall cover no price, tile, marquee text or event banner at 1920×1080 and
  1280×720, with the marquees filling the width to its right.
- **AC17.** When admin opens `/koers`, the page shall show the same block as a display key does.

**Live and offline — SD8, SD12**

- **AC18.** When admin saves a different code, the connected screen shall show the new QR code,
  with no reload and without ever drawing the old code after the message arrives. When admin
  clears the code or turns the switch off, the block shall go.
- **AC19.** When the WebSocket drops, the block shall stay as it was; when it reconnects, the
  block shall show what AC5 sent.
- **AC20.** When the page is served over plain HTTP from a non-loopback host, the block shall
  draw and nothing shall throw. *(e2e at `http://signup.test:<port>`, where `isSecureContext`
  is false, as `web/e2e/payments.spec.ts:32-50`.)*

**Boundaries**

- **AC21.** The diff shall touch nothing under `exchange/` or `tests/engine/golden/fixtures/`,
  and shall add no entry to `web/package.json` or `pyproject.toml` dependencies. The new
  migration shall be the only new file in `db/migrations/versions/`.
- **AC22.** B-09's tests shall pass unchanged in what they assert: admin's QR code, files and
  filenames keep the address admin is open at.
- **AC23.** `docs/design/realtime-protocol.md`, `docs/design/data-model.md`,
  `docs/runbooks/venue.md` and B-05's spec shall carry the changes named under "In scope".

## Verification

- **Python (pytest):**
  - `tests/unit`: `public_url` set, unset and malformed (AC1).
  - `tests/api`: the settings round trip, 422 and draining (AC9); the `signup` broadcast on a
    save, with and without a live run (AC4); the unicast after connect, replay, snapshot and
    resync, `seq` unmoved (AC5); the restart (AC8).
  - `tests/integration`: the migration up and down, the default false.
- **Web (vitest):** the block for every combination of switch, code and address, with
  `public_url` and with a loopback origin (AC2, AC3, AC13); the decoded link, `Q`, quiet zone,
  size (AC12); no run and closed run (AC14); the phone width (AC15); the store applying a
  `signup` out of order and during a resync (AC6, AC19); the checkbox and the unchanged
  confirm (AC10); the fixture through Zod (AC7).
- **e2e (Playwright), at `http://signup.test:<port>`:**
  1. Open `/koers` as a display key: no block (AC13).
  2. As admin save code `BORREL`: still none (switch off). Turn the switch on: the block appears
     on the open screen with no reload, and its decoded link is
     `http://signup.test:<port>/speler?code=BORREL` (AC11, AC12, AC18, AC20).
  3. Save `ANDERS` (confirm "Wijzigen"): the screen's QR code changes; open the decoded link
     in a new context and the player page's code field holds `ANDERS` (AC18).
  4. Start a crash from Manipulation: the block stays and stays readable (AC14).
  5. Reload the display: the block is there at once (AC5). Clear the code: it goes (AC18).
  6. Restart-style check: drop the socket and let it reconnect; the block matches the server's
     state (AC19).
- **Visual check (the owner's):** screenshots at 1920×1080 and 1280×720 with and without a
  promo image, and during a crash, confirm AC16.
- **The gate:** `./scripts/check.sh`, 13/13, output pasted. `git diff --stat main` shows nothing
  under `exchange/` and no dependency added (AC21), so `golden_linux.sh` and `engine-guardian`
  are not required.
- **Manual exit check (the owner's):**
  - on Render, turn the switch on and scan the big screen from an iPhone and an Android phone
    across the room;
  - at the next venue bundle, with `BB_PUBLIC_URL` set and the TV on the laptop at
    `http://localhost/`, scan the screen from a phone on the venue Wi-Fi and reach the player
    page with the code filled in.

## Exit condition

With the switch on and a sign-up code set, the koers screen shows a QR code at the top left that a
phone across the room scans straight onto the player page with the code filled in, at the venue
with the laptop driving the TV as well as on Render, and it follows the code live and hides itself
when sign-up is closed or the switch is off.
