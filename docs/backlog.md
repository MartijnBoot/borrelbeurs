# Feature backlog

Feature ideas for after the rebuild, gathered and ordered before any of them becomes a spec.
An item here is a thought worth keeping, not a commitment: nothing in this file is scheduled
until it goes through `/spec`.

    /backlog <idea>      brainstorm an idea, then add it here
    /backlog             show the order and pick what to do
    /backlog order       re-order the list
    /backlog spec B-nn   mark an item ready and hand it to /spec

## Order

Top is next. Every item that is not `specced` or `dropped` appears here exactly once.

| # | ID | Feature | Size | Status |
|---|---|---|---|---|
| 1 | B-07 | Price bounds on the Prijsstap grid | S | idea |
| 2 | B-08 | Short keys you can read aloud | S | idea |

## Items

<!--
Template — copy it below the last item, take the next free B-nn, never reuse a number.

### B-nn — <short title>

- **Status:** idea | ready | specced → `docs/specs/<file>.md` | dropped (<why>)
- **Added:** YYYY-MM-DD
- **Size:** S (a day or less) | M (a few tasks) | L (a phase of its own)

**Problem.** Who runs into what, and when — a real moment at a borrel, not a wish.

**Idea.** What would change, in their terms. Not how it is built.

**Why it matters.** What gets better, for whom, and what it costs us not to have it.

**Not this.** What it explicitly is not, or what would make it a failure even if it works.

**Open questions.** What `/spec` will have to settle. Fine to have many.

**Touches.** Areas likely involved (koers screen, bar, admin, engine, …) and any `D-nn` or ADR
it brushes against. A guess is fine; mark it as one.
-->

### B-01 — Settings that explain themselves

- **Status:** built → `docs/plans/phase-b-01-settings-explained.md` (spec:
  `docs/specs/phase-b-01-settings-explained.md`)
- **Added:** 2026-10-18
- **Size:** M (a few tasks) — a guess: ~25 settings over two pages, and each explanation has
  to be true to what the engine does

**Problem.** Coming back to the settings or manipulation page after weeks away, you no longer
remember what 🎚️ Drempel, ⚔️ Rivaliteit, 🧠 Geheugen (ρ), the idle settings or the a/d/s0/c
columns do, and the only way to find out is the manual. Other people, such as next year's
committee, have never seen the page and have nobody to ask.

**Idea.** Every setting on the settings page and the manipulation page gets a clearer name that
says what it does, and an info popup (hover or click) that says, in plain Dutch: what the
setting does, what you would see on the koers screen if you turn it up or down, and roughly what
value is normal. Someone new can understand the pages just by going through them.

**Why it matters.** You and whoever comes after you can set up and steer a borrel without the
manual and without breaking the prices by accident. Without it, the pages only work for whoever
still remembers v1.

**Not this.** (A guess, not contradicted.) No change to the pricing maths or to what a setting
does — names and explanations only. No separate help page or in-app manual. A failure, even if
it works: an explanation that sounds clear but is wrong about what the engine does — worse than
none.

**Open questions.**
- Hover or click — hover does not exist on a phone, and the admin pages have a mobile layout.
- The new names themselves; the Phase 6 spec's label table lists the current ones and gets
  updated.
- Do other places showing these names (analytics, exports, the v1 import) follow, or is this
  screen text only?
- Who checks each explanation against `exchange/`? Any doubt about the maths is the owner's.
- Does the existing manual change with it?
- Emoji: settled — the new names have none; icons are B-02.

**Touches.** (A guess.) `features/settings` (global, demand, bounds, drinks, theme, system),
`features/manipulation`, `components/ui/Field.tsx` (already shows a one-line hint), the label
table in `docs/specs/phase-6-admin.md`. `exchange/` read, never changed. No ADR.

### B-02 — Own pixel icons instead of emoji

- **Status:** built → `docs/plans/phase-b-02-pixel-icons.md` (spec:
  `docs/specs/phase-b-02-pixel-icons.md`)
- **Added:** 2026-10-18
- **Size:** M (a few tasks) — a guess: a set of ~20–30 icons, swapped in across five pages

**Problem.** Every page uses emoji as icons — settings, manipulation, bar, keys, and the crash
banner on the koers screen. They look different on every phone, laptop and browser, and they
are not BorrelBeurs's own.

