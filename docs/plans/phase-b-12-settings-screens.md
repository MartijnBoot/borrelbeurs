# Plan: B-12 — Settings on separate screens per kind of work

Spec: [docs/specs/phase-b-12-settings-screens.md](../specs/phase-b-12-settings-screens.md) (`Status: Approved`) · Status: **Owner-confirmed 2026-11-02 (OQ1 = B, every Confirm row); audit PASS 2026-11-02**
Design: `docs/design/frontend-architecture.md` is amended at `:44` and `:64` (SD1; the owner approved this at the spec interview). T15 makes the change. Nothing else in `docs/design/` changes.
ADRs honoured:
- 0002 and 0012: nothing under `exchange/` is read or changed (AC26).
- 0004: no migration, no new engine.

No product ADR is reversed. **No new dependency:** `react-router` 8.4.0 is already in `web/package.json` and ships `createBrowserRouter`, `createMemoryRouter`, `RouterProvider` and `useBlocker` (checked in `web/node_modules/react-router`).
Backlog: [B-12](../backlog.md) · Fixes: no open defect · Amends: `frontend-architecture.md`, Phase 6 SD25, B-03 SD5, B-06's placement of the two payment settings (T15)

Line references are to `main` at `e1da324`.

---

## Approach

**The server change is one tuple; everything else is composition.**
- `ROLE_ROUTES["admin"]` gains `/settings/spel`, `/settings/wallets`, `/settings/beheer` right after `/settings` (`app/api/security.py:128`). `SPA_ROUTES` (`app/main.py:112-114`), `/auth/me`'s `allowed_routes` (`app/api/auth.py:54`) and `RequireRole` (`web/src/features/auth/RequireRole.tsx:19`) already follow from that table, so nothing else on the server changes.
- `NavMenu` renders every route it is given (`web/src/components/ui/NavMenu.tsx:61`). It learns to skip a route nested under another one (PD5), so the menu still lists "Instellingen" once (SD11).
- The screens are composed in `app/pages/`, as `SettingsPage.tsx` composes today's page. The features stay sibling-isolated (`web/eslint.config.js:123-138`). A new `SettingsScreens.tsx` holds the three section lists and one frame (the "← Instellingen" link above `SettingsLayout`). `SettingsPage.tsx` becomes the landing page.
- The sections split along SD3–SD5 inside `features/settings/`. Each new piece reuses the pattern of the section it came from:
  - `PriceStepSection` takes Prijsstap and B-07's dialog out of `GlobalSection.tsx:122-136, 232-255`;
  - `PaymentSection` takes the two run columns out of `GlobalSection.tsx:206-223`;
  - `DemandSection.tsx` becomes two components, the switches form (`:141-159`) and the table form (`:160-213`).
  Every save still goes through `useEditableRecord` and the same endpoints (SD13).

**The leave guard uses the router the app already has, mounted the other way (SD18).**
- `main.tsx` replaces `<BrowserRouter><AppRoutes /></BrowserRouter>` with `createBrowserRouter([{ path: '*', element: <AppRoutes /> }])` and `<RouterProvider>`. `AppRoutes`' `<Routes>` stay as descendant routes, unchanged. That is enough for `useBlocker`, which covers links, `navigate()` and the back button (a POP).
- `useEditableRecord` reports its `dirty` flag to a small context (`lib/unsavedEdits.tsx`). It is a no-op where no provider is mounted.
- One `LeaveGuard` in the shell asks "Niet-opgeslagen wijzigingen weggooien?" with the existing `ConfirmDialog`. It acts only on the three screen addresses. It ignores a change of the `#hash` alone (the section links) and a navigation to `/login` (a lost session). It also requests the browser's `beforeunload` prompt.
- The cost: a test that mounts a screen needs a data router (`createMemoryRouter`), because `useBlocker` throws inside a plain `MemoryRouter`.

