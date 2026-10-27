# Plan: B-07 — Price bounds on the Prijsstap grid

Spec: [docs/specs/phase-b-07-bounds-on-grid.md](../specs/phase-b-07-bounds-on-grid.md) (`Status: Approved`) · Status: **Proposed — awaiting audit**
Design: no change. `docs/design/` names the bounds as columns (`data-model.md:28`) and the `MarketSpec` check (`architecture.md:72`); neither changes.
ADRs honoured:
- 0002 and 0012: `exchange/` is read, never changed (AC17, SD12).
- 0003: no clock is read by anything this plan adds; a move is part of the transition the caller already stamps.
- 0004: one Postgres engine; no migration.
- 0008: a live Prijsstap change still holds every quote (`hold_quoted_prices`), now under the moved bounds.

No ADR is reversed. No new dependency.
Backlog: [B-07](../backlog.md) · Fixes: no open defect · Amends: B-01 SD11, Phase 6 SD8 (T13)

Line references are to `main` at `8f47ec5`.

---

## Approach

**One pure helper decides every bound, and every path in SD8 calls it.**
- **`app/runtime/price_grid.py`** (new, a leaf like `config_patch.py`) holds three things:
  - the SD1 check and its message (two grid neighbours, Dutch cents);
  - the SD3 move inward, generic over any frozen dataclass with `name`, `p_min_cents`, `p0_cents`, `p_max_cents` (`DrinkRow`, `app/db/mapping.py:25-40`, and `ImportedDrink`, `app/cli/v1_files.py:119-130`);
  - the SD4 collision, raised as one 422.
- **Every caller reuses it:**
  - `app/runtime/drinks.py` calls the check;
  - `app/runtime/config.py` (draft write, live write, profile load) calls the move and writes the moved rows with the existing `update_drink` (`app/db/runs.py:279`) before `_record`, so the revision document (`append_revision`, `config.py:259-270`) already shows them;
  - `app/db/runs.py` `create_run` moves the copied rows before `add_drink`;
  - `app/cli/v1_files.py` moves the plan's drinks before the database opens.
- **It is a leaf.** `app/db/runs.py` already imports the leaf `app.runtime.config_patch` (`runs.py:50`), so it can import this one the same way. No layer rule is bent.
- **Live, the spec is rebuilt from rows only when the step changes.** Today a live config write builds its spec as `dataclasses.replace(view.spec, params=params)` (`config.py:420`), which would keep the old bounds. A step change instead takes `spec_from_rows` over the moved rows, as a drink edit does (`drinks.py:326`). Then the existing single `hold_quoted_prices` runs over every active slot, from the old spec to the new one (`config.py:422-424`). Every other config write keeps `replace`, so the bitwise-`y` tests (`tests/integration/test_config_live.py:233-277`) are unaffected.

**Web: one pure grid model, used by three forms and one dialog.**
- `web/src/features/settings/grid.ts` mirrors the server helper: on grid, neighbours, the SD1 message, the SD6 hint, and the list of SD3 moves for a new step.
- The bounds rows and the add-drink form check SD1 with it before sending (SD10).
- Globale instellingen lists the moves in the existing `ConfirmDialog`, whose `message` is already a `ReactNode` (`components/ui/ConfirmDialog.tsx:25`).
- The profile-load and Nieuwe borrel errors recognise the collision by its code and show the server's sentence.