**Idea.** All emoji leave all pages. Where an icon helps, it is a BorrelBeurs-made 8- or 16-bit
pixel icon that looks the same on every device.

**Why it matters.** The app gets one look of its own, on the big screen too, instead of whatever
the device's emoji font draws.

**Not this.** (A guess, not contradicted.) No downloaded icon pack or CDN — made for this app
and shipped with it (ADR 0006). Not an icon on every label for the sake of it: a spot that does
not need one just loses its emoji.

**Open questions.**
- 8-bit or 16-bit; one colour or full colour?
- Do icons follow the theme colours on the koers screen?
- Which spots keep an icon and which only lose the emoji?
- Does text the admin types (news messages) still allow emoji?
- Does the logo stay as it is?

**Touches.** (A guess.) Every `web/src/features` page with emoji, the shared UI components, the
koers screen's market-event layer, possibly theming (ADR 0005). Not the engine.

### B-03 — Brownian settings in Globale instellingen

- **Status:** built → `docs/plans/phase-b-03-brownian-settings.md` (spec:
  `docs/specs/phase-b-03-brownian-settings.md`)
- **Added:** 2026-10-18
- **Size:** S (a day or less) — a guess

**Problem.** To find the right market feel for a borrel, the owner experiments on dry runs
before setting up live games. The Brownian noise and the settings around it cannot be changed
from `/settings`: they stay at whatever the run was imported or created with, so one of the
biggest knobs is out of reach.

**Idea.** "⚙️ Globale instellingen" gains `bm_enabled`, `bm_sigma_y`, `bm_dt_minutes`,
`flow_vol_amp`, `flow_beta` and `y_clip`, edited and saved like the global settings already
there.

**Why it matters.** The market feel can only be found by trying settings; without these the
noise, and how strongly a busy bar amplifies it, cannot be tuned at all.

**Not this.** No change to the pricing maths or to any default; an existing run keeps its
values. Not the legacy `bm_sigma` (v1 maps it onto `bm_sigma_y`). `tick_interval_ms` and
`quote_grace_versions` stay not editable.

**Open questions.**
- The range and the Dutch label of each field.
- Editable on a live run, or on a draft only?
- What a mid-run change of `bm_dt_minutes` (the gate is measured from `last_bm_ms`) or of
  `y_clip` (prices already beyond the new cap) does to prices.

**Touches.** Settings web (`web/src/features/settings/GlobalSection.tsx`), `PATCH
/api/runs/{run_id}/config` validation. Reverses Phase 6 SD8's "Not editable" line and its
out-of-scope entry (`docs/specs/phase-6-admin.md`) — a spec decision, not an ADR. An
`engine-guardian` check that no maths moved (a guess).

### B-04 — Named setting profiles per type of game

- **Status:** built → `docs/plans/phase-b-04-setting-profiles.md` (spec:
  `docs/specs/phase-b-04-setting-profiles.md`)
- **Added:** 2026-10-18
- **Size:** M (a few tasks) — a guess

**Problem.** Different types of game want different settings. Once a good set is found on a
dry run, the only way to reuse it is to remember which past run had it and copy from that run
("kopieer drankjes uit", Phase 7 SD4).

**Idea.** Save a set of settings under a name ("rustige borrel", "wilde beurs") and pick a
profile when starting a new borrel.

**Why it matters.** Dry-run experiments become reusable per type of game, instead of being
buried in past runs.

**Not this.** Not a replacement for "kopieer drankjes uit": drinks still come from a past run.

**Open questions.**
- What a profile holds: the engine settings only, or also the candle interval and the
  demand switches?
- Global like the theme, or something else?
- Can the current run's settings be saved as a profile?
- Applied only when a borrel is created, or also to a draft or live run?
- What wins when both a profile and a run to copy from are picked?
- Rename and delete?

**Touches.** Settings web, the "Nieuwe borrel" form, `POST /api/runs`, probably a new table and
migration (a guess); Phase 7 SD4 (`copy_from_run_id` copies params). Depends on B-03 to be
worth much.

### B-05 — Player wallets with a QR code

- **Status:** built → `docs/plans/phase-b-05-player-wallets.md` (spec:
  `docs/specs/phase-b-05-player-wallets.md`)
