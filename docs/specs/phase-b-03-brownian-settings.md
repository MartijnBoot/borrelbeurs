# Spec: B-03 — Brownian settings in Globale instellingen

Status: Approved · Depends on: Phase 6 (SD7–SD9: live config writes), B-01 (the (i) popups,
their table and its guard test), B-02 (headings) · Fixes: no open defect · Backlog:
[B-03](../backlog.md)

Line references are to `main` at `b9a83c9`.

## Problem

To find the right market feel for a borrel, the owner experiments on dry runs (a live run nobody
drinks at) before setting up live games. The noise is one of the biggest knobs, and it cannot be
reached:

- **The engine reads six noise settings on every tick, and the API refuses all six.**
  `apply_brownian` reads `bm_enabled`, `bm_dt_minutes`, `bm_sigma_y`, `flow_vol_amp` and
  `y_clip` (`exchange/steps.py:271-302`); `apply_orders` reads `flow_beta`
  (`exchange/steps.py:53-56`). `ParamsPatch` lists none of them and forbids extra keys
  (`app/runtime/config.py:112-135`), so each is a 422. That is Phase 6 SD8's "Not editable"
  line (`docs/specs/phase-6-admin.md:212-213`) and out-of-scope entry (`:537`).
- **The page does not show them.** Globale instellingen edits ten fields
  (`web/src/features/settings/GlobalSection.tsx:23-34`). The config document does not carry
  the six either (`ParamsData`, `app/runtime/config.py:150-167`).
- **They stay at whatever the run was created with.** `DEFAULT_PARAMS` overrides none of
  them (`app/db/runs.py:58-70`), so a first borrel gets `Params()`'s v1 values: on, 0,18, 1,
  0,7, 0,25, 6 (`exchange/spec.py:50-56`). Every later borrel copies a previous run's params
  (`app/db/runs.py:462-464`), so the same values are carried along forever.
- v1 accepted all six through its config API with no range checks
  (`legacy/v1/backend/api.py:83-89`, `:429-441`, tag `v2-rebuild-complete`) and never put
  them on a screen.

No defect in the register is about these settings. D-23 (`flow_ema` never decays in time) is
closed by [ADR 0012](../adr/0012-flow-ema-keeps-v1-semantics.md) and stays closed: making
`flow_beta` editable changes how fast `flow_ema` follows orders, not the fact that time does
not decay it.

## Decisions

Settled at the spec interview (2026-10-24). SD1–SD9 were put to the owner one at a time, each
with a recommendation, and the owner chose it. SD10–SD12 follow from the code or from B-01's
rules and were stated, not asked. The planner must not reopen any of them.

- **SD1 — Editable on a draft and on a live run**, like every other global setting (Phase 6
  SD7). A dry run is a live run, and the noise only runs on a live market; draft-only would
  make every try a new borrel.
- **SD2 — A live change moves no price at the moment of saving.** It is an ordinary Phase 6
  SD7 config transition (`write_live_config`, `app/runtime/config.py:429-462`): one
  `mutate("config")`, `version + 1`, a `price_tick` of source `config`, a `ConfigChanged`. It
  is not a `step_quant` change, so no `hold_quoted_prices` runs and `y` is untouched. Each
  setting then acts at the engine's next step, as the code already does:
  - **`bm_enabled` off:** no draw from the next tick on. On again: one draw at the next tick
    or order batch, sized by `bm_dt_minutes`, nothing caught up (`exchange/steps.py:284-288`).
  - **`bm_dt_minutes`:** the gate is measured from `last_bm_ms`. Lowered below the time since
    the last draw, the next tick or order batch draws once, sized for the new value, and
    nothing is caught up.
  - **`bm_sigma_y`, `flow_vol_amp`:** the next draw is larger or smaller.
  - **`flow_beta`:** the next order batch moves `flow_ema` by the new fraction. No price
    moves.
  - **`y_clip` lowered:** at the next noise draw, every active drink beyond the new limit is
    cut back to it in one go (`exchange/steps.py:301`). That can be a visible jump on the
    board. v1's maths, unchanged; the explanation says so (E39). No clip at the moment of
    saving, and a live `y_clip` change is not refused.