Rejected:
- **Rounding a bound for the admin**, or a "snap" button: SD1.
- **A database CHECK, or a migration fixing stored bounds:** SD6, SD12. A CHECK cannot see `run.params.step_quant` anyway.
- **Rebuilding the live spec from rows on every config write:** it would make every save depend on the rows matching the view bit for bit. Only a step change needs the rows.
- **Moving bounds inside `exchange/`** (a "snap spec" helper next to `hold_quoted_prices`): SD12 and ADR 0002. The move is storage policy, not pricing maths.
- **Telling the collision apart by its message text on the web:** brittle. It gets its own error code (PD2).

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. The rest follow from the spec and the code. No row is an owner stop: the spec settles every user-visible choice.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | The helper's shape | **`app/runtime/price_grid.py`**, importing only the stdlib and `app.runtime.config_patch.InvalidConfig`. It holds:<br>• `step_cents(step_quant: float) -> int`: `round(step_quant * 100)`;<br>• `euro_text(cents) -> str`: `124` gives `"1,24"`, the spelling of the web's `centsText`;<br>• `neighbours(cents, step) -> (lower, upper)`: `lower = cents // step * step`, `upper = lower + step` (only asked for an off-grid value);<br>• `grid_faults(values: Mapping[str, int], step, *, loc) -> list[fault]`: one fault per off-grid value;<br>• `@dataclass(frozen=True) BoundMove(name, field, old_cents, new_cents)`, where `field` is `"p_min_cents"` or `"p_max_cents"`;<br>• `move_inward(drinks: Sequence[T], step, *, loc) -> tuple[list[T], list[BoundMove]]`. Minimum goes up to `ceil`, Maximum down to `floor`, a bound on the grid stays (`dataclasses.replace`). It then checks `p_min < p0 < p_max` on every returned drink and raises `BoundsCollision` (PD2) if any fails. The rows come back in input order, moves in slot order with Minimum before Maximum. | SD1's "decided in whole cents". The step is validated as whole cents (`config_patch.py:55-61`), so `round` is exact. One place for SD1, SD3 and SD4 means the four paths of SD8 cannot drift apart. |
| PD2 | The two 422s on the wire | **Off the grid:** `InvalidConfig` (422 `invalid_request`), with one fault per off-grid bound sent: `{"loc": ["body", "<field>"], "msg": "Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30."}`. The error message joins the faults' messages. This is the shape `check_bounds` uses (`drinks.py:136-146`).<br>**A collision:** a new `BoundsCollision(InvalidConfig)` with `code = "bounds_collision"`, still 422. It carries one fault whose `msg` is every collided drink's SD4 sentence, in slot order, joined by a space. Its `loc` ends in `step_quant`:<br>• the config PATCH: `["body", "params", "step_quant"]`;<br>• a profile load, or a create with a profile: `["profile", "params", "step_quant"]` (`profile_patch`'s shape, `config_patch.py:160`);<br>• a create that copies with no profile: `["body", "copy_from_run_id"]`.<br>**SD4's sentences:** when the moved bounds meet or cross, "Past niet bij Fris: de grenzen worden 2,00–1,50.", with an en dash. Otherwise "Past niet bij Bier: de grenzen worden 1,25–2,75 en de Startprijs 1,22 valt daarbuiten." **Confirm** (the new code) | `faultsOf` keeps one message per field (`useRunConfig.ts:107-117`), so one joined fault shows every drink under Prijsstap with no change to `GlobalSection`'s error mapping. The profile and Borrel pages map a 422 on a known setting to the generic "valt buiten" (`ProfilesSection.tsx:39-42`, `BorrelSection.tsx:47-51`). SD5 forbids that here, and a code is the robust way to tell the collision apart. |
| PD3 | Which drinks are checked for a collision | Every drink handed to `move_inward`, moved or not. The config paths hand it the **active** rows (`not d.removed`). `create_run` hands it the copied (active) rows. The import hands it every drink. A drink that did not move already satisfies the order on the database paths (every write checks it), so this matters only for a v1 file that is already out of order: it is now refused with SD4's sentence instead of failing at go-live (`exchange/spec.py:129-132`). **Confirm** | One rule, no "moved" flag to carry. |
| PD4 | "The step changes" (SD8) | The merged `Params.step_quant != ` the stored one, as floats. This is the test the live hold already uses (`config.py:422`), so on a live run the move and the hold always fire together. A profile load moves regardless (SD8). | Two tests could disagree on `0.1` vs `0.10000000000000001`. One cannot. |
| PD5 | A profile load whose 22 equal the draft's (`config.py:391-393`) | When `_merged` is `None` and no bound moves: as today, nothing is written and the current revision is returned. When `_merged` is `None` but a stored off-grid bound moves (SD6, SD8): the moves and one revision are written. | B-04's "appends nothing" stays true wherever nothing changes. |
| PD6 | The order of checks on a drink write (SD1, SD6) | `check_bounds` first, as today: before the transaction for an add (`drinks.py:174`, `:189`), inside `_edited` for an edit. Then `grid_faults` over the bounds **present in the request** (`body` for an add; `patch.model_fields_set ∩ {p_min_cents, p_max_cents}` for an edit), under the step read from the locked `run` row (`Params.from_dict(run.params).step_quant`). On the live run that equals the view's. A request out of order gets only the ordering 422. | SD6: "only a bound present in the request". The run row lock is already taken on every write path (`drinks.py:176`, `:196`, `:296`, `:321`). |
| PD7 | The import (SD7) | `build_plan` (`v1_files.py:166-197`):<br>• first checks `params.step_quant` is positive, finite and whole cents, with `config_patch._whole_cents`'s rule, else `ValueError` naming it;<br>• then runs `move_inward` on the drinks under that step. A `BoundsCollision` is re-raised as a `ValueError` carrying its message, so `main`'s existing `except (OSError, ValueError)` gives exit 2 and "import_v1: invalid input: Past niet bij …" (`import_v1.py:74-78`).<br>`ImportPlan` gains `moves: tuple[BoundMove, ...]`. After `write_plan` succeeds and before the `run_id` is printed, `main` prints one line per move to stderr: `import_v1: Bier: p_min 1,24 → 1,30` (`p_min` / `p_max`, as the spec writes them). **Confirm** (the step check) | Without a step check, a step of 0 divides by zero. Today such a file imports and then fails at go-live. Printing after the write means a failed import prints only its failure. |
| PD8 | The web grid model | **`web/src/features/settings/grid.ts`** (pure) holds:<br>• `stepCents(step) = Math.round(step * 100)`;<br>• `onGrid`, `neighbours`;<br>• `gridMessage(cents, stepCents)`: SD1's text;<br>• `offGridHint(cents, stepCents)`: "Niet op de Prijsstap: kies 1,20 of 1,30.";<br>• `boundMoves(drinks, stepCents)`: `[{name, field, from, to}]` over the active drinks, in slot order with Minimum before Maximum.<br>Amounts use `centsText` (`lib/format.ts:74`), so 10 gives "0,10". `grid.test.ts` pins the spec's own examples: 124 on a 0,10 step gives "1,20 of 1,30"; 160 on 0,25 gives "1,50 of 1,75"; 0 is on the grid. `tests/unit/test_price_grid.py` pins the same strings, so the two sides cannot drift. | SD10: the browser checks first, and the server stays the authority. |
| PD9 | The Min/Max/Startprijs row (SD1, SD6, SD10) | **SD1 check:** on save, after the order check, each bound the save would send (the dirty ones) is checked with `gridMessage`. A failure goes into `faults[field]`, shows under that field, and nothing is sent.<br>**SD6 hint:** while a field still holds its stored value and that value is off the grid, the `MoneyField` shows `offGridHint` as its `hint` (`MoneyField.tsx:14`).<br>An unchanged off-grid bound is never sent, so the row still saves (AC5).<br>**The add form** checks both bounds before sending, with the `step_quant` `DrinksSection` already has in `config.params`. **Confirm** (the hint shows only while the stored value is untouched) | `useEditableRecord.save` sends only dirty fields, which matches SD6's "present in the request" on the server. |
| PD10 | The Prijsstap dialog (SD3, AC10) | On "Opslaan instellingen", if the patch holds a `step_quant` that is a valid number above 0 with whole cents, `boundMoves(config.drinks, stepCents(new))` is computed.<br>• **Some moves:** `ConfirmDialog` opens. Its `message` is "Prijsstap 0,25 opslaan? Deze grenzen schuiven mee:" and a list, one item per move: "Bier: Minimumprijs 1,60 → 1,75" (the plain words "Minimumprijs" and "Maximumprijs", not the field names with "(€)"). `confirmLabel` "Opslaan", `cancelLabel` "Annuleren". Cancelling sends nothing and keeps the typed values.<br>• **No moves, or an unparsable step:** it sends as today, and the server judges.<br>The dialog does not pre-check a collision. The server's `bounds_collision` fault shows under Prijsstap through `faultsOf`. **Confirm** | SD3: "the dialog is advice, the server's result is what is stored". A second client-side refusal would duplicate SD4's text and could disagree with the server. |
| PD11 | The profile-load and Nieuwe borrel errors (SD5, SD9) | `loadFailure` (`ProfilesSection.tsx:39`) and `failureText` (`BorrelSection.tsx:47`) check `code === 'bounds_collision'` **first**. They show the fault's `msg` verbatim, with no prefix, so the page reads "Past niet bij Bier: …". **Confirm** | "Profiel niet toegepast:" would be false for a copy with no profile. The server's sentence already names the drink. |
| PD12 | Existing tests that B-07 makes untrue | These change, each in the task that causes it:<br>• `tests/integration/test_drink_lifecycle.py:320-326` (T2) edits `p_max` to 325 on a 0,10 grid, which is now refused. It keeps its R6 coverage (the hold stepping back inside an off-grid bound): Bier is seeded with a stored `p_max` of 325 before go-live, and the edit changes `p_min` instead (the AC2 path).<br>• `tests/api/test_config.py:363` (T3), `{"step_quant": 5}` on drinks of 1,50–5,00, now collides. That case runs on a draft whose drinks fit a 5,00 grid (0 / 2,60 / 5,00).<br>• `tests/integration/test_runs.py:497` (T5): the copy on a 0,3 step now moves Bier's `p_max` from 500 to 480 (SD9). The assertion expects that move and every other column unchanged.<br>• `web/src/features/settings/BoundsSection.test.tsx:139` (T9) sends `p_max` 475 on a 0,10 step, now refused in the browser. It becomes 480.<br>Any **other** existing test that fails for a B-07 reason is a stop-and-ask. | These were found by searching every off-grid bound and every step change in `tests/` and `web/` (Risks R2). |

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `app/runtime/price_grid.py` | Create | PD1: the grid check, the move inward, `BoundsCollision` |
| `tests/unit/test_price_grid.py` | Create | PD1, PD2: neighbours, moves, collisions, the exact Dutch texts |
| `app/runtime/drinks.py` | Modify | SD1 on add and edit, bounds present only (PD6) |
| `tests/api/test_drinks.py` | Modify | AC1–AC3 |
| `tests/integration/test_drink_lifecycle.py` | Modify | PD12: R6 coverage kept via a stored off-grid bound |
| `app/runtime/config.py` | Modify | Moves on draft write, live write, profile load (SD3, SD5, SD8) |
| `tests/api/test_config.py` | Modify | AC6, AC8 (draft), AC9; PD12's step 5 case |
| `tests/api/test_profiles.py` | Modify | AC12 (server) |
| `tests/integration/test_config_live.py` | Modify | AC7, AC8 (live), AC9 (live), AC11 |
| `app/db/runs.py` | Modify | SD9 in `create_run` |
| `tests/integration/test_runs.py` | Modify | AC13 (repository); PD12's copy assertion |
| `tests/api/test_runs.py` | Modify | AC13 (route: 422 `bounds_collision`, no run) |
| `app/cli/v1_files.py` | Modify | PD7: step check, moves, `ImportPlan.moves` |
| `app/cli/import_v1.py` | Modify | PD7: moves on stderr |
| `tests/unit/test_v1_files.py` | Modify | AC14 (plan level) |
| `tests/integration/test_import_v1.py` | Modify | AC14 (end to end: stderr, stdout, exit 2, the real file) |
| `tests/integration/test_place_order.py` | Modify | T7: `_market` takes the drinks' bounds and params (defaults unchanged) |
| `tests/integration/test_unstick_on_grid.py` | Create | AC15 |
| `web/src/features/settings/explanations.json` | Modify | E1, E17, E19 (SD11) |
| `tests/unit/test_setting_explanations_text.py` | Modify | AC16: B-07's three rows from the spec |
| `tests/unit/test_setting_explanations_values.py` | Modify | AC16: the new "Toegestaan" phrases, each tied to a probe |
| `web/src/features/settings/explanations.test.ts` | Create | AC16 (Vitest): the three texts as the page loads them |
| `web/src/features/settings/grid.ts` | Create | PD8 |
| `web/src/features/settings/grid.test.ts` | Create | PD8 |
| `web/src/features/settings/BoundsSection.tsx` | Modify | PD9: SD1 check, SD6 hint |
| `web/src/features/settings/BoundsSection.test.tsx` | Modify | AC4, AC5; PD12's 475 |
| `web/src/features/settings/DrinksSection.tsx` | Modify | PD9: add-form check |
| `web/src/features/settings/DrinksSection.test.tsx` | Modify | AC4 |
| `web/src/features/settings/GlobalSection.tsx` | Modify | PD10: the dialog |
| `web/src/features/settings/GlobalSection.test.tsx` | Modify | AC10; AC8's message under Prijsstap |
| `web/src/features/settings/ProfilesSection.tsx` | Modify | PD11 |
| `web/src/features/settings/ProfilesSection.test.tsx` | Modify | AC12 (web) |
| `web/src/features/settings/BorrelSection.tsx` | Modify | PD11 |
| `web/src/features/settings/BorrelSection.test.tsx` | Modify | AC13 (web) |
| `web/e2e/bounds.spec.ts` | Create | The spec's Playwright flow |
| `docs/specs/phase-6-admin.md` | Modify | The "Per drink" note (spec › Documents) |
| `docs/specs/phase-b-01-settings-explained.md` | Modify | Notes on SD11, E1, E17, E19 pointing to B-07 |

---

## Tasks

### T1 — The grid helper
- **Implements:** AC1 (the message and its two neighbours), AC6 and AC8 (the move and the collision, as pure functions). SD1, SD3, SD4, PD1, PD2.
- **Expected output:**
  - `app/runtime/price_grid.py` as PD1, with `BoundsCollision` as PD2.
  - `tests/unit/test_price_grid.py` covers:
    - 124 and 160 refused on a 0,10 and a 0,25 step, with the spec's exact messages; 120, 0, 150 and 175 accepted;
    - a move up and a move down;
    - a bound already on the grid left alone;
    - both SD4 sentences, verbatim;
    - two collided drinks joined in slot order into one fault on the given `loc`;
    - moves listed in slot order, Minimum before Maximum;
    - `DrinkRow` and `ImportedDrink` both accepted.
- **Verification:** `uv run pytest tests/unit/test_price_grid.py`; `uv run mypy app/runtime/price_grid.py`.
- **Depends on:** —
- **Autonomy note:** The builder may choose internal names, a `Protocol` or a `TypeVar` for the generic row, and the test layout. Stop and ask if a spec message cannot be produced exactly, or if the helper seems to need an `exchange/` import beyond types.

### T2 — The bound check on drink add and edit
- **Implements:** AC1, AC2, AC3. SD1, SD2, SD6, PD6.
- **Expected output:**
  - `add_draft_drink`, `add_live_drink`, `_edit` and `_edited` (`app/runtime/drinks.py:170-228`) run `grid_faults` on the bounds present, under the locked run's step. Off-grid is 422 naming the field, with nothing written. On the live run no transition is taken: the error is raised inside `step` before `commit_transition`, so the holder's view stays unchanged (`holder.py` rolls back).
  - The module docstring's Validation paragraph says so.
  - `tests/api/test_drinks.py` covers:
    - add and edit on 0,10 (124 refused, "1,20 of 1,30"; 120 and 0 accepted) and on 0,25 (160 refused; 150 and 175 accepted), with nothing stored on a refusal;
    - a partial edit of a drink whose other bound is stored off the grid (seeded by SQL), sending only `p0_cents` and then only the other bound: 200, and the stored bound unchanged (AC2);
    - an off-grid Startprijs between on-grid bounds accepted (AC3).
  - `test_drink_lifecycle.py` gets PD12's change.
- **Verification:** `uv run pytest tests/api/test_drinks.py`; `uv run pytest tests/integration/test_drink_lifecycle.py` (separately, MEMORY: pytest api+integration split).
- **Depends on:** T1
- **Autonomy note:** The builder may decide how the test switches a run to a 0,25 step (a config PATCH before any drink exists, or SQL). Stop and ask if keeping R6 coverage in `test_drink_lifecycle.py` needs more than PD12 describes.

### T3 — A Prijsstap change and a profile load on a draft
- **Implements:** AC6, AC8 (draft), AC9, AC12 (server). SD3, SD4, SD5, SD8, PD3–PD5.
- **Expected output:**
  - **A shared helper.** `app/runtime/config.py` gains `_move_bounds(conn, drinks, step, *, loc) -> list[DrinkRow]`. It runs `move_inward` on the active rows, `update_drink`s each moved row, and returns every row as it now is.
  - **The draft write.** `write_draft_config` calls `_move_bounds` when PD4 says the step changed, after `_merged` and before `_record`, so one transaction holds the moves, the run columns and one revision. A collision raises before any write.
  - **The profile load.** `load_profile_onto_draft` always calls it under the merged step, with loc `["profile", "params", "step_quant"]`. It follows PD5.
  - Both docstrings say so.
  - **Tests in `tests/api/test_config.py`:**
    - a draft step change from 0,10 to 0,25 over Bier (1,60–3,10), Wijn (on grid) and a drink removed by SQL. Bier moves to 1,75–3,00 and Wijn does not. The removed drink is untouched (its row is deleted on a draft, so the test seeds a draft that still has a `removed_at` row by SQL). The revision count goes up by exactly one, and the new revision's document shows the moved bounds;
    - a collision: `{"name": …, "params": {"step_quant": 0.25, "eta": …}}` gives 422 `bounds_collision` on `step_quant` naming each drink, and leaves the name, `eta`, the bounds and the revision count unchanged;
    - a non-step write (`eta`, name, Kaarsbreedte) over a stored off-grid bound moves nothing (AC9);
    - PD12's step 5 case.
  - **Tests in `tests/api/test_profiles.py`:**
    - a load whose step differs moves the bounds;
    - a load whose step is equal still moves a stored off-grid bound and appends one revision;
    - an equal load with nothing to move appends nothing;
    - a collision gives 422 `bounds_collision` with nothing written.
- **Verification:** `uv run pytest tests/api/test_config.py tests/api/test_profiles.py`.
- **Depends on:** T1
- **Autonomy note:** The builder may lay out `_move_bounds` and the tests as it likes. Stop and ask if moving bounds needs `_merged`'s return type to change in a way that also changes the live path's behaviour (that is T4's).

### T4 — A Prijsstap change on the live run
- **Implements:** AC7, AC8 (live), AC9 (live), AC11, AC17 (the guardian check over the engine-feeding paths). SD3, SD8, SD12.
- **Expected output:**
  - **The write.** In `write_live_config` (`config.py:397-430`), when PD4 says the step changed:
    - `_move_bounds` runs on the locked run's rows;
    - the spec is `spec_from_rows(rows, params)`, asserted to give `view.drink_ids`;
    - `hold_quoted_prices(view.spec, spec, state, active)` runs once over every active slot;
    - then `_record` and `commit_transition`, as today.
  - **Every other change** keeps `dataclasses.replace(view.spec, params=params)`.
  - A collision raises inside `step` before any write, so no transition is taken.
  - The docstring says so.
  - **Tests in `tests/integration/test_config_live.py`.** `_live` takes optional bounds per drink; its default is unchanged.
    - **A live step change from 0,10 to 0,25** with a running jump and a market event:
      - one transition (version + 1, one `config` tick, one revision);
      - the moved bounds in the rows and in `holder.spec`;
      - `state.jumps == ()`;
      - every quote under the new spec equal to its old quote, clamped into the new bounds and re-quantised. Each lies within its bounds and is a multiple of 25 cents;
      - the transition's `price_tick` prices equal those quotes.
    - **A collision:** version, rows, tick count and revision count all unchanged.
    - **A non-step live save** with a stored off-grid bound: no move, `y` bitwise.
    - **A restart** after the step change (`rehydrate`, as `test_a_restart_runs_on_the_changed_values`, `:532`): the new step and the moved bounds.
- **Verification:**
  - `uv run pytest tests/integration/test_config_live.py`;
  - `bash scripts/golden_linux.sh`;
  - `engine-guardian` on the T1–T4 diff, reporting no maths change.
- **Depends on:** T3
- **Autonomy note:** The builder may choose the drinks and prices that make the hold observable. It is a **hard stop** (CLAUDE.md) if a golden fixture diverges, if `engine-guardian` reports a maths change, or if a held quote can lie outside its new bounds. That last case would mean `hold_quoted_prices` meets a case its R6 rule does not cover, which is a pricing question.

### T5 — Nieuwe borrel copies drinks onto the grid
- **Implements:** AC13 (server). SD9, PD3.
- **Expected output:**
  - **The move.** `create_run` (`app/db/runs.py:470-562`) runs `move_inward` on the copied rows under the new draft's final `params.step_quant`: the profile's, else the source run's. This happens after the profile is applied and before `create_draft_run`, so a collision raises with nothing written. The loc follows PD2.
  - Only the bounds of a copied drink can change.
  - The docstring says so.
  - **Tests in `tests/integration/test_runs.py`:**
    - a copy with no profile, from a source whose bound is off its own step: the bound is moved;
    - a copy with a profile whose step differs: moved onto the profile's step;
    - a collision: `BoundsCollision` and `count(*) FROM run` unchanged;
    - PD12's copy assertion.
  - **`tests/api/test_runs.py`:** `POST /api/runs` with a colliding copy gives 422 `bounds_collision` naming the drink, and `GET /api/runs/current` still answers 404 (no draft).
- **Verification:** `uv run pytest tests/integration/test_runs.py`; `uv run pytest tests/api/test_runs.py` (separately).
- **Depends on:** T1
- **Autonomy note:** The builder may choose fixtures. Stop and ask if `create_run` must re-read the source rows to move them. They are already `DrinkRow`s (`runs.py:510`), so it should not.

### T6 — The v1 import moves bounds and says so
- **Implements:** AC14. SD7, PD3, PD7.
- **Expected output:**
  - `build_plan` and `ImportPlan` as PD7, and `main` printing the moves to stderr.
  - Both modules' docstrings say so.
  - **`tests/unit/test_v1_files.py`:**
    - a crafted config with `p_min` 1,24 on 0,10 gives 130 and a `BoundMove`;
    - a step of 0 or 0,015 raises a `ValueError` naming `step_quant`;
    - a collision raises a `ValueError` naming the drink.
  - **`tests/integration/test_import_v1.py`:**
    - that crafted file imports with exit 0; stdout is exactly the `run_id`; stderr holds `import_v1: Bier: p_min 1,24 → 1,30`; the stored bound is 130 and so is revision 1's;
    - a colliding file exits 2, naming the drink, and leaves `count(*) FROM run` unchanged;
    - the real file (`LIVE_CONFIG_PATH`) imports with empty stderr.
- **Verification:** `uv run pytest tests/unit/test_v1_files.py`; `uv run pytest tests/integration/test_import_v1.py`.
- **Depends on:** T1
- **Autonomy note:** The builder may write the crafted files in `tmp_path`. It must never edit `tests/fixtures/v1/` (CLAUDE.md, hash-pinned). Stop and ask if the real file needs any move: the spec says it needs none.

### T7 — The evidence: a crashed drink leaves an on-grid floor at the first order
- **Implements:** AC15.
- **Expected output:**
  - `_market` in `tests/integration/test_place_order.py` takes optional `bounds` and `params`, with today's values as its defaults, so every existing caller is unchanged.
  - **`tests/integration/test_unstick_on_grid.py`**, with idle drift and noise off so only the order moves the price:
    - **On-grid floor.** Bier at 1,20–5,00 on a 0,10 step. A Marktcrash runs to its end, and Bier's quote is exactly 1,20. One order for Bier is placed at its live quote. After that order the quote is above 1,20.
    - **Off-grid floor.** The same with a Minimumprijs of 1,24, seeded by SQL as a pre-B-07 row. The quote sits at 1,20, below the bound, and after one order it is still 1,20.
- **Verification:** `uv run pytest tests/integration/test_unstick_on_grid.py tests/integration/test_place_order.py tests/integration/test_bar_price_snapshot.py` (the last imports `_market`).
- **Depends on:** —
- **Autonomy note:** The builder may choose the event length, the tick count and the params that isolate the order (for example `bm_enabled=False`, `idle_strength=0`, `idle_rise_strength=0`). It is a **hard stop** (a question about the pricing maths) if the on-grid floor does not leave at the first order, or the off-grid one does. Either contradicts the measurement the spec cites.

### T8 — The texts E1, E17, E19 and their guards
- **Implements:** AC16. SD11.
- **Expected output:**
  - **The texts.** `explanations.json`'s `step_quant`, `p_min_cents` and `p_max_cents` paragraphs are exactly the spec's "The texts (SD11)". Their names are unchanged.
  - **`test_setting_explanations_text.py`:**
    - `parse_spec_table` gains a `heading` argument, defaulting to `"## The table"`;
    - `B07_ROWS` parses the B-07 spec under `"### The texts (SD11)"`;
    - `EXPECTED_ROWS` overlays it last;
    - a new test pins that `B07_ROWS` is exactly E1, E17 and E19, keyed by their fields;
    - every other row is still compared to its old source (AC16's "every other row unchanged").
  - **`test_setting_explanations_values.py`.** Each new phrase is asserted only while its probe holds, as `_bounds_are_strict` does:
    - `step_quant`'s "Toegestaan" becomes `render_range(...)` + "; niet als een drankje daardoor geen ruimte meer heeft tussen Minimumprijs, Startprijs en Maximumprijs". Its probe: `move_inward` raises `BoundsCollision` on a drink with no room;
    - `p_min_cents`'s becomes "0 of meer, een veelvoud van de Prijsstap, en lager dan de Startprijs";
    - `p_max_cents`'s becomes "een veelvoud van de Prijsstap, hoger dan de Startprijs";
    - the probe for both: `grid_faults` refuses 124 and accepts 120 on a 10-cent step.
  - **`explanations.test.ts` (Vitest):** the three entries, as the page imports them, hold the new sentences ("schuiven ze mee naar binnen", "een veelvoud van de Prijsstap").
- **Verification:** `uv run pytest tests/unit/test_setting_explanations_text.py tests/unit/test_setting_explanations_values.py`; `pnpm -C web vitest run src/features/settings/explanations.test.ts`.
- **Depends on:** T1
- **Autonomy note:** The builder may restructure the parser minimally. Stop and ask if a spec paragraph cannot be matched exactly (an invisible character, say), or if a "Toegestaan" phrase cannot be tied to a probe. In that case the text would be pinned by nothing, which is what B-01 SD8.1 forbids.

### T9 — The grid model, the bounds rows and the add form
- **Implements:** AC4, AC5. SD1, SD6, SD10, PD8, PD9.
- **Expected output:**
  - `grid.ts` and `grid.test.ts` as PD8.
  - `BoundsRow` takes `stepCents` from `config.params.step_quant`, and checks and hints as PD9. `AddDrinkForm` checks both bounds.
  - Both modules' header comments say so.
  - **`BoundsSection.test.tsx`:**
    - typing 1,24 on a 0,10 run shows "Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30." under Minimumprijs, with no request sent;
    - a stored 1,24 shows "Niet op de Prijsstap: kies 1,20 of 1,30." under it, and changing only the Startprijs sends `{p0_cents}`;
    - PD12's 475.
  - **`DrinksSection.test.tsx`:** the add form refuses an off-grid Maximumprijs, with no request sent.
- **Verification:** `pnpm -C web vitest run src/features/settings/grid.test.ts src/features/settings/BoundsSection.test.tsx src/features/settings/DrinksSection.test.tsx`.
- **Depends on:** —
- **Autonomy note:** The builder may lay out the model and the tests as it likes. Stop and ask if `MoneyField`'s `hint` cannot show beside an `error`, or if the check would have to block a save that sends no off-grid bound (SD6).

### T10 — The Prijsstap dialog
- **Implements:** AC10, and AC8's message as shown on the page. SD3, PD10.
- **Expected output:**
  - `GlobalSection` behaves as PD10, with a state for the pending body, and its header comment says so.
  - **`GlobalSection.test.tsx`:**
    - 0,10 → 0,25 over a drink at 1,50–3,10 shows the dialog with "Prijsstap 0,25 opslaan? Deze grenzen schuiven mee:" and "…: Maximumprijs 3,10 → 3,00";
    - "Annuleren" sends nothing; "Opslaan" sends one PATCH;
    - a step change that moves nothing sends without a dialog;
    - a 422 `bounds_collision` shows its message under Prijsstap.
  - Existing tests whose fixture moves a bound on a step change are adapted. That is a named change in the commit, not silent (PD12).
- **Verification:** `pnpm -C web vitest run src/features/settings/GlobalSection.test.tsx`.
- **Depends on:** T9
- **Autonomy note:** The builder may choose the list markup inside the dialog. Stop and ask if `ConfirmDialog` would need a change (it should not: `message` is a `ReactNode`).

### T11 — The profile-load and Nieuwe borrel messages
- **Implements:** AC12 (web), AC13 (web). SD5, SD9, PD11.
- **Expected output:**
  - `loadFailure` and `failureText` as PD11.
  - **`ProfilesSection.test.tsx`:** a load answered 422 `bounds_collision` with the fault "Past niet bij Bier: …" shows that text, not "valt buiten de toegestane waarden".
  - **`BorrelSection.test.tsx`:** the same for a create with a copy.
- **Verification:** `pnpm -C web vitest run src/features/settings/ProfilesSection.test.tsx src/features/settings/BorrelSection.test.tsx`.
- **Depends on:** T1 (the code name, so the web and the server use one spelling)
- **Autonomy note:** Trivial wiring. Stop and ask if either page needs more than its failure text to change.

### T12 — The Playwright flow, and the closing check on the maths
- **Implements:** AC4, AC10 and AC6 end to end (the spec's Playwright paragraph); AC17 over the whole branch.
- **Expected output:** `web/e2e/bounds.spec.ts`, laid out as `profiles.spec.ts` (its own `startServer('bounds', ['--empty'])`, serial). The steps:
  1. a borrel;
  2. Bier added at 1,50 / 2,00 / 3,10;
  3. Prijsstap 0,10 → 0,25, and the dialog lists "Maximumprijs 3,10 → 3,00";
  4. "Opslaan", then a reload: Bier's Maximumprijs reads 3,00;
  5. Minimumprijs 1,60 typed and saved shows "Moet een veelvoud van de Prijsstap (0,25) zijn: 1,50 of 1,75." and the row still reads 1,50 after a reload.
- **Verification:**
  - `pnpm -C web exec playwright test e2e/bounds.spec.ts`;
  - `./scripts/check.sh` (13/13, output pasted);
  - `bash scripts/golden_linux.sh`;
  - `git diff main -- exchange/` empty.
- **Depends on:** T3, T10
- **Autonomy note:** The builder may choose selectors, following `profiles.spec.ts`. A golden divergence is a hard stop.

### T13 — The document notes
- **Implements:** the spec's In scope › Documents (support for SD11's "B-01 SD11 is superseded"). Traced to AC16, whose texts these notes point to.
- **Expected output:**
  - **`docs/specs/phase-6-admin.md`.** The "Per drink" list (`:213-218`) gains one line: since B-07, `p_min_cents` and `p_max_cents` are a multiple of the Prijsstap, and a Prijsstap change moves them inward. It links the B-07 spec.
  - **`docs/specs/phase-b-01-settings-explained.md`:**
    - SD11 (`:119-123`) gains a note: superseded by B-07 SD1/SD3;
    - E1 (`:169`), E17 (`:306`) and E19 (`:322`) each gain a note after their `Bron:` line: the shipped text is B-07's.
  - No `> ` line of B-01's table changes.
- **Verification:** `uv run pytest tests/unit/test_setting_explanations_text.py` (the parser still reads B-01's table unchanged).
- **Depends on:** T8
- **Autonomy note:** The builder may choose the wording of the notes. It must put no note between a row line and its `> ` lines: the parser expects them adjacent (`test_setting_explanations_text.py:75-82`). Stop and ask if a note seems to need a change to any `> ` paragraph.

---

## AC coverage

| AC | Tasks |
|---|---|
| AC1 | T1, T2 |
| AC2 | T2 |
| AC3 | T2 |
| AC4 | T9, T12 |
| AC5 | T9 |
| AC6 | T1, T3, T12 |
| AC7 | T4 |
| AC8 | T1, T3, T4, T10 |
| AC9 | T3, T4 |
| AC10 | T10, T12 |
| AC11 | T4 |
| AC12 | T3, T11 |
| AC13 | T5, T11 |
| AC14 | T6 |
| AC15 | T7 |
| AC16 | T8, T13 |
| AC17 | T4, T12 |

---

## Task graph

```
T1 ──┬── T2
     ├── T3 ── T4
     │     └──────── T12
     ├── T5
     ├── T6
     ├── T8 ── T13
     └── T11
T9 ── T10 ──────── T12
T7
```

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T7, T9 | T1: `app/runtime/price_grid.py`, `tests/unit/test_price_grid.py` · T7: `tests/integration/test_place_order.py`, `tests/integration/test_unstick_on_grid.py` · T9: `web/src/features/settings/{grid.ts, grid.test.ts, BoundsSection.tsx, BoundsSection.test.tsx, DrinksSection.tsx, DrinksSection.test.tsx}` |
| G2 | T2, T3, T5, T6, T8, T10, T11 | T2: `app/runtime/drinks.py`, `tests/api/test_drinks.py`, `tests/integration/test_drink_lifecycle.py` · T3: `app/runtime/config.py`, `tests/api/test_config.py`, `tests/api/test_profiles.py` · T5: `app/db/runs.py`, `tests/integration/test_runs.py`, `tests/api/test_runs.py` · T6: `app/cli/v1_files.py`, `app/cli/import_v1.py`, `tests/unit/test_v1_files.py`, `tests/integration/test_import_v1.py` · T8: `web/src/features/settings/explanations.json`, `web/src/features/settings/explanations.test.ts`, `tests/unit/test_setting_explanations_{text,values}.py` · T10: `web/src/features/settings/GlobalSection{.tsx,.test.tsx}` · T11: `web/src/features/settings/{ProfilesSection,BorrelSection}{.tsx,.test.tsx}` |
| G3 | T4, T12, T13 | T4: `app/runtime/config.py`, `tests/integration/test_config_live.py` · T12: `web/e2e/bounds.spec.ts` · T13: `docs/specs/phase-6-admin.md`, `docs/specs/phase-b-01-settings-explained.md` |

No two tasks in one group write the same file:
- `config.py` is T3 (G2) then T4 (G3);
- `test_profiles.py` imports from `test_config.py` (`tests/api/test_profiles.py:27`), and both are written only by T3;
- `test_bar_price_snapshot.py` imports `_market`, which T7 changes only by adding defaulted parameters.

---

## Data changes

None (SD12). No migration, no backfill, no deploy-time fix-up. A bound already stored off the grid stays as it is until one of SD8's paths moves it (SD6).

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | The live step change now builds its spec from rows (`spec_from_rows`) instead of `replace`. If the rows and the view ever differ in more than the bounds (an `s0` anchored live but not written, say), the hold would start from a spec the market never ran. | `anchor_s0` writes every active `drink.s0` (`config.py:447-451`), and every other live drink write rebuilds from rows already (`drinks.py:198`, `:326`, `:393`). T4 asserts `drink_ids == view.drink_ids` and checks every held quote against the old quote, clamped. `engine-guardian` reviews T1–T4. |
| R2 | Existing tests and fixtures written with off-grid bounds, or step changes that now move or collide. | Searched: every bound in `tests/` and `web/` whose last digit is not 0 (two hits), and every step change (PD12 lists the four that break). The e2e flows add drinks on 0,50 multiples and change the step only to 0,05 (`admin.spec.ts:16-19`, `:123`), which moves nothing. Any other failure is a stop-and-ask (PD12). |
| R3 | `hold_quoted_prices`' R6 step-back (`exchange/state.py:115-120`) becomes reachable only through a stored off-grid bound. | Its test is kept on that path (PD12, T2), and the engine's own tests are unchanged. |
| R4 | The text guard reads a second section shape (`### The texts (SD11)` inside `## Decisions`) from a spec, where earlier rows sit in a `## The table` section. | `parse_spec_table` gains a heading argument, and the existing calls keep the default. The section ends at the next `\n## ` (`## In scope`), and `\n### ` cannot match it. |
| R5 | `faultsOf` keeps one message per field, so two collided drinks need one joined fault (PD2). A future change to one fault per drink would silently show only the last drink. | `test_price_grid.py` pins the single joined fault. `GlobalSection.test.tsx` shows a two-drink message in full. |
| R6 | The import gains a step check (PD7). A v1 file with a bad step that used to import now exits 2. | Such a run could never go live (`exchange/spec.py:146-152`). v1's real file has 0,10 (`tests/fixtures/v1/config/exchange_config.json:71`). The audit confirms PD7. |
| R7 | The SD3 dialog is computed from a config document that may be stale (a bound changed meanwhile in another tab). | SD3: the server recomputes from the rows inside the transaction, and the dialog is advice. The section's conflict banner (`GlobalSection.tsx:142-147`) already covers a server change while editing. |
| R8 | AC15's evidence depends on engine behaviour, which a test can only observe. If idle drift, noise or demand move the price, the test proves nothing. | T7 turns them off, and its autonomy note makes a contrary result a hard stop instead of a test to tweak. |

---

## Out of scope for this plan

Everything in the spec's Out of scope, and also:
- **Pre-checking a collision in the dialog.** PD10: the server's message is the one answer.
- **The manipulation page's Doelprijs, market event targets and `bar_price_cents`:** spec Out of scope. `grid.ts` is used only by the settings section.
- **A grid check on a profile save:** a profile stores a step and no bounds (spec Out of scope).
- **Committing the spec and the backlog change** now uncommitted on `main` (`docs/backlog.md`, `docs/specs/phase-b-07-bounds-on-grid.md`). That is the owner's branch choice before `/build` (MEMORY: B-07 spec progress), not a task.

---

## Audit (plan-auditor — PASS required before implementation starts)
- [ ] Every AC maps to at least one task
- [ ] Every task maps to at least one AC (no orphans)
- [ ] Each task's expected output is what we actually need
- [ ] Existing patterns reused; nothing reinvented
- [ ] No new dependency without an approval note
- [ ] Data changes additive and reversible
- [ ] Errors, empty states and permissions are tasks, not afterthoughts
- [ ] Each task reviewable in one sitting
- [ ] Verification named per task
- [ ] Nothing touches prod, secrets or infra it should not
- [ ] Every task has a Depends on and an Autonomy note
- [ ] No two tasks in one parallel group write the same file

Audited by: ______  Date: ______