- **Added:** 2026-10-18
- **Size:** L (a phase of its own) — a guess: a new kind of user, new tables, a camera
  library, two new pages

**Problem.** Players pay with a paper voucher: a 10×10 grid of 100 points (€10), where a €2,50
drink crosses off 25 points. Crew sell the vouchers and do the arithmetic on cards that are
already partly crossed off.

**Idea.** The landing page offers **Speler** or **Crew**. A player signs themselves up and gets
their own page on their phone with a QR code and their balance in euros. Crew go to the
existing pages with a key granted by an admin. A new **top-up page** scans a player's QR code
with the camera and adds €10 per top-up. The payment itself happens with crew, through the
existing payment system outside the app.

**Why it matters.** It replaces the paper voucher and its points with a balance that is always
right, and it is what B-06 builds on.

**Not this.** No payment inside the app. No points. No purchase history for players (a later
item). Render only, not the offline venue path. Nothing to do with the venue's own till.

**Open questions.**
- Player sign-up: what is asked (a name?), and what happens to the money when a phone is lost
  or the browser data is cleared.
- Does a balance carry over to the next borrel, and is leftover money ever refunded?
- Who may top up: admin only, bar crew too, or a new role?
- Undoing a wrong top-up.
- The QR-scanning library is a new dependency (owner's call), bundled with the app (ADR 0006).
- Offline later: the camera needs HTTPS, and the venue path has none (Phase 8 SD1).
- Personal data: how long player names are kept.

**Touches.** (A guess.) The landing page and routes, a new player identity next to the
display/bar/admin keys, new tables and a migration, a new top-up page. Not the engine.

### B-06 — Pay at the bar by scanning a player's wallet

- **Status:** built → `docs/plans/phase-b-06-wallet-payments.md` (spec:
  `docs/specs/phase-b-06-wallet-payments.md`)
- **Added:** 2026-10-18
- **Size:** M (a few tasks) — a guess: the server already accepts multi-line orders

**Problem.** For a group order on one voucher, the bartender works out the points in their
head, crosses them off, then picks up a phone and enters every drink again on the bar page.
At busy moments this is the bottleneck.

**Idea.** The bartender builds the whole order on the bar page, scans the player's QR code, and
the order is charged in one go: the total comes off the wallet, and the orders go into the
system and the engine as any order does today. During the event only vouchers are accepted, so
every bar order becomes a wallet order.

**Why it matters.** No arithmetic, no pen, no entering things twice, and a shorter queue at the
bar. Orders reach the engine the moment they are paid (a guess: today they can arrive late, in
batches).

**Not this.** No change to the pricing maths: orders reach the engine exactly as they do now.
Nothing to do with the venue's own till, which staff still fill in by hand. A failure, even if
it works (a guess): a wallet charged twice, charged a price nobody was shown (route invariant
5), or someone else's money spent from a screenshot of their QR code.

**Open questions.**
- Too little balance: refuse the whole order, or never let a balance go below zero?
- Prices moving between building the order and the scan (ADR 0008's grace rule).
- Building a multi-drink order reverses Phase 5 SD5 (one drink per tap, no carts).
- Undoing a mis-tap now costs a player real money; Phase 5 has no voids.
- Can crew drinks or a dry run still order without a scan?

**Touches.** (A guess.) The bar page, the order path (`app/runtime/orders.py`: the deduction in
the same transaction as the order), the wallet tables from B-05. `exchange/` read, never
changed. Depends on B-05.

### B-07 — Price bounds on the Prijsstap grid

- **Status:** idea
- **Added:** 2026-10-18
- **Size:** S (a day or less) — a guess; more if existing runs need fixing up

**Problem.** A Minimumprijs or Maximumprijs can be any whole number of cents, but the quoted
price is rounded to the Prijsstap (`exchange/pricing.py:32-42`). With Minimumprijs 1,24 on a
0,10 step the bar charges 1,20, below the minimum. The engine's "unstick" rule only fires
when the quote sits exactly on the bound (`exchange/steps.py:113-130`), so after a Marktcrash
such a drink stayed on the floor for 30 straight orders where an on-grid bound leaves it on
the first (measured by `engine-guardian` while specifying B-01, 2026-10-18). B-01's popups
now warn about it; nothing prevents it.

**Idea.** The settings page only accepts bounds that are a multiple of the Prijsstap, so a
bound is a price the bar can actually charge.

**Why it matters.** The minimum and maximum mean what they say, and a crash does not strand a
drink at the bottom for half the evening.

**Not this.** No change to the pricing maths; the rounding and the unstick rule stay v1's.

**Open questions.**
- Reject an off-grid bound, or round it on save (and which way)?
- What a live Prijsstap change does to bounds that are then off-grid: refuse the change, or
  move the bounds too (and with Phase 6 SD9's hold rule, in which order)?
- Existing runs and the v1 import with off-grid bounds: leave, warn, or fix up?
- The add-drink defaults and copied drinks ("kopieer drankjes uit").

**Touches.** (A guess.) Drink and config validation (`app/runtime/drinks.py`,
`app/runtime/config.py`), the Min/Max/Startprijs and Drankjes forms, B-01's E17/E19 texts.
`exchange/` read, never changed. Reverses nothing in an ADR; Phase 6 SD8's ranges change.

### B-08 — Short keys you can read aloud

- **Status:** idea
- **Added:** 2026-10-24
- **Size:** S (a day or less) — a guess: only how keys are made and typed changes, not who may
  do what

**Problem.** A key is about 50 characters (`bb_<id>_` plus 43 random characters). Getting one
onto your own phone and copying it in is too much hassle; reading one aloud for a crew member
to type in is impossible.

**Idea.** Every key, admin keys included, is 9 characters: short enough to read aloud for
someone to type in. (A guess: no look-alike characters such as `0`/`O` or `1`/`l`, and upper
or lower case does not matter.)

**Why it matters.** Handing a bar or display key to crew at the borrel takes seconds, not a
copy-paste between devices — while the admin pages stay closed to anyone not given an admin
key.

**Not this.** (A guess, not contradicted.) No usernames or passwords, no QR code or login link,
no change to the roles or to what each key opens. The protection around keys stays: login tries
limited per IP, keys stored only as a hash, the 24-hour session. A failure, even if it works:
a short key that lets someone guess or try their way into the admin pages.

**Open questions.**
- Do the 9 characters include the part that tells the server which key it is (today the
  `<id>`), or does that come on top? Without it, login has to check every stored key
  (`docs/design/architecture.md:199`).
- Which characters, and how laid out: grouped for reading aloud (e.g. `K7M-4QX-9PR`)? A missing
  or extra dash accepted?
- Is 9 enough for admin with today's 10 tries per minute per IP (a guess: about 45 bits, far
  out of reach), or does it also need a lockout, given Render sees many IPs? `/spec` shows the
  numbers.
- Do existing long keys keep working, or is every key reissued?

**Touches.** (A guess.) `app/api/security.py` (minting and parsing keys), `app.cli.keys`, the
Toegangssleutels page (`web/src/features/keys/KeysSection.tsx`), the login page,
`scripts/smoke.py` / `BB_SMOKE_KEY`. Changes Phase 3 SD5/SD6 and Phase 6 SD30 — spec
decisions, not an ADR. Probably no migration. Not the engine.

## Deferred work

Not features: work the rebuild left unfinished on purpose. It stays out of the `Order`
table above. Each item says where it came from.

### Offline venue path: rehearse it (from Phase 8 H2 and H3 step 1)

Deferred 2026-10-17 because the hardware (travel router with no uplink, venue laptop) is not
available. The software is built and merged (Phase 8 T-tasks, `docs/runbooks/venue.md`); what is
missing is the evidence that it works in the real world:

- A mock borrel offline, at least 1 hour, two bar phones and one display: drink added mid-run,
  "Sluit app" then `start.cmd`, hard power-off and restart, laptop clock +1 h and back, manual
  export on a phone, dumps and auto exports accruing, run closed, restore of the newest dump
  (steps and evidence: `docs/plans/phase-8-human-steps.md`, H2). Record:
  `docs/runbooks/rehearsals/<date>-mock-borrel.md`.
- Venue rollback rehearsal (H3 step 1), from bundle n+4 to n+3, timed against 5 minutes.
- Until this is done, the Phase 8 exit ("runs on Render *and* offline; mock borrel passed") is
  not met, and the offline path is unproven in practice (only the image drills in `tests/image`).
