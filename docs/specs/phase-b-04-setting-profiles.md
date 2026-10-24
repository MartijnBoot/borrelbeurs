# Spec: B-04 — Named setting profiles per type of game

Status: Approved · Depends on: Phase 6 (SD2, SD5–SD8, SD24: drafts, config writes, draining),
Phase 7 (SD4: "kopieer drankjes uit", SD13: expand-only migrations), Phase 8 (SD3:
`schema_compat`), B-01 (setting names), B-02 (SD9: the owner approves every icon), B-03 (the six
noise settings) · Fixes: no open defect · Backlog: [B-04](../backlog.md)

Line references are to `main` at `b6fec1e` (B-03 merged, PR #21).

## Problem

The owner finds the right market feel for a kind of borrel by experimenting on dry runs. Once a
good set is found, there is no way to keep it under a name:

- **A new borrel inherits whatever run happened to be created last.** `create_run` takes the
  latest run's `params`, else `DEFAULT_PARAMS` (`app/db/runs.py:462`, `latest_params` at
  `:428`). After one "wilde beurs" dry run, the next "rustige borrel" starts wild unless every
  field is set back by hand.
- **The only way to reuse a set is to remember which run had it.** "Kopieer drankjes uit"
  (`copy_from_run_id`, Phase 7 SD4) copies a past run's params *and* its drinks
  (`app/db/runs.py:464-465`; the form at `web/src/features/settings/BorrelSection.tsx:117-122`).
  The settings cannot be taken without that run's drinks, and the run list names borrels, not
  types of game.
- **Kaarsbreedte is never carried over.** It is a run column, `candle_interval_ms`, defaulted to
  60 s (`app/db/models.py:69`); `create_draft_run` does not set it (`app/db/runs.py:191-199`),
  copy or not.