- **SD3 — The ranges.** Every value must be strict and finite (NaN, ±∞, a string or a bool is
  422), as SD8's existing fields are.

  | Field | Range | Why |
  |---|---|---|
  | `bm_enabled` | bool | — |
  | `bm_sigma_y` | ≥ 0 | 0 draws nothing (`exchange/steps.py:290-291`). No upper limit, like `eta`, `lambda_orders` and `idle_strength` (SD9). |
  | `bm_dt_minutes` | 0,05–10 | The ticker runs once a second; below a tick the draw would still come once a second but be sized smaller, quietly weakening the noise. 0,05 = 3 s is clear of it. 10 matches `refresh_minutes`. Any decimal is allowed (SD8). |
  | `flow_vol_amp` | ≥ 0 | 0: busy drinks get no extra noise. Negative has no meaning. |
  | `flow_beta` | 0–1 | **Required, not taste:** above 1, `flow_ema` can go below −1, `log1p` returns NaN, and the drink's price becomes NaN. |
  | `y_clip` | 1–20 | Below 1 the noise holds every price near the middle. Above about 20,7 it cannot cut even a jump's bound target (`exchange/steps.py:164-165`). See SD7 for the low end. |

  Ranges include both ends (Phase 6 SD8's convention). The legacy `bm_sigma`,
  `tick_interval_ms` and `quote_grace_versions` stay not editable: still 422.
- **SD4 — Where:** the end of ⚙️ Globale instellingen's grid, after Kaarsbreedte, in this
  order: Willekeurige ruis (a switch), Sterkte ruis, Ritme ruis (min), Extra ruis bij drukte,
  Reactiesnelheid drukte, Grens ruis. Behind the existing "Opslaan instellingen" button, with
  the section's existing save rules (only changed fields sent, "Niets te wijzigen", a 422
  under its field, "Overnemen" on a server change). No sub-heading, no new section, no new
  icon.
- **SD5 — With Willekeurige ruis off, the other five stay editable.** Each explanation says
  it does nothing then, as B-01 does for the demand columns. Nothing is greyed out.
- **SD6 — The names** (no emoji, B-01 SD6; units in brackets as B-01 does):

  | Field | Name |
  |---|---|
  | `bm_enabled` | Willekeurige ruis |
  | `bm_sigma_y` | Sterkte ruis |
  | `bm_dt_minutes` | Ritme ruis (min) |
  | `flow_vol_amp` | Extra ruis bij drukte |
  | `flow_beta` | Reactiesnelheid drukte |
  | `y_clip` | Grens ruis |

- **SD7 — `y_clip` keeps 1 as its floor, and its explanation tells the trade-off.**
  `engine-guardian` measured (2026-10-24, a €1–€3 drink, Prijsstap 0,10) that `y_clip` has a
  visible effect only below about 3,7, and that is where Marktcrash and Prijsbubbel stop
  holding a drink on its bound: at the next noise draw after landing, the drink is cut back to
  the limit, and during the event it flashes back for one tick per draw, which leaves a wick
  in the candles (`app/runtime/candles.py:24-26`, `:92`). A floor of 4 would leave a knob
  with no visible effect. A drink with more than about €20 between its bounds is already
  affected at 6. v1's maths, unchanged.
- **SD8 — `bm_dt_minutes` takes any decimal in its range.** Draws happen on whole-second
  ticks, so a value that is not a whole number of seconds is effectively rounded up, while
  the draw stays sized for the value set. At worst, just above 3 s, the noise per minute is
  about 25 % lower in variance (about 13 % in size). Whole seconds and whole minutes are
  exact. The explanation keeps "ongeveer".
- **SD9 — `bm_sigma_y` has no upper limit.** A cap would stop a typo of 18 but not of 1,8,
  and no other force setting has one.
- **SD10 — The six get B-01 popups, rows E34–E39 below.** B-01 gives an (i) to every control
  that changes prices (B-01 SD2) and makes its table the source of truth (SD3); these are such
  controls. B-01's 33 become 39: SD2's scope, AC10's "outside the 33", and the guard test's
  count (`tests/unit/test_setting_explanations_values.py:267`) follow. The table below is
  this spec's part of that source of truth: the build copies each name and text verbatim, and
  a test pins them. B-01 SD7's "Tijdens de borrel" rule is widened for three rows (E34, E36,
  E39), where a live change behaves in a way the room would not guess.
