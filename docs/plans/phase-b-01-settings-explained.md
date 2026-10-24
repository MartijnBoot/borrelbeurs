# Plan: B-01 — Settings that explain themselves

Spec: [docs/specs/phase-b-01-settings-explained.md](../specs/phase-b-01-settings-explained.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-24)**
Design: [frontend-architecture.md](../design/frontend-architecture.md) ("Structure": `components/ui/`, per-feature `index.ts`, `eslint-plugin-boundaries`)
ADRs honoured: 0006 (no new frontend dependency; the popup is plain React and CSS), 0002 (`exchange/` read, never changed). Nothing in an ADR is reversed.
Backlog: [B-01](../backlog.md) · Fixes: the screen-text side of D-21 and D-22

---

## Approach

**One table per feature, pinned to the spec, rendered by one component.** The spec's table
(E1–E33) is the source of truth (SD3). The build copies it once into two JSON files:
- `features/settings/explanations.json` holds E1–E20 and E33;
- `features/manipulation/explanations.json` holds E21–E32.

Each entry is keyed by its field (`step_quant`, `p_min_cents`, `crash`, …). A pytest parses the
spec's table and requires both files to match it exactly (T3), so changing a word is a change
to the spec, as SD3 says. A second pytest imports the code the "Eerste borrel", "Standaard",
"Leeg bij toevoegen" and "Toegestaan" phrases quote. It fails when a value drifts (T4). The
sections render each control's label and its (i) from the same entry, so a field shown in
three places (AC9) cannot say two things. A new `InfoButton` in `components/ui` does the
popup (T2). `Field` (and so `NumberField` and `MoneyField`) and `Switch` gain an optional
`info` prop. For a table header, a fieldset legend and a `Button`, the section places the
`InfoButton` beside the control. The one server change is SD9's floor (T1).

Rejected:
- **One shared table in `lib/` or `components/`.** `lib/` holds code, not copy. The E-rows
  split cleanly by feature, and every duplicated field (E13–E20) lives inside
  `features/settings`. Per-feature files keep `eslint-plugin-boundaries` happy with no exception.
- **A TypeScript module for the texts.** The value guard is Python: it can import
  `DEFAULT_PARAMS`, `ParamsPatch` and the drink validators directly. Python reads JSON as
  easily as the web does; it cannot read TS. Precedent:
  `web/src/features/exchange/model/__fixtures__/ws-messages.json`, read by both `tests/api/ws_fixture.py:63` and Vitest.
- **A Vitest that reads the spec markdown with `?raw`.** That needs `server.fs.allow`
  widened to `../docs` (`web/vite.config.ts:21`), and the guard would still need Python. Keeping
  all markdown parsing in pytest means one parser.
- **Putting the (i) inside `Field`'s `<label>`, `Switch`'s `<button>` or a `Button`.** A
  nested button is invalid HTML. Its text would also join the control's accessible name and
  break AC7's exact names (`Switch.tsx:13-24`, `Field.tsx:19-21`, `Button.tsx:12-17`). The (i)
  is always a sibling.
- **`<dialog>` or the Popover API.** `ConfirmDialog.tsx:4-5` already avoids `<dialog>`
  because jsdom supports `showModal` only in part. The popup follows `NavMenu`'s pattern
  instead: listeners on the document while it is open (`NavMenu.tsx:29-43`).

---

## Decisions this plan makes

