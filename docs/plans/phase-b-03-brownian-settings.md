# Plan: B-03 — Brownian settings in Globale instellingen

Spec: [docs/specs/phase-b-03-brownian-settings.md](../specs/phase-b-03-brownian-settings.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-24)**
Design: [frontend-architecture.md](../design/frontend-architecture.md) (unchanged; nothing in `docs/design/` names the six)
ADRs honoured: 0002 and 0012 (`exchange/` read, never changed; `flow_ema` keeps v1's semantics), 0004 (no migration, one engine). Nothing in an ADR is reversed.
Backlog: [B-03](../backlog.md) · Fixes: no open defect

Line references are to `main` at `b9a83c9`.

---

## Approach

**Open the model, then show it; the engine already does the rest.** SD2 says every live
behaviour the spec asks for is what the code already does, once the six can be written. So the
server change is two pydantic models: `ParamsPatch` gains the six with SD3's ranges and
`ParamsData` gains them for the document (`app/runtime/config.py:112-135`, `:150-167`). The
draft and live write paths (`write_draft_config`, `write_live_config`, `:413-462`) are not
touched: `_merged` already merges any present key into `run.params`, `Params.from_dict` already
reads all six, and `ConfigChanged` already carries `spec.params` whole. T1 makes the six
writable and proves the API half (AC1–AC4). T2 proves SD2 on a live market (AC5–AC9) with tests
only, and if one of those tests fails the code does not do what the spec says, and the builder
stops (a fix would be in `exchange/`, a hard stop). T3 adds E34–E39 to the B-01 table and its
two guards. T4 puts the six on the page, reusing `Switch`, `NumberField`, `useEditableRecord`
and the section's save. T5 writes the notes on the older specs and runs the exit gate (AC17).

Rejected:
- **A "Ruis" sub-section or its own form and save button**, as DemandSection has for its
  switches. SD4 rules it out: same grid, same button, same rules.
- **Making the six optional in the web's `RunConfig` zod schema** to avoid touching the other
  section tests' fixtures. The server always sends them (AC4). An optional field would hide a
  missing one and make `recordOf` deal with `undefined` (PD4).
- **A shared config fixture for the web tests.** Five test files each build their own config
  document today. Unifying them is a refactor the spec does not ask for. T4 adds the six to each.
- **Editing B-01's E9 row in place.** The spec asks for a *note* on B-01 and says E34–E39 live in
  this spec. The text guard applies SD11's one substitution to B-01's row instead (PD2).
- **Disabling the five when the switch is off.** SD5.

---

## Decisions this plan makes

Rows marked **Confirm** are readings that the audit confirms or overrules.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | The six's validators | Reuse the existing aliases where they fit: `bm_enabled: StrictBool`, `bm_sigma_y: NonNegative`, `flow_vol_amp: NonNegative`, `flow_beta: Fraction` (`config.py:101-103`). Add two aliases beside them for the bounded ranges: `NoiseMinutes` (`ge=0.05, le=10`) and `NoiseClip` (`ge=1, le=20`), both `strict=True, allow_inf_nan=False`. Field order in both models follows SD4: `bm_enabled, bm_sigma_y, bm_dt_minutes, flow_vol_amp, flow_beta, y_clip`, appended after `auto_calibrate_s0`. The `_no_null` validator (`"*"`) covers them as is | The existing types already give SD3's strict/finite/no-bool rules (D-03). `render_range` in the value guard reads these exact constraints (`test_setting_explanations_values.py:79-123`) |
| PD2 | How the text guard gets E34–E39 and E9 (SD10, SD11) | `test_setting_explanations_text.py` parses **both** specs with the existing `parse_spec_table`. B-01's gives E1–E33 and B-03's gives E34–E39 (its `## The table` has the same row format; the `### E9, amended (SD11)` prose has no `**E<n> — ` line and is skipped). E9's expected first paragraph is B-01's with one literal substitution, `"en de ruis loopt op een eigen klok."` → `"en de ruis loopt op een eigen klok (Ritme ruis)."`. The test asserts the old phrase occurs exactly once in B-01's E9 and that the B-03 spec contains `eigen klok (Ritme ruis).` Every other row is compared unchanged (AC16). **Confirm** | The spec is the fixture, as B-01 PD2. B-01's table stays the record of what B-01 shipped; the note (T5) points here |
| PD3 | Where E34–E39 live | `web/src/features/settings/explanations.json`, keyed by field (`bm_enabled`, …, `y_clip`), ids `E34`–`E39`, placed after `candle_interval_s` (E10), as the spec's "after E10" | B-01 PD1: a field row is keyed by its field (`test_a_field_row_is_keyed_by_its_field`) |
| PD4 | The web's config schema | `RunConfig.params` (`useRunConfig.ts:23-41`) gains the six as required: `bm_enabled: z.boolean()`, the rest `z.number()`. Every Vitest fixture of the config document gains them: `GlobalSection.test.tsx:25-43`, `SettingsPage.test.tsx` (~`:125-145`), `DemandSection.test.tsx`, `BoundsSection.test.tsx`, `DrinksSection.test.tsx` (each at `auto_calibrate_s0: false`, ~`:44-47`), with `Params()`'s values | AC4: the document always carries them; a fixture without them would fail to parse and show "Verbindingsfout" |
| PD5 | The switch in a number grid | `GlobalRecord` becomes `Record<NumberField, number> & { bm_enabled: boolean }`. The grid renders the ten existing `NumberField`s, then the `Switch` (`label` and `info` from `explanations.bm_enabled`, as in `DemandSection.tsx:143-148`), then the five `NumberField`s, in SD4's order. `bm_enabled` is a param, so `submit`'s existing split (`GlobalSection.tsx:76-80`) sends it under `params` unchanged. A 422 naming `bm_enabled` shows in a `styles.error` line next to the switch. `Switch` itself is not changed | AC10, AC11. A shared component does not grow an `error` prop for a fault the page can never cause (it only sends booleans) |
| PD6 | AC9's "restart" | A fresh `rehydrate(engine, now_ms=…)` of the committed run, as boot does (`app/runtime/rehydrate.py:86`), then a new `MarketHolder` and one tick. Not an OS process restart | `tests/integration/test_config_live.py` already assembles the runtime this way (`:92-125`); the spec's Verification says "a restart reading the changed value" |
| PD7 | AC8's "sized for the new value" | Two assertions on the tick after the change: `rng_counter` + 1 and `last_bm_ms` = the tick's time (one draw); and the y change equals `sqrt(new / 1)` times the y change of the same pre-state advanced with `bm_dt_minutes = 1` and `last_bm_ms` moved back past that gate. Both use the same `rng_counter`, so the same normal draw: the ratio is exact. A second tick 1 s later draws nothing (nothing caught up). Drinks away from the clip, so it does not bite | Non-tautological: it shows the draw used the new interval, not just the new spec object |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `app/runtime/config.py` | Modify | `ParamsPatch` + `ParamsData` gain the six (PD1); two aliases; module docstring's "`bm_*`, `y_clip`, ..." becomes the legacy `bm_sigma`, `tick_interval_ms`, `quote_grace_versions` | T1 |
| `tests/api/test_config.py` | Modify | Shape test gains the six; `bm_sigma_y`/`y_clip` 422 rows (`:260-261`) replaced by out-of-range rows; new edges, null, NaN/±∞, string, bool and legacy-422 cases | T1 |
| `web/src/api/generated/schema.d.ts` | Modify (regenerated) | `./scripts/gen_api_types.sh`; never hand-edited | T1 |
| `tests/integration/test_config_live.py` | Modify | AC5–AC9 on a live market; a `tick` helper after `test_drink_lifecycle.py:96-120` | T2 |
| `web/src/features/settings/explanations.json` | Modify | E34–E39 verbatim; E9's first paragraph per SD11 | T3 |
| `tests/unit/test_setting_explanations_text.py` | Modify | Parse B-03's table too; E9's substitution; `SETTINGS_IDS` gains E34–E39; E34–E39 are field rows | T3 |
| `tests/unit/test_setting_explanations_values.py` | Modify | Count 33 → 39 (`:267`); a render check for the two new aliases | T3 |
| `web/src/features/settings/useRunConfig.ts` | Modify | `RunConfig.params` gains the six (PD4) | T4 |
| `web/src/features/settings/GlobalSection.tsx` | Modify | The six controls (PD5); docblock names E34–E39 | T4 |
| `web/src/features/settings/GlobalSection.test.tsx` | Modify | AC10–AC14 for the six | T4 |
| `web/src/app/pages/SettingsPage.test.tsx` | Modify | Fixture; Globale instellingen 10 → 16 (i); test name "E1–E20, E33 or E34–E39" | T4 |
| `web/src/features/settings/DemandSection.test.tsx` | Modify | Fixture only (PD4) | T4 |
| `web/src/features/settings/BoundsSection.test.tsx` | Modify | Fixture only (PD4) | T4 |
| `web/src/features/settings/DrinksSection.test.tsx` | Modify | Fixture only (PD4) | T4 |
| `web/e2e/admin.spec.ts` | Modify | Step 3: Sterkte ruis + Willekeurige ruis, save, reload, values kept | T4 |
| `docs/specs/phase-6-admin.md` | Modify | Notes on SD8 "Not editable" (`:212-213`) and out-of-scope (`:536-537`) | T5 |
| `docs/specs/phase-b-01-settings-explained.md` | Modify | Notes on SD2/SD3 (`:58`, `:62`), the 33 → 39 (AC10 `:495`), E9 amended, the B-03 out-of-scope line (`:462`) | T5 |
| `docs/backlog.md` | Modify | B-03 → `built → docs/plans/phase-b-03-brownian-settings.md (spec: …)` | T5 |

Untouched, and checked at T5: `exchange/`, `tests/engine/`, `db/migrations/`, `docs/design/`,
`app/realtime/` (the `config` and snapshot messages already send every param,
`app/realtime/messages.py:144-159`), `web/src/features/exchange/` (its `params` is
`Record<string, unknown>`, `applyMessage.ts:88`).

---

## Tasks

### T1 — The six are writable and in the document (server)

- **Implements:** AC1, AC2, AC3, AC4; SD1, SD3, SD12
- **Expected output:**
  - `ParamsPatch` and `ParamsData` carry the six per PD1. The draft and live write paths are
    unchanged in code and now carry the six.
  - The module docstring's validation paragraph names the legacy three as the non-editable ones.
  - `tests/api/test_config.py`:
    - the shape test (`:102-130`) expects the six keys, and their values equal `DEFAULT_PARAMS`';
    - the violation table (`:257-283`) loses `bm_sigma_y: 0.2` and `y_clip: 5.0` as 422 rows and
      gains, for each of the six, just outside each bounded edge (`bm_sigma_y: -0.01`,
      `bm_dt_minutes: 0.04` and `10.01`, `flow_vol_amp: -0.01`, `flow_beta: -0.01` and `1.01`,
      `y_clip: 0.99` and `20.01`), a string, and a bool for the five numbers; `bm_enabled` as
      `0`, `1` and `"true"`; and `bm_sigma`, `tick_interval_ms`, `quote_grace_versions` (AC3);
    - the null table (`:230-240`) gains one of the six as a number and `bm_enabled`;
    - the non-finite test (`:306-318`) is parametrised over the five numbers too;
    - the edges test (`:320-346`) gains `bm_sigma_y: 0`, `bm_dt_minutes: 0.05` and `10`,
      `flow_vol_amp: 0`, `flow_beta: 0` and `1`, `y_clip: 1` and `20`, and `bm_enabled: false`;
    - one test on the `live_run` fixture: a PATCH of all six returns `revision + 1`, and the
      `GET` returns them (AC1 live half, AC4).
  - `web/src/api/generated/schema.d.ts` regenerated.
- **Verification:** `uv run pytest tests/api/test_config.py`; `./scripts/gen_api_types.sh &&
  git diff --stat -- web/src/api/generated` shows only `schema.d.ts`; `uv run mypy app`.
- **Depends on:** —
- **Autonomy note:** The alias names, test ids and the exact out-of-range values are the
  builder's. The ranges are SD3's and are not the builder's to widen or narrow. Stop and ask if
  a write-path change turns out to be needed beyond the two models and the docstring: SD2 says
  none is.

### T2 — A live change acts at the next step, not at the save (integration)

- **Implements:** AC5, AC6, AC7, AC8, AC9; SD2
- **Expected output:** In `tests/integration/test_config_live.py`, reusing `_live`, `Runtime`,
  `_ticks` and `_revisions` (`:58-155`), plus a `tick` helper that runs one `advance` inside
  `holder.mutate` with `save_transition`, following `test_drink_lifecycle.py:96-120`:
  - **AC5:** for each of the six, a live write leaves `y` bitwise equal and gives `version + 1`,
    one more `config` tick whose stored prices equal the quotes before the write, and one more
    `config` frame whose `data.params` carries the new value, extending the pattern of
    `test_a_scalar_change_leaves_y_bitwise_and_is_one_transition` (`:157-201`). The `y_clip`
    case lowers it to 1 while a drink sits beyond ±1 (a drink with `p0` near `p_max`, or after a
    jump to `p_max`), and its `y` is still unchanged.
  - **AC6:** after `bm_enabled = false`, a tick past the draw interval leaves `rng_counter` and
    `last_bm_ms` unchanged. After `true` again, the next tick draws exactly once (`rng_counter + 1`)
    and the tick after does not.
  - **AC7:** after lowering `y_clip` to 1, the next drawing tick leaves every active `y` within
    ±1.
  - **AC8:** with `bm_dt_minutes = 1` and ten seconds since the last draw, lowering it to `0.05`
    makes the next tick draw once, sized per PD7; the tick after draws nothing.
  - **AC9:** after a live write of the six, a fresh `rehydrate` (PD6) has `spec.params` equal to
    the written values. One tick on the rehydrated holder with `bm_enabled = false` draws
    nothing.
  - Runs use a short draw interval where a draw is needed (`Params(step_quant=0.5,
    bm_dt_minutes=2 / 60)`, as `test_drink_lifecycle.py:62`), so no test waits a minute of
    fake time.
- **Verification:** `uv run pytest tests/integration/test_config_live.py` (needs the compose
  `db`).
- **Depends on:** T1
- **Autonomy note:** Test layout, helper names and which drink is pushed past the clip are the
  builder's. This task changes **no source file**. If any assertion fails, the code does not do
  what SD2 says. Stop and report: the fix would be in `exchange/` or would change what a live save
  does, and both are the owner's.

### T3 — E34–E39 and E9 in the table, pinned by both guards

- **Implements:** AC14 (the pin), AC15, AC16; SD10, SD11
- **Expected output:**
  - `explanations.json` holds E34–E39 per PD3, each `name` and `paragraphs` copied verbatim from
    the spec's table, one paragraph per `> ` line. E9's first paragraph reads per SD11; no other
    entry changes.
  - `test_setting_explanations_text.py` per PD2:
    - a `B03_SPEC` beside `SPEC`, parsed with the same `parse_spec_table`;
    - a test that B-03's table is exactly E34–E39, each a field row;
    - `SETTINGS_IDS` = E1–E20, E33, E34–E39;
    - the name-and-paragraph test runs over both tables, with E9's expected row taken from B-01's
      after SD11's substitution;
    - a test that the substitution applies exactly once and that the B-03 spec states it;
    - the docstring says "39".
  - `test_setting_explanations_values.py`: `len(ENTRIES) == 39` (`:267`); the docstring's "33"
    follows; `test_the_ranges_render_as_the_server_validates` gains
    `render_range(ParamsPatch, "bm_dt_minutes") == "0,05 tot en met 10"` and `y_clip` →
    `"1 tot en met 20"`. The existing rules already cover the six: each is a `Params` field, so
    "Eerste borrel" is checked against `DEFAULT_PARAMS` (`bm_enabled` as "aan", `bm_dt_minutes`'s
    "(elke 60 seconden)" by the seconds rule) and "Toegestaan" against `ParamsPatch`. `bm_enabled`
    is a bool, so it quotes no range.
  - Proved as the spec asks: temporarily narrowing `NoiseClip` to `le=15` fails only E39, then is
    reverted (the commit message records it). `test_a_changed_range_is_caught` stays as the
    permanent proof.
- **Verification:** `uv run pytest tests/unit/test_setting_explanations_text.py
  tests/unit/test_setting_explanations_values.py`; `pnpm -C web exec vitest run
  src/features/settings src/app/pages/SettingsPage.test.tsx` (still green: the E9 popup text is
  read from the JSON).
- **Depends on:** T1 (`render_range(ParamsPatch, "y_clip")` needs the field)
- **Autonomy note:** JSON formatting follows the file as it is (2-space, UTF-8, LF; edit with
  the Edit tool, not a Python text-mode write, which would write CRLF). The texts are the spec's,
  character for character: if one seems wrong, stop and ask, never "fix" it here. A guard
  failure on a value or range means the spec and code disagree, and that is the owner's to
  settle.

### T4 — The six on Globale instellingen

- **Implements:** AC10, AC11, AC12, AC13, AC14 (the popups); SD4, SD5, SD6
- **Expected output:**
  - `useRunConfig.ts` per PD4. `GlobalSection.tsx` per PD5: the six after Kaarsbreedte in SD4's
    order, `Willekeurige ruis` a `Switch`, the rest `NumberField`s, each `label` and `info` from
    `explanations.json`. Nothing is disabled by the switch. The docblock names E34–E39 and B-03.
  - `GlobalSection.test.tsx`:
    - `PARAMS` gains the six;
    - the six labels and order in the DOM after Kaarsbreedte; `getByRole('switch', { name:
      'Willekeurige ruis' })` with `aria-checked` from the server (AC10);
    - `it.each` over the six with `expectExplained` (AC14);
    - editing Sterkte ruis sends `{params: {bm_sigma_y}}` only; toggling the switch sends
      `{params: {bm_enabled: false}}` only; untouched sends nothing (AC11, covered by the
      existing test);
    - a 422 naming `y_clip` shows under Grens ruis (AC11);
    - with the switch off, the five are enabled and an edit to Ritme ruis saves both fields (AC12);
    - a server config with a changed `y_clip` while Sterkte ruis is dirty offers "Overnemen", and
      taking it shows the server's values (AC13).
  - `SettingsPage.test.tsx`: fixture; `['Globale instellingen', 16]`; the AC10 test's name lists
    E34–E39.
  - The other three section tests: fixture only.
  - `admin.spec.ts` step 3 (`:121-125`): also fill Sterkte ruis `0,5` and switch Willekeurige ruis
    off, save, see "Opgeslagen", `page.reload()`, and see `0,5` and `aria-checked="false"`.
    Then switch it back on and save, so the rest of the flow runs on the defaults it was written
    against.
- **Verification:** `pnpm -C web exec vitest run src/features/settings
  src/app/pages/SettingsPage.test.tsx`; `pnpm -C web exec tsc -b` (typecheck: the JSON keys and
  `GlobalRecord`); `pnpm -C web exec playwright test e2e/admin.spec.ts`.
- **Depends on:** T1 (the API accepts the six; e2e), T3 (`explanations.bm_enabled` etc. must
  exist to typecheck)
- **Autonomy note:** How the grid splits the field list around the switch, test names, and the
  error line's markup for `bm_enabled` are the builder's. Adding a prop to `Switch`, a new
  section, a sub-heading or an icon is not (SD4). If the e2e flow's later steps turn out to
  depend on the switch's state, a separate `test()` in `admin.spec.ts` on its own run is fine.

### T5 — The older specs, the backlog, and the exit gate

- **Implements:** AC17; spec "In scope › Documents"
- **Expected output:**
  - In B-01's note style (`phase-6-admin.md:199-203`: an indented blockquote, here starting
    `**Superseded in part by B-03**` with a link to the B-03 spec):
    - Phase 6 SD8's "Not editable" (`:212-213`) and its out-of-scope line (`:536-537`): the six
      are editable since B-03; `bm_sigma`, `tick_interval_ms`, `quote_grace_versions` still are
      not;
    - B-01 SD2 (`:58`) and SD3 (`:62`): the market controls are 39, E34–E39 live in B-03's spec,
      E9 is amended by B-03 SD11; AC10 (`:495`) "outside the 33" reads as 39;
    - B-01's out-of-scope line on B-03 (`:462`) points to the B-03 spec.
  - The old texts stay as the record.
  - `docs/backlog.md`: B-03's status becomes `built → docs/plans/phase-b-03-brownian-settings.md
    (spec: docs/specs/phase-b-03-brownian-settings.md)`, as B-01's (`:51-52`).
- **Verification:**
  - `grep -c "Superseded in part by B-03"` gives 2 in `phase-6-admin.md` and 3 or more in
    `phase-b-01-settings-explained.md`;
  - `git diff --stat <T1's base>..HEAD -- exchange tests/engine db/migrations docs/design` is
    empty (AC17);
  - `bash scripts/golden_linux.sh` green (AC17);
  - `engine-guardian` on the whole B-03 diff reports no maths change (AC17);
  - `./scripts/check.sh` green, output pasted.
