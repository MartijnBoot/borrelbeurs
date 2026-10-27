# Spec: B-07 — Price bounds on the Prijsstap grid

Status: Approved · Depends on: Phase 6 (SD5–SD9: draft and live config and drink writes, the
hold on a bounds or step change), Phase 7 (SD4: "kopieer drankjes uit"), B-01 (E1, E17, E19 and
their guard tests), B-04 (profiles carry `step_quant`; loading onto a draft; a profile on
Nieuwe borrel) · Fixes: no open defect · Amends: B-01 SD11, Phase 6 SD8 (per-drink bounds) ·
Backlog: [B-07](../backlog.md)

Line references are to `main` at `8f47ec5`.

## Problem

A Minimumprijs or Maximumprijs can be any whole number of cents, but every price the bar charges
is rounded to the Prijsstap. So a bound off that grid is not a price the bar can charge, and it
breaks the engine's rule for getting a drink off its bound:

- **The quote is rounded to the Prijsstap.** `prices_from_y` maps `y` into `[p_min, p_max]` and
  rounds the result to `step_quant` (`exchange/pricing.py:32-42`). With Minimumprijs 1,24 on a
  0,10 step, the lowest quote is 1,20: below the minimum.
- **The unstick rule needs the quote exactly on the bound.** A drink at its bound that orders
  push away from moves one step only when `|p_q − lo| ≤ 1e-9` (`exchange/steps.py:113-130`).
  With an off-grid bound that is never true, so after a Marktcrash such a drink stayed on the
  floor for 30 straight orders, where an on-grid bound leaves it on the first (measured by
  `engine-guardian` while specifying B-01, 2026-10-18).
- **Nothing checks a bound against the step.** A drink write checks only `p_min_cents ≥ 0` and
  `p_min < p0 < p_max` on the resulting row (`app/runtime/drinks.py:132-147`, `:223-228`). The
  `step_quant` check is about the step alone (`app/runtime/config_patch.py:55-71`). The bound
  forms check only the order of the three prices
  (`web/src/features/settings/BoundsSection.tsx:73-85`).
- **A step can change under existing bounds.** A Prijsstap save on a live run holds every
  active quote (`app/runtime/config.py:419-424`, Phase 6 SD9) but leaves the bounds as they
  are. Loading a profile onto a draft (`app/runtime/config.py:376-394`), or starting a Nieuwe
  borrel with a profile and copied drinks (`app/db/runs.py:506-523`), takes the profile's step
  and keeps the drinks' bounds. The v1 import stores whatever bounds and step the file has
  (`app/cli/import_v1.py:44-57`).
- **B-01 only warns.** E17 and E19 advise "Kies hem als veelvoud van de Prijsstap"
  (`docs/specs/phase-b-01-settings-explained.md:302`, `:318`), and B-01 SD11 left the rule
  itself to this item (`:119-123`).

v1's real config (`tests/fixtures/v1/config/exchange_config.json`) has every bound on its 0,10
grid. No defect in the register is about this.

## Decisions

Settled at the spec interview (2026-10-27). SD1–SD6 were put to the owner one at a time, each
with a recommendation; the owner chose the recommendation for each, except SD2. SD7–SD12 follow
from those answers or from the code, and were stated, not asked. The planner must not reopen
any of them.

- **SD1 — An off-grid bound is refused, not rounded.** A write that sets `p_min_cents` or
  `p_max_cents` to a value that is not a whole multiple of the Prijsstap is 422 naming that
  field, and nothing is stored. The message names the two nearest grid points: "Moet een
  veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30." What is stored is always what the admin
  typed. "On the grid" is decided in whole cents: `p_cents % step_cents == 0`, with
  `step_cents = round(step_quant × 100)` (the step is already a whole number of cents,
  `app/runtime/config_patch.py:55-61`). 0 is always on the grid.
- **SD2 — The Startprijs is not bound to the grid.** `p0_cents` stays any whole number of cents
  strictly between the bounds, rounded at the start as today. (The owner chose this over the
  recommendation to include it.)