- The settings of a run live in three places: Globale instellingen (nine engine params,
  Kaarsbreedte, and B-03's six; `web/src/features/settings/GlobalSection.tsx`), the two
  Vraag/Aanbod switches (`DemandSection.tsx`), and the four idle numbers on the manipulation page
  (`web/src/features/manipulation/IdleSection.tsx`). All are written through one validated
  `PATCH /api/runs/{run_id}/config` (`ConfigPatch`, `ParamsPatch`:
  `app/runtime/config.py:116-158`).

No defect in the register is about this. It changes no pricing maths: a profile only supplies
values that `PATCH config` already accepts.

## Decisions

Settled at the spec interview (2026-10-24). SD1–SD12 were put to the owner one at a time, each
with a recommendation, and the owner chose it every time. SD13–SD15 were stated at the end of
the interview and accepted. The planner must not reopen any of them.

- **SD1 — What a profile holds: 22 settings, nothing per drink.** Under their `PATCH config`
  wire names:

  | Where on the page | Fields |
  |---|---|
  | Globale instellingen | `step_quant`, `eta`, `K`, `lambda_orders`, `alpha_price`, `phi_persist`, `decay_rho`, `history_window_minutes`, `refresh_minutes`, `candle_interval_s` (Kaarsbreedte), and B-03's `bm_enabled`, `bm_sigma_y`, `bm_dt_minutes`, `flow_vol_amp`, `flow_beta`, `y_clip` |
  | Vraag/Aanbod (the switches) | `demand_enabled`, `auto_calibrate_s0` |
  | Manipulatie, stille drankjes | `idle_decay_minutes`, `idle_strength`, `idle_rise_minutes`, `idle_rise_strength` |

  **Not** in a profile: `idle_targets` and `idle_rise_targets` (they name drinks), anything per
  drink (bounds, `p0`, `a/d/s0/c`, bar price), the run's name, and the settings no page edits
  (legacy `bm_sigma`, `tick_interval_ms`, `quote_grace_versions`, `run_seed`).
- **SD2 — A profile is made only as a snapshot of the current run.** On a draft or a live run,
  "Opslaan als profiel" with a name stores that run's 22 values as committed at that moment.
  There is no profile editor. To change a profile: load it onto a draft, tweak, save again under
  the same name (SD5). An ended run cannot be saved from (there is no current run then).
- **SD3 — A profile is applied when a borrel is created, or onto a draft. Never onto a live
  run.** The "Nieuwe borrel" form gets a profile select; a draft gets "Profiel laden". A live
  run has no load action, and the API refuses one.
- **SD4 — The profile wins for its fields; the rest comes from where it comes from today.** At
  "Nieuwe borrel":
  - the 22 fields come from the profile;
  - every other param (the idle target lists, legacy `bm_sigma`) and the drinks come from the
    "kopieer drankjes uit" run if one is picked, else from the latest run's params as today
    (else `DEFAULT_PARAMS`), with no drinks;
  - without a profile, nothing changes from today, including Kaarsbreedte at its 60 s default.

  Onto a draft, the 22 fields are replaced and every other param and every drink stay the
  draft's.
- **SD5 — Saving under an existing name overwrites, after a confirm.** Names are compared
  trimmed and case-folded (as drink names, Phase 6 SD14). The page asks "Profiel '<naam>'
  overschrijven?"; on confirm the profile's 22 values, its saved-at time and its source borrel
  are replaced. The stored spelling of the name stays the original's.
- **SD6 — Delete yes, rename no.** "Verwijderen" behind a plain confirm ("Profiel '<naam>'
  verwijderen?", no typed name). Renaming is: load onto a draft, save under the new name, delete
  the old one.
- **SD7 — No link between a run and a profile.** The values are copied when applied. Deleting or
  overwriting a profile changes no run, past, draft or live. A profile copies its source run's
  name at save time; deleting or renaming that run later does not touch the profile.
- **SD8 — A profile lives in the database it was saved in.** The venue laptop's Postgres
  (`docs/runbooks/venue.md:15-25`) shares nothing with Render's, so a profile saved on Render
  does not exist at the venue; there the settings are set by hand or saved again. No file
  download or upload, no CLI.
- **SD9 — Strict on save and on apply; a missing field keeps its base value.**
  - **Save** checks the run's 22 values against today's `ConfigPatch`/`ParamsPatch` rules. If
    one is outside them (a run can carry an old out-of-range value, B-03 "Out of scope"), the
    save is refused, the field named, nothing stored.
  - **Apply** (create or load) checks the profile's stored values against the same rules at the
    moment of applying. If any is outside them (a range tightened since it was saved), the whole
    apply is refused, the field named, nothing written: no new draft, no change to the draft.
  - A field one of the 22 that the stored profile **lacks** (a profile saved before a field was
    added) keeps the base value of SD4: the copied run's, the latest run's, or the draft's own.
  - A stored key that is not one of the fields a profile holds is ignored on apply.
- **SD10 — A section of its own: "Profielen"**, directly after Globale instellingen in the
  settings order (`web/src/app/pages/SettingsPage.tsx:24`), with its own anchor in the mobile
  nav. It holds the list, save, load and delete. The Borrel section gains only the profile select
  on the "Nieuwe borrel" form.
- **SD11 — The section gets a new pixel icon**, drawn by the build (a floppy disk is the
  starting motif; the owner may change it) and approved by the owner before it reaches the page
  (B-02 SD9). **That approval is a hard stop in the build.** No existing icon is reused.
- **SD12 — The list shows name, saved-at and source borrel, no values.** One row per profile:
  "<naam> · opgeslagen <d mmm HH:mm> · uit '<borrelnaam>'", the time in Amsterdam time as every
  time in the app (`6a1c9cc`). Sorted by name, case-folded. Values are seen by loading the
  profile onto a draft; the draft's revision history keeps what it had before.
- **SD13 — Loading onto a draft asks first:** "Profiel '<profiel>' laden op '<borrel>'? Dit
  vervangt de instellingen van deze borrel." Picking a profile on the "Nieuwe borrel" form asks
  nothing more than the form does today.
- **SD14 — Who and when.** Every profile route is admin only. Every profile write (save,
  overwrite, delete, load, and a create carrying a profile) is refused while draining (Phase 6
  SD24). Names are 1–100 characters after trimming, as run names.
- **SD15 — Concurrency and restarts.**
  - Saving a name that exists, without the request saying it may overwrite, is 409
    `profile_exists`; the page then shows SD5's confirm and resends with overwrite. Two admins
    saving the same new name at once: one creates it, the other gets `profile_exists`. An
    overwrite of a profile deleted in the meantime creates it.
  - Loading onto a run that is no longer a draft is 409 `run_not_draft`, nothing written.
  - Applying, or deleting, a profile that no longer exists is 404 `profile_not_found`, nothing
    written.
  - Each save, overwrite, delete and load is one transaction; a create with a profile reads the
    profile inside `create_run`'s transaction. A restart leaves the old state or the new one,
    never half.

## The interface

For the planner to refine, not to rename without a reason.

- **Table** `settings_profile`: `profile_id` (identity), `name`, `name_key` (unique; the trimmed,
  case-folded name, computed in Python as `drink.name_key` is), `settings` (JSONB: the 22 values
  under their wire names, `candle_interval_s` in seconds), `source_run_name`, `saved_at`,
  `saved_by` (the key label). A new migration, expand-only (Phase 7 SD13); `schema_compat` is
  unchanged (Phase 8 SD3).
- `GET /api/profiles` → `[{profile_id, name, saved_at, source_run_name}]`, in SD12's order.
- `POST /api/profiles {name, run_id, overwrite?: bool}` → the profile; 201 created, 200
  overwritten. 409 `profile_exists` (with its `profile_id`), 404 `run_not_found`, 409
  `run_ended`, 422 naming a run field outside the rules (SD9).
- `DELETE /api/profiles/{profile_id}` → 204; 404 `profile_not_found`.
- `POST /api/runs/{run_id}/profile {profile_id}` → the new revision; through
  `write_draft_config` (`app/runtime/config.py:429-442`) with a `ConfigPatch` built from the
  profile, so a profile equal to the draft appends no revision. 404 `run_not_found` /
  `profile_not_found`, 409 `run_not_draft`, 422 naming the profile field (SD9).
- `POST /api/runs` gains optional `profile_id` (`CreateRunRequest`, `app/api/runs.py:50-54`);
  404 `profile_not_found`, 422 as above. Revision 1 carries the profile's values.

## In scope

- **Persistence:** the `settings_profile` table and its migration.
- **Server:**
  - the profile routes above, admin only, refused while draining;
  - `create_run` taking a profile (SD4), setting `candle_interval_ms` from it;
  - the draft load through `write_draft_config`;
  - validation of a profile's values through the same `ConfigPatch`/`ParamsPatch` rules, at save
    and at apply (SD9);
  - the OpenAPI types regenerated (`web/src/api/generated/schema.d.ts`).
- **Web:**
  - the "Profielen" section after Globale instellingen (SD10), with its new pixel icon (SD11):
    the list (SD12) with "Verwijderen" per row; "Opslaan als profiel" (name field and button)
    while a draft or live run exists; "Profiel laden" (select and button) while a draft exists;
    "Nog geen profielen" when the list is empty;
  - the "Profiel" select on the "Nieuwe borrel" form, beside "Kopieer drankjes uit";
  - the three `ConfirmDialog`s (overwrite, delete, load);
  - after a load, every settings section (and the manipulation page's idle section) showing the
    loaded values;
  - their component tests and the Playwright admin flow.
- **Documents:**
  - `docs/design/data-model.md` (the new table);
  - a note on Phase 6 SD2 (`docs/specs/phase-6-admin.md:102`, a new draft's params) and on
    Phase 7 SD4 (`docs/specs/phase-7-analytics.md:101`, `copy_from_run_id`): a profile, when
    picked, wins for its 22 fields (SD4);
  - B-04's backlog status.

## Out of scope

- Any change to the pricing maths, to any default (`Params()`, `DEFAULT_PARAMS`), or to any
  range. `exchange/` is read, never changed.
- Applying a profile to a live run (SD3), including on a dry run. Comparing profiles there means
  closing the run and starting a new borrel from the other profile.
- A profile editor, or seeing a profile's values without loading it (SD2, SD12).
- Rename (SD6). Version history of a profile (SD5 overwrites).
- Idle target lists, drinks, bounds, coefficients, bar prices, the theme, images, keys or news in
  a profile (SD1). "Kopieer drankjes uit" stays the only way to reuse drinks.
- Remembering which profile a run came from, on any screen, analytics or export (SD7).
- Moving profiles between databases (SD8): no export/import file, no CLI, no seeding the venue
  bundle. A candidate backlog item once the offline path has been rehearsed (backlog "Deferred
  work").
- Profiles in the v1 import (`app.cli.import_v1`) or `app.cli.runs`.
- Changing what a new borrel inherits without a profile (SD4), including carrying Kaarsbreedte
  over on "kopieer drankjes uit".
- Fixing up a run's out-of-range values; SD9 only refuses to save them.
- Any change to the profile select or list for display or bar keys: they never see `/settings`.

## Acceptance criteria

**Save — SD2, SD5, SD9, SD14, SD15**

- **AC1.** When an admin saves the current draft or live run under a new name, the system shall
  store a profile with that run's 22 SD1 values as committed, the run's name as its source, the
  time and the key label, and the list shall show it.
- **AC2.** When a save's name matches an existing profile's trimmed, case-folded name and the
  request does not say it may overwrite, the system shall return 409 `profile_exists` and store
  nothing; when it says it may, the system shall replace that profile's values, saved-at and
  source, and keep its stored name.
- **AC3.** When the page gets `profile_exists`, it shall show "Profiel '<naam>' overschrijven?";
  on confirm it shall resend with overwrite, on cancel send nothing.
- **AC4.** If one of the run's 22 values is outside today's `PATCH config` rules, then a save
  shall return 422 naming that field and store nothing.
- **AC5.** If the run is ended, then a save shall return 409 `run_ended`; if it does not exist,
  404 `run_not_found`. A name empty after trimming or over 100 characters shall be 422.
- **AC6.** A profile shall never contain `idle_targets`, `idle_rise_targets`, any drink field,
  `bm_sigma`, `tick_interval_ms`, `quote_grace_versions` or the run's name.

**Create a borrel — SD3, SD4, SD9**

- **AC7.** When "Nieuwe borrel" is sent with a profile and no run to copy, the new draft shall
  have the profile's 22 values (Kaarsbreedte included), every other param from the latest run
  (else `DEFAULT_PARAMS`), no drinks, and revision 1 shall carry the profile's values.
- **AC8.** When it is sent with both a profile and `copy_from_run_id`, the draft shall have the
  profile's 22 values, the copied run's drinks as Phase 7 SD4 copies them, and the copied run's
  `idle_targets`, `idle_rise_targets` and other params outside the 22.
- **AC9.** When it is sent without a profile, the draft shall be exactly what it is today, with
  or without a copied run, Kaarsbreedte at 60 s.
- **AC10.** If the profile does not exist, then the create shall return 404 `profile_not_found`;
  if one of its values is outside today's rules, 422 naming the field. In both cases no run shall
  be created.

**Load onto a draft — SD3, SD9, SD13, SD15**

- **AC11.** When an admin confirms "Profiel laden" on a draft, the system shall replace the
  draft's 22 values with the profile's in one transaction and append one revision authored by
  the key label; every other param and every drink shall be unchanged. When the values are
  already equal, no revision shall be appended.
- **AC12.** "Profiel laden" shall ask SD13's confirm first; cancel shall send nothing.
- **AC13.** When the target run is live or ended, the system shall return 409 `run_not_draft`
  and write nothing; the page shall offer no load action on a live run.
- **AC14.** If the profile does not exist, then a load shall return 404 `profile_not_found`; if
  one of its values is outside today's rules, 422 naming the field. In both cases the draft
  shall be unchanged.
- **AC15.** When a stored profile lacks one of the 22 fields, a create or load shall keep that
  field's base value (SD4) and apply the others; a stored key outside the 22 shall be ignored.
- **AC16.** After a load, Globale instellingen, Vraag/Aanbod and the manipulation page's idle
  section shall show the loaded values without a page reload; a section with unsaved edits shall
  keep them and offer its existing "Overnemen".

**Delete — SD6, SD7**

- **AC17.** When an admin confirms "Verwijderen" ("Profiel '<naam>' verwijderen?"), the system
  shall remove the profile and return 204; an unknown one is 404 `profile_not_found`. Cancel
  sends nothing.
- **AC18.** Deleting or overwriting a profile shall change no run's params, Kaarsbreedte or
  revisions. Deleting the source run shall not change the profile's source name.

**The section — SD10, SD11, SD12**

- **AC19.** `/settings` shall show "Profielen" directly after Globale instellingen, with its own
  anchor and mobile-nav entry and its approved pixel icon before the name.
- **AC20.** The list shall show each profile as "<naam> · opgeslagen <d mmm HH:mm> · uit
  '<borrelnaam>'", in Amsterdam time, sorted by case-folded name; with none, "Nog geen
  profielen". No profile values shall be shown.
- **AC21.** "Opslaan als profiel" shall show only while a draft or live run exists; "Profiel
  laden" only while a draft exists. The list and "Verwijderen" shall show with or without a run.
- **AC22.** The "Nieuwe borrel" form shall offer "—" plus every profile by name; if the list
  cannot be fetched, only "—", and the form shall still create a borrel.
- **AC23.** A 422 naming a field shall be shown with that field's name from the settings
  explanations (B-01, B-03), not its wire name.

**Permissions and draining — SD14**

- **AC24.** Every profile route, and a create carrying a profile, shall be 401/403 for a display
  or bar key and for no session.
- **AC25.** While draining, every profile write and a create carrying a profile shall be refused
  as Phase 6 SD24 refuses admin writes, writing nothing.

**Restart — SD15**

- **AC26.** When the app restarts, every profile shall be there as last committed, and a run
  created from or loaded with a profile shall have the profile's values.

**No maths change**

- **AC27.** `exchange/` shall be unchanged by this item, and the golden fixtures shall replay
  unchanged.

## Verification

- **API (pytest):** save from a draft and from a live run, the 22 stored and nothing else (AC1,
  AC6); `profile_exists`, overwrite keeps the stored name, a concurrent same-name save (AC2,
  SD15); an out-of-range run value refused (AC4); ended, unknown, bad names (AC5); create with a
  profile, with a profile and a copy, without (AC7–AC10); load onto a draft, an equal profile
  appending nothing, a live and an ended target, an unknown and an out-of-range profile (AC11,
  AC13, AC14); a profile with a field removed from its stored JSON and an extra key (AC15);
  delete and its 404, and no run changed by delete or overwrite (AC17, AC18); every route as
  display, bar and no session (AC24); draining (AC25).
- **Integration (pytest):** a create with a profile and a load, then the market brought up from
  the database as at boot, running on the profile's values (AC26); a draft built from a profile
  going live with them.
- **Vitest:** the section, its order, the list text and order, the empty state (AC19–AC21); the
  three confirms and their cancels (AC3, AC12, AC17); the create form's select, its fallback, and
  the POST body (AC22); a 422 shown under the setting's name (AC23); the sections refetching
  after a load and "Overnemen" with unsaved edits (AC16).
- **Playwright (in the gate):** on a draft, change Sterkte ruis and Kaarsbreedte, save as
  "Wilde beurs"; change them back; load "Wilde beurs" and see both values return; delete the
  draft (Phase 7 SD3), create "Nieuwe borrel" with "Wilde beurs" and see them on the new draft.
- **The gate:** `./scripts/check.sh` green; `bash scripts/golden_linux.sh` green (AC27);
  `engine-guardian` on the diff reports no maths change.
- **Manual (exit check, the owner):** approve the icon (SD11). On a live dry run with the board
  open, tune the noise until it feels wild, save it as "Wilde beurs"; close the run; create a new
  borrel with "Wilde beurs" and "kopieer drankjes uit" the dry run, go live, and see the board
  move as it did.

## Exit condition

The owner can save a run's settings as a named profile, start a new borrel or reset a draft from
it alongside "kopieer drankjes uit", and delete it, and the pricing maths has not moved.
