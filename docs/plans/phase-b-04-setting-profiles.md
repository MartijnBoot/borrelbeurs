# Plan: B-04 — Named setting profiles per type of game

Spec: [docs/specs/phase-b-04-setting-profiles.md](../specs/phase-b-04-setting-profiles.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-24)**
Design: [data-model.md](../design/data-model.md) gains one row (T13, an owner stop: `docs/design/`), [frontend-architecture.md](../design/frontend-architecture.md) unchanged (no new feature folder)
ADRs honoured: 0002 and 0012 (`exchange/` read, never changed), 0004 (one Postgres engine; a profile lives in the database it was saved in, SD8), 0011 (the migration runs at boot, unattended, so it is a plain `create_table`). Nothing in an ADR is reversed.
Backlog: [B-04](../backlog.md) · Fixes: no open defect

Line references are to `docs/phase-b-04-spec` at `54d6a03` (`main` `b6fec1e` plus the spec).

---

## Approach

**One table, one rule set, three doors.** A profile is a row in a new `settings_profile` table
holding the 22 SD1 values as JSONB. Every door into or out of it goes through one function pair
that knows what the 22 are and checks them against today's `ConfigPatch` rules:
`profile_settings(params, candle_interval_ms)` makes the 22 from a run (save) and
`profile_patch(settings, source=...)` turns stored values into a validated `ConfigPatch` (create
and load). A field the stored profile lacks is simply not set in the patch, so it keeps its base
value (SD9, AC15). A stored key outside the 22 is never read. A value outside the rules becomes
the same 422 envelope `_target_names` already produces (`app/runtime/config.py:275-289`), so
the web's `faultsOf` (`web/src/features/settings/useRunConfig.ts:99-114`) finds the field
without change. The three doors reuse what exists:
- the save reads the run as `config_document` does (`Params.from_dict`, `candle_interval_ms //
  1000`, `config.py:231-250`);
- the load is a draft config write through `_merged` and `_record` (`config.py:300-329`), so an
  equal profile appends no revision and the author is the key label;
- the create is `create_run` (`app/db/runs.py:438-501`) with the profile overlaid on the params
  it already picks, inside its one transaction.

On the web, "Profielen" is one more section in `features/settings`. It refreshes the other
sections with the existing `useCurrentRun` version bump (`useCurrentRun.ts:29-46`), and their
unsaved edits are kept by the existing `useEditableRecord` "Overnemen" (`useEditableRecord.ts:60-74`).

**The one structural change** is moving the patch models (`ParamsPatch`, `ConfigPatch`, their
validators and `InvalidConfig`, `config.py:79-157`) into a leaf module,
`app/runtime/config_patch.py`, re-exported from `config.py` so no importer changes. `create_run`
lives in `app/db/runs.py`, and `config.py` imports `app/db/runs.py` (`config.py:60`). For
`create_run` to validate a profile with the same rules, the rules must sit somewhere that does not
import `app.db`. `app/db` already imports leaf runtime modules (`app/db/theme.py:27`,
`engine_state.py:27`).

Rejected:
- **A lazy import of `config.py` inside `create_run`, or a validator callback passed in from the
  route.** Both hide a cycle instead of removing it. The move is a pure cut-and-paste plus a
  re-export.
- **Routing the load through `write_draft_config` unchanged**, as the spec's interface sketches.
  It opens its own transaction (`config.py:435`), so the profile read would sit outside it
  (SD15). It answers an ended run with `run_ended`, where AC13 wants `run_not_draft`
  (`readable()` at `:436` runs before the status check). And it returns 200 for an empty patch
  without checking the status at all (`:433-434`). The load is a sibling function in
  `config.py` that uses the same `_merged` and `_record` in one transaction, checking the status
  first. `write_draft_config` itself is not changed.
- **A `features/profiles/` folder.** The boundaries rule (`web/eslint.config.js:109-137`) would cut
  it off from `useCurrentRun`, `useRunConfig`, `faultsOf` and the version bump, so a load could
  not refresh the other sections. It would also make `frontend-architecture.md:36` stale.
- **Sending a profile's values in `GET /api/profiles`.** SD12 shows none, so the API carries
  none.
- **A FK from `settings_profile` to `run`.** SD7: no link. The source name is copied text.

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. The row marked **Owner** is
a spec ambiguity with two user-visible readings (CLAUDE.md hard stop).