- **SD3 — A Prijsstap change moves the bounds inward, in the same save.** When `step_quant`
  changes, every *active* drink's bound that is off the new grid moves inward to it:
  Minimumprijs up to the next multiple, Maximumprijs down to the previous one. A bound already
  on the new grid does not move. This happens in the same transaction and the same revision as
  the step change, on a draft and on a live run.
  - **Live:** it is one config transition (Phase 6 SD7). The hold of SD9 runs once, from the old
    spec (old step, old bounds) to the new spec (new step, moved bounds), over every active
    slot, as a step change already does; so every quote stays where it was, clamped into the
    new bounds and on the new grid, and every running jump is cancelled.
  - **A removed drink's bounds are not moved.** It is masked and never quoted.
  - **The page warns first.** Before sending a Prijsstap change, Globale instellingen lists the
    bounds that will move, from its own config document, in a confirm dialog: "Prijsstap 0,25
    opslaan? Deze grenzen schuiven mee:" and one line per bound, "Bier: Minimumprijs 1,60 →
    1,75". "Opslaan" sends; "Annuleren" sends nothing. When no bound moves, there is no dialog.
    The server recomputes the moves from the rows it reads inside the transaction; the dialog
    is advice, the server's result is what is stored.
- **SD4 — A move that leaves a drink with no room refuses the whole save.** When a drink's moved
  bounds would no longer satisfy `p_min < p0 < p_max` (the Startprijs falls outside, or the
  bounds meet or cross), the whole write is 422 and nothing is stored, not even the other
  fields of the same save. The fault is on `step_quant` and names each such drink: "Past niet
  bij Bier: de grenzen worden 1,25–2,75 en de Startprijs 1,22 valt daarbuiten." or "Past niet
  bij Fris: de grenzen worden 2,00–1,50." The admin fixes that drink first.
- **SD5 — A profile's Prijsstap moves bounds the same way, with no extra preview.** Loading a
  profile onto a draft, and Nieuwe borrel with a profile, apply SD3 and SD4 to the draft's
  drinks under the profile's step. The existing "Dit vervangt de instellingen van deze borrel."
  confirm stays as it is; the moved bounds are visible in the drink rows afterwards. A
  collision is refused as in SD4, and the page shows the message naming the drink, not the
  generic "valt buiten de toegestane waarden".
- **SD6 — A bound already stored off the grid is kept, warned about, and checked only when
  sent.** No migration and no fix-up at deploy; no price moves when this ships.
  - The Min/Max/Startprijs row shows, under each off-grid bound, "Niet op de Prijsstap: kies
    1,20 of 1,30." The row still saves.
  - SD1's check applies only to a bound present in the request. Editing only the Startprijs, or
    only the other bound, of such a drink succeeds and leaves the off-grid bound as it is.
  - A Prijsstap change (SD3), a profile load (SD5) or a copy into a Nieuwe borrel (SD9) moves
    it inward like any other bound (SD8).
- **SD7 — The v1 import moves bounds inward and says so.** `app.cli.import_v1` applies SD3 and
  SD4 to the file's drinks under the file's `step_quant`, before the database is opened. A
  collision is invalid input: exit 2, nothing written, the drink named. Each moved bound is
  printed to **stderr** ("import_v1: Bier: p_min 1,24 → 1,30"), so stdout stays the bare
  `run_id` that scripts read.
- **SD8 — What triggers a move.** Bounds are moved only on the paths named here: a write whose
  merged `step_quant` differs from the stored one (SD3), a profile load onto a draft (SD5),
  every Nieuwe borrel that copies drinks (SD9), and the v1 import (SD7). A profile whose step
  equals the draft's still moves that draft's stored off-grid bounds: the load replaces the
  settings wholesale and the result is always on the grid. A plain save of other global
  settings never moves a bound.
- **SD9 — Every Nieuwe borrel that copies drinks starts on the grid.** "Kopieer drankjes uit",
  with or without a profile, applies SD3 and SD4 to the copied drinks under the new draft's
  final step (the profile's, else the source run's). A collision refuses the create, naming the
  drink, nothing written. A copied drink's other columns are copied unchanged.
- **SD10 — The forms check before sending.** The Min/Max/Startprijs rows and the add-drink form
  check SD1 in the browser and show the server's message under the field; the server stays the
  authority and checks every write.