- **Depends on:** T2, T4
- **Autonomy note:** Note wording is the builder's, in the B-02 notes' register; a note must
  not restate the B-03 spec. A golden diff or a guardian finding is a hard stop. The manual exit
  check (spec Verification: the board on a dry run, noise off then Sterkte ruis 0,5) is the
  owner's and is done with them. The item is not done without it.

---

## Task graph

```
T1 ──┬── T2 ──────────┐
     └── T3 ── T4 ────┴── T5
```

| Group | Tasks | Files they write |
|---|---|---|
| 1 | T1 | `app/runtime/config.py`, `tests/api/test_config.py`, `web/src/api/generated/schema.d.ts` |
| 2 | T2, T3 | T2: `tests/integration/test_config_live.py` · T3: `web/src/features/settings/explanations.json`, `tests/unit/test_setting_explanations_text.py`, `tests/unit/test_setting_explanations_values.py` |
| 3 | T4 | `web/src/features/settings/{useRunConfig.ts, GlobalSection.tsx, GlobalSection.test.tsx, DemandSection.test.tsx, BoundsSection.test.tsx, DrinksSection.test.tsx}`, `web/src/app/pages/SettingsPage.test.tsx`, `web/e2e/admin.spec.ts` |
| 4 | T5 | `docs/specs/phase-6-admin.md`, `docs/specs/phase-b-01-settings-explained.md`, `docs/backlog.md` |