- **SD11 — E9 names the noise's clock.** B-01's E9 (Ritme stille drankjes) says "de ruis
  loopt op een eigen klok"; that control now exists. Its first paragraph changes from "…, en
  de ruis loopt op een eigen klok. …" to "…, en de ruis loopt op een eigen klok (Ritme ruis).
  …". Nothing else in E1–E33 changes.
- **SD12 — No migration and no stored-shape change beyond the document.** `run.params` is
  JSON and already holds all six. `ParamsData` (the `GET` body and every new revision) gains
  the six; stored revisions keep their shape, and nothing reads them back
  (`app/runtime/config.py:316-327`). The `config` and snapshot messages already send every
  param (`app/realtime/messages.py:144-159`). Default values do not change.

**After `engine-guardian`'s check of the drafted texts (2026-10-24)**

The guardian found no maths ambiguity and no wrong value or range. It corrected these claims,
taken directly as plain factual fixes: E34 (the drukte is still tracked while the noise is
off), E37 (`flow_ema` counts units per batch, not how often a drink is ordered, and drops
whenever a batch sells fewer units of the drink than its current value), E38 (same as E34,
and the 0 case at the start of a borrel), and E39 (a hard cut, not a pull; the crash and
bubble effect only below about 3; "kan een sprong zijn"). The three range questions it raised
are SD7–SD9.

## The table

As B-01's: the field, its new name, and the explanation, shown verbatim, one paragraph per
line, in B-01's order (what it does; *Hoger/Lager* or *Aan/Uit*; *Eerste borrel* and
*Toegestaan*; *Tijdens de borrel* where SD10 asks for it). The popup's title is the name.
**Bron** is for `engine-guardian`'s re-check (B-01 SD8.2) and is not shown.

### Globale instellingen (`/settings`), after E10

**E34 — `bm_enabled`.** **Willekeurige ruis** (a switch)

> Aan: om de zoveel minuten (Ritme ruis) krijgt elk drankje een willekeurig duwtje omhoog of omlaag, ook als er niets besteld wordt. Een drankje met een grote afstand tussen Minimumprijs en Maximumprijs beweegt daarbij meer, en een druk drankje ook (Extra ruis bij drukte). Tijdens een prijssprong of marktgebeurtenis houdt die het drankje op zijn pad; de ruis is daar hooguit één tel te zien.
> Uit: prijzen bewegen alleen door bestellingen, duwtjes bij stilte, marktgebeurtenissen en prijssprongen. Sterkte ruis, Ritme ruis, Extra ruis bij drukte, Reactiesnelheid drukte en Grens ruis doen dan niets aan de prijzen; de drukte wordt wel bijgehouden.
> Eerste borrel: aan.
> Tijdens de borrel: weer aanzetten geeft binnen een seconde één duwtje; gemiste duwtjes worden niet ingehaald.

Bron: `exchange/steps.py:271-302`, `:54-56`, `:180-202`; `exchange/advance.py:53-59`; `exchange/spec.py:50`.

**E35 — `bm_sigma_y`.** **Sterkte ruis**