- **SD11 — B-01's texts change; nothing else on the page does.** E1, E17 and E19 are replaced
  as below; the guard test that pins every "Toegestaan" against the validation
  (`tests/unit/test_setting_explanations_values.py`) covers the new wording. B-01 SD11 ("told,
  not forbidden") is superseded by this item.
- **SD12 — No maths change, no schema change.** `exchange/` is read, never changed: the
  rounding, the unstick rule and `hold_quoted_prices` stay as they are. Bounds stay integer
  cents on `drink`; a move is an ordinary update of those columns. No migration.

### The texts (SD11)

Shown verbatim, one paragraph per line, as B-01's table is. Unchanged paragraphs are repeated
for completeness.

**E1 — `step_quant`.** **Prijsstap (€)**

> De prijs op het bord en aan de bar is altijd een veelvoud van dit bedrag. De grafieken lopen per cent en kunnen tussen de stappen door bewegen. Ook de Doelprijs van een sprong wordt hierop afgerond. Minimumprijs en Maximumprijs zijn ook een veelvoud van de Prijsstap: verander je de stap, dan schuiven ze mee naar binnen, de Minimumprijs omhoog en de Maximumprijs omlaag.
> Hoger: grotere stappen, en een prijs blijft vaker even staan. Lager: fijnere bewegingen.
> Eerste borrel: 0,10. Toegestaan: meer dan 0 en hoogstens 5, in hele centen; niet als een drankje daardoor geen ruimte meer heeft tussen Minimumprijs, Startprijs en Maximumprijs.
> Tijdens de borrel: elke koers blijft staan, afgerond op de nieuwe stap en binnen Minimumprijs en Maximumprijs. Alle lopende prijssprongen stoppen, ook die van een marktgebeurtenis; de melding van een marktgebeurtenis blijft staan.

**E17 — `p_min_cents`.** **Minimumprijs (€)**

> De koers van dit drankje komt nooit lager dan de Minimumprijs. Een Marktcrash zakt hierheen. Hoe dichter een prijs bij de Minimumprijs of Maximumprijs, hoe minder ver hij per stap beweegt.
> Toegestaan: 0 of meer, een veelvoud van de Prijsstap, en lager dan de Startprijs.
> Tijdens de borrel: de huidige koers blijft staan, binnen de nieuwe grenzen en op de Prijsstap. Een lopende prijssprong op dit drankje stopt, ook die van een marktgebeurtenis.

**E19 — `p_max_cents`.** **Maximumprijs (€)**

> De koers van dit drankje komt nooit hoger dan de Maximumprijs. Een Prijsbubbel stijgt hierheen. Hoe dichter een prijs bij de Minimumprijs of Maximumprijs, hoe minder ver hij per stap beweegt.
> Toegestaan: een veelvoud van de Prijsstap, hoger dan de Startprijs.
> Tijdens de borrel: de huidige koers blijft staan, binnen de nieuwe grenzen en op de Prijsstap. Een lopende prijssprong op dit drankje stopt, ook die van een marktgebeurtenis.

Bron for all three: as B-01's, plus this spec's SD1, SD3 and SD4. `engine-guardian` re-checks
"komt nooit lager/hoger" against `exchange/pricing.py:32-42` during the build (B-01 SD8.2).

## In scope

- **Server:**
  - the on-grid check of SD1 on drink add and edit (`app/runtime/drinks.py`), on a bound
    present in the request only (SD6), with SD1's message and the two neighbours;
  - one shared helper that moves a set of drinks' bounds inward to a step and reports each move
    and each collision (SD3, SD4), used by every path in SD8;
  - the draft and live config writes (`app/runtime/config.py`): moved bounds in the same
    transaction and revision; on live, the spec rebuilt with the moved bounds before the single
    hold over every active slot (SD3);
  - `load_profile_onto_draft` and `create_run` (`app/db/runs.py`) applying the helper (SD5,
    SD9); a collision is 422 naming the drink, nothing written;
  - `app.cli.import_v1` / `app/cli/v1_files.py` applying it before the database is opened, the
    moves on stderr, a collision exit 2 (SD7).
- **Web:**
  - the Prijsstap confirm dialog listing the bounds that will move (SD3), and the SD4 message
    under Prijsstap;
  - the SD1 check and message in the Min/Max/Startprijs rows and the add-drink form (SD10), and
    the off-grid warning on stored bounds (SD6);
  - the profile-load and Nieuwe borrel error naming the drink (SD5, SD9);
  - E1, E17 and E19 in `web/src/features/settings/explanations.json` (SD11);
  - their component tests and a Playwright flow.
- **Guards:** the B-01 text and range tests pin the new E1, E17 and E19.
- **Documents:**
  - a note on Phase 6 SD8's per-drink bounds (`docs/specs/phase-6-admin.md`, the "Per drink"
    list): bounds are a multiple of the Prijsstap since B-07, and a Prijsstap change moves them;
  - a note on B-01 SD11 (`docs/specs/phase-b-01-settings-explained.md:119-123`) and on E1, E17,
    E19 pointing here.