Rows marked **Confirm** are readings of an acceptance criterion that the audit confirms or overrules.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | Where the 33 texts live | Two JSON files, one per feature (Approach). Shape: `{ "<key>": { "id": "E1", "name": "Prijsstap (€)", "paragraphs": ["…", "…"] } }`. Keys: the field name for fields; `event_duration_s`, `crash`, `correction`, `bubble`, `jump_target`, `jump_duration_s`, `anchor_s0` for the rest. `components/ui/InfoButton.tsx` exports `type Explanation = { name: string; paragraphs: readonly string[] }` | Boundaries; one source per feature; Python and Vitest can both read it |
| PD2 | How SD3's "a test pins every one" is met | `tests/unit/test_setting_explanations_text.py` parses the spec's `**E<n> — …** … **<new name>**` lines and the `> ` lines under each. It asserts that the two JSON files together hold exactly E1–E33, each with the spec's name and paragraphs character for character. Settings must hold E1–E20 and E33; manipulation must hold E21–E32 | The spec is the fixture. A doc edit with no code edit fails the gate, which is SD3's intent |
| PD3 | The guard: pytest or Vitest (spec leaves it to the planner) | **pytest**, `tests/unit/test_setting_explanations_values.py`. It reads the JSON, not the spec, since T3 pins the two together. See T4 for the rules. The two web-only defaults are pinned in Vitest instead: the jump's 5 (`PriceJumpSection.tsx:57`) and the event form's 30 (`MarketEventsSection.tsx:42`) | The values live in Python. Only these two live only in the web |
| PD4 | How the (i) attaches | `Field`, and through it `NumberField` and `MoneyField`, plus `Switch` take `info?: Explanation`. Each renders `InfoButton` as a sibling of the `<label>` or the switch's `<button>`, in a wrapping row. Table headers, the Idle legends and the five buttons (E28–E30, E33, and the jump/event fields are `Field`s already) render `<InfoButton>` next to the control. The Idle `<fieldset>` keeps `aria-label={name}`, so its accessible name stays exactly the new name even with the (i) inside the `<legend>` | AC7's exact accessible names; valid HTML |
| PD5 | The popup's placement (AC6) | Rendered with `createPortal` into `document.body` (`react-dom`, already a dependency). `position: fixed`, with width `min(20rem, 100vw − 16px)`. Horizontally it is clamped to an 8 px margin. It sits below the (i), or above it when the space below is too small, with `max-height: calc(100vh − 16px)` and vertical scroll. It is re-placed on window `scroll` (capture) and `resize` | A table header or a narrow flex row cannot overflow a fixed, clamped box, and an ancestor's `overflow` cannot clip it |
| PD6 | Focus (AC4) | Focus is **not** moved into the popup. The (i) has `aria-expanded` and `aria-controls` pointing at the popup; the popup is labelled by its title. Escape and a second activation close it, and the (i) keeps focus. A tap outside closes it and leaves focus where the tap put it. **Confirm** | A non-modal disclosure. Returning focus after an outside tap would steal the tap from the input the user just chose. With focus never moved, "focus returns to the (i)" holds for every keyboard close |
| PD7 | The (i)'s look and name | The visible content is the letter `i`, drawn as a circle by CSS, with no emoji and no `ⓘ` character. Accessible name `Uitleg: {name}` (AC4). `type="button"`, so it never submits (AC5) | B-02 owns emoji; AC4 |
| PD8 | At most one open (AC2) | A module-level "close the open one" handle in `InfoButton.tsx`. Opening calls the previous handle first. Document listeners (`click`, `keydown`) exist only while a popup is open, as in `NavMenu` | Holds for keyboard and pointer alike, without relying on the order click events arrive in |
| PD9 | Where the (i) appears for E13–E20 (AC9) | E13–E16: on each Vraag/Aanbod column header (not on every cell) and on each add-drink field. E17–E19: on each bounds row's fields and on the add-drink form. E20: on the add-drink form and on each drink row. Every one comes from the same JSON entry | AC9 "wherever a field appears"; spec In scope "a table column header" |
| PD10 | Playwright selectors | Every e2e selector that names a renamed control uses `{ exact: true }` with the full new name, e.g. `getByLabel('Minimumprijs (€)', { exact: true })` | Playwright's `getByLabel` also matches `aria-label` and matches substrings by default, so `'Minimumprijs'` would also hit "Uitleg: Minimumprijs (€)" and fail strict mode |
| PD11 | The durations' "Toegestaan" | Quoted in seconds against the server's milliseconds ÷ 1000: `EventRequest.duration_ms` 1 000–600 000 and `JumpRequest.duration_ms` 1 000–1 800 000 (`app/api/market.py:29-45`) | "Toegestaan ranges are the server's" (spec, The table) |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `app/runtime/config.py` | Modify | `IdleMinutes` `ge=0.5` → `ge=0.1` (`:106`) | T1 |
| `tests/api/test_config.py` | Modify | Floor pins at `:274` and `:330`, plus `idle_rise_minutes` cases; AC18 API case | T1 |
| `web/src/components/ui/InfoButton.tsx`, `InfoButton.module.css`, `InfoButton.test.tsx` | Create | The (i) and popup, PD4–PD8 | T2 |
| `web/src/components/ui/infoTesting.ts` | Create | Test helper: `expectExplained(scope, explanation)` opens the (i), asserts the title and paragraphs, closes | T2 |
| `web/src/components/ui/Field.tsx`, `Field.module.css`, `NumberField.tsx`, `MoneyField.tsx`, `Switch.tsx`, `Switch.module.css`, `FormControls.test.tsx` | Modify | `info?` prop (PD4) | T2 |
| `web/src/features/settings/explanations.json` | Create | E1–E20, E33 | T3 |
| `web/src/features/manipulation/explanations.json` | Create | E21–E32 | T3 |
| `tests/unit/test_setting_explanations_text.py` | Create | JSON = spec table (PD2); no emoji in a name (AC8); AC12/AC13 phrases | T3 |
| `tests/unit/test_setting_explanations_values.py` | Create | The value and range guard (PD3), with its self-test | T4 |
| `web/src/features/settings/GlobalSection.tsx`, `.test.tsx` | Modify | E1–E10 | T5 |
| `web/src/features/settings/DemandSection.tsx`, `.test.tsx` | Modify | E11–E16 | T6 |
| `web/src/features/settings/BoundsSection.tsx`, `.test.tsx` | Modify | E17–E19, the bounds error text | T7 |
| `web/src/features/settings/SystemSection.tsx`, `.test.tsx` | Modify | E33 | T7 |
| `web/src/features/manipulation/IdleSection.tsx`, `.test.tsx` | Modify | E21–E26, AC18 web case | T8 |
| `web/src/features/manipulation/MarketEventsSection.tsx`, `PriceJumpSection.tsx`, `ManipulationPage.test.tsx` | Modify | E27–E32 | T9 (`ManipulationPage.test.tsx` again in T11) |
| `web/src/features/settings/DrinksSection.tsx`, `.test.tsx` | Modify | E13–E20 in the add-drink form, E20 in the drink row | T10 |
| `web/e2e/admin.spec.ts` | Modify | `Tickgrootte` → `Prijsstap (€)` (T5); add-form `Min/Start/Max` (T10); AC6 at 360 px (T11) | T5, T10, T11 |
| `web/e2e/analytics.spec.ts` | Modify | Add-form `Min/Start/Max` (`:99-101`), drink row `Barprijs` (`:177`) | T10 |
| `web/src/app/pages/SettingsPage.test.tsx` | Modify | AC10 (no (i) outside the 33, per section) | T11 |
| `docs/specs/phase-6-admin.md` | Modify | Note on SD8 (`:179-199`): labels and idle floor superseded by B-01 | T12 |
| `docs/backlog.md` | Modify | B-01 status | T12 |
| `.claude/agents/engine-guardian.md` | Modify | AC16's checklist line, **owner-committed** | T13 |