> Hoe groot de willekeurige duwtjes van Willekeurige ruis zijn. De sterkte geldt per minuut: bij een korter Ritme ruis komen er meer, kleinere duwtjes, en blijft de beweging over langere tijd ongeveer gelijk. Een drankje met een grote afstand tussen Minimumprijs en Maximumprijs beweegt meer in euro's; vlak bij de Minimumprijs of Maximumprijs beweegt een prijs minder ver.
> Hoger: prijzen trillen meer. 0: geen ruis.
> Eerste borrel: 0,18. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:288-299`, `exchange/pricing.py:36-42`, `exchange/spec.py:53`.

**E36 — `bm_dt_minutes`.** **Ritme ruis (min)**

> Om de zoveel minuten krijgt elk drankje een duwtje van Willekeurige ruis. Hoe langer dit is, hoe groter elk duwtje, zodat de ruis over langere tijd ongeveer even sterk blijft (Sterkte ruis). Doet niets als Willekeurige ruis uit staat of Sterkte ruis 0 is.
> Hoger: minder vaak, grotere duwtjes. Lager: vaker, kleinere duwtjes.
> Eerste borrel: 1 (elke 60 seconden). Toegestaan: 0,05 tot en met 10.
> Tijdens de borrel: een nieuwe waarde telt vanaf het laatste duwtje. Is die tijd al voorbij, dan komt het volgende duwtje binnen een seconde, één keer, zo groot als bij de nieuwe waarde hoort; gemiste duwtjes worden niet ingehaald.

Bron: `exchange/steps.py:282-291`, `:299`; `exchange/advance.py:57-59`; `app/runtime/ticker.py:139` (the 1 s grid); SD8.

**E37 — `flow_vol_amp`.** **Extra ruis bij drukte**

> Drankjes die in de laatste bestellingen in grote aantallen zaten, krijgen grotere duwtjes van Willekeurige ruis. Die drukte telt hoeveel stuks een drankje per bestelling verkocht, niet hoe vaak er besteld wordt; hoe snel ze meegaat, stel je in met Reactiesnelheid drukte. De drukte verandert alleen bij een nieuwe bestelling, niet door de tijd: een drankje dat vroeg op de avond druk was en daarna niemand meer iets bestelt, houdt zijn extra ruis. Doet niets als Willekeurige ruis uit staat of Sterkte ruis 0 is.
> Hoger: drukke drankjes trillen sterker. 0: drukte maakt geen verschil.
> Eerste borrel: 0,7. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:54-56`, `:297`; ADR 0012 (D-23).

**E38 — `flow_beta`.** **Reactiesnelheid drukte**

> Hoe snel de drukte van een drankje, die Extra ruis bij drukte gebruikt, meegaat met de nieuwste bestellingen. Bij elke bestelling schuift de drukte van elk drankje dit deel van de afstand op naar het aantal dat het in die bestelling verkocht; niet besteld telt als nul. Zonder bestellingen blijft de drukte staan. De prijzen merken er alleen via de ruis iets van: staat Willekeurige ruis uit of is Sterkte ruis 0, dan doet dit niets aan de prijzen (de drukte wordt wel bijgehouden).
> Hoger: de drukte volgt de nieuwste bestellingen sneller; 1: alleen de laatste bestelling telt. Lager: de drukte verandert langzamer; 0: de drukte blijft staan waar hij staat, en aan het begin van de borrel is dat nul.
> Eerste borrel: 0,25. Toegestaan: 0 tot en met 1.

Bron: `exchange/steps.py:54-56`, `:282-291`, `:297`; `exchange/state.py:81` (`flow_ema` starts at zero); ADR 0012.

**E39 — `y_clip`.** **Grens ruis**

> Hoe ver de ruis een prijs naar zijn Minimumprijs of Maximumprijs laat gaan. Bij elk duwtje van Willekeurige ruis wordt elk drankje dat daarna voorbij deze grens zit, teruggezet op de grens, ook als bestellingen, een Marktcrash, Prijsbubbel of prijssprong het daar bracht. Bij 6 zie je dat op het koersbord vrijwel nooit: een prijs komt nog tot zijn Minimumprijs of Maximumprijs. Bij 1 komt een prijs nog maar tot ongeveer een kwart en driekwart van de weg daartussen (bij 1 tot 3 euro: 1,50 en 2,50). Doet niets als Willekeurige ruis uit staat of Sterkte ruis 0 is.
> Hoger: prijzen kunnen verder naar hun grenzen. Lager: de ruis kapt hoge en lage prijzen af. Bij ongeveer 3 of lager blijft een drankje na een Marktcrash of Prijsbubbel niet op zijn grens staan, en springt het tijdens zo'n gebeurtenis bij elk duwtje één tel terug.
> Eerste borrel: 6. Toegestaan: 1 tot en met 20.
> Tijdens de borrel: lager zetten zet bij het volgende duwtje van de ruis elk drankje buiten de nieuwe grens in één keer terug; op het koersbord kan dat een sprong zijn.

Bron: `exchange/steps.py:290-291`, `:301`, `:102-134` (no clip on the order path), `:164-165`, `:192-201`; `exchange/advance.py:57-59`; `app/runtime/candles.py:24-26`, `:92`; measured by `engine-guardian` 2026-10-24 (€1–€3, step 0,10: y_clip 6 holds 1,00 after a crash, 1 gives 1,50; 2 gives 1,20/2,80, 3 gives 1,10/2,90).