## Out of scope

- Any change to the pricing maths: the rounding, the unstick rule, `hold_quoted_prices`,
  `quantize_step`'s round-half-to-even. `exchange/` is read, never changed.
- Putting the Startprijs on the grid (SD2), or a minimum distance between the bounds beyond what
  `p_min < p0 < p_max` with on-grid bounds already gives (at least one step).
- Rounding a typed bound for the admin (SD1), or offering a "snap to grid" button.
- A migration, a deploy-time fix-up, or any change to an ended run (SD6). Fixing a stored
  off-grid bound by any path but those in SD8.
- Moving the Startprijs to resolve a collision (SD4): the save is refused instead.
- A bound preview on profile load or Nieuwe borrel (SD5).
- The manipulation page's Doelprijs, a market event's targets, or any other price that is not a
  stored bound: they keep being rounded as today.
- Profiles themselves: a profile stores a step and no bounds, so nothing about saving one
  changes.
- `bar_price_cents` (Normale barprijs): not quoted, not on the grid.
- Any change to E2–E16, E18, E20 and later rows.

## Acceptance criteria

**The bound check — SD1, SD6, SD10**

- **AC1.** When a drink add or edit sends `p_min_cents` or `p_max_cents` that is not a whole
  multiple of the run's Prijsstap in cents, the system shall return 422 naming that field, with
  the two nearest grid points in the message, and store nothing. On a 0,10 step: 124 is refused
  ("1,20 of 1,30"), 120 and 0 are accepted; on a 0,25 step, 150 and 175 are accepted, 160 is
  refused ("1,50 of 1,75").
- **AC2.** When a drink edit sends only `p0_cents`, or only one bound, for a drink whose other
  bound is stored off the grid, the system shall accept the write and leave the unsent bound
  unchanged.
- **AC3.** When a drink is added or edited with an off-grid Startprijs strictly between on-grid
  bounds, the system shall accept it (SD2).
- **AC4.** When the admin types an off-grid bound in a Min/Max/Startprijs row or the add-drink
  form and saves, the page shall show SD1's message under that field and send nothing.
- **AC5.** When a drink's stored bound is off the grid, its Min/Max/Startprijs row shall show
  "Niet op de Prijsstap: kies x of y." under that bound, and the row shall still save.

**A Prijsstap change — SD3, SD4, SD8**

- **AC6.** When `step_quant` is changed on a draft, the system shall, in the same transaction and
  the same revision, move every active drink's off-grid bound inward to the new step (Minimum up,
  Maximum down) and leave every on-grid bound and every removed drink unchanged.