`exchange/`, `app/api/`, `app/db/`, `db/migrations/` and `web/src/api/generated/` are not
touched. The generated types carry no `minimum`, so T1 does not change `schema.d.ts`
(`scripts/gen_api_types.sh:23-33`; `ParamsPatch` emits `idle_decay_minutes?: number | null`).

---

## Tasks

### T1 — Idle-minutes floor 0.5 → 0.1 (SD9)

- **Implements:** AC17, AC18 (API side), AC11 (the one permitted change)
- **Expected output:**
  - `app/runtime/config.py:106`: `IdleMinutes = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.1)]`.
  - `tests/api/test_config.py`:
    - in the 422 parametrize (`:257-283`), `{"idle_decay_minutes": 0.4}` becomes `0.09`,
      and a new `{"idle_rise_minutes": 0.09}` case is added. Both must return 422 naming the
      field and leave the config unchanged (the existing test body checks both);
    - in the inclusive-ends parametrize (`:319-332`), `{"idle_decay_minutes": 0.5}` becomes
      `0.1`, and a new `{"idle_rise_minutes": 0.1}` case is added (200 and stored);
    - AC18: a test that on a run started from `DEFAULT_PARAMS` (idle minutes 0.1) a
      `PATCH config {"params": {"idle_strength": 2.0}}` returns 200 and keeps both idle
      minutes at 0.1.
  - Write the tests first. The 0.1 cases fail before the one-line change.
- **Verification:** `uv run pytest tests/api/test_config.py` (needs the compose `db`). Before the change: the 0.1 cases fail. After: green.
- **Depends on:** —
- **Autonomy note:** The builder may name and place the new cases. Stop and ask if any other
  test or caller relies on 0.5. The analyst found none: `tests/engine/test_mask.py:172,174`
  uses 0.5 only as an engine input. Stop and ask before changing any other range.

### T2 — `InfoButton` and the `info` prop on Field, NumberField, MoneyField, Switch

- **Implements:** AC1, AC2, AC3, AC4, AC5 (component level); AC6 (placement logic, proved in T11)
- **Expected output:**
  - `InfoButton.tsx` exports `InfoButton({ explanation })` and `type Explanation`:
    - the (i) follows PD7;
    - the popup has a title (the name) and one `<p>` per paragraph, follows PD5, and opens on
      click only (no `mouseenter` or `pointerenter` handler);
    - it closes on a second click, an outside click and Escape; focus follows PD6; only one is
      open at a time (PD8);
    - `aria-expanded` reflects the state.
  - `Field` gains `info?: Explanation` and renders the (i) beside the `<label>`, outside it.
    The existing `hint` line stays exactly where it is (SD1). `NumberField` and `MoneyField`
    pass `info` through. `Switch` gains `info?` and renders the (i) beside its `<button>`.
  - `infoTesting.ts`: `expectExplained(scope, explanation)`, used by T5–T10. It clicks
    `Uitleg: {name}`, asserts the popup's title and paragraphs equal the entry, then presses
    Escape.
  - Tests (`InfoButton.test.tsx`, jsdom, `fireEvent` as elsewhere; no `user-event`, which is not installed):
    - opens on click, with title and paragraphs;
    - closes on a second click, an outside click and Escape;
    - opening B closes A;
    - `mouseOver` / `mouseEnter` alone opens nothing;
    - Enter and Space on the focused (i) open it, and focus is on the (i) after Escape;
    - accessible name and `aria-expanded`;
    - inside a `<form onSubmit={spy}>` next to a `NumberField`, activating the (i) does not
      call `spy` and does not call `onChange`;
    - the placement function, given a 360-wide viewport and an anchor at the right edge,
      returns a box inside `[8, 352]`.
  - `FormControls.test.tsx`: `Field` and `Switch` with `info` render the (i) as a sibling. The
    control's accessible name is unchanged; for example, `getByRole('switch', { name })` still
    matches exactly.