### E9, amended (SD11)

The first paragraph of E9's explanation ends its second sentence "…, en de ruis loopt op een
eigen klok (Ritme ruis)." Bron gains `exchange/steps.py:284-286` (already cited).

## In scope

- **Server:**
  - `ParamsPatch` gains the six with SD3's ranges; `ParamsData` gains the six
    (`app/runtime/config.py`); the module docstring's "a non-editable param (`bm_*`,
    `y_clip`, ...) is 422" becomes the legacy `bm_sigma`;
  - the draft and live write paths unchanged, and carrying the six (SD2);
  - the OpenAPI types regenerated (`web/src/api/generated/schema.d.ts`).
- **Web:**
  - the six controls in `GlobalSection.tsx` (SD4), `bm_enabled` as a `Switch`, the rest as
    `NumberField`s, each with its (i) (SD10);
  - E34–E39 in `web/src/features/settings/explanations.json`, and E9 amended (SD11);
  - their component tests and the Playwright admin flow.
- **Guards (B-01 SD8):** the start-value and range test covers E34–E39 and expects 39
  entries; the text test pins the six names and texts and E9's change.
- **Documents:**
  - a note on Phase 6 SD8's "Not editable" line (`docs/specs/phase-6-admin.md:212-213`) and
    its out-of-scope entry (`:537`): `bm_enabled`, `bm_sigma_y`, `bm_dt_minutes`,
    `flow_vol_amp`, `flow_beta` and `y_clip` are editable since B-03; the legacy `bm_sigma`,
    `tick_interval_ms` and `quote_grace_versions` are still not;
  - a note on B-01 SD2/SD3 (`docs/specs/phase-b-01-settings-explained.md`): the market
    controls are 39, E34–E39 live in this spec, E9 amended by SD11; and its out-of-scope line
    on B-03 (`:462`) pointing here;
  - B-03's backlog status.

## Out of scope

- Any change to the pricing maths or to any default (`Params()`, `DEFAULT_PARAMS`). `exchange/`
  is read, never changed. `flow_ema` keeps ADR 0012's semantics.
- A hold, clip or any other price action at the moment of a live save (SD2). Refusing a live
  `y_clip` change.
- Editing the legacy `bm_sigma`, `tick_interval_ms` or `quote_grace_versions`.
- A "Ruis" section, a sub-heading, or a new pixel icon (SD4). Greying out fields while the
  noise is off (SD5).
- An upper limit on `bm_sigma_y` (SD9); restricting `bm_dt_minutes` to whole seconds, or
  showing it in seconds (SD8).
- What a new borrel inherits. It copies the latest run's params, the six included, as today
  (`app/db/runs.py:462-464`); saving and choosing named settings is
  [B-04](../backlog.md).
- Making `flow_ema` decay in time (D-23, ADR 0012), or any other change to how the noise is
  computed, including drawing per elapsed time rather than per configured interval.
- Showing the noise or `flow_ema` on any screen, analytics or export.
- Fixing up an existing run's values: v1's values are all within SD3's ranges; a stored value
  outside them is shown, kept, and only checked when that field is edited.
- Any change to E1–E33 other than SD11.

## Acceptance criteria

**The API — SD1, SD3, SD12**

- **AC1.** When a `PATCH /api/runs/{run_id}/config` sends any of the six within SD3's range,
  on a draft or a live run, the system shall store it in `run.params` and append a revision.
- **AC2.** When one of the six is sent outside its range, as `null`, NaN, ±∞, a string, or
  (for the five numbers) a bool, or `bm_enabled` as a non-bool, the system shall return 422
  naming the field and store nothing. The edges are accepted: `bm_sigma_y` 0,
  `bm_dt_minutes` 0,05 and 10, `flow_vol_amp` 0, `flow_beta` 0 and 1, `y_clip` 1 and 20;
  just outside each bounded edge is rejected.
- **AC3.** When `bm_sigma`, `tick_interval_ms` or `quote_grace_versions` is sent, the system
  shall return 422 naming it, as before.
- **AC4.** `GET /api/runs/{run_id}/config` shall return the six with the run's stored values,
  and every revision appended from now on shall include them.

**A live change — SD2**