- **AC7.** When `step_quant` is changed on a live run, the system shall commit one config
  transition in which the bounds are moved as AC6 and every active quote is held under the new
  bounds and step (SD9's clamp, re-quantise, refit), every running jump cancelled; the
  transition's `price_tick` shall carry the held prices, and each lies within its drink's new
  bounds and on the new grid.
- **AC8.** When a moved drink would no longer satisfy `p_min < p0 < p_max`, the system shall
  return 422 on `step_quant` naming each such drink with SD4's message, and store nothing of
  the request, including its other fields; on a live run no transition is taken.
- **AC9.** When a config write changes other settings but not `step_quant`, the system shall
  move no bound, including a stored off-grid one.
- **AC10.** When the admin changes Prijsstap on the page and at least one bound would move, the
  page shall show SD3's dialog listing each moving bound with its old and new value before
  sending; "Annuleren" shall send nothing. When no bound would move, the page shall send
  without a dialog.
- **AC11.** When the app restarts after a live Prijsstap change, the run shall have the moved
  bounds and the new step.

**Profiles, Nieuwe borrel and the import — SD5, SD7, SD9**

- **AC12.** When a profile is loaded onto a draft, the system shall move the draft's active
  drinks' bounds onto the profile's step as AC6, including when the step is unchanged; a
  collision shall be 422 naming the drink, nothing written, and the page shall show that
  message.
- **AC13.** When a Nieuwe borrel copies drinks from a past run, with or without a profile, every
  copied drink's bounds shall be on the new draft's step; a collision shall refuse the create
  naming the drink, with no run written.
- **AC14.** When `import_v1` reads a config with an off-grid bound, it shall store the bound moved
  inward and print each move to stderr, with stdout the bare `run_id`; on a collision it shall
  exit 2 naming the drink and write nothing. v1's real config
  (`tests/fixtures/v1/config/exchange_config.json`) shall import with no move.

**What it is for**

- **AC15.** Given a live drink with on-grid bounds held at its Minimumprijs after a Marktcrash
  has ended, when one order for that drink is placed, its quote shall move off the floor at that
  order (the unstick rule fires). The same test with an off-grid Minimumprijs shows the old
  behaviour, as the evidence of the difference.

**The texts — SD11**

- **AC16.** E1, E17 and E19 shall show the texts above exactly; the guard tests shall pin them,
  and every other row shall be unchanged.

**No maths change — SD12**

- **AC17.** `exchange/` shall be unchanged by this item, and the golden fixtures shall replay
  unchanged.

## Verification

- **API (pytest, `tests/api/test_drinks.py`, `tests/api/test_config.py`):** on-grid accepted and
  off-grid refused with the neighbours, on 0,10 and 0,25 steps (AC1); a partial edit of a drink
  with a stored off-grid bound (AC2); an off-grid Startprijs (AC3); a draft step change moving
  bounds, removed drink untouched (AC6); a collision refusing the whole patch (AC8); a non-step
  write moving nothing (AC9); profile load and Nieuwe borrel with and without a profile (AC12,
  AC13).
- **Integration (pytest, live market):** a live step change: one transition, moved bounds, held
  quotes within the new bounds and on the new grid, jumps cancelled (AC7); a collision taking no
  transition (AC8); a restart (AC11); a crash, then one order, on an on-grid and an off-grid
  floor (AC15).
- **CLI (pytest):** the import on a crafted off-grid config, the stderr lines and stdout, a
  collision exit 2, and the v1 fixture with no move (AC14).
- **Vitest:** the forms' SD1 check (AC4); the off-grid warning (AC5); the Prijsstap dialog and
  its absence (AC10); the profile-load message (AC12); the texts (AC16).
- **Playwright (in the gate):** on `/settings` with a drink at 1,50–3,10, change Prijsstap from
  0,10 to 0,25, see the dialog list "Maximumprijs 3,10 → 3,00", confirm, reload, see 3,00; type
  Minimumprijs 1,60 and see the refusal.
- **The gate:** `./scripts/check.sh` green; `bash scripts/golden_linux.sh` green (AC17);
  `engine-guardian` on the diff reports no maths change and confirms E17/E19's "nooit
  lager/hoger".
- **Manual (exit check, the owner):** on a dry run with the board open, a drink with on-grid
  bounds is crashed, then ordered once, and leaves the floor on that order; Prijsstap 0,10 →
  0,25 shows the dialog, and the board keeps every price within the new bounds.

## Exit condition

Every Minimumprijs and Maximumprijs written from now on is a price the bar can charge — typed
bounds off the Prijsstap are refused and a step change moves them inward — so a crashed drink
leaves its floor on the first order, and the pricing maths has not moved.