Rejected:
- **Converting the whole route table to data routes** (`createRoutesFromElements`, loaders). Same blocker, a much larger diff, no gain.
- **Intercepting history by hand** (`popstate` and wrapped `<Link>`s). `react-router` owns the history stack, and a second owner is how a back press gets swallowed.
- **A new dependency** for the guard: a hard stop, and not needed.
- **One provider per screen.** `Uitloggen` lives in the shell's menu (`routes.tsx:63-66`), above any screen, and SD9 counts the header menu as a way out. So the guard has to sit in the shell.
- **Each section calling the guard by hand.** It would touch every section file and could forget one. The hook every edit form already uses (`useEditableRecord`) reports instead. The forms that do not use it are wired explicitly in T11.

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. **Owner** rows are user-visible choices the spec leaves open. CLAUDE.md makes each one an owner stop: the audit answers it, and the plan carries a recommendation.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | The router (SD18) | `web/src/main.tsx`:<br>`const router = createBrowserRouter([{ path: '*', element: <AppRoutes /> }])`<br>`<RouterProvider router={router} />`, both from `react-router`.<br>`AppRoutes` keeps its `<Routes>`. Tests that mount a settings screen render through `createMemoryRouter` + `RouterProvider`. A shared test helper builds that, at a place the builder chooses. | The smallest change that makes `useBlocker` legal. A splat parent with descendant `<Routes>` is a supported data-router shape. |
| PD2 | The unsaved-edits registry | **`web/src/lib/unsavedEdits.tsx`** holds:<br>• `UnsavedEditsProvider`;<br>• `useReportUnsaved(dirty: boolean)`, which registers while `dirty` is true and unregisters on unmount or when it turns false, and does nothing without a provider;<br>• `useHasUnsaved(): boolean`.<br>`useEditableRecord` calls `useReportUnsaved(dirty)`. The provider wraps the shell's `<Outlet>` in `ShellLayout` (`routes.tsx:50-70`). | One hook, used by every edit form already. Hidden noise fields stay in the same record, so they still count (SD6). The demand table unmounts when the switch goes off, and its record unmounts with it, so it stops counting (SD16). Outside a settings screen, the guard ignores reports (PD3), so `/manipulation`'s Idle form is unaffected. |
| PD3 | `LeaveGuard` (SD9; AC23, AC24) | **`web/src/app/LeaveGuard.tsx`**, rendered once inside the provider in `ShellLayout`.<br>• **When it blocks:** `useBlocker(({ currentLocation, nextLocation }) => …)` blocks only when all four hold: `useHasUnsaved()`; `currentLocation.pathname` is one of `/settings/spel`, `/settings/wallets`, `/settings/beheer`; `nextLocation.pathname !== currentLocation.pathname`; and `nextLocation.pathname !== '/login'`.<br>• **The dialog:** `ConfirmDialog` with message "Niet-opgeslagen wijzigingen weggooien?", `confirmLabel` "Weggooien" (calls `blocker.proceed()`), `cancelLabel` "Blijven" (calls `blocker.reset()`). Escape is "Blijven".<br>• **Reload and tab close:** while it would block, a `beforeunload` listener calls `event.preventDefault()` and sets `returnValue = ''`.<br>• **Uitloggen:** the shell's logout goes through the guard too. `useConfirmLeave()(then)` asks the same dialog when unsaved, else runs `then` at once. `ShellLayout`'s `onLogout` becomes `confirmLeave(() => { navigate('/login', …); void logout() })`. **Confirm** | Pathname-only, so `MobileSectionNav`'s `<a href="#…">` links (`MobileSectionNav.tsx:35-40`) pass. `/login` is exempt because a 401 sends there through `useGoToLogin` (`useSession.ts:98-111`) after the session is already gone. Blocking that would trap the user on a dead session. Uitloggen sits in the header menu, which SD9 names as a way out, so it asks first. |
| PD4 | Forms that do not use `useEditableRecord` | **Counted in every reading** (they hold typed values next to stored ones):<br>• `WalletsSection`'s Aanmeldcode and the two Bewaartermijnen, while they differ from the stored settings;<br>• `ThemeEditor`, while its draft differs from the active theme.<br>Each calls `useReportUnsaved(…)` (T11). | SD9: "typed values that differ from what is stored". |
| PD5 | The menu (SD11; AC4) | `NavMenu` drops a route that starts with another listed route followed by `/` (`/settings/spel` under `/settings`). Every other route is still listed, labelled or not (its header comment's rule). **Confirm** | General, not a list of three names, and it leaves B-13 room to decide. A role with `/settings/spel` but no `/settings` would still see it. |
| PD6 | Where the guard counts (SD9) | Only the three screens. The landing page has no form. **Confirm** | SD9 is about "a screen". The rest of the app is out of scope (`/manipulation` "stays as it is", SD7). |
| PD7 | The landing (SD2, SD10, SD15) | `SettingsPage` renders:<br>• the status line from `useCurrentRun()` (`features/settings/useCurrentRun.ts`): `failed` gives "Borrel: onbekend", `null` gives "Geen actieve borrel", live gives "Borrel: <naam> (live)", draft gives "Borrel: <naam> (concept)", and "Laden…" while `undefined`;<br>• then one `<Link>` tile per screen in `session.me.allowed_routes`, in SD3's order, each with its name as `h2`, SD15's line and the address.<br>The tile styles copy `HomePage.module.css`'s `.grid` and `.tile` into `pages.module.css`. A feature's CSS module is not importable from `app/` (entry-point rule, `eslint.config.js:109-117`). The grid stacks to one column at 375 px. **Confirm** ("Laden…") | The Borrel section's own source (SD10). "Laden…" is the app's loading word (`GlobalSection.tsx:117`). |
| PD8 | A screen's frame (SD8; AC22) | `SettingsScreen({ sections })` in `app/pages/SettingsScreens.tsx`: a `<Link to="/settings">← Instellingen</Link>` above `<SettingsLayout sections={…} />`. `SettingsLayout` drops its nav column when it has fewer than two sections (`settings.module.css:1-6` grid). The screen has no `h1` of its own (see Out of scope). | One frame, three lists, as `SettingsPage.tsx` does today. |
| PD9 | Prijzen's Prijsstap form (SD4) | `PriceStepSection`: a `useEditableRecord({ step_quant })` form with one `NumberField` (`explanations.step_quant`) and the submit **"Opslaan prijsstap"**. It sends `PATCH config { params: { step_quant } }`. It keeps the B-07 dialog, its texts, `faultsOf` and "Niets te wijzigen" exactly as they are in `GlobalSection.tsx:122-164, 232-255`. It shows its own "Serverwaarden gewijzigd — overnemen?" while dirty. In the Prijzen section it renders above `BoundsSection`. **Confirm** (the button text) | It follows DemandSection's "Opslaan schakelaars" / "Opslaan coëfficiënten" pattern. SD4 asks that everything B-07 gave Prijsstap is kept. |
| PD10 | Betalen (SD13; AC16) | `PaymentSection`: `useEditableRecord({ wallet_required, credit_limit_cents })`, the `Switch` and the `MoneyField` moved verbatim from `GlobalSection.tsx:206-223`, and submit "Opslaan". The body is the changed keys at the top level, never under `params`. It reuses `faultsOf` for a 422 under its field, and has the same conflict prompt. | SD13. |
| PD11 | Globale instellingen' groups (SD5; AC12) | One form, one "Opslaan instellingen". Three `<section aria-label=…>` groups, each with an `h3`, as `WalletsSection.tsx:189-190` does:<br>• **"Hoe bestellingen de prijs bewegen":** `eta`, `K`, `lambda_orders`, `alpha_price`, `phi_persist`, `decay_rho`, `refresh_minutes`;<br>• **"Willekeurige ruis":** the switch, then the five fields;<br>• **"Koersbord":** `history_window_minutes`, `candle_interval_s`.<br>The body is built as today, minus the removed keys. | The names in SD5 map to these keys in `explanations.json`. |
| PD12 | A hidden noise field that blocks the save (SD6; AC14) | While `bm_enabled` is off, the five fields are not rendered. Their values stay in the record. A submit whose patch holds a noise field that is `null` or `'invalid'` while the switch is off sends nothing. It shows one `role="alert"` line per such field: **"<naam> is leeg of ongeldig. Zet Willekeurige ruis aan om het te verbeteren."** (`<naam>` is `explanations[field].name`). **Confirm** (the sentence) | SD6 says what the message must say, not its words. `useEditableRecord.save` already refuses (`'invalid'`); this only makes the refusal visible. |
| PD13 | The demand split (SD3, SD16; AC17, AC18) | `DemandSection.tsx` exports two components:<br>• **`DemandSwitches`** (Beheer): today's switches form, the two `Switch`es stacked in one column (AC20);<br>• **`DemandTable`** (Spelopzet): today's table form while `config.params.demand_enabled` is true; otherwise the single `<p>` "Vraag/Aanbod staat uit. Zet het aan onder Beheer.", with no link.<br>Each keeps its own `useEditableRecord`, conflict prompt and toast. `DemandTable` renders its form, and so its record, only while the switch is on, so turning it off drops the edits (SD16). Live, the `config` message changes the store's `params`, which refetches `useCurrentRun` and then `useRunConfig` (`useCurrentRun.ts:55-62`). **Confirm** (draft runs: R3) | Splitting along the existing two `useEditableRecord`s keeps every save rule as it is. |
| PD14 | Switch layout (SD7; AC19, AC20) | `Switch` renders one row: the label text, then the (i), then, at the row's right end, a `<button type="button" role="switch" aria-checked>` holding only the track. The button is named by the label through `aria-labelledby` (or a `<label htmlFor>`, the builder's choice), so the (i) stays outside the name. The row has a fixed width (`width: 20rem; max-width: 100%`, or the builder's equivalent), with the track pushed right. The track keeps 2.25 × 1.25 rem (`Switch.module.css:24-30`). Clicking the label text toggles too. | Every existing `getByRole('switch', { name })` (11 in `src` and `e2e`) keeps working. A fixed row width puts the tracks of one column on one x. |
| PD15 | Idle's lists (SD7; AC21) | Each fieldset (`IdleSection.tsx:140-163`) keeps its `aria-label`, legend and (i). Its checkboxes become one `Switch` per drink, labelled `drink.name`, in a wrapping grid (`grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr))` or equivalent). `toggle(list, id)` is unchanged, so the saved lists are byte-for-byte what the checkbox produced. **Confirm** (AC20 for Idle: "same x" holds per grid column) | A wrapping grid has several columns. AC20's "one x per section" can only mean per column there. |
| PD16 | The coverage test (AC10, AC11) | `web/src/app/pages/settingsCoverage.test.tsx`. Each control is listed as a pair: its role (checkbox and switch both counted as `toggle`) and its accessible name. The roles are textbox, spinbutton, combobox, switch or checkbox, button (including every "Uitleg: …"), table and the `h3` subsections. The section navigation, its select and "← Instellingen" are left out.<br>• **T5 captures the old page's list as a literal**, `OLD_CONTROLS`. It renders today's `SettingsPage` with the old test's live-run fixture (`SettingsPage.test.tsx:145-277`), with noise and demand on, and asserts that the literal matches.<br>• **The test then asserts** that the three screens' lists, joined, equal `OLD_CONTROLS` plus exactly the buttons B-12 adds: "Opslaan prijsstap" (PD9) and one more "Opslaan" (Betalen, PD10). Each pair appears on exactly one screen as often as on the old page.<br>• **It pins `explanations.json` byte for byte** by its sha256 at `e1da324`.<br>• **It checks that each "Uitleg: <naam>" button** sits in the same region as a control or column header named `<naam>`. | The spec says "a test lists them from the old `SettingsPage` test and `explanations.json`". Capturing before the old page is gone makes the list evidence, not memory. |
| PD17 | Old `/settings#…` links (SD14; AC7) | Nothing is translated. The landing has no element with a section id, so the browser scrolls nowhere. | SD14. |
| PD18 | Existing tests B-12 makes untrue | Each changes in the task that causes it:<br>• `SettingsPage.test.tsx`: its sections, icons and (i) counts move to `SettingsScreens.test.tsx` (T5), and the file becomes the landing's test (T6);<br>• `GlobalSection.test.tsx`: the B-07 dialog cases move to `PriceStepSection.test.tsx` (T7) and the payment cases to `PaymentSection.test.tsx` (T8);<br>• `WalletsSection.test.tsx` and `IdleSection.test.tsx`: checkbox becomes switch (T4);<br>• `HomePage.test.tsx:67-80`: the tile text (T6);<br>• `NavMenu.test.tsx`, `test_security.py:29-35`, `test_auth.py:70`, `test_static.py:108-133`: the new admin list (T1);<br>• 13 e2e specs: their `goto('/settings')` and their `section(...)` lookups (T12, T13).<br>Any **other** test that fails for a B-12 reason is a stop-and-ask. | Found by grepping `/settings`, `checkbox`, `Globale instellingen`, `Wallet verplicht` and `Prijsstap` in `src/` and `e2e/`. |

### Owner question — answered 2026-11-02: **B** (T11b is built; the owner also confirmed every **Confirm** row as written)

**OQ1 — Does a half-filled *create* form count as unsaved (SD9)?** The create forms are Nieuwe borrel's name, "Opslaan als profiel"'s name, "Drankje toevoegen", and "Nieuwe sleutel"'s label. Nothing of theirs is stored yet. SD9 says "typed values that differ from what is stored", and the exit condition says "never lose a half-typed value by leaving". The two readings differ on screen:
- **A** — they do not count. Leaving with a half-typed new drink drops it silently.
- **B (recommended)** — they count while any of their **text** fields holds typed text. Selects do not count (a select has no half-typed state). This is task T11b.

B satisfies both sentences of the spec. A satisfies only the first. If the audit answers A, T11b is dropped and nothing else changes.

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `app/api/security.py` | Modify | SD1, SD17: three addresses in `ROLE_ROUTES["admin"]` |
| `tests/unit/test_security.py` | Modify | AC1: the table |
| `tests/api/test_auth.py` | Modify | AC1: `allowed_routes` per role |
| `tests/api/test_static.py` | Modify | AC2: `SPA_ROUTES`, the reload of the four, `/settings/x` 404 |
| `web/src/components/ui/NavMenu.tsx` | Modify | PD5 |
| `web/src/components/ui/NavMenu.test.tsx` | Modify | AC4 |
| `web/src/main.tsx` | Modify | PD1 |
| `web/src/lib/unsavedEdits.tsx` | Create | PD2 |
| `web/src/lib/unsavedEdits.test.tsx` | Create | PD2 |
| `web/src/lib/useEditableRecord.ts` | Modify | PD2: reports `dirty` |
| `web/src/lib/useEditableRecord.test.ts` | Modify | PD2 |
| `web/src/app/LeaveGuard.tsx` | Create | PD3 |
| `web/src/app/LeaveGuard.test.tsx` | Create | AC23, AC24 (mechanism) |
| `web/src/app/routes.tsx` | Modify | PD2/PD3 in `ShellLayout` (T2); three screen routes (T5) |
| `web/src/features/auth/auth.test.tsx` | Modify | PD1's test router (T2, if needed); AC3 on the new paths (T5) |
| `web/src/components/ui/Switch.tsx`, `Switch.module.css` | Modify | PD14 |
| `web/src/components/ui/FormControls.test.tsx` | Modify | AC19, AC20 (unit) |
| `web/src/features/wallets/WalletsSection.tsx`, `.test.tsx` | Modify | AC19, AC21 (T4); PD4 (T11a) |
| `web/src/features/manipulation/IdleSection.tsx`, `.test.tsx`, its CSS module | Modify | PD15 |
| `web/src/noCheckbox.test.ts` | Create | AC19: the source scan |
| `web/src/app/pages/SettingsScreens.tsx` | Create | PD8: frame and the three section lists |
| `web/src/app/pages/SettingsScreens.test.tsx` | Create | AC8, AC9, AC22, AC23 (screen level), (i) counts |
| `web/src/app/pages/settingsCoverage.test.tsx` | Create | PD16 |
| `web/src/features/settings/SettingsLayout.tsx`, `settings.module.css` | Modify | PD8: the single-section rule |
| `web/src/app/pages/SettingsPage.tsx`, `SettingsPage.test.tsx`, `pages.module.css` | Modify | PD7: the landing |
| `web/src/features/home/HomePage.tsx`, `HomePage.test.tsx` | Modify | SD15: the home tile's line |
| `web/src/features/settings/PriceStepSection.tsx`, `.test.tsx` | Create | PD9 |
| `web/src/features/settings/PaymentSection.tsx`, `.test.tsx` | Create | PD10 |
| `web/src/features/settings/GlobalSection.tsx`, `.test.tsx` | Modify | PD9, PD10 (removals), PD11, PD12 |
| `web/src/features/settings/GlobalSection.module.css` | Create (if needed) | PD11's group styles, kept out of `settings.module.css` so T9 ∥ T10 |
| `web/src/features/settings/DemandSection.tsx`, `.test.tsx` | Modify | PD13 |
| `web/src/features/settings/index.ts` | Modify | exports for PD9, PD10, PD13 |
| `web/src/features/settings/ThemeEditor.tsx`, `.test.tsx` | Modify | PD4 |
| `web/src/features/settings/BorrelSection.tsx`, `ProfilesSection.tsx`, `DrinksSection.tsx` and their tests; `web/src/features/keys/KeysSection.tsx`, `.test.tsx` | Modify | OQ1 = B only (T11b) |
| `web/e2e/{admin,analytics,bounds,icons,offline,profiles,theme}.spec.ts` | Modify | T12: moved to the new addresses |
| `web/e2e/{auth,keys,payments,signup-koers,signup-qr,wallets}.spec.ts` | Modify | T13: moved; `signup-koers` checkbox → switch in T4 |
| `web/e2e/settings-screens.spec.ts` | Create | T14: the spec's Playwright flows 1–5, 7, 8 |
| `docs/design/frontend-architecture.md` | Modify | SD1: `:44`, `:64` |
| `docs/specs/phase-6-admin.md`, `phase-b-03-brownian-settings.md`, `phase-b-06-wallet-payments.md` | Modify | AC27: notes on SD25, SD5 and the two settings' placement |

---

## Tasks

### T1 — The three addresses on the server, and the menu that skips them
- **Implements:** AC1 (server), AC2, AC4. SD1, SD11, SD17, PD5.
- **Expected output:**
  - **The table.** `ROLE_ROUTES["admin"]` is `("/", "/koers", "/bar", "/manipulation", "/settings", "/settings/spel", "/settings/wallets", "/settings/beheer", "/analytics", "/kassa")`. The other three roles are unchanged.
  - **`NavMenu`** drops nested routes (PD5), and its header comment says so.
  - **Tests:**
    - `test_security.py`: the table;
    - `test_auth.py`: admin's `allowed_routes` holds the four, the others are exactly as before;
    - `test_static.py`: the four reload to `index.html`, `/settings/x` and `/settings/spel/x` are a plain 404, and the `SPA_ROUTES` equality includes the three;
    - `NavMenu.test.tsx`: given admin's new list, the menu shows "Instellingen" once and no `/settings/…` item.
  - Between T1 and T5 an admin opening a screen address sees "Geen toegang" (the client's `*` route). Nothing links there yet.
- **Verification:**
  - `uv run pytest tests/unit/test_security.py`;
  - `uv run pytest tests/api/test_auth.py tests/api/test_static.py` (with `.env.local` sourced; MEMORY: pytest api+integration split);
  - `pnpm -C web vitest run src/components/ui/NavMenu.test.tsx`.
- **Depends on:** —
- **Autonomy note:** The builder may lay out the tests. Stop and ask if the generated API types change (they should not: `allowed_routes` is `list[str]`), or if any route list other than admin's would change.

### T2 — The data router and the leave guard
- **Implements:** AC23, AC24 (the mechanism, on a test screen). SD9, SD18, PD1–PD3, PD6.
- **Expected output:**
  - **`main.tsx`** as PD1.
  - **The registry.** `lib/unsavedEdits.tsx` as PD2, and `useEditableRecord` calling `useReportUnsaved(dirty)`. Its header comment says so.
  - **The guard.** `app/LeaveGuard.tsx` as PD3. `ShellLayout` wraps its children in the provider, renders `LeaveGuard` once, and routes `onLogout` through `useConfirmLeave`.
  - **The test helper** for a data memory router (PD1).
  - `auth.test.tsx` is moved to it if any of its cases mounts a guarded path.
  - **`LeaveGuard.test.tsx`:** a test page reports dirty at `/settings/beheer`, with a link to `/settings`.
    - dirty, a link click: the dialog shows "Niet-opgeslagen wijzigingen weggooien?";
    - "Blijven" keeps the location and the page's state;
    - "Weggooien" goes;
    - dirty, a `router.navigate(-1)` (the back button) asks too;
    - a `#hash`-only change passes;
    - a navigation to `/login` passes;
    - clean, a link passes with no dialog;
    - the same dirty page at `/manipulation` passes (PD6);
    - Uitloggen asks while dirty and logs out at once while clean;
    - a dispatched `beforeunload` is `defaultPrevented` only while dirty on a guarded path.
  - **`unsavedEdits.test.tsx`:** register and unregister on unmount and on clean; a no-op without a provider.
  - **`useEditableRecord.test.ts`:** the record reports while dirty and stops after `save` or `reset`.
- **Verification:**
  - `pnpm -C web vitest run src/app/LeaveGuard.test.tsx src/lib/unsavedEdits.test.tsx src/lib/useEditableRecord.test.ts src/features/auth/auth.test.tsx src/app/AppShell.test.tsx`;
  - `pnpm -C web build` (types and the bundle).
- **Depends on:** —
- **Autonomy note:** The builder may name the hooks and choose the helper's location and the test page. **Stop and ask:**
  - if `useBlocker` does not see the descendant `<Routes>`' navigations under PD1's splat route;
  - if `react-router` 8 needs a future flag or the `react-router/dom` entry to do this;
  - if any other existing test breaks under the data router.
  That last one would mean PD1's cost is larger than planned.

### T3 — The new `Switch` row
- **Implements:** AC19, AC20 (the component). SD7, PD14.
- **Expected output:**
  - `Switch.tsx` and `Switch.module.css` as PD14, and the header comment says so.
  - **`FormControls.test.tsx`:**
    - `role="switch"`, `aria-checked` following `checked`;
    - the element is a native `<button type="button">`, so Space and Enter work, and a disabled one does not toggle;
    - its name is exactly `label`, with the (i) outside the name (B-01);
    - DOM order is label, (i), track;
    - a click on the label text toggles.
  - Every existing `getByRole('switch', { name })` test in `src/` still passes.
- **Verification:** `pnpm -C web vitest run src/components/ui/FormControls.test.tsx src/features/settings src/features/manipulation`.
- **Depends on:** —
- **Autonomy note:** The builder may choose `aria-labelledby` or `<label htmlFor>`, and the row width. Stop and ask if a switch's accessible name would have to change, or if the track's size would.

### T4 — The last two checkboxes become switches
- **Implements:** AC19, AC20 (Idle's rows), AC21. SD7, PD15.
- **Expected output:**
  - **"QR-code op het scherm"** is a `Switch` with that label (`WalletsSection.tsx:208-216`). It still calls `storeOnScreen(on)` at once, with no confirm, and is disabled while `busy`.
  - **Idle's lists** as PD15. Both header comments say so.
  - **`src/noCheckbox.test.ts`,** laid out as `noEmoji.test.ts`: no `type="checkbox"` and no `type: 'checkbox'` in any `.ts`/`.tsx` under `web/src` except itself. It has an anti-vacuity probe on a crafted string.
  - **Tests:**
    - `WalletsSection.test.tsx`: the toggle is a switch; one toggle sends one `PUT` and no dialog appears;
    - `IdleSection.test.tsx`: toggling Bier in "Verlagen" and saving sends `idle_targets` exactly as before; a clean save sends nothing.
  - **`e2e/signup-koers.spec.ts`:** its `checkbox` lookup becomes `switch`.
- **Verification:**
  - `pnpm -C web vitest run src/noCheckbox.test.ts src/features/wallets/WalletsSection.test.tsx src/features/manipulation/IdleSection.test.tsx`;
  - `pnpm -C web exec playwright test e2e/signup-koers.spec.ts`.
- **Depends on:** T3
- **Autonomy note:** The builder may choose the grid CSS. Stop and ask if Idle's saved lists would come out in a different order than the checkbox produced: the spec says "exactly".

### T5 — The three screens, with today's sections
- **Implements:** AC1 and AC3 (client), AC8 and AC9 (order and icons; the final contents land in T7, T8, T10), AC10 (the capture), AC22, AC23 (screen level). SD1, SD3, SD8, SD12, PD8, PD16.
- **Expected output:**
  - **`SettingsScreens.tsx`** exports `SpelopzetPage`, `WalletsScreenPage` and `BeheerPage` (names are the builder's), each a `SettingsScreen` over its list:
    - **Spelopzet:** Borrel, Profielen, Drankjes beheren (`cup`), **Prijzen** (`padlock`, today's `BoundsSection`), Vraag/Aanbod (today's whole `DemandSection`), Kleurenschema, Afbeeldingen;
    - **Mensen en wallets:** Wallets;
    - **Beheer:** Globale instellingen (today's whole `GlobalSection`), Toegangssleutels, Systeemacties.
  - **`routes.tsx`** adds the three paths to `PAGES`, so each is `guarded(path, …)`. The old `/settings` page still renders until T6.
  - **`SettingsLayout`** follows PD8's single-section rule.
  - **`SettingsScreens.test.tsx`** carries the old page test's cases per screen:
    - section order and headings, the icon before each name (none on Borrel), nav links and narrow select;
    - the (i) count per section;
    - "← Instellingen" goes to `/settings`;
    - a one-section list shows no nav (a test-only list);
    - a dirty Drukdrempel on Beheer, then "← Instellingen": the dialog appears, "Blijven" keeps "7", "Weggooien" lands on `/settings`;
    - a clean Beheer leaves without a dialog.
  - **`auth.test.tsx`:** display, bar and kassa at each of the three addresses see "Geen toegang", and the address does not change.
  - **`settingsCoverage.test.tsx`** as PD16: the literal captured and asserted against the old page, and the screens' joined list equal to it (no additions yet).
- **Verification:** `pnpm -C web vitest run src/app/pages src/features/auth/auth.test.tsx src/features/settings`.
- **Depends on:** T1 (the routes in `allowed_routes`), T2 (the guard; `routes.tsx`)
- **Autonomy note:** The builder may name the exports and lay out the tests. Stop and ask if the captured list of the old page holds a control whose label is not unique enough to pin it to one screen. That would make AC10's "exactly one screen" untestable as planned.

### T6 — `/settings` becomes the landing page
- **Implements:** AC5, AC6, AC7, AC25 (the tiles stack), AC27 (the home tile). SD2, SD10, SD14, SD15, PD7, PD17.
- **Expected output:**
  - **`SettingsPage.tsx`** as PD7, with its header comment rewritten. `pages.module.css` gains the tile styles.
  - **`HomePage.tsx`'s** Instellingen line is "Spelopzet, wallets en beheer."
  - **`settingsCoverage.test.tsx`** drops its old-page leg and keeps the literal.
  - **`SettingsPage.test.tsx`** is rewritten for the landing:
    - admin sees three tiles in SD3's order, each with SD15's line and its `href`;
    - a session whose `allowed_routes` holds one screen sees one tile;
    - the status line in all four states (live, draft, 404 `no_current_run`, a 500), and each tile still a link;
    - `/settings#borrel` renders the landing, `getElementById('borrel')` is `null` and `scrollIntoView` is not called;
    - no `textbox`, `spinbutton`, `switch` or `combobox` on the page.
  - **`HomePage.test.tsx`:** the new line.
- **Verification:** `pnpm -C web vitest run src/app/pages src/features/home/HomePage.test.tsx`.
- **Depends on:** T5
- **Autonomy note:** The builder may choose the tile markup within PD7. Stop and ask if `SettingsPage` would need anything from a feature beyond `useCurrentRun` (via `features/settings`' index) and `useSession` (via `features/auth`' index).

### T7 — Prijsstap moves to Prijzen
- **Implements:** AC8 (Prijzen), AC10 (kept), AC15. SD4, PD9.
- **Expected output:**
  - **`PriceStepSection`** as PD9.
  - **`GlobalSection`** loses `step_quant` from `FIELDS`, together with the dialog state, `validStep`, `BOUND_NAMES` and the `grid` import. Its header comment's B-07 paragraph moves to the new file.
  - **`index.ts`** exports it.
  - **Spelopzet's Prijzen** renders `<PriceStepSection />` then `<BoundsSection />`.
  - **`PriceStepSection.test.tsx`** takes `GlobalSection.test.tsx`'s B-07 cases verbatim:
    - the dialog text and list;
    - "Annuleren" sends nothing and keeps the input;
    - "Opslaan" sends one `PATCH` with `{params: {step_quant}}`;
    - no move sends with no dialog;
    - `bounds_collision` shows under Prijsstap.
    It adds a clean save ("Niets te wijzigen", no request).
  - **`GlobalSection.test.tsx`:** no Prijsstap field.
  - **`SettingsScreens.test.tsx`:** the (i) counts (Globale −1, Prijzen +1).
  - **`settingsCoverage.test.tsx`'s** allowed additions gain "Opslaan prijsstap".
- **Verification:** `pnpm -C web vitest run src/features/settings src/app/pages`.
- **Depends on:** T5, T6 (both T6 and T7 write `settingsCoverage.test.tsx`)
- **Autonomy note:** The builder may move code as it sees fit inside PD9. Stop and ask if any B-07 text or behaviour would change in the move. AC15 calls for B-07's AC "on its new screen", unchanged.

### T8 — Betalen on Mensen en wallets
- **Implements:** AC9 (Mensen en wallets), AC10 (kept), AC16. SD3, SD13, PD10.
- **Expected output:**
  - **`PaymentSection`** as PD10.
  - **`GlobalSection`** loses `wallet_required` and `credit_limit_cents` from its record, its body and its JSX. Its header comment's B-06 paragraph moves.
  - **`index.ts`** exports it.
  - **Mensen en wallets** lists Betalen (no icon, SD12) then Wallets.
  - **`PaymentSection.test.tsx`:**
    - toggling "Wallet verplicht" sends `{wallet_required: false}` at the top level and nothing under `params`;
    - "Rood staan tot" 2,50 sends `{credit_limit_cents: 250}`;
    - a clean save sends nothing;
    - a 422 on `credit_limit_cents` shows under the field;
    - a server change while dirty offers "Overnemen".
  - **`GlobalSection.test.tsx`:** neither field is shown, and a save never carries them.
  - **`SettingsScreens.test.tsx`:** Mensen en wallets shows two sections and `MobileSectionNav`; Globale's count is −2 and Betalen's is 2.
  - **`settingsCoverage.test.tsx`'s** additions gain Betalen's "Opslaan".
- **Verification:** `pnpm -C web vitest run src/features/settings src/app/pages`.
- **Depends on:** T7 (both write `GlobalSection.tsx`, `index.ts`, `SettingsScreens.tsx`)
- **Autonomy note:** The builder may lay out the form. Stop and ask if B-06's server validation of the two columns would show differently than it did in Globale instellingen.

### T9 — Globale instellingen in three groups, the noise fields hidden while off
- **Implements:** AC12, AC13, AC14. SD5, SD6, PD11, PD12.
- **Expected output:**
  - **`GlobalSection`** as PD11 and PD12. Its header comment replaces B-03's "disables none of them" with SD6.
  - **`GlobalSection.test.tsx`:**
    - the three groups with 7, 1 + 5 and 2 controls, in order, and one "Opslaan instellingen";
    - the body splits as today (`params`, `candle_interval_s` at the top level); a clean save gives "Niets te wijzigen" and no request; the conflict prompt once;
    - with the switch off the five fields are absent, with it on present;
    - edit Sterkte ruis, switch off, save: the body holds `bm_sigma_y` and `bm_enabled: false`;
    - empty Sterkte ruis, switch off, save: no request, and PD12's sentence naming "Sterkte ruis".
- **Verification:** `pnpm -C web vitest run src/features/settings/GlobalSection.test.tsx src/app/pages/settingsCoverage.test.tsx` (the coverage fixture has noise on, so the list is unchanged).
- **Depends on:** T8
- **Autonomy note:** The builder may style the groups in a new `GlobalSection.module.css`. It must not edit `settings.module.css`, which T10 may write in the same group. Stop and ask if hiding the fields would need `useEditableRecord` to change.

### T10 — Vraag/Aanbod split between Beheer and Spelopzet
- **Implements:** AC8 and AC9 (Vraag/Aanbod's two places), AC10 (kept), AC17, AC18, AC20 (two stacked switches). SD3, SD16, PD13.
- **Expected output:**
  - **`DemandSection.tsx`** as PD13, with its header comment rewritten. `index.ts` exports the two components and drops `DemandSection`.
  - **The screens:** Beheer lists Globale instellingen, Vraag/Aanbod (`chart`, `DemandSwitches`), Toegangssleutels, Systeemacties. Spelopzet's Vraag/Aanbod renders `DemandTable`.
  - **`DemandSection.test.tsx`:**
    - switches: toggling one sends `{params: {demand_enabled}}` only;
    - table, on: a clean save sends nothing; an empty cell blocks with D-03's message;
    - table, off: only the sentence, and no link or anchor inside the region;
    - **live:** with an edited cell, a store `params` change to `demand_enabled: false` (the `config` message's effect, as `useCurrentRun.test.tsx` drives it) hides the table, and `useHasUnsaved()` turns false. Switching it back on shows the server's values, not the edit.
  - **`SettingsScreens.test.tsx`:** both screens' final order and (i) counts (Beheer Vraag/Aanbod 2, Spelopzet Vraag/Aanbod 4).
- **Verification:** `pnpm -C web vitest run src/features/settings src/app/pages`.
- **Depends on:** T6 (the old page, which imported `DemandSection`, is gone), T8 (`index.ts`, `SettingsScreens.tsx`)
- **Autonomy note:** The builder may keep both components in one file or split it. Stop and ask if the live hide needs a refetch path other than `useCurrentRun`'s `params` dependency.

### T11a — The guard counts the Wallets and theme forms
- **Implements:** AC23, AC24 (the two forms with stored values outside `useEditableRecord`). SD9, PD4.
- **Expected output:**
  - **`WalletsSection`** reports while the code, days or months field differs from `settings`.
  - **`ThemeEditor`** reports while its draft differs from the active theme.
  - **Tests:** inside an `UnsavedEditsProvider`, typing makes `useHasUnsaved()` true, and saving or typing the stored value back makes it false.
- **Verification:** `pnpm -C web vitest run src/features/wallets/WalletsSection.test.tsx src/features/settings/ThemeEditor.test.tsx`.
- **Depends on:** T2, T4 (`WalletsSection.tsx`)
- **Autonomy note:** The builder may decide how "differs" is computed (trimmed or not, for the code). Stop and ask if the theme editor has no clear "stored" value to compare against.

### T11b — The guard counts half-filled create forms *(OQ1 = B, answered)*
- **Implements:** AC23 under OQ1 = B; the exit condition's "never lose a half-typed value". SD9.
- **Expected output:**
  - **The four create forms** report while any of their text fields is non-empty: `BorrelSection`'s name, `ProfilesSection`'s profile name, `DrinksSection`'s add form (name and the three money fields) and `KeysSection`'s label.
  - Selects do not count.
  - After a successful create the form is empty again, so it stops reporting.
  - **Tests:** one per file, as T11a's.
- **Verification:** `pnpm -C web vitest run src/features/settings/BorrelSection.test.tsx src/features/settings/ProfilesSection.test.tsx src/features/settings/DrinksSection.test.tsx src/features/keys/KeysSection.test.tsx`.
- **Depends on:** T2
- **Autonomy note:** OQ1 is answered B, so this task is built. The builder may decide what "text field" means for a money field (non-empty input).

### T12 — The e2e specs move to the new addresses (Spelopzet and Beheer flows)
- **Implements:** AC27 (the moved specs); keeps the existing flows' evidence for AC8, AC9, AC12, AC15.
- **Expected output:** `admin`, `analytics`, `bounds`, `icons`, `offline`, `profiles` and `theme`:
  - each `goto('/settings')` becomes the screen that holds the section it uses;
  - Prijsstap is looked up under Prijzen, and the noise and Kaarsbreedte under Beheer;
  - a flow that crosses screens goes through the landing, or saves before `goto`, so no `beforeunload` prompt stalls it (R4);
  - `icons.spec.ts`' route list gains the three screens, each checked like `/settings`.
  - Assertions are kept, not weakened.
- **Verification:** `pnpm -C web exec playwright test e2e/admin.spec.ts e2e/analytics.spec.ts e2e/bounds.spec.ts e2e/icons.spec.ts e2e/offline.spec.ts e2e/profiles.spec.ts e2e/theme.spec.ts`.
- **Depends on:** T4, T6, T9, T10, T11a (T11b if built)
- **Autonomy note:** The builder may choose how each flow reaches its screen. Stop and ask if a flow must drop an assertion to pass.

### T13 — The e2e specs move to the new addresses (Wallets, keys, auth)
- **Implements:** AC3 (`auth.spec`), AC16 (flow 6, in `payments.spec`), AC27.
- **Expected output:** `auth`, `keys`, `payments`, `signup-koers`, `signup-qr` and `wallets` moved as T12's:
  - `payments.spec.ts` sets "Wallet verplicht" and "Rood staan tot" under Mensen en wallets › Betalen and sees them at the bar (flow 6);
  - `auth.spec.ts` keeps display at `/settings` and adds display at `/settings/beheer`: "Geen toegang", address unchanged.
- **Verification:** `pnpm -C web exec playwright test e2e/auth.spec.ts e2e/keys.spec.ts e2e/payments.spec.ts e2e/signup-koers.spec.ts e2e/signup-qr.spec.ts e2e/wallets.spec.ts`.
- **Depends on:** T4, T6, T9, T10, T11a (T11b if built)
- **Autonomy note:** As T12.

### T14 — The B-12 flows in the browser, and the gate
- **Implements:** AC3, AC4–AC6, AC14, AC15, AC17, AC20, AC21, AC23–AC25 end to end (the spec's flows 1–5, 7, 8); AC19's keyboard; AC26.
- **Expected output:** `web/e2e/settings-screens.spec.ts`, laid out as `profiles.spec.ts` (its own server, serial):
  1. Admin opens `/settings`: three tiles, the status line, and "Instellingen" once in the open menu.
  2. Beheer: Drukdrempel changed, "← Instellingen": the dialog; "Blijven" keeps the value; save; leave with no dialog. Then dirty again, `page.goBack()` from a screen reached via the landing: the dialog.
  3. Beheer: Willekeurige ruis off and on, and the five fields go and come.
  4. Beheer: "Verwachte verkoop meetellen" off and saved, then Spelopzet shows the sentence. On again: the table, and "Opslaan coëfficiënten" with no edit sends no `PATCH` (watched with `page.on('request')`).
  5. Spelopzet: a Prijsstap that moves a bound; the confirm lists it; "Opslaan" stores it (a reload shows it).
  7. `/manipulation`: toggle a drink in Idle's "Verlagen" with Space, then save; a reload shows it on.
  8. A display key at `/settings/beheer` sees "Geen toegang".
  - **At 375 px:** the landing's tiles share one x and stack, and `scrollWidth ≤ 375` on the landing and the three screens.
  - **At 1280 px:** the two switch tracks of Beheer's Vraag/Aanbod share one x, and in Idle's lists the tracks of each grid column share one x.
  - One switch is toggled with Enter.
- **Verification:**
  - `pnpm -C web exec playwright test e2e/settings-screens.spec.ts`;
  - `./scripts/check.sh` (13/13, output pasted);
  - `git diff --stat main -- exchange/ tests/engine/golden/fixtures/ db/migrations/versions/ web/package.json pyproject.toml` empty (AC26);
  - `git diff main -- web/src/api/generated/` empty;
  - `git diff main -- web/src/features/settings/explanations.json` empty.
- **Depends on:** T12, T13 (the gate runs over the whole branch)
- **Autonomy note:** The builder may choose selectors and the order of flows. Stop and ask if a flow needs a server change. The diff check proves `exchange/` is untouched, so `golden_linux.sh` and `engine-guardian` are not required (spec, Verification).

### T15 — The documents
- **Implements:** AC27 (design and spec notes). SD1.
- **Expected output:**
  - **`frontend-architecture.md`:**
    - `:44`: "the Wallets section on /settings" becomes "the Mensen en wallets screen, `/settings/wallets`";
    - `:64`: the route sentence names the six v1 paths, and that *B-12* adds `/settings/spel`, `/settings/wallets` and `/settings/beheer` under the `/settings` landing.
  - **`phase-6-admin.md`:** after SD25 (`:357`), a note that the sections now live on three screens (B-12 SD3).
  - **`phase-b-03-brownian-settings.md`:** after SD5 (`:83`), a note that B-12 SD6 hides the five while off.
  - **`phase-b-06-wallet-payments.md`:** at `:63`, `:277` and `:325`, a note that the two settings are in Betalen on `/settings/wallets` (B-12 SD3).
  - Each note links the B-12 spec.
- **Verification:** `uv run pytest tests/unit/test_setting_explanations_text.py` (it parses the B-03 spec and must read it unchanged).
- **Depends on:** —
- **Autonomy note:** The builder may word the notes. It must put no note between a `**E<n> — …**` row and its `> ` lines in the B-03 spec. The parser expects them adjacent. Stop and ask if a note would seem to change any decision rather than point to B-12.

---

## AC coverage

| AC | Tasks |
|---|---|
| AC1 | T1, T5 |
| AC2 | T1 |
| AC3 | T5, T13, T14 |
| AC4 | T1, T14 |
| AC5 | T6, T14 |
| AC6 | T6, T14 |
| AC7 | T6 |
| AC8 | T5, T7, T10, T12 |
| AC9 | T5, T8, T10 |
| AC10 | T5, T6, T7, T8, T10 |
| AC11 | T5 (PD16), T14 |
| AC12 | T9, T12 |
| AC13 | T9 |
| AC14 | T9, T14 |
| AC15 | T7, T12, T14 |
| AC16 | T8, T13 |
| AC17 | T10, T14 |
| AC18 | T10 |
| AC19 | T3, T4, T14 |
| AC20 | T3, T4, T10, T14 |
| AC21 | T4, T14 |
| AC22 | T5 |
| AC23 | T2, T5, T11a, T11b, T14 |
| AC24 | T2, T5, T11a, T14 |
| AC25 | T6, T14 |
| AC26 | T14 |
| AC27 | T6, T12, T13, T15 |

---

## Task graph

```
T1 ──┐
T2 ──┴── T5 ── T6 ── T7 ── T8 ──┬── T9 ───┐
                                └── T10 ──┤
T3 ── T4 ─────────────────────────────────┼── T12 ──┐
T2, T4 ── T11a ───────────────────────────┤         ├── T14
T2 ── T11b (OQ1 = B) ─────────────────────┴── T13 ──┘
T15
```

The settings chain T5 → T8 is serial on purpose. Each step writes `SettingsScreens.tsx` and either `GlobalSection.tsx` or the coverage test, so no two of them can share a group.

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T2, T3, T15 | T1: `app/api/security.py`, `tests/unit/test_security.py`, `tests/api/test_{auth,static}.py`, `web/src/components/ui/NavMenu{.tsx,.test.tsx}` · T2: `web/src/main.tsx`, `web/src/lib/{unsavedEdits.tsx,unsavedEdits.test.tsx,useEditableRecord.ts,useEditableRecord.test.ts}`, `web/src/app/{LeaveGuard.tsx,LeaveGuard.test.tsx,routes.tsx}`, `web/src/features/auth/auth.test.tsx`, the test helper · T3: `web/src/components/ui/{Switch.tsx,Switch.module.css,FormControls.test.tsx}` · T15: `docs/design/frontend-architecture.md`, `docs/specs/phase-{6-admin,b-03-brownian-settings,b-06-wallet-payments}.md` |
| G2 | T4, T5, T11b | T4: `web/src/features/wallets/WalletsSection{.tsx,.test.tsx}`, `web/src/features/manipulation/IdleSection{.tsx,.test.tsx}` and its CSS, `web/src/noCheckbox.test.ts`, `web/e2e/signup-koers.spec.ts` · T5: `web/src/app/pages/{SettingsScreens.tsx,SettingsScreens.test.tsx,settingsCoverage.test.tsx}`, `web/src/app/routes.tsx`, `web/src/features/settings/{SettingsLayout.tsx,settings.module.css}`, `web/src/features/auth/auth.test.tsx` · T11b: `web/src/features/settings/{BorrelSection,ProfilesSection,DrinksSection}{.tsx,.test.tsx}`, `web/src/features/keys/KeysSection{.tsx,.test.tsx}` |
| G3 | T6, T11a | T6: `web/src/app/pages/{SettingsPage.tsx,SettingsPage.test.tsx,pages.module.css,settingsCoverage.test.tsx}`, `web/src/features/home/HomePage{.tsx,.test.tsx}` · T11a: `web/src/features/wallets/WalletsSection{.tsx,.test.tsx}`, `web/src/features/settings/ThemeEditor{.tsx,.test.tsx}` |
| G4 | T7 | `web/src/features/settings/{PriceStepSection.tsx,PriceStepSection.test.tsx,GlobalSection.tsx,GlobalSection.test.tsx,index.ts}`, `web/src/app/pages/{SettingsScreens.tsx,SettingsScreens.test.tsx,settingsCoverage.test.tsx}` |
| G5 | T8 | `web/src/features/settings/{PaymentSection.tsx,PaymentSection.test.tsx,GlobalSection.tsx,GlobalSection.test.tsx,index.ts}`, `web/src/app/pages/{SettingsScreens.tsx,SettingsScreens.test.tsx,settingsCoverage.test.tsx}` |
| G6 | T9, T10 | T9: `web/src/features/settings/{GlobalSection.tsx,GlobalSection.test.tsx,GlobalSection.module.css}` · T10: `web/src/features/settings/{DemandSection.tsx,DemandSection.test.tsx,index.ts,settings.module.css}`, `web/src/app/pages/{SettingsScreens.tsx,SettingsScreens.test.tsx}` |
| G7 | T12, T13 | T12: `web/e2e/{admin,analytics,bounds,icons,offline,profiles,theme}.spec.ts` · T13: `web/e2e/{auth,keys,payments,signup-koers,signup-qr,wallets}.spec.ts` |
| G8 | T14 | `web/e2e/settings-screens.spec.ts` |

No two tasks in one group write the same file:
- `routes.tsx` and `auth.test.tsx` are T2 (G1) then T5 (G2).
- `settingsCoverage.test.tsx` is T5 (G2), T6 (G3), T7 (G4), then T8 (G5).
- `WalletsSection.tsx` is T4 (G2) then T11a (G3).
- `GlobalSection.tsx` and `index.ts` are T7 (G4), T8 (G5), then T9 or T10 (G6). T9 does not touch `index.ts`.
- `SettingsScreens.tsx` is T5, T7, T8, then T10. T9 does not touch it.
- `settings.module.css` is T5 (G2) then T10 (G6). T9 uses its own module.
- `signup-koers.spec.ts` is T4 (G2) then T13 (G7).

---

## Data changes

None (spec, Out of scope). No migration, no endpoint, no request or response body. The generated API types do not change (AC26, checked in T14).

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **The data router changes how every page mounts** (PD1). A test or a page that relied on `BrowserRouter`-only behaviour could break, and `useBlocker` throws in any test that mounts a screen inside a plain `MemoryRouter`. | Only `main.tsx` mounts the real router. T2 runs the auth, shell and page tests under it, and its autonomy note stops on any unplanned break. A memory data-router helper is part of T2. |
| R2 | **`useBlocker` and the hash links.** A click on `<a href="#borrel">` fires `popstate`, which the router treats as a POP. | PD3 blocks on a pathname change only. T2 tests a hash-only change, and T14 clicks a section link on a dirty screen with no dialog (flow 2, after the edit). |
| R3 | **SD16's live hide reaches another session only on a live run.** A draft write broadcasts nothing (Phase 6 SD7; `useCurrentRun.ts:30-34`). On a draft, another session's open Spelopzet shows the change at its next fetch, not at once. AC18 is met on a live run. **Confirm** | The spec names "the `config` message" as the path, and that message exists only live. In one tab, a draft change in Beheer is seen when Spelopzet next mounts. Adding a draft broadcast would be a server change, out of scope. |
| R4 | **e2e and `beforeunload`.** Chromium prompts on `page.goto` after a real input on a dirty screen, and Playwright dismisses dialogs by default, which cancels the navigation and stalls the test. | T12 and T13 save before any `goto`, or cross screens through the landing. T14 asserts the prompt on purpose with `page.on('dialog')`. |
| R5 | **Uitloggen now asks while dirty** (PD3). That is a change on the header menu. | SD9 names the header menu. A 401 still leaves without asking (`/login` exempt), so a dead session cannot trap anyone. |
| R6 | **"Weggooien" is the dialog's confirm**, which `ConfirmDialog` focuses first (`ConfirmDialog.tsx:62-63`), so Enter discards. | Escape and the backdrop-safe "Blijven" stay one key away. This matches every other destructive dialog in the app, and changing `ConfirmDialog` is out of scope. Flagged for the owner's visual check. |
| R7 | **AC10's literal is captured from a fixture.** A control that renders only in another state, such as the draft-only "Live zetten", "Profiel laden" or the closed-code text, is not in it. | The fixture is the old page test's live run with two drinks. The draft-only controls are covered by their own section tests, which T5–T10 do not change. The audit may ask for a second, draft fixture. |
| R8 | **AC20's "same x per section" for Idle's wrapping grid** (PD15). | Read per column, and T14 measures it so. Confirm at audit. |
| R9 | **Thirteen e2e specs change** (T12, T13). A stale selector can fail far from its cause. | They are split by screen into two parallel tasks, each with its own Playwright run, before the new spec and the gate. |
| R10 | **`frontend-architecture.md:64`** is a design document. Its change is approved in the spec, but CLAUDE.md lists any change in `docs/design/` as an owner stop. | The spec records the owner's approval (SD1, In scope). T15 makes only the two named edits. |

---

## Out of scope for this plan

Everything in the spec's Out of scope, and also:
- **A page title (`h1`) per screen.** The spec names none, and the old page had none. The landing's tiles and each screen's sections name where one is.
- **Guarding `/manipulation`'s Idle form, or any page outside the three screens** (PD6).
- **A draft-run broadcast for SD16** (R3): a server change.
- **Changing `ConfirmDialog`'s focus order** (R6).
- **Committing the spec, this plan and the backlog change**, now uncommitted on `docs/backlog-settings-groups`. That is the owner's branch choice before `/build`, not a task.

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

Audit notes (2026-11-02, owner accepted every line):
- `react-router` ^8.4.0 is already a dependency and exports `useBlocker`; `BrowserRouter` is mounted only in `web/src/main.tsx`.
- T2 touches about 11 files (over the 10-file guide; source lines are within the limit, tests excluded). Accepted as one task: the files are one mechanism.
- T4 (8 files), T5 (about 7 plus the coverage test), T12 (7 specs) and T13 (6 specs) are near the guide. Accepted.
- AC2, AC13, AC18, AC22 and AC26 each rest on a single task. Accepted.
- R3, R6, R7 and R8 are accepted as written. PD3 (Uitloggen asks while a screen is dirty) is accepted.

Audited by: Martijn Boot (owner)  Date: 2026-11-02