No file is written by two tasks. T4 waits on T3 for the JSON keys, not for safety.

### Coverage

| AC | Task(s) | AC | Task(s) |
|---|---|---|---|
| AC1 | T1 | AC10 | T4 |
| AC2 | T1 | AC11 | T4 |
| AC3 | T1 | AC12 | T4 |
| AC4 | T1 | AC13 | T4 |
| AC5 | T2 | AC14 | T3 (pin), T4 (popups) |
| AC6 | T2 | AC15 | T3 |
| AC7 | T2 | AC16 | T3 |
| AC8 | T2 | AC17 | T5 |
| AC9 | T2 | | |

---

## Data changes

None. No migration, no column, no backfill (SD12). `run.params` (JSON) already holds all six for
every run. `ParamsData` grows, so revisions appended from now on carry the six, and older
revisions keep their shape; nothing reads a revision back (`config.py:316-327`). The OpenAPI
schema gains six optional request fields and six response fields, so it is additive. Reverting
the item restores the 422 and the old document, and leaves stored values as they were.

## New dependencies

None.

---

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| A T2 assertion fails: the engine does not behave as SD2 describes (most likely AC8's "nothing caught up" or AC6's "on again, one draw") | T2 changes no source, and its autonomy note makes a failure a stop. The fix would be `exchange/` (a hard stop) or a live-save change the spec rules out |
| PD2 reads two specs and patches E9 in the test, so a later edit to B-01's E9 sentence breaks the substitution | The test asserts the old phrase occurs exactly once and fails loudly, naming SD11 |
| Fixture churn: five web test files gain six params (PD4) | Mechanical; listed per file. The alternative (optional fields) is rejected in Approach |
| The e2e flow switches noise off mid-flow and a later step relied on moving prices | T4 switches it back on before continuing; or a separate `test()` (autonomy note) |
| The value guard's `_START` regex on E36's `1 (elke 60 seconden)` and the seconds rule | Already exercised by E9's `0,2 (elke 12 seconden)`; T3 runs it |
| Windows: a Python text-mode edit of the JSON writes CRLF into an LF repo | T3's autonomy note: Edit tool only |
| `y_clip` floor of 1 vs SD7's measurement (visible effect only below ~3,7, crash/bubble no longer held below ~3) | The spec settles it (SD7); E39 says it. Not reopened |