- **AC5.** When any of the six is changed on a live run, the system shall commit one config
  transition: `version + 1`, a `price_tick` of source `config` whose prices equal the prices
  before the write, and one `config` message carrying the new values. No drink's `y` shall
  change at the write, including when `y_clip` is lowered below a drink's current `y`.
- **AC6.** After a live write of `bm_enabled = false`, the next tick shall draw no noise
  (`rng_counter` and `last_bm_ms` unchanged). After `bm_enabled = true` again, the next tick
  shall draw exactly once.
- **AC7.** After a live write that lowers `y_clip`, the next noise draw shall leave every
  active drink's `y` within the new ±`y_clip`.
- **AC8.** After a live write that lowers `bm_dt_minutes` below the time since the last draw,
  the next tick shall draw exactly once, sized for the new value.
- **AC9.** When the app restarts after a live change of any of the six, the market shall run
  on the changed value.

**The page — SD4, SD5, SD6**

- **AC10.** Globale instellingen shall show the six after Kaarsbreedte, in SD4's order, under
  SD6's names as their visible label and accessible name; Willekeurige ruis is a switch.
- **AC11.** When one of the six is changed and saved, the request shall carry only the changed
  fields under `params`; when nothing changed, the page shall say "Niets te wijzigen" and send
  nothing. A 422 shall show under the field it names.
- **AC12.** While Willekeurige ruis is off, the other five shall stay editable and save.
- **AC13.** When the server's config changes while the six are being edited, the section's
  existing "Overnemen" offer shall cover them.

**The explanations — SD10, SD11**

- **AC14.** Each of the six shall carry an (i) whose popup is titled with its name and shows
  its text from the table, exactly, one paragraph per line; B-01's popup behaviour (B-01
  AC1–AC6) applies. A test shall pin every name and text.
- **AC15.** Every "Eerste borrel" value in E34–E39 shall equal `DEFAULT_PARAMS`' value, and
  every "Toegestaan" range shall equal `ParamsPatch`'s validation; when either changes, a test
  shall fail until the text changes. The guard shall count 39 entries.
- **AC16.** E9's first paragraph shall read as amended by SD11, and E1–E33 shall otherwise be
  unchanged.

**No maths change**

- **AC17.** `exchange/` shall be unchanged by this item, and the golden fixtures shall replay
  unchanged.

## Verification

- **API (pytest, `tests/api/test_config.py`):** each of the six accepted at its edges and
  rejected just outside, as null, NaN, ±∞, a string and a bool (AC1, AC2); `bm_sigma`,
  `tick_interval_ms`, `quote_grace_versions` still 422 (AC3); the `GET` document carries the
  six (AC4).
- **Integration (pytest, live market, `tests/integration/test_config_live.py`):** a live write
  of each field; the `price_tick` equals the prices before; no `y` moves when `y_clip` drops
  below a drink's `y` (AC5); then the next advance: no draw with the noise off, one with it on
  (AC6); every `y` within the new clip (AC7); one draw after lowering `bm_dt_minutes` (AC8); a
  restart reading the changed value (AC9).
- **Vitest:** the six controls, order, names and switch (AC10); the patch body and "Niets te
  wijzigen" (AC11); the five editable with the switch off (AC12); "Overnemen" (AC13); the
  popups (AC14).
- **Guard tests:** the start-value and range test over E34–E39, 39 entries (AC15); the text
  test with E9's amendment (AC14, AC16). Proved by temporarily changing one of the six's
  ranges and seeing it fail.
- **Playwright (in the gate):** on `/settings`, change Sterkte ruis and Willekeurige ruis,
  save, reload, and see the new values.
- **The gate:** `./scripts/check.sh` green; `bash scripts/golden_linux.sh` green, since
  `exchange/` must not move (AC17); `engine-guardian` on the diff reports no maths change.
- **Manual (exit check, the owner):** on a dry run with the board open, switch Willekeurige
  ruis off and see the prices stop moving without orders; switch it on with Sterkte ruis 0,5
  and see them move more than at 0,18 within a few Ritme ruis intervals.

## Exit condition

The owner can switch the noise on and off and tune its five settings from Globale
instellingen on a draft or a live run, each with a tap-to-open explanation that matches the
engine, and the pricing maths has not moved.