- **Verification:** `pnpm --dir web exec vitest run src/components/ui`
- **Depends on:** —
- **Autonomy note:** The builder decides the internal layout, CSS, the placement maths and
  the helper's signature. It may extract the placement into a pure function for testing. It
  may rename the arbitrary labels in the generic component tests ("Snelheid",
  "Vraag/aanbod actief") or leave them. Stop and ask before adding any dependency,
  including `@testing-library/user-event`. Stop and ask before moving focus into the popup,
  which would reverse PD6.

### T3 — The explanation tables, pinned to the spec

- **Implements:** AC7 (the pin), AC8 (no emoji in a name), AC12, AC13 (the text side), AC9 (one entry per field)
- **Expected output:**
  - The two JSON files from PD1. Each text is copied verbatim from the spec, typographic
    characters included: `€`, `≈`, `…`, the Dutch decimal comma.
  - `tests/unit/test_setting_explanations_text.py`:
    - `parse_spec_table(path) -> dict[str, (name, paragraphs)]` reads the spec's
      `## The table`. The name is the last bold run on the `**E<n> — …**` line: for E31 that
      is "Doelprijs (€)", before "(unchanged)". The paragraphs are the consecutive `> ` lines
      under it. `Bron:` lines are ignored. It asserts 33 rows, E1–E33.
    - Asserts:
      - the JSON ids are exactly E1–E33, split per PD2;
      - every name and paragraph list is equal to the spec's;
      - no name contains a character of Unicode category `So` (AC8);
      - E9's name is "Ritme stille drankjes (min)" and a paragraph contains "Dit is niet hoe
        vaak de prijzen verversen" (AC12);
      - E12 contains neither "init" nor "reset" and contains "alleen bij Live zetten";
      - E33 contains "huidige koers" (AC13).
    - A self-test: the parser on a small inline table, and on one with a changed word, which
      must not compare equal.
- **Verification:** `uv run pytest tests/unit/test_setting_explanations_text.py`. Also
  `pnpm --dir web exec prettier --check src/features/settings/explanations.json src/features/manipulation/explanations.json`.
- **Depends on:** —
- **Autonomy note:** The builder decides the parser's internals and the keys' order. **Stop and ask, never fix, if the spec's
  table cannot be parsed unambiguously or a row looks wrong.** The text is the owner's
  (SD3). A row that looks wrong goes to the owner as an `engine-guardian` question, never to
  a silent edit of the spec or the JSON.

### T4 — The value and range guard (SD8.1)