**Uncertain, for the audit:**
- PD2's E9 mechanism: the spec does not say how the guard learns SD11. Patching B-01's E9 row in
  place is the alternative, but then B-01's table no longer records what B-01 shipped.
- PD5's error line for `bm_enabled`: AC11 says a 422 shows "under the field it names", but the
  page can only send a boolean, so this line is defensive. The alternative is no line at all.
- PD7's ratio check depends on `apply_brownian` using `sqrt(dt_min)` from the configured
  interval, not the elapsed time (`exchange/steps.py:288-299`; SD2 and the spec's out-of-scope
  line say so). If the guardian reads that differently, AC8's test shape changes, not the code.

---

## Out of scope for this plan

As the spec, plus:
- Any change to `Switch`, `NumberField`, `useEditableRecord` or `InfoButton`.
- A shared web test fixture for the config document.
- Showing `bm_dt_minutes` in seconds, an upper limit on `bm_sigma_y`, editing the legacy three,
  greying out (spec SD5, SD8, SD9).

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible (none: no migration; the API only grows)
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Rulings at the audit (owner, 2026-10-24): every line accepted as the plan stands.

- **PD2 confirmed.** The text guard parses both specs and applies SD11's substitution to
  B-01's E9 row; B-01's table stays the record of what B-01 shipped.
- **PD5 confirmed.** The defensive error line beside the `bm_enabled` switch stays.
- **PD6 confirmed.** AC9's "restart" is a fresh `rehydrate` of the committed run, not an OS
  process restart.
- **PD7 confirmed.** AC8's size check is the exact `sqrt(new / 1)` ratio; if the guardian reads
  `apply_brownian`'s sizing differently, the test's shape changes, not the code.
- Noted, not changed: T4 is the largest task (eight files, five of them test fixtures).

Audited by: Martijn Boot (owner), walked through by Claude  Date: 2026-10-24