**Audit 2026-10-24:** the owner confirmed every **Confirm** row as written (PD1, PD9, PD12) and
ruled PD10 **reading A**.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | Where the 22 and their rules live | `app/runtime/config_patch.py` (leaf: imports pydantic, `app.core.errors`, `exchange.Params` only) holds the moved patch models plus `PROFILE_FIELDS`, `profile_settings(params: Params, candle_interval_ms: int) -> dict` and `profile_patch(settings: Mapping, *, source: Literal["run", "profile"]) -> ConfigPatch`. `config.py` re-exports the moved names explicitly (`X as X` or `__all__`: mypy `strict = true`, `pyproject.toml:104`). `PROFILE_FIELDS` is *derived*: `ParamsPatch` fields minus `idle_targets`/`idle_rise_targets`, plus `candle_interval_s`. A unit test pins it to SD1's 22 literally. **Confirm** | Removes the cycle (Approach). Derived plus pinned means a future `ParamsPatch` field shows up as a failing pin. It is not silently added to profiles |
| PD2 | The 422 for a stored or run value outside the rules | `profile_patch` catches `pydantic.ValidationError` and raises `InvalidConfig(f"{field}: {msg}", extra={"faults": [{"loc": [source, *loc], "msg": msg}]})`, e.g. `["profile", "params", "y_clip"]`, `["run", "candle_interval_s"]`. Status 422, code `invalid_request`. Every failing field is listed, not only the first | The envelope `_target_names` already uses (`config.py:283-288`). Nothing turns an in-code `ValidationError` into an envelope today (`app/core/errors.py:76-98` handles `RequestValidationError` only), so without this it would be a 500. `faultsOf` reads `loc.at(-1)` |
| PD3 | What a save stores, and from where | `profile_settings(Params.from_dict(run.params), run.candle_interval_ms)`: the 21 params by attribute, `candle_interval_s = candle_interval_ms // 1000`. The result is then run through `profile_patch(…, source="run")`, and what is stored is exactly that dict, all 22 keys | "As committed" is what the page shows, and the page reads it this way (`config.py:235-246`). `Params.from_dict` fills a key a raw run lacks with its default, as the document does |
| PD4 | Table and repository | `settings_profile`: `profile_id` BigInteger identity PK; `name` text, CHECK `char_length(btrim(name)) BETWEEN 1 AND 100` (as `run_name_check`, `app/db/models.py:51`); `name_key` text, unique index `settings_profile_name_key`; `settings` JSONB; `source_run_name` text; `saved_at` timestamptz `server_default now()`; `saved_by` text. All NOT NULL. `name_key` = `app.db.runs.name_key` (`runs.py:186-188`), reused, not copied. Repository `app/db/profiles.py`, connection-taking like `runs.py:1-18`: `list_profiles`, `get_profile` (`ProfileNotFound`, 404 `profile_not_found`), `save_profile(…, overwrite)` and `delete_profile` | Column style of `run` and `product` (`0010_phase_7_lifecycle.py:45-51`) |
| PD5 | Save under an existing name, and concurrency (SD5, SD15) | Without `overwrite`: `INSERT … ON CONFLICT (name_key) DO NOTHING RETURNING profile_id`. If no row comes back, read the existing id and raise `ProfileExists` (409 `profile_exists`, `extra={"profile_id": …}`, as `DraftExists`, `runs.py:456-458`). With `overwrite`: `ON CONFLICT (name_key) DO UPDATE SET settings, source_run_name, saved_by, saved_at = now()`, leaving `name` alone. Created vs overwritten comes from `RETURNING (xmax = 0)`. 201 if created, 200 if overwritten. A profile deleted in the meantime is simply inserted | Upsert precedent `app/db/theme.py:86-123`. Two same-name saves: the unique index lets exactly one insert win. The stored spelling stays the original's (SD5) |
| PD6 | `saved_at` on the wire, and the list order | `saved_at: datetime` (ISO), as `app/api/keys.py:63-64`. The web parses it with `Date.parse` (`KeysSection.tsx:144`). `list_profiles` sorts in Python by `(name_key, profile_id)`, not `ORDER BY` | SD12 says "case-folded". Postgres collation would order differently from `str.casefold()` (`models.py:103-105` gives the same reason for `name_key`) |
| PD7 | The load (SD3, SD15) | `load_profile_onto_draft(engine, run_id, profile_id, *, author) -> int` in `config.py` beside `write_draft_config`, as one `engine.begin()`:<br>1. `get_run(lock=True)` (404 `run_not_found`);<br>2. status `!= "draft"`, ended included, gives `RunNotDraft` (409 `run_not_draft`) with a load-specific message;<br>3. `get_profile` (404);<br>4. `profile_patch(source="profile")` (422);<br>5. `_merged`: `None` gives `latest_revision`, otherwise `_record(author=…)`.<br>The route is `POST /api/runs/{run_id}/profile {profile_id}` in `app/api/config.py`, returning `RevisionData` | Approach. The status check comes first, so an empty or equal profile on a live run is still 409 (AC13) |
| PD8 | The create (SD4) | `create_run(…, profile_id: int \| None = None)`. After today's refusals and base params (`runs.py:452-471`):<br>1. `get_profile(conn, …)`;<br>2. `profile_patch(source="profile")`;<br>3. `params = dataclasses.replace(params, **patch.params.model_dump(exclude_unset=True))`;<br>4. Kaarsbreedte = `patch.candle_interval_s * 1000` when set.<br>`create_draft_run` gains keyword `candle_interval_ms: int \| None = None`; `None` keeps the column default, so `import_v1` is unaffected. `CreateRunRequest` gains `profile_id: int \| None = None` | One transaction. A 404 or 422 rolls back, so no run is created (AC10). Without a profile no line of today's path changes (AC9) |
| PD9 | "Revision 1 shall carry the profile's values" (AC7), and Kaarsbreedte in it | Revision 1 (`runs.py:491-500`) gains one key, `"candle_interval_s": <the run's>`, on **every** create, 60 when no profile. Its other keys and shape stay as they are. **Confirm** | Revision 1 never recorded Kaarsbreedte, so it cannot carry the profile's otherwise. Writing it only when a profile is picked would give revision 1 two shapes. Nothing in `app/` reads a revision back, and the run itself is unchanged, so AC9 holds |
| PD10 | AC16's idle clause | **Owner.** A profile loads only onto a draft (SD3). The manipulation page's idle section shows only the store's *live* run (`IdleSection.tsx:47-74`) and shows "Laden…" while there is none (`:85-87`). So right after a load there is no idle section showing a value. **Reading A (recommended):** satisfied when the draft goes live. The section then fetches that run's config and shows the loaded idle numbers. Tested by the go-live integration (T11) and a Vitest on `IdleSection` with a live run built from a profile's values. `IdleSection` is not changed. **Reading B:** the idle section also shows a draft's idle numbers, so they are visible right after a load. That is a new behaviour on `/manipulation` the spec does not describe. **Owner ruled A at the audit, 2026-10-24** | The two readings give different screens. That is the owner's call (CLAUDE.md hard stops) |
| PD11 | The setting names for a 422 (AC23) | `features/manipulation/index.ts` also exports its `explanations.json` as `manipulationExplanations` (as `features/settings/index.ts:9` exports `settingsExplanations`). `SettingsPage` (app layer) builds `settingNames: Record<string, string>` (wire name → `name`) from both and passes it as a `names` prop to `ProfilesSection` and `BorrelSection`. A Vitest pins that all 22 SD1 wire names have a name | `features/settings` may not import `features/manipulation` (`eslint.config.js:109-137`), and the four idle entries may not be copied (`test_setting_explanations_text.py:142-147`). The app layer may import both. B-01 and B-03 named all 22 |
| PD12 | The page texts the spec does not fix | Save 422 on a value: "Niet opgeslagen: '<naam instelling>' valt buiten de toegestane waarden." Load or create 422: "Profiel niet toegepast: '<naam instelling>' valt buiten de toegestane waarden." Name 422: "Vul een naam in (1–100 tekens)." (as `BorrelSection.tsx:37`). `profile_not_found`: "Dit profiel bestaat niet meer." plus a list reload. `run_not_draft` on a load: "Deze borrel is geen concept meer." plus a run reload. List fetch failure in Profielen: "Verbindingsfout. Probeer opnieuw." Overwrite confirm label "Overschrijven", load "Laden", delete "Verwijderen", cancel "Annuleren". **Confirm** | Errors are tasks, not afterthoughts. Wording follows the existing sections |
| PD13 | Keeping the "Nieuwe borrel" select fresh | `features/settings/useProfiles.ts`: `GET /api/profiles` with a module-level version bump copied from `useCurrentRun` (`:33-46`). Every save, overwrite and delete in Profielen bumps it, so the form's select refetches. A failed fetch yields `[]` plus `failed` | `BorrelSection` fetches its run list only when `noRun` flips (`:50-61`). Delete works with no run (AC21), so a list fetched once would go stale and the next create would 404 |
| PD14 | "d mmm HH:mm" in Amsterdam time (SD12) | `web/src/lib/time.ts` gains `formatDayMonthTime(ms)`. It uses the module's `nl-NL` `Europe/Amsterdam` formatter with `formatToParts` for day, short month (a trailing `.` stripped) and `HH:mm`, giving `"24 okt 14:05"`. Tested in `time.test.ts` on one CET and one CEST instant | No existing helper yields it (`time.ts:12-46`). `nl-NL` short-month output differs between ICU builds (`okt` vs `okt.`), so the parts are joined, not the formatted string |
| PD15 | The new icon (SD11) | Grid `floppy`, 16×16, in `pixelIcons.json`. The B-02 lists that enumerate the grids gain it: `PixelIcon.test.tsx:11-29,56-57` (21 → 22) and `SPOTS` in `scripts/pixel_icons.py:53-74` (spot "Instellingen › Profielen", replaces "(nieuw)", colour `--text`), covered by `tests/unit/test_pixel_icons.py:192-193`. Approval is recorded in § Icon approval below, as B-02 did | B-02 SD9 and AC15's mechanism, reused |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `db/migrations/versions/0012_settings_profile.py` | Create | The table (PD4); `min_code_revision = "unchanged"` | T1 |
| `app/db/models.py` | Modify | `SettingsProfile`, column for column with the migration | T1 |
| `app/db/profiles.py` | Create | Repository and its two errors (PD4, PD5, PD6) | T1 |
| `tests/integration/test_schema.py` | Modify | `B_04_TABLES = {"settings_profile"}` in the inspected set (`:19-35,109-120`) | T1 |
| `tests/integration/test_profiles_repo.py` | Create | Repository: insert, exists, overwrite, race, list order, delete | T1 |
| `app/runtime/config_patch.py` | Create | Moved patch models and the profile pair (PD1, PD2, PD3) | T2 |
| `app/runtime/config.py` | Modify | Remove the moved block, re-export it (T2); `load_profile_onto_draft` (T4) | T2, T4 |
| `tests/unit/test_profile_settings.py` | Create | The 22, the snapshot, the patch, the faults, missing and extra keys | T2 |
| `app/runtime/profiles.py` | Create | `save_profile_from_run` (one transaction) | T3 |
| `app/api/profiles.py` | Create | `GET`/`POST /api/profiles`, `DELETE /api/profiles/{profile_id}` | T3 |
| `app/main.py` | Modify | Register the profiles router (`:77-90`) | T3 |
| `tests/api/test_profiles.py` | Create | Save, list, delete, roles, overwrite, source rename | T3 (T4, T5 extend) |
| `tests/api/test_authorization_matrix.py` | Modify | Rows for the four routes; `{profile_id}` in `_status` (`:111-134`) | T3, T4 |
| `tests/api/test_draining.py` | Modify | `DRAINING_WRITES` rows (`:23-51`) | T3, T4, T5 |
| `web/src/api/generated/schema.d.ts` | Modify (regenerated) | `./scripts/gen_api_types.sh`; never hand-edited | T3, T4, T5 |
| `app/api/config.py` | Modify | `POST /api/runs/{run_id}/profile` | T4 |
| `app/db/runs.py` | Modify | `create_run(profile_id)`, `create_draft_run(candle_interval_ms)`, revision 1 key (PD8, PD9) | T5 |
| `app/api/runs.py` | Modify | `CreateRunRequest.profile_id` | T5 |
| `tests/api/test_runs.py` | Modify | Create with a profile, with a copy too, unknown, out of range | T5 |
| `tests/integration/test_runs.py` | Modify | Repository-level create; revision 1's new key (`:282-312`) | T5 |
| `web/src/components/ui/pixelIcons.json` | Modify | `floppy` (T6); owner-named redraws only (T7) | T6, T7 |
| `web/src/components/ui/PixelIcon.test.tsx` | Modify | 21 → 22 grids | T6 |
| `scripts/pixel_icons.py` | Modify | `SPOTS` entry | T6 |
| `tests/unit/test_pixel_icons.py` | Modify | Any count it states | T6 |
| `docs/plans/phase-b-04-setting-profiles.md` | Modify | § Icon approval | T7 |
| `web/src/features/settings/useProfiles.ts` | Create | List hook with version bump (PD13) | T8a |
| `web/src/features/settings/useProfiles.test.ts` | Create | Fetch, failure → `[]` + `failed`, refetch on bump | T8a |
| `web/src/lib/time.ts`, `web/src/lib/time.test.ts` | Modify | `formatDayMonthTime` (PD14) | T8a |
| `web/src/features/settings/ProfilesSection.tsx` | Create | The section (T8b), the load (T9) | T8b, T9 |
| `web/src/features/settings/ProfilesSection.test.tsx` | Create | AC3, AC17, AC19–AC21, AC23 (T8b); AC12, AC13, AC14, AC16 (T9) | T8b, T9 |
| `web/src/features/settings/index.ts` | Modify | Export `ProfilesSection` | T8b |
| `web/src/features/manipulation/index.ts` | Modify | Export `manipulationExplanations` (PD11) | T8b |
| `web/src/app/pages/SettingsPage.tsx` | Modify | The section after `globaal`, icon `floppy`, `settingNames` (T8b); `names` to `BorrelSection` (T10) | T8b, T10 |
| `web/src/app/pages/SettingsPage.test.tsx` | Modify | Ten sections, order, icon, `['Profielen', 0]`, `/api/profiles` served, all 22 named | T8b |
| `web/src/features/manipulation/IdleSection.test.tsx` | Modify | PD10 reading A: a live run's profile-built idle numbers shown | T9 |
| `web/src/features/settings/BorrelSection.tsx`, `BorrelSection.test.tsx` | Modify | The "Profiel" select, body, failure texts | T10 |
| `tests/integration/test_profiles_restart.py` | Create | AC26: rehydrate as boot, after a create and after a load | T11 |
| `web/e2e/profiles.spec.ts` | Create | The spec's Playwright flow, own `--empty` server | T12 |
| `docs/design/data-model.md` | Modify | The `settings_profile` row (**owner stop**) | T13 |
| `docs/specs/phase-6-admin.md`, `docs/specs/phase-7-analytics.md` | Modify | Notes on SD2 (`:102-106`) and SD4 (`:101-104`) | T13 |
| `docs/backlog.md` | Modify | B-04 → built | T13 |