- **Implements:** AC14, AC15
- **Expected output:** `tests/unit/test_setting_explanations_values.py` reads both JSON files and imports `app.db.runs.DEFAULT_PARAMS`, `app.runtime.config.ParamsPatch` / `ConfigPatch`, `app.runtime.drinks` (`DEFAULT_A`…`DEFAULT_C`, `DrinkCreate`, `check_bounds`, `_bar_price`), `app.api.market` (`EventRequest`, `JumpRequest`), `app.runtime.manipulation.DEFAULT_EVENT_MS` and `app.db.models` (the run's `candle_interval_ms` server default, `"60000"`). One function `mismatches(...) -> list[str]` holds every rule. The test asserts it returns `[]`.
  - **Start values (AC14).** Taken from `Eerste borrel: ….`, `Standaard: ….` and
    `Leeg bij toevoegen: …`, with the leading Dutch number parsed (`0,10` → 0.1):
    - every entry keyed by a `Params` field quotes `Eerste borrel:`, never `Standaard:`, and
      its number equals `getattr(DEFAULT_PARAMS, key)`. `DEFAULT_PARAMS` is a `Params`, so
      the keys it does not set already carry `Params()`'s default, as SD5 asks;
    - `uit` / `aan` ↔ `False` / `True`, and `geen drankjes` ↔ `()`;
    - E9's "(elke 12 seconden)" equals `refresh_minutes × 60`;
    - E10's `Standaard: 60` equals the server default ÷ 1000;
    - E27's `Standaard: 30` equals `DEFAULT_EVENT_MS / 1000`, and E27 also equals
      `EventRequest`'s default;
    - E13–E16 equal `DEFAULT_A`…`DEFAULT_C`;
    - E20's "de Startprijs" is probed: `_bar_price` on a body without `bar_price_cents`
      returns `p0_cents`;
    - E32's 5 has no server value. The test asserts the text says `Standaard: 5`, and T9
      pins the web side.
  - **Ranges (AC15).** The text after `Toegestaan:` up to the next full stop:
    - For a numeric field, the expected phrase is rendered from the pydantic metadata of
      `ParamsPatch` / `ConfigPatch` / `DrinkCreate` / the market requests:
      - `ge` gives "X of meer";
      - `gt` gives "meer dan X";
      - `ge` + `le` gives "X tot en met Y";
      - `gt` + `le` gives "meer dan X en hoogstens Y";
      - no bound gives "elk getal";
      - `_whole_cents` adds ", in hele centen", and `multiple_of=5` adds ", in veelvouden van 5".
      - Numbers are Dutch, with no trailing zeros; durations are ÷ 1000 (PD11); money fields
        are in euros.
      - The phrase must equal the text exactly.
    - Relational rows (E17–E19 and E31) are probed against the validator:
      - for E17–E19, `check_bounds` must reject `p_min == p0` and `p0 == p_max` and accept
        `p_min < p0 < p_max`, and `p_min_cents` keeps `ge=0`;
      - for E31, the inclusive `[p_min, p_max]` check in `app/runtime/manipulation.py:72-77`.
        If that is not reachable without the holder, assert the phrase literally and cite the
        existing API test that pins inclusivity.
  - **Self-test.** `mismatches` is called with a perturbed `DEFAULT_PARAMS`
    (`dataclasses.replace(DEFAULT_PARAMS, eta=0.9)`) and a perturbed range (a `ParamsPatch`
    subclass with `refresh_minutes` `le=20`). Each must return a non-empty list that names
    E2 and E9 respectively. This is the spec's "proved by temporarily changing one default and one range",
    made permanent, like the planted forgery in `quote.provenance.test.ts`.
- **Verification:** `uv run pytest tests/unit/test_setting_explanations_values.py`
- **Depends on:** T1 (E21 and E23 say "0,1 of meer"), T3 (the JSON)
- **Autonomy note:** The builder decides the internals and how the phrase is rendered. Each
  row may be checked by metadata or by a probe, but **no row with a quoted value or range may
  be left unchecked**. If a phrase cannot be rendered from the code without special-casing
  it, a literal assertion with a comment naming the code line is acceptable. Stop and ask if
  any quoted value does not match the code. That is the guard firing, and the owner decides
  which side is wrong.

### T5 — Globale instellingen: E1–E10

- **Implements:** AC1, AC5, AC7, AC12 (E1–E10)
- **Expected output:**
  - `GlobalSection.tsx`: `FIELDS` (`:22-33`) carries the keys only. Each `NumberField` takes
    `label` and `info` from `explanations.json`.
  - `GlobalSection.test.tsx`:
    - the old-label assertions (`:88-98`, `:113-183`) are rewritten to the new names, on the
      same behaviour;
    - a table-driven test runs `expectExplained` for all ten;
    - a test clicks every (i) and then saves, which shows "Niets te wijzigen" and sends no
      `PATCH` (AC5).
  - `web/e2e/admin.spec.ts:123`: `global.getByLabel('Prijsstap (€)', { exact: true })` (PD10).
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/GlobalSection.test.tsx`, then `pnpm --dir web run e2e -- admin.spec.ts`
- **Depends on:** T2, T3
- **Autonomy note:** The builder decides the layout of the label map. Stop and ask if a
  request body changes (AC11).

### T6 — Vraag/Aanbod: E11–E16

- **Implements:** AC1, AC5, AC7, AC9 (E13–E16 header side), AC13 (E12)
- **Expected output:**
  - `DemandSection.tsx`:
    - the switches at `:140` and `:145` take `label` and `info` from E11 and E12;
    - each column header (`:159-160`) shows the new name with an (i); the visible name sits
      in its own `<span>`, so a test can read it apart from the (i);
    - each cell's accessible name becomes `` `${drink.name} ${name}` ``, e.g.
      "Bier Basisvraag (a)" (AC7);
    - `COEFFICIENTS` stays the key list.
  - `DemandSection.test.tsx`: `'Wijn a'`, `'Bier d'`, `'Bier s0'` and the rest
    (`:107-166`), plus the switch at `:129`, become the new names. New tests:
    `expectExplained` for E11–E16; the header texts; clicking a header's (i) leaves the table
    form clean (AC5).
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/DemandSection.test.tsx`
- **Depends on:** T2, T3
- **Autonomy note:** The builder decides the header markup. Stop and ask before adding an (i)
  to each cell; PD9 puts it on the header.

### T7 — Min/Max/Startprijs (E17–E19) and Systeemacties (E33)

- **Implements:** AC1, AC5, AC7, AC9 (E17–E19 bounds side), AC13 (E33)
- **Expected output:**
  - `BoundsSection.tsx`:
    - `FIELDS` (`:26-30`) becomes keys only, and each `MoneyField` takes `label` and `info`
      from E17–E19;
    - `:85` `setError('Minimumprijs < Startprijs < Maximumprijs')`.
  - `BoundsSection.test.tsx`: `getByLabelText('Min' / 'Start' / 'Max')` (`:96-145`) and the
    alert text (`:124`) are updated; `expectExplained` runs for one row's three fields.
  - `SystemSection.tsx:64`: the button text becomes "Evenwicht op huidige prijzen", with an
    `InfoButton` (E33) beside it. The (i) stays enabled while the button is disabled on a
    draft (`:63`).
  - `SystemSection.test.tsx:74,84` gets the new name, plus a test that the (i) opens on a
    draft run while the button is disabled.
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/BoundsSection.test.tsx src/features/settings/SystemSection.test.tsx`
- **Depends on:** T2, T3
- **Autonomy note:** The builder decides the markup around the anchor button. The notice
  "Evenwicht gezet op de huidige prijzen" and "⛔ Sluit app" stay unchanged (SD2). Ask
  before touching either.

### T8 — Idle: E21–E26, and AC18 on the web

- **Implements:** AC1, AC5, AC7, AC18 (web side)
- **Expected output:**
  - `IdleSection.tsx`: `NUMBERS` and `TARGETS` (`:33-43`) become keys only. Each field takes
    `label` and `info` from E21–E24. Each `<fieldset>` keeps `aria-label={name}`, and its
    `<legend>` (`:143`) shows the name and an (i) (E25, E26) (PD4).
  - `IdleSection.test.tsx`:
    - `'Decay targets'` and `'Rise targets'` (`:98-99`) and `'🕒 Idle-decay (min)'` (`:104`)
      become the new names;
    - `expectExplained` runs for E21–E26;
    - the groups are still found by `getByRole('group', { name: 'Omlaag bij stilte' })`;
    - AC18: with config params `idle_decay_minutes = idle_rise_minutes = 0.1`, editing only
      Kracht omlaag and saving sends a `PATCH` whose `params` is exactly `{ idle_strength: … }`,
      and the save shows success;
    - clicking an (i) and saving gives "Niets te wijzigen" (AC5).
- **Verification:** `pnpm --dir web exec vitest run src/features/manipulation/IdleSection.test.tsx`
- **Depends on:** T2, T3
- **Autonomy note:** The builder decides the legend markup. Stop and ask before dropping the
  fieldset's `aria-label`.

### T9 — Market events and price jump: E27–E32

- **Implements:** AC1, AC7, AC14 (the two web-only defaults)
- **Expected output:**
  - `MarketEventsSection.tsx`:
    - the duration field (`:69`) takes `label` and `info` from E27;
    - `EVENTS` (`:27-34`) gets the button texts "Marktcrash", "Terug naar startprijs" and
      "Prijsbubbel", each with an `InfoButton` (E28–E30) beside it;
    - `question` and `word` stay unchanged (SD6).
  - `PriceJumpSection.tsx`: "Doelprijs (€)" keeps its name, gains `info` (E31) and keeps its
    bounds hint. The duration (`:111`) takes "Duur sprong (sec)" and E32.
  - `ManipulationPage.test.tsx`:
    - the button table (`:155-157`) gets the new names, with the confirmation questions
      unchanged;
    - `expectExplained` runs for E27–E32;
    - a test that each duration field's initial value equals the number in its explanation's
      `Standaard:` paragraph (30 and 5, PD3).
- **Verification:** `pnpm --dir web exec vitest run src/features/manipulation/ManipulationPage.test.tsx`
- **Depends on:** T2, T3
- **Autonomy note:** The builder decides the layout of the button row. The board banner
  "Terug naar start" (`features/koers/MarketEventLayer.tsx:19`) is koers text, not a
  control, and stays as it is. Stop and ask if a confirmation text or the
  "{word} gestart!" status would change.

### T10 — Drankjes beheren: the add-drink form (E13–E20) and the drink row (E20)

- **Implements:** AC1, AC5, AC7, AC9 (E13–E20 form and row side)
- **Expected output:**
  - `DrinksSection.tsx`:
    - in the add form (`:175-205`), "Min", "Start", "Max" and "Barprijs" become E17, E18, E19
      and E20, each with `info`;
    - the coefficient fields (`:199-205`) take E13–E16's name and `info`; their hints
      "Leeg: de startprijs" and "Leeg: standaard" stay (SD1);
    - the drink row's "Barprijs" (`:308`) takes E20.
  - Both reuse the same entries as T6 and T7 (AC9).
  - `DrinksSection.test.tsx` (`:99-163`) is updated to the new names. New tests:
    `expectExplained` once in the form and once in a row; clicking an (i) in the add form
    sends no `POST`.
  - e2e: `admin.spec.ts:112-114` and `analytics.spec.ts:99-101` become
    `add.getByLabel('Minimumprijs (€)', { exact: true })` and the like, and
    `analytics.spec.ts:177` becomes `'Normale barprijs (€)'` (PD10).
- **Verification:** `pnpm --dir web exec vitest run src/features/settings/DrinksSection.test.tsx`, then `pnpm --dir web run e2e -- admin.spec.ts analytics.spec.ts`
- **Depends on:** T2, T3, T5 (both edit `web/e2e/admin.spec.ts`)
- **Autonomy note:** The builder decides how the form maps keys to entries. `NameField` and
  its unlinked error (`DrinksSection.tsx:206-230`) are out of scope; do not fix them here.

### T11 — The whole pages: AC8 headings, AC10, and AC6 at 360 px

- **Implements:** AC6, AC8 (headings), AC10, AC9 (cross-check)
- **Expected output:**
  - `SettingsPage.test.tsx`:
    - every button whose name starts with `Uitleg: ` names one of E1–E20 or E33;
    - per section, the count is: Global 10; Vraag/Aanbod 6; Min/Max/Startprijs 3 per drink;
      Drankjes beheren 8 in the add form plus 1 per drink; Systeemacties 1;
    - Borrel, Kleurenschema, Afbeeldingen and Toegangssleutels have 0 (AC10);
    - for E13–E20, every (i) with the same name opens the same paragraphs (AC9);
    - the existing heading pins (`:8-18`) stay unchanged (AC8).
  - `ManipulationPage.test.tsx`:
    - the same rules: Nieuws 0, Market events 4, Price jump 2, Idle 6;
    - "Start jump" and "Drankje" have none;
    - all four headings are pinned exactly: "📰 Nieuws", "💥 Market events", "⚡ Price jump",
      "⏳ Idle".
  - `web/e2e/admin.spec.ts`, a new test at `page.setViewportSize({ width: 360, height: 800 })`
    (pattern `bar.spec.ts:217`):
    - on `/settings`, click "Uitleg: Prijsstap (€)"; on `/manipulation`, click
      "Uitleg: Kracht omlaag";
    - each time the popup's bounding box lies within `[0, 360]` and
      `document.documentElement.scrollWidth <= 360`;
    - Escape hides it.
    - The existing save of Globale instellingen through "Prijsstap (€)" (T5) still passes.
- **Verification:** `pnpm --dir web exec vitest run src/app/pages/SettingsPage.test.tsx src/features/manipulation/ManipulationPage.test.tsx`, then `pnpm --dir web run e2e -- admin.spec.ts`
- **Depends on:** T5, T6, T7, T8, T9, T10
- **Autonomy note:** The builder decides how to count per section. If `/manipulation` at
  360 px already scrolls sideways for a reason unrelated to the popup, stop and report it
  rather than fixing it.

### T12 — Documents and the exit check

- **Implements:** AC19, AC11 (the evidence); the spec's In scope: Documents
- **Expected output:**
  - `docs/specs/phase-6-admin.md`, after SD8's table (`:179-199`): a note that the labels and
    the idle-minutes floor are superseded by B-01 (SD9). The table itself stays as written.
  - `docs/backlog.md` B-01: status "built → `docs/plans/phase-b-01-settings-explained.md`".
  - Evidence, pasted into the PR:
    - `git diff --stat main -- exchange/ app/api app/db db web/src/api` is empty;
    - `./scripts/check.sh` is green;
    - `bash scripts/golden_linux.sh` is green.
- **Verification:** the three commands above; `git diff main -- exchange/` empty.
- **Depends on:** T4, T11
- **Autonomy note:** The builder writes the note's wording; `docs/` prose only. Run the
  manual exit check (a person reads every popup on a phone) with the owner. It is a human
  step, and the item is not done without it.

### T13 — engine-guardian's checklist line (SD8.2) — owner

- **Implements:** AC16
- **Expected output:** `.claude/agents/engine-guardian.md`, "## How to check" (`:22-41`)
  gains a fifth item. Proposed text, for the owner to paste:
  > 5. **Re-check B-01's explanations.** If the diff changes lines in `exchange/` that a
  >    **Bron** in `docs/specs/phase-b-01-settings-explained.md` ("The table") cites, re-read
  >    those rows against the new code and report every row that is no longer true. Any doubt
  >    goes to the owner, never to the builder.
- **Verification:** `grep -n "phase-b-01" .claude/agents/engine-guardian.md`
- **Depends on:** —
- **Autonomy note:** **Owner only.** This is a `.claude/` edit; SD8 says the owner commits it,
  and in auto mode an agent cannot write `.claude/**`. The builder only reminds the owner.

---

## Task graph

```
T1 ──┐
     ├── T4 ───────────────────────────┐
T3 ──┤                                 │
     ├── T5 ── T10 ──┐                 │
T2 ──┤   T6 ─────────┤                 │
     │   T7 ─────────┼── T11 ── T12 ───┘ (T12 also waits for T4)
     │   T8 ─────────┤
     └── T9 ─────────┘
T13 (owner, any time)
```

T5–T10 depend on both T2 and T3; T4 on T1 and T3.

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T2, T3, T13 | `app/runtime/config.py`, `tests/api/test_config.py` · `components/ui/{InfoButton*,infoTesting.ts,Field*,NumberField,MoneyField,Switch*,FormControls.test}` · `features/{settings,manipulation}/explanations.json`, `tests/unit/test_setting_explanations_text.py` · `.claude/agents/engine-guardian.md` |
| G2 | T4, T5, T6, T7, T8, T9 | `tests/unit/test_setting_explanations_values.py` · `GlobalSection*`, `e2e/admin.spec.ts` · `DemandSection*` · `BoundsSection*`, `SystemSection*` · `IdleSection*` · `MarketEventsSection`, `PriceJumpSection`, `ManipulationPage.test` |
| G3 | T10 | `DrinksSection*`, `e2e/admin.spec.ts`, `e2e/analytics.spec.ts` |
| G4 | T11 | `SettingsPage.test`, `ManipulationPage.test`, `e2e/admin.spec.ts` |
| G5 | T12 | `docs/specs/phase-6-admin.md`, `docs/backlog.md` |

No two tasks in one group write the same file. `admin.spec.ts` is written by T5 → T10 → T11,
and `ManipulationPage.test.tsx` by T9 → T11; both are chained for that reason. T5–T9 only
*read* the JSON files T3 wrote.

---

## Data changes

None. No migration, no column, no `run.params` key and no API field changes (SD4). The only
behaviour change on the server is SD9's validation floor (T1). It is reversible by putting
`ge=0.5` back. Stored values are not rewritten either way.

---

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| **AC18 already passes today.** `useEditableRecord` sends only the changed keys (`web/src/lib/useEditableRecord.ts:91-101`), and the server validates only the patch (`app/runtime/config.py:284-301`). So editing another field on a `DEFAULT_PARAMS` run succeeds even with the 0.5 floor in place. The case that fails before SD9 is saving the idle field itself at 0.1, which is AC17 | T1 and T8 test AC18 anyway, as a regression; T1's AC17 cases are the ones that fail first. Noted so the audit does not expect AC18 to go red before T1 |
| The spec cites `tests/api/test_config.py:272` for the 0.5 pin; it is really `:274` (422) and `:330` (inclusive). `DEFAULT_PARAMS` is at `app/db/runs.py:58-70`. `idle_rise_minutes` had no range test | T1 names the right lines and adds the missing `idle_rise_minutes` cases. The spec is not edited: it is approved, and these are citations, not behaviour |
| A spec typo found during the build would fail T3 with no way for the builder to fix it | T3's autonomy note: stop and ask. The owner edits the spec, which is SD3's rule |
| JSON imported by non-test source for the first time. `resolveJsonModule` is not set explicitly; TS 6 turns it on for `moduleResolution: "bundler"` (`tsconfig.app.json:12`), and test files under `src` already import JSON (`ws-messages.json`) | If `tsc -b` or `vite build` refuses, T3/T5 may set `"resolveJsonModule": true` in `web/tsconfig.app.json`. That is configuration, not a dependency |
| A `position: fixed` popup inside a transformed ancestor would be placed wrongly; a long explanation near the bottom of a phone screen could run off it | PD5: portal into `body`, clamped in both axes, with vertical scroll inside. T11's e2e proves the horizontal case at 360 px |
| Playwright's substring `getByLabel` matches the (i)'s `aria-label` | PD10: `{ exact: true }` on every renamed selector |
| PD6 reads AC4's "on close, focus shall return to the (i)" as holding for keyboard closes, not for an outside tap | Marked **Confirm**. If the owner wants focus pulled back on an outside tap as well, it is a three-line change in T2 |
| "Eerste borrel" is true only for the very first run; later runs copy the previous run's params (`app/db/runs.py:462`) | That is SD14's wording, decided at the interview. Not reopened |
| Golden tests are skipped on Windows | T12 runs `bash scripts/golden_linux.sh` (Docker). If Docker is unavailable, T12 stops and says so rather than claiming AC19 |
| The gate needs the compose `db` on 5432, which another local stack sometimes holds | The builder asks the owner, never stops another stack |

---

## Out of scope for this plan

- Everything in the spec's Out of scope: maths, defaults, other ranges, API and DB keys,
  section headings, theme token names, hover, a manual, B-02, B-03, B-04 and B-07.
- The board banner "Terug naar start" (`features/koers/MarketEventLayer.tsx:19`). It is not
  one of the 33 controls.
- The arbitrary labels in the generic component tests (`NumberField.test.tsx` "Snelheid" and
  "Drempel", `FormControls.test.tsx` "Vraag/aanbod actief"). They exercise a component, not
  the real control. T2 may rename them.
- Found by the analysts while planning, not fixed here. Candidates for `/backlog` or the
  defect register, at the owner's choice:
  - `JumpRequest` and `EventRequest` use non-strict `int`, unlike the D-03 rule
    (`app/api/market.py:32-45`);
  - stored params are never re-validated against `ParamsPatch`, so imported or copied
    out-of-range values persist silently;
  - `create_run` writes revision 1 in a different shape from later revisions
    (`app/db/runs.py:491-500` vs `app/runtime/config.py:316-327`);
  - `copy_from_run_id` does not copy the candle interval (`app/db/runs.py:191-199`);
  - every settings section fetches the config on its own (`useCurrentRun.ts:68-70`);
  - `NameField`'s error is not linked by `aria-describedby` (`DrinksSection.tsx:206-230`);
  - `NavMenu` does not return focus on close.

---

## AC → task traceability

| AC | Tasks |
|---|---|
| AC1 | T2, T5, T6, T7, T8, T9, T10 |
| AC2 | T2 |
| AC3 | T2 |
| AC4 | T2 |
| AC5 | T2, T5, T6, T8, T10 |
| AC6 | T2 (placement), T11 (e2e) |
| AC7 | T3 (pin), T5–T10 (rendered) |
| AC8 | T3 (names), T11 (headings) |
| AC9 | T3, T6, T7, T10, T11 |
| AC10 | T11 |
| AC11 | T1, T5, T12 |
| AC12 | T3, T5 |
| AC13 | T3, T6, T7 |
| AC14 | T4, T9 |
| AC15 | T4 |
| AC16 | T13 |
| AC17 | T1 |
| AC18 | T1, T8 |
| AC19 | T12 |

Every task maps to at least one AC; none is an orphan.

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

PD6 (focus not pulled back on an outside tap) confirmed as written.

Audited by: MartijnBoot (owner, `/audit`)  Date: 2026-10-24