Untouched, and checked at T13: `exchange/`, `tests/engine/`, `app/realtime/`,
`web/src/features/exchange/`, `IdleSection.tsx`, `useEditableRecord.ts`, `ConfirmDialog.tsx`,
every `explanations.json`, every existing migration.

---

## Tasks

### T1 — The `settings_profile` table and its repository

- **Implements:** AC2 (the store half), AC18 (no FK), AC26 (the rows survive); SD5, SD7, SD8, SD14 (name length), SD15 (race)
- **Expected output:**
  - Migration `0012` per PD4, following `0011_schema_compat.py`'s layout. Identity and timestamp columns follow `0010_phase_7_lifecycle.py:45-51`. `downgrade()` drops the table. `min_code_revision = "unchanged"` (`tests/meta/test_schema_compat_coverage.py`).
  - `SettingsProfile` in `models.py`, matching the migration. Index and constraint names are checked by `test_the_models_match_the_migrated_schema`.
  - `app/db/profiles.py`:
    - `ProfileRow` frozen dataclass (`profile_id, name, settings, source_run_name, saved_at, saved_by`);
    - `ProfileNotFound`, `ProfileExists` as `AppError`s;
    - `list_profiles`, `get_profile`, `save_profile(conn, *, name, settings, source_run_name, saved_by, overwrite) -> tuple[ProfileRow, bool]` (the bool: created), `delete_profile` per PD5, PD6. Names are stored `strip()`ped.
  - `test_schema.py` lists the table.
  - `test_profiles_repo.py`:
    - insert;
    - same name case- and space-different → `ProfileExists` with the id, nothing changed;
    - overwrite replaces settings, source, saved_by, a later `saved_at`, and keeps `name`;
    - overwrite of a missing name inserts;
    - two concurrent non-overwrite saves of one new name → one row, one `ProfileExists` (after `test_config_draft.py`'s concurrency pattern);
    - list order `["alpha", "Beta", "gamma"]`;
    - delete, and delete/get of an unknown id → `ProfileNotFound`.
- **Verification:** `uv run pytest tests/integration/test_profiles_repo.py tests/integration/test_schema.py tests/integration/test_migrations.py tests/meta/test_schema_compat_coverage.py` (needs the compose `db`); `uv run mypy app`.
- **Depends on:** —
- **Autonomy note:** Function and dataclass names, the test layout and how the race is staged are the builder's. The columns, their names and NOT NULL-ness are PD4's. Adding a column, a FK to `run` or a CHECK on `settings` is not the builder's: stop and ask. The guard hook blocks edits to `0011`, so never work around it.

### T2 — The 22 under today's rules (pure)

- **Implements:** AC4, AC6, AC14, AC15 (the rules all three doors use); SD1, SD9
- **Expected output:**
  - `app/runtime/config_patch.py` holds `config.py:79-157` moved verbatim (`InvalidConfig`, `_whole_cents`, `_not_null`, the aliases, `ParamsPatch`, `ConfigPatch`), plus PD1's `PROFILE_FIELDS`, `profile_settings` and `profile_patch` with PD2's faults.
  - `config.py` imports and explicitly re-exports them. No other importer changes. `tests/unit/test_setting_explanations_values.py` still imports `ParamsPatch` from `config.py` and passes.
  - `tests/unit/test_profile_settings.py`:
    - `PROFILE_FIELDS` equals SD1's 22, literally (AC6: no `idle_targets`, `idle_rise_targets`, `bm_sigma`, `tick_interval_ms`, `quote_grace_versions`, `name`);
    - `profile_settings(DEFAULT_PARAMS, 60_000)` has exactly those keys, with `candle_interval_s == 60`, and passes `profile_patch`;
    - `Params()` does too;
    - `y_clip: 25` → `InvalidConfig` whose faults `loc[-1] == "y_clip"` and `loc[0] == source`;
    - `candle_interval_s: 7` → `loc == [source, "candle_interval_s"]`;
    - two bad fields → two faults;
    - a dict lacking `eta` → a patch with `eta` unset and the other 21 set (AC15);
    - an extra key `"bm_sigma": 1` or `"foo"` → ignored, no 422 (AC15);
    - an empty dict → an empty patch.
- **Verification:** `uv run pytest tests/unit/test_profile_settings.py tests/unit/test_setting_explanations_values.py tests/api/test_config.py`; `uv run mypy app`; `uv run ruff check app`.
- **Depends on:** —
- **Autonomy note:** The move is cut-and-paste: no validator, range, message or field order may change. `tests/api/test_config.py` passing unchanged is the proof. Helper names inside the module are the builder's. If something other than `config.py` turns out to define or need the moved names in a way a re-export cannot serve, stop and ask.

### T3 — Save, list and delete over HTTP

- **Implements:** AC1, AC2, AC4, AC5, AC6, AC17, AC18, AC24, AC25 (the profile routes); SD2, SD5, SD6, SD7, SD12 (order), SD14, SD15
- **Expected output:**
  - `app/runtime/profiles.py`: `save_profile_from_run(engine, *, name, run_id, overwrite, author) -> tuple[ProfileRow, bool]`, as one `engine.begin()`:
    1. `get_run` (404);
    2. `readable` (409 `run_ended`);
    3. PD3's snapshot and check (422 naming the field, `loc[0] == "run"`);
    4. `save_profile` with `source_run_name = run.name`, `saved_by = author`.
  - `app/api/profiles.py`, router `prefix="/profiles"`, each route with `require_role("admin")`, and on the writes `refuse_while_draining` declared after it (`app/api/deps.py`, PD19):
    - `GET ""` → `list[ProfileData{profile_id, name, saved_at, source_run_name}]`;
    - `POST ""` with `SaveProfileRequest{name: RunName, run_id: int, overwrite: StrictBool = False}` (`extra="forbid"`) → `ProfileData`, 201 or 200;
    - `DELETE "/{profile_id}"` → 204.
  - Registered in `app/main.py`. Schema regenerated.
  - `tests/api/test_profiles.py`:
    - save from a draft and from a live run (`live_run` fixture): stored `settings` keys are exactly the 22, equal to the run's document values, with `source_run_name`, `saved_by` the key label and the list row (AC1, AC6);
    - `profile_exists` with `profile_id`, nothing stored; `overwrite: true` → 200, stored name kept, values replaced (AC2);
    - a run with `y_clip` set to 25 by SQL → 422 naming `y_clip`, nothing stored (AC4);
    - an ended run → 409 `run_ended`, an unknown run → 404, names `""`, `"   "` and 101 characters → 422 (AC5);
    - delete → 204 then gone, unknown → 404 (AC17);
    - delete and overwrite leave every run's `params`, `candle_interval_ms` and revision count unchanged; deleting the source run (Phase 7 delete route) leaves `source_run_name` (AC18);
    - display, bar and no session on all three → 403/403/401 (AC24).
  - `test_authorization_matrix.py`: three rows, `ADMIN`, plus a `{profile_id}` replace.
  - `test_draining.py`: `POST /api/profiles` and `DELETE /api/profiles/999999` with valid bodies (AC25).
- **Verification:** `uv run pytest tests/api/test_profiles.py tests/api/test_authorization_matrix.py tests/api/test_draining.py tests/meta/test_route_authorization.py`; `./scripts/gen_api_types.sh && git diff --stat -- web/src/api/generated` shows only `schema.d.ts`; `uv run mypy app`.
- **Depends on:** T1, T2
- **Autonomy note:** Response model names, how 201/200 is returned and the test layout are the builder's. The status codes and error codes are the spec's (§ The interface). Returning a profile's `settings` from any route is not the builder's call (SD12). Stop and ask if the save cannot be one transaction.

### T4 — Load a profile onto a draft

- **Implements:** AC11, AC13 (the API half), AC14, AC15 (load), AC24, AC25 (the load route); SD3, SD9, SD15
- **Expected output:**
  - `load_profile_onto_draft` in `config.py` per PD7. Its `RunNotDraft` message says the run is not a draft. `write_draft_config` is unchanged.
  - `POST /api/runs/{run_id}/profile` in `app/api/config.py` with `LoadProfileRequest{profile_id: int}` (`extra="forbid"`), admin plus draining, returning `RevisionData`. Schema regenerated.
  - In `tests/api/test_profiles.py`:
    - load onto `test_config.py`'s draft shape: the 22 replaced, `idle_targets`, `idle_rise_targets`, `bm_sigma`, the drinks and the name unchanged, revision + 1 with `author` the key label (AC11);
    - the same load again → the same revision, no new row (AC11);
    - a live (`live_run`) and an ended target → 409 `run_not_draft`, nothing written (AC13);
    - an unknown profile → 404, an unknown run → 404, a profile whose stored `y_clip` was set to 25 by SQL → 422 naming `y_clip`, the draft unchanged in each case (AC14);
    - a profile with `eta` removed from its JSON and `"foo": 1` added: `eta` stays the draft's, the other 21 applied (AC15);
    - a profile whose JSON is `{}`, onto a live run → still 409 (PD7).
  - Matrix row, draining row, and a role test (AC24, AC25).
- **Verification:** `uv run pytest tests/api/test_profiles.py tests/api/test_config.py tests/api/test_authorization_matrix.py tests/api/test_draining.py tests/integration/test_config_draft.py`; schema drift as T3; `uv run mypy app`.
- **Depends on:** T3 (the shared `test_profiles.py`, matrix, draining list and generated schema)
- **Autonomy note:** The function and request names are the builder's. The check order is PD7's. Making the load reachable on a live run, or changing `write_draft_config`'s behaviour, is not the builder's: stop and ask.

### T5 — "Nieuwe borrel" with a profile (server)

- **Implements:** AC7, AC8, AC9, AC10, AC15 (create), AC24, AC25 (a create carrying a profile); SD4, SD9
- **Expected output:**
  - `create_run`, `create_draft_run` and revision 1 per PD8 and PD9. `CreateRunRequest.profile_id`. The route passes it. Schema regenerated.
  - `tests/integration/test_runs.py`:
    - with a profile and no copy: the 22 from the profile, Kaarsbreedte included (`candle_interval_ms == profile × 1000`), `bm_sigma` and the idle lists from the latest run, no drinks, revision 1's `params` and `candle_interval_s` equal to the profile's (AC7);
    - the same on an empty database → `DEFAULT_PARAMS` outside the 22;
    - with a profile and `copy_from_run_id`: the 22 from the profile, the copied drinks as `:404-496` assert, and `idle_targets`, `idle_rise_targets` and `bm_sigma` from the copied run (AC8);
    - `test_create_run_takes_params_defaults_and_writes_revision_one` (`:282-312`) gains `config["candle_interval_s"] == 60`;
    - one more test: with a copy and no profile → `candle_interval_ms == 60_000` and params equal to the source's (AC9).
  - `tests/api/test_runs.py`:
    - `profile_id` unknown → 404 `profile_not_found` and no run created;
    - a stored out-of-range value → 422 naming the field and no run (AC10);
    - a profile missing `eta` → `eta` from the latest run (AC15);
    - display, bar and no session with a `profile_id` → 403/403/401 (AC24).
  - `test_draining.py`: `POST /api/runs {"name": "Nieuw", "profile_id": 999999}` (AC25).
- **Verification:** `uv run pytest tests/integration/test_runs.py tests/api/test_runs.py tests/api/test_draining.py tests/integration/test_import_v1.py tests/integration/test_config_draft.py`; schema drift as T3; `uv run mypy app`.
- **Depends on:** T4 (the shared draining list and generated schema)
- **Autonomy note:** Where inside the transaction the profile is read is the builder's, as long as it is after today's refusals (so `draft_exists` and `live_run_exists` keep precedence) and before any insert. Changing what a create without a profile inherits is out of scope (SD4). If an existing `test_runs.py` assertion has to change beyond PD9's one key, stop and ask.

### T6 — The `floppy` grid

- **Implements:** AC19 (the icon's grid); SD11
- **Expected output:**
  - A 16×16 `floppy` in `pixelIcons.json`, a floppy disk as the starting motif, drawn in the style of the existing 16×16 grids (2-pixel strokes as `gear`).
  - `PixelIcon.test.tsx` lists it (22 grids). `SPOTS` has its entry per PD15.
  - `uv run python -m scripts.pixel_icons sheet` shows it.
  - Not placed on any page yet.
- **Verification:** `pnpm -C web exec vitest run src/components/ui/PixelIcon.test.tsx src/noEmoji.test.ts`; `uv run pytest tests/unit/test_pixel_icons.py`; the sheet command writes `.dev/pixel-icons.html`.
- **Depends on:** —
- **Autonomy note:** The drawing is the builder's first proposal. The owner decides in T7. Reusing an existing grid is not allowed (SD11).

### T7 — Icon approval — **hard stop, owner**

- **Implements:** AC19 (the approved icon); SD11 (B-02 SD9)
- **Expected output:**
  - The build **stops** after T6 and gives the owner the absolute path of `.dev/pixel-icons.html`.
  - The owner either says "go" or asks for a redraw (or a different motif). On a redraw the builder edits only `floppy`, re-runs T6's checks and the sheet, and stops again.
  - On "go", § Icon approval below gets the date, each round's answer and the redraws, committed as `docs(phase-b-04): T7 — icon approved`.
- **Verification:** § Icon approval holds a dated "go" from the owner; T6's checks green on the approved grid.
- **Depends on:** T6
- **Autonomy note:** **Stop. This is the owner's, not a step to note and carry on past.** T8b depends on it. The builder may not approve, may not read silence as approval, and may not change anything the owner did not ask for. If the owner changes the motif, the grid may keep the name `floppy` or take a new one (then T6's lists follow): the builder may choose.

### T8a — The profiles list hook and the time format

Split out of T8 at the audit (2026-10-24) so each half is reviewable in one sitting.

- **Implements:** AC20 (Amsterdam time), AC22 (a failed fetch gives `[]`); SD12, PD13, PD14
- **Expected output:**
  - `useProfiles.ts` per PD13, with zod `Profile{profile_id, name, saved_at, source_run_name}`, and the exported bump.
  - `useProfiles.test.ts`: the parsed list in server order; a failed fetch → `[]` and `failed`; a bump makes a second mounted `useProfiles` refetch.
  - `formatDayMonthTime` per PD14; `time.test.ts` on a CET and a CEST instant.
  - Not used by any component yet.
- **Verification:** `pnpm -C web exec vitest run src/features/settings/useProfiles.test.ts src/lib/time.test.ts`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`.
- **Depends on:** T3 (the route the hook calls)
- **Autonomy note:** Hook internals and test names are the builder's. If `formatDayMonthTime` cannot produce `"24 okt 14:05"` from `formatToParts`, stop and ask; do not hard-code month names.

### T8b — The Profielen section: list, save and delete

- **Implements:** AC1, AC2, AC3, AC17, AC19, AC20, AC21 (save and list half), AC23 (save); SD2, SD5, SD6, SD10, SD12, SD14
- **Expected output:**
  - `ProfilesSection.tsx`, using `useCurrentRun`, `request`, `faultsOf`, `ConfirmDialog`, `Select`, `Button` and `settings.module.css`:
    - the list: one row per profile, "<naam> · opgeslagen <d mmm HH:mm> · uit '<borrelnaam>'", in server order, each with a "Verwijderen" button; "Nog geen profielen" when empty; PD12's failure text;
    - "Verwijderen" opens `ConfirmDialog` "Profiel '<naam>' verwijderen?", then `DELETE` → bump;
    - "Opslaan als profiel" (a `Naam` input with `maxLength={100}` and the button) only while the current run is a draft or live. `409 profile_exists` opens "Profiel '<naam>' overschrijven?" with the listed spelling, else the typed one. Confirm resends with `overwrite: true`, cancel sends nothing. Success → bump and clear the input. A 422 shows PD12's text with `names[field]`.
  - `SettingsPage.tsx`: `{ id: 'profielen', label: 'Profielen', icon: 'floppy', content: <ProfilesSection names={settingNames} /> }` directly after `globaal`. `settingNames` per PD11. `features/settings/index.ts` and `features/manipulation/index.ts` exports.
  - `ProfilesSection.test.tsx`, with fetch stubbed as `BorrelSection.test.tsx:40-71`:
    - rows text and order as served, and in Amsterdam time;
    - the empty text;
    - no value of a profile shown (AC20);
    - save visible on a draft and on a live run, absent with no run, while the list shows with no run (AC21);
    - the overwrite confirm, its confirm body `{"name":…,"run_id":…,"overwrite":true}` and its cancel sending nothing (AC3);
    - the delete confirm and cancel (AC17);
    - a 422 on `y_clip` shows "Grens ruis", not `y_clip` (AC23);
    - a save or delete makes a second `useProfiles` refetch (PD13).
  - `SettingsPage.test.tsx`:
    - `SECTIONS` gains Profielen after Globale instellingen (nav, anchor `#profielen`, narrow `Sectie` select; the "nine" texts become "ten");
    - its heading has one `aria-hidden` icon;
    - `['Profielen', 0]` in the `(i)` table;
    - `/api/profiles` is served `[]` in `openWithLiveRun`;
    - every one of SD1's 22 wire names has a non-empty entry in `settingNames` (AC23).
- **Verification:** `pnpm -C web exec vitest run src/features/settings src/app/pages/SettingsPage.test.tsx src/lint-rules.test.ts`; `pnpm -C web exec tsc -b`; `pnpm -C web exec eslint src`.
- **Depends on:** T8a (`useProfiles`, `formatDayMonthTime`), T7 (the approved icon)
- **Autonomy note:**
  - Markup, CSS class reuse, test names and how the overwrite resend is staged are the builder's.
  - The texts are the spec's and PD12's. A different wording is a stop.
  - A new shared UI component, a new CSS file, a change to `useEditableRecord` or `ConfirmDialog`, or an `(i)` button on the section is not the builder's.
  - If `settingNames` lacks one of the 22, stop. That is an explanations gap, not something to patch with a wire name.

### T9 — Load onto a draft, in the page

- **Implements:** AC11, AC12, AC13 (no load action on a live run), AC14, AC16, AC21 (load half); SD3, SD13, PD10 (reading A)
- **Expected output:**
  - `ProfilesSection` gains "Profiel laden" (a `Select` of the profiles by name and a "Laden" button), only while the current run is a draft. Confirm "Profiel '<profiel>' laden op '<borrel>'? Dit vervangt de instellingen van deze borrel." On confirm it sends `POST /api/runs/{id}/profile` and then `useCurrentRun().reload()`, so every settings section refetches. Cancel sends nothing. PD12's texts for 404, 409 and 422; on `run_not_draft` it also reloads the run.
  - `ProfilesSection.test.tsx`:
    - the load form appears on a draft and not on a live run or with no run (AC13, AC21);
    - confirm text, body, and cancel sending nothing (AC12);
    - a 404 and a 422 shown by name, nothing else changed (AC14);
    - **AC16:** `ProfilesSection`, `GlobalSection` and `DemandSection` rendered together on a draft. After a load the served config changes and both sections show the loaded Sterkte ruis, Kaarsbreedte and "Verwachte verkoop meetellen" without a remount. With Sterkte ruis edited first, Globale instellingen keeps the edit and offers "Overnemen" (the pattern of `GlobalSection.test.tsx:224-245` and `useCurrentRun.test.tsx:31-51`).
  - `IdleSection.test.tsx`: a live run whose idle numbers are a profile's shows them (PD10 reading A).
- **Verification:** `pnpm -C web exec vitest run src/features/settings src/features/manipulation`; `pnpm -C web exec tsc -b`.
- **Depends on:** T8b, T4
- **Autonomy note:** Test staging is the builder's. If the owner rules PD10 reading B, this task grows an `IdleSection` change and the plan is amended and re-audited first. The builder does not do it unplanned.

### T10 — The "Profiel" select on "Nieuwe borrel"

- **Implements:** AC7, AC8, AC9 (the form half), AC10, AC22, AC23 (create); SD3, SD4, SD13 (no extra confirm)
- **Expected output:**
  - `BorrelSection.tsx`:
    - takes `names` and uses `useProfiles`;
    - shows `<Select label="Profiel">` with "—" plus every profile by name beside "Kopieer drankjes uit";
    - on failure to list, only "—" (AC22);
    - sends `profile_id: Number(...)` only when one is picked, with or without `copy_from_run_id`, and no new confirm.
  - `failureText` gains `profile_not_found` (PD12, plus a profiles bump) and, before the name fallback, a 422 whose fault is not `name` → PD12's "Profiel niet toegepast: …" by `names` (AC10, AC23). A 422 on `name` keeps today's text.
  - `SettingsPage.tsx` passes `names={settingNames}`.
  - `BorrelSection.test.tsx`:
    - the options;
    - the POST bodies: profile only, profile + copy, neither (unchanged from `:259`);
    - the fetch-failure fallback still creating (AC22);
    - a 404 and a 422 by setting name;
    - a profile deleted elsewhere (a `useProfiles` bump) disappearing from the select.
- **Verification:** `pnpm -C web exec vitest run src/features/settings src/app/pages/SettingsPage.test.tsx`; `pnpm -C web exec tsc -b`.
- **Depends on:** T8a (`useProfiles`), T8b (`settingNames`), T5 (the server accepts `profile_id`)
- **Autonomy note:** Layout beside the copy select is the builder's. A confirm on create is not (SD13).

### T11 — A profile survives a restart and goes live with its values

- **Implements:** AC26; spec Verification › Integration
- **Expected output:** `tests/integration/test_profiles_restart.py`, assembling the runtime as `tests/integration/test_config_live.py:51-129` (`rehydrate`, `MarketHolder.from_rehydrated`):
  - **Create:** save a profile from a draft whose 22 differ from `DEFAULT_PARAMS` (e.g. Kaarsbreedte 30, `bm_sigma_y` 0.5). Close and delete that run. Create a new borrel with the profile, add drinks, `go_live`, `rehydrate`. `spec.params` holds the 21, the rehydrated `candle_interval_ms == 30_000`, and one tick advances.
  - **Load:** a draft from defaults, a load, `go_live`, `rehydrate`, the same assertions.
  - **Survives:** a fresh `create_app` against the same database lists the profile with its stored values unchanged.
- **Verification:** `uv run pytest tests/integration/test_profiles_restart.py` (needs the compose `db`).
- **Depends on:** T4, T5
- **Autonomy note:** This task changes **no source file**. If an assertion fails, the code does not do what SD4 or SD15 say. Stop and report: do not patch around it in `rehydrate` or `go_live`.

### T12 — The Playwright profiles flow

- **Implements:** the spec's Playwright step, covering AC1, AC7, AC11, AC12, AC16, AC19, AC20 end to end
- **Expected output:** `web/e2e/profiles.spec.ts`, with its own `startServer('admin', ['--empty'])` and serial mode, as `admin.spec.ts:36-69`, plus local `login` and `section` helpers:
  1. create "Proef" in Borrel;
  2. Globale instellingen: Sterkte ruis `0,5`, Kaarsbreedte (sec) `30`, "Opslaan instellingen";
  3. Profielen: name "Wilde beurs", "Opslaan als profiel"; the row matches `/^Wilde beurs · opgeslagen \d{1,2} [a-z]{3} \d{2}:\d{2} · uit 'Proef'$/`;
  4. set both back to their defaults and save;
  5. "Profiel laden" "Wilde beurs", confirm, and both fields show `0,5` and `30` without a reload;
  6. delete the draft on `/analytics` (typed name, as `analytics.spec.ts:228-231`);
  7. `/settings`: "Nieuwe borrel" "Proef 2" with Profiel "Wilde beurs"; Globale instellingen shows `0,5` and `30`.
- **Verification:** `pnpm -C web exec playwright test e2e/profiles.spec.ts`; then `pnpm -C web exec playwright test` (the whole e2e suite, as the gate runs it).
- **Depends on:** T9, T10
- **Autonomy note:**
  - Selectors and the helpers are the builder's.
  - `getByText('Opgeslagen')` is a case-insensitive substring and would also match a row's "opgeslagen". Use `{ exact: true }` or the toast's role.
  - If the month regex fails on Chromium's ICU (PD14), fix `formatDayMonthTime`, not the regex.

### T13 — Documents, the older specs, the backlog, and the exit gate

- **Implements:** AC27; spec In scope › Documents
- **Expected output:**
  - `docs/design/data-model.md`: one row for `settings_profile` in the table at `:20-37`, naming its columns, B-04 SD7 (no link to a run) and SD8 (per database), and that it is overwritten and deleted in place (not evidence, `:17-18`). **The builder writes the row, shows it to the owner and waits for approval before committing it** (CLAUDE.md: anything in `docs/design/` is the owner's).
  - Notes in the existing style, an indented `> **Amended by B-04** ([phase-b-04-setting-profiles.md](phase-b-04-setting-profiles.md)).` followed by one sentence (a profile, when picked, wins for its 22 fields, SD4):
    - Phase 6 SD2's params line (`phase-6-admin.md:106`);
    - Phase 7 SD4's `copy_from_run_id` line (`phase-7-analytics.md:104`).
  - `docs/backlog.md`: B-04 → `built → docs/plans/phase-b-04-setting-profiles.md (spec: docs/specs/phase-b-04-setting-profiles.md)`, as B-03's.
- **Verification:**
  - `git diff --stat <T1's base>..HEAD -- exchange tests/engine app/realtime web/src/features/exchange` is empty (AC27);
  - `bash scripts/golden_linux.sh` green (AC27);
  - `engine-guardian` on the whole B-04 diff reports no maths change (AC27);
  - `./scripts/check.sh` green, output pasted.
- **Depends on:** T11, T12
- **Autonomy note:**
  - Note wording is the builder's. A note must not restate the spec.
  - A golden diff or a guardian finding is a hard stop.
  - The `data-model.md` row needs the owner's go.
  - The manual exit check (spec Verification › Manual: a live dry run tuned wild, saved, closed, a new borrel from it plus "kopieer drankjes uit", the board moving as before) is the owner's. The item is not done without it.

---

## Task graph

```
T1, T2 ──► T3 ──► T4 ──► T5
T6 ──► T7 (owner)

T3 ──► T8a
T8a + T7 ──► T8b
T8b + T4 ──► T9
T8b + T5 ──► T10
T4 + T5 ──► T11
T9 + T10 ──► T12
T11 + T12 ──► T13
```

| Group | Tasks | Files they write |
|---|---|---|
| 1 | T1, T2, T6 | T1: migration `0012`, `models.py`, `app/db/profiles.py`, `test_schema.py`, `test_profiles_repo.py` · T2: `config_patch.py`, `config.py`, `test_profile_settings.py` · T6: `pixelIcons.json`, `PixelIcon.test.tsx`, `scripts/pixel_icons.py`, `test_pixel_icons.py` |
| 2 | T3, T7 (owner) | T3: `app/runtime/profiles.py`, `app/api/profiles.py`, `app/main.py`, `test_profiles.py`, matrix, draining, `schema.d.ts` · T7: `pixelIcons.json` (redraws), this plan |
| 3 | T4, T8a | T4: `config.py`, `app/api/config.py`, `test_profiles.py`, matrix, draining, `schema.d.ts` · T8a: `useProfiles.{ts,test.ts}`, `lib/time.{ts,test.ts}` |
| 4 | T5, T8b | T5: `app/db/runs.py`, `app/api/runs.py`, `tests/api/test_runs.py`, `tests/integration/test_runs.py`, draining, `schema.d.ts` · T8b: `ProfilesSection.{tsx,test.tsx}`, `settings/index.ts`, `manipulation/index.ts`, `SettingsPage.{tsx,test.tsx}` |
| 5 | T9, T10, T11 | T9: `ProfilesSection.{tsx,test.tsx}`, `IdleSection.test.tsx` · T10: `BorrelSection.{tsx,test.tsx}`, `SettingsPage.tsx` · T11: `test_profiles_restart.py` |
| 6 | T12 | `web/e2e/profiles.spec.ts` |
| 7 | T13 | `data-model.md`, `phase-6-admin.md`, `phase-7-analytics.md`, `backlog.md` |

No file is written by two tasks in one group. T3 → T4 → T5 is a chain only because they share `test_draining.py` and the generated schema. T2 and T4 both write `config.py`, in groups 1 and 3.

### Coverage

| AC | Task(s) | AC | Task(s) |
|---|---|---|---|
| AC1 | T3, T8b, T12 | AC15 | T2, T4, T5 |
| AC2 | T1, T3, T8b | AC16 | T9, T12 (idle half per PD10, reading A) |
| AC3 | T8b | AC17 | T3, T8b |
| AC4 | T2, T3 | AC18 | T1, T3 |
| AC5 | T3 | AC19 | T6, T7, T8b |
| AC6 | T2, T3 | AC20 | T8a, T8b, T12 |
| AC7 | T5, T10, T12 | AC21 | T8b, T9 |
| AC8 | T5, T10 | AC22 | T8a, T10 |
| AC9 | T5, T10 | AC23 | T8b, T10 |
| AC10 | T5, T10 | AC24 | T3, T4, T5 |
| AC11 | T4, T9, T12 | AC25 | T3, T4, T5 |
| AC12 | T9 | AC26 | T1, T11 |
| AC13 | T4, T9 | AC27 | T13 |
| AC14 | T2, T4, T9 | | |

Every task maps to at least one AC. T6 and T7 serve AC19, and T13 serves AC27 and the spec's Documents scope.

---

## Icon approval (SD11, B-02 SD9)

T7 fills this in. No page shows the icon (T8b) before it holds "go".

| Round | Date | Owner's answer | Grids redrawn |
|---|---|---|---|
| 1 | 2026-10-24 | "go" (from the grid and `.dev/pixel-icons.html`, T6 `a4231fb`) | none |

---

## Data changes

- **Migration `0012_settings_profile`:** `create_table` per PD4 plus one unique index. No backfill: the table starts empty.
- **Expand-only (Phase 7 SD13):** the previous image ignores the table. `min_code_revision = "unchanged"` (Phase 8 SD3), so `schema_compat`'s row is not touched. The downgrade drops the table, and the round trip is tested by `test_migrations.py`.
- **No column of an existing table changes.**
- **Revision 1 gains a key** (PD9). Older revisions keep their shape, and nothing reads a revision back.
- **The OpenAPI schema grows:** four routes, three request models, one response model, and an optional field on `CreateRunRequest`.
- **Reverting the item** leaves the table in place (harmless, as above), and every run as it is.

## New dependencies

None.

---

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| PD10: the owner rules reading B | T9's autonomy note: amend and re-audit, never build it unplanned |
| T2's move silently changes a rule | Cut-and-paste only. `tests/api/test_config.py` and the explanation value guard run unchanged in T2's verification |
| A future `ParamsPatch` field is silently swept into profiles | PD1: `PROFILE_FIELDS` is derived but pinned to SD1's 22 by a literal test |
| An in-code `ValidationError` escapes as a 500 | PD2 catches it in the one function every door uses. T3, T4 and T5 each test a 422 on a stored or run value |
| `RETURNING (xmax = 0)` is a Postgres idiom some readers will not know | One comment at the call. T1's tests pin both outcomes. A pre-select under `FOR UPDATE` is the fallback if the auditor objects |
| `candle_interval_ms` not a multiple of 1000 (raw SQL only; the app writes multiples of 5000) floors on save | PD3 matches what the page shows. The CandleSeconds check still refuses a non-multiple of 5 |
| `nl-NL` short month as `okt.` in Chromium's ICU | PD14 joins parts and strips the dot. T12 checks it in the real browser |
| The e2e "Opgeslagen" substring clashes with a row's "opgeslagen" | T12's autonomy note. `admin.spec.ts` never creates a profile, so it is unaffected |
| `data-model.md` is in the spec's scope but `docs/design/` is an owner stop | T13 writes it and waits for the owner's go |
| The spec credits trimmed, case-folded names to "Phase 6 SD14". That is Phase 2 SD14 (`phase-2-persistence.md:83`) | A citation slip with no effect on behaviour. Noted here. The spec is not this plan's to edit |
| `data-model.md` already lacks `schema_compat` (Phase 8) | Out of scope. T13 adds only B-04's row |

**Uncertain, for the audit and the owner:**
- **PD10 (owner):** AC16's idle clause cannot be seen right after a load, because the idle section
  shows only a live run. Recommended: reading A, met at go-live, no `IdleSection` change.
- **PD9:** revision 1 gains `candle_interval_s` on every create, not only with a profile.
- **PD1:** moving the patch models into `config_patch.py` is a refactor the spec does not name.
  It is the smallest way I found to let `create_run` validate inside its own transaction without
  an import cycle.
- **PD12:** the error and button texts are mine; the spec fixes only the three confirm messages.
- Unverified: whether a dependency's 401/403 precedes a 422 for an unparseable
  `{profile_id}`. T3 adds the `{profile_id}` replace to the matrix so the question does not
  arise there.

---

## Out of scope for this plan

As the spec, plus:
- Fixing `write_draft_config`'s empty-patch shortcut or its `run_ended` answer for PATCH (PD7
  avoids both for the load; PATCH behaviour is unchanged).
- `IdleSection`'s "Laden…" with no live run, and Demand/Idle sections not mapping 422 faults:
  existing behaviour, candidates for the defect register.
- The legacy shape of revision 1 beyond PD9's one key, and the false comment in
  `test_config_live.py` ("Revision 1, as `create_run` writes it").
- `schema_compat` missing from `data-model.md`.
- Any change to `ConfirmDialog`, `Select`, `useEditableRecord`, `PixelIcon`, or an explanations
  entry for Profielen.

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting (after splitting T8 into T8a and T8b)
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audit notes (2026-10-24):
- PD10 ruled reading A; PD1, PD9 and PD12 confirmed as written.
- Accepted spec departures: the load is a sibling of `write_draft_config`, not a call through it
  (PD7), and revision 1 gains `candle_interval_s` on every create (PD9).
- T8 split into T8a (hook and time format) and T8b (the section) for size.

Audited by: MartijnBoot (owner)  Date: 2026-10-24

---

## Build notes (after the audit)

Three files changed that the Files table does not name. None changes a task's scope or an AC:
- `app/db/products.py` (T5): `name_key` moved here from `app/db/runs.py`, because `runs.py`
  now imports `app/db/profiles.py`, which needs it (an import cycle). PD4's reuse holds: the
  function still exists once, with the same body.
- `tests/meta/test_guard_migrations_hook.py` (T1): its real-tree test names `0012` as the head,
  as any new migration requires.
- `web/src/app/pages/settingNames.ts` (T8b): PD11's `settingNames` lives in its own file
  rather than inline in `SettingsPage.tsx`, so the test can import it (react-refresh lint).

The `data-model.md` row was approved by the owner at `/review b-04` (2026-10-25).
