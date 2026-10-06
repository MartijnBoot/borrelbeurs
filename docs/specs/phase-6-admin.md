# Spec: Phase 6 — Manipulation, settings and the admin hub

Status: Approved · Depends on: Phase 5 · Fixes: D-02, D-03, D-04, D-19, D-26, D-29, D-44, D-45,
D-46, D-47, D-48

## Problem

The admin surface is the most destructive part of the app, and it carries v1's most dangerous
defect. Phase 6 comes last on purpose: by now the read-only board (Phase 4) and the money path
(Phase 5) have proven the stack.

**Forms that destroy what they were not asked to change.**

- **Demand/supply form (D-03).** It renders `a/d/s0/c` as `placeholder`, not `value`
  (`legacy/v1/static/settings.html:668-671`), and parses with `+el(...).value`. Since
  `+"" === 0` is not `NaN`, **save without editing writes 0 to all four coefficients of every
  drink** (`settings.html:678-680`). The live v1 config shows it already happened: every `a`,
  `d`, `s0` and `c` in `legacy/v1/config/exchange_config.json` is `0.0`.
- **Add-drink form (D-04).** Same pattern (`settings.html:712-715`), so the server defaults
  `a=10, d=0.6, s0=8, c=0.4` never apply. An empty bar price also arrives as 0.
- **Price-jump form (D-46).** Same pattern: an empty "Doelprijs" sends 0 and jumps the drink
  to `p_min` (`legacy/v1/static/manipulation.html:348-351`).

**Drink changes reset the market.** `POST /drinks` rebuilds the whole `ExchangeState`
(`legacy/v1/backend/api.py:635-686`; the register's `:599-643` predates the ADR 0007 hotfix).
Adding one drink mid-borrel resets every price to `p0` and wipes history, totals, revenue and
running jumps for all drinks (D-02).

**Config is writable by the wrong role and moves prices it should hold.**

- `POST /config` is `require_role("bar", "admin")` (`api.py:404`). Only the `/settings`
  *page* is admin-gated, so a bar key can rewrite every bound, coefficient and engine scalar
  (D-44).
- `/config` mutates `p_min`/`p_max` first (`api.py:409-419`), then calls
  `retarget_y_to_hold_quantized_prices` (`api.py:453`). The retarget therefore reads the old
  `y` against the new bounds and **rescales every price** instead of holding it. It also runs
  on *every* save, so even an idle-only save snaps `y` to the grid and discards sub-tick drift
  (D-45).

**Theme and uploads.**

- The theme editor exposes 13 of the theme's tokens (`settings.html:428-442`), so custom
  themes look half-applied (D-19).
- Uploads accept `.svg` and serve it from the session's origin (`api.py:246`, `:258-260`):
  stored XSS (D-29).
- The 5 MB limit is checked only after `await file.read()` has buffered the whole body
  (`api.py:254-256`; D-47).
- The image→slot mapping lives in the admin's `localStorage['theme-images']`
  (`legacy/v1/static/theme.js:150,215`), so **the big screen never shows the uploaded logo,
  background or promo tile** (D-48).

**The home page throws.** `home.html`'s health strip queries `#wsDot`, `#apiDot` and others,
none of which exist (`legacy/v1/static/home.html:110-151`). Every load throws uncaught (D-26).

**What v2 has today.**

- **Server routes.** News (`app/api/news.py`), jumps and market events (`app/api/market.py`,
  bar and admin), shutdown (`app/api/admin.py`), and a preset-only `PUT /api/theme`
  (`app/api/theme.py:260-285`).
- **No config, drinks, asset or key routes.** The holder has no config command
  (`app/runtime/holder.py:127`). Nothing in `app/` writes `drink.removed_at`
  (`app/db/runs.py:8-9`). There is no `asset` table.
- **Fixed drink set.** The engine has no active mask (`exchange/spec.py:94-123`).
- **A latent boot failure.** Soft-deleting a drink row today would brick the next boot:
  `rehydrate` builds the drink set from active rows, but `decode_state` demands that the
  stored keys equal that set exactly (`app/db/codec.py:291-330`).
- **No way to start a borrel from scratch.** Run creation is `import_v1`-only. Go-live is
  CLI-only, refused while the app runs, and effective at the next boot
  (`app/cli/runs.py:124-163`). The empty holder refuses every mutation
  (`holder.py:325-326`). This phase's exit condition is unreachable without bringing part of
  the run lifecycle forward.
- **Web.** `/` and `/manipulation` are placeholders (`web/src/app/routes.tsx:23-29`), and
  `/settings` holds only the preset picker.
- **Deferred to this phase by earlier specs:**
  - the `config` message (`docs/design/realtime-protocol.md:55`);
  - candle-interval edits (Phase 4 SD3);
  - the key UI and closing revoked sockets (Phase 3 spec :76, :301);
  - theme images and the `has-promo` layout (Phase 4 SD2);
  - drinks changing while `/bar` is open (Phase 5 out of scope).

## Decisions

Settled at the spec interview (2026-10-06).

- **SD1 was put to the human with a recommendation, and they chose it (B).** They then
  delegated every later question ("implement the recommended option for all further
  questions").
- **Every SD below records the recommendation taken.** The planner must not reopen them. The
  human may overrule any of them at spec approval.

**Run lifecycle slice**

- **SD1 — Phase 6 brings forward run creation and in-process go-live.**
  - **In this phase:** "Nieuwe borrel" creates an empty draft. Drinks and settings are
    editable on the draft. "Live zetten" makes it live inside the running process, with no
    restart: the holder moves from empty to live, and the ticker starts stepping it.
  - **Stays in Phase 7:** closing a run, reset within a run, switching between runs, and the
    run list. Phase 7's spec gets a note that create and go-live now exist, as Phase 5 did
    for the earnings series.
  - **The cost:** an ADR 0003 addendum. The single writer can now start its clock mid-process
    rather than only at boot.
- **SD2 — A run has a name, and at most one draft exists.**
  - `run` gains `name` (text, 1–100 characters after trim, required). `import_v1` sets it
    from the config file's stem.
  - **`POST /api/runs {name}` (admin) creates a draft.**
    - `params` are copied from the most recently created run; with none, from `Params()`'s
      defaults.
    - No drinks. A random `run_seed`. `tick_interval_ms` 1000, `candle_interval_ms` 60 000,
      `quote_grace_versions` 2.
  - **It refuses:**
    - with 409 `live_run_exists` while a run is live;
    - with 409 `draft_exists` while a draft exists. The UI then opens that draft.
- **SD3 — `POST /api/runs/{run_id}/go-live` (admin) makes a draft live in-process.**
  - **Confirmation:** "'{name}' live zetten?" in a `ConfirmDialog`.
  - **It refuses:**
    - without an active drink, with 409 `run_not_ready`;
    - for a non-draft run, with 409 `run_not_draft`;
    - while another run is live, with 409 `live_run_exists`.
  - **With `auto_calibrate_s0` set,** go-live anchors `s0` on the initial prices and writes
    each `drink.s0` and one config revision in the same transaction. This replaces today's
    `RunNotReady` refusal (`app/db/runs.py:188`).
  - **After the commit,** under the state lock:
    - the holder loads the run through the same rehydrate path boot uses;
    - the ticker adopts the run's `tick_interval_ms`;
    - the hub adopts the run's replay window;
    - every connected client receives the new run's `snapshot` without a reload.
  - `app.cli.runs go-live` remains for when the app is down.
- **SD4 — `/settings` edits "the current run".** That is the live run if there is one, else
  the draft. With neither, the page shows "Geen borrel" and a "Nieuwe borrel" form (name
  only). The "Borrel" section shows the name and status, plus "Live zetten" for a draft.

**Config writes**

- **SD5 — The API is resource-shaped, partial and admin-only.** Every route is keyed by
  `run_id` and works on a draft or the live run. An ended run is 409 `run_ended`.
  - **`GET /api/runs/{run_id}/config`** returns:
    - `revision`;
    - `run{run_id, name, status, candle_interval_s}`;
    - `params` (SD8's fields);
    - `drinks[{drink_id, slot, name, active, p_min_cents, p0_cents, p_max_cents,
      bar_price_cents, a, d, s0, c}]`, in slot order.
  - **`PATCH /api/runs/{run_id}/config`** `{name?, candle_interval_s?, params?: {field: value}}`.
    - Only keys present change.
    - An explicit `null` for any field is 422 with that field named. No field here is
      nullable; nothing is defaulted.
    - **An empty body, or one whose every key is absent, changes nothing.** It returns 200
      with the current revision and writes no revision.
  - **`POST /api/runs/{run_id}/drinks`**
    `{name, p_min_cents, p0_cents, p_max_cents, bar_price_cents?, a?, d?, s0?, c?}`.
    An absent optional field takes the server default: `bar_price_cents = p0_cents`, `a = 10`,
    `d = 0.6`, `s0 = 8`, `c = 0.4`.
  - **`PATCH /api/runs/{run_id}/drinks/{drink_id}`** takes any subset of `name`, the three
    bounds, `bar_price_cents` and `a/d/s0/c`, with `PATCH config`'s rules.
  - **`DELETE /api/runs/{run_id}/drinks/{drink_id}`** removes the drink (SD13).
  - **`POST /api/runs/{run_id}/anchor-s0`** (live run only) is v1's "📌 Zet huidige prijs als
    evenwicht" (`settings.html:184`). It runs `anchor_s0_to_current_y` over active drinks
    and writes every active drink's `s0`.
  - **Money is integer cents on the wire.** UI euro fields accept "2,50" or "2.50" and parse
    to integer cents exactly. More than two decimals is invalid in the field and is never
    rounded.
- **SD6 — Concurrency is last-writer-wins per field; the revision log is history.**
  - No `base_revision` is required. A PATCH carries only the fields its author changed, so
    two admins collide only on the same field.
  - `run.params` and the `drink` rows are the authority.
  - Every write that changes something appends one `run_config_revision`. It holds the full
    config after the write, `author` = the session key's label, and the next revision number,
    allocated under a row lock on `run` (no `max+1` race).
  - Every such write returns the new revision.
- **SD7 — A live config write is one engine transition.**
  - It runs inside `holder.mutate`, so the state lock is held, and commits in one
    transaction:
    - the row changes;
    - the revision;
    - the `engine_state` compare-and-set;
    - a `price_tick` with the new `source = 'config'` (an expand-only migration widens the
      CHECK).
  - `version` +1.
  - **A draft write** is a plain transaction with no holder, no transition and no broadcast.
- **SD8 — Editable params are v1's UI set, with server-side ranges.** Every value must be
  finite; NaN and ±∞ are 422.

  | Field | Label (v1) | Range |
  |---|---|---|
  | `step_quant` | 🧱 Tickgrootte | positive multiple of 0.01, ≤ 5 |
  | `eta` | ⚡ Snelheid | ≥ 0 |
  | `K` | 🎚️ Drempel | > 0 |
  | `lambda_orders` | ⚔️ Rivaliteit | ≥ 0 |
  | `alpha_price` | 🧭 Aantrekking naar gemiddelde | ≥ 0 |
  | `phi_persist` | 📈 Na-ijlen | ≥ 0 |
  | `decay_rho` | 🧠 Geheugen (ρ) | 0–1 |
  | `history_window_minutes` | 🗂️ Historie (min) | 1–240 |
  | `refresh_minutes` | 🔁 Update-interval (min) | 0.1–10 |
  | `idle_decay_minutes`, `idle_rise_minutes` | 🕒 Idle-decay / Idle-rise (min) | ≥ 0.5 |
  | `idle_strength`, `idle_rise_strength` | ⬇️ Decay-sterkte / ⬆️ Rise-sterkte | ≥ 0 |
  | `idle_targets`, `idle_rise_targets` | Decay / Rise targets | active `drink_id`s (SD11) |
  | `demand_enabled` | Vraag/aanbod actief | bool |
  | `auto_calibrate_s0` | Evenwicht, s0, auto-kalibreren bij init/reset | bool |

  - `candle_interval_s` (🕯️ Kaarseninterval (sec)) is 5–3600 and a multiple of 5 (SD10).
  - Per drink:
    - `p_min_cents ≥ 0` and `p_min_cents < p0_cents < p_max_cents`, checked on the
      *resulting* row;
    - `bar_price_cents ≥ 0`;
    - `a/d/s0/c` finite;
    - `name` 1–40 characters after trim.
  - **Not editable:** `bm_*`, `flow_vol_amp`, `flow_beta`, `y_clip`, `tick_interval_ms` and
    `quote_grace_versions` stay as imported or created. The API rejects them with 422.
- **SD9 — What a live change does to prices (D-45).**
  - **A scalar param, `a/d/s0/c`, `p0` or `bar_price`:** no price moves. The change takes
    effect at the next step. `p0` matters to the "correction" event; `bar_price` matters to
    Phase 7's reporting.
  - **A drink's `p_min`/`p_max`, or `step_quant`, holds every affected quoted price:**
    1. compute `p_q` under the *old* spec;
    2. clamp it into the new `[p_min, p_max]`;
    3. re-quantise it on the new grid;
    4. refit `y` to the new spec.

    A running jump on an affected drink (including one belonging to a market event) is
    cancelled. Its old target was computed against the old bounds.
  - **This deliberately differs from v1,** which rescaled every price and snapped `y` on
    every save. No golden scenario saves config, so the fixtures are unaffected.
- **SD10 — Changing the candle interval live re-buckets on the server.** The `config` message
  tells clients to resync (SD18), and they redraw from the new snapshot's bars.
- **SD11 — Idle targets are chosen per drink and stored as names.**
  - The UI shows checkboxes over active drinks, and the API takes `drink_id`s. `run.params`
    keeps v1's name lists, so the engine is unchanged.
  - A rename rewrites the name in both target lists, in the same transaction.
  - A removal drops the drink from both lists.

**Drinks**

- **SD12 — Add on a live run appends a slot (D-02).**
  - The new drink gets a new `drink_id` and the next `slot`.
  - Its `y` is initialised from `p0` exactly as `initial_state` does for one slot. Its flow,
    orders and totals start at zero.
  - **Every existing drink's state is bitwise unchanged:** `y`, `history`, `totals`,
    `cum_orders`, `flow_ema`, jumps and `rng_counter`. So are its earnings.
  - The noise draw is prefix-stable, so existing drinks' raw draws do not change. Checked:
    `default_rng(SeedSequence([s, k])).normal(0, σ, N+1)[:N]` equals the size-`N` draw.
    Their noise *scale* does change from the next draw, through `mean_range` (SD14). That is
    a consequence of having one more drink, not a reset.
- **SD13 — Remove on a live run is a soft delete. On a draft it is a hard delete.**
  - **Confirmation:** "'{name}' verwijderen?".
  - **Live:**
    - `removed_at` is set. The slot stays, masked inactive.
    - Its `y` freezes. It takes no orders: the server answers 422 `drink_unavailable`, which
      the bar shows as "{name} is niet meer beschikbaar".
    - It takes no jumps, and is no market-event target. Its running jump is cancelled.
    - It leaves both idle-target lists.
    - Its order lines and revenue stay in the ledger and the earnings.
    - Re-adding the same name creates a new `drink_id` and slot.
  - **Draft:** there is no ledger to keep, so the row is simply deleted.
- **SD14 — The engine gains an active mask (`MarketSpec.active`, default all true).**
  - **Over active slots only:**
    - `p_mean` in `_single_step` and `apply_idle`;
    - the `N` of `others_avg_dev`;
    - `mean_range` in `apply_brownian`;
    - the mean in `anchor_s0_to_current_y`.
  - Orders and jumps never touch inactive slots, and Brownian `dy` is applied only to active
    slots. The draw size stays `len(names)`, so a removal does not shift other drinks' draws.
  - **This is a change to the maths only when a removal exists,** which v1 could not express
    without a reset (`docs/design/architecture.md` "Non-destructive drink add and remove").
    With every slot active, the outputs are bitwise those of today, and the golden fixtures
    stay green. `engine-guardian` reviews the change.
- **SD15 — Persisted state covers every slot.**
  - `engine_state` holds keys for every drink row of the run, active and removed.
  - `rehydrate` builds the spec from all rows in slot order, with the mask taken from
    `removed_at`. One source defines the slot set and another defines the mask, which
    removes today's latent boot failure.
- **SD16 — Removing the last active drink is refused** with 409 `last_active_drink`.
- **SD17 — Rename is allowed.** `name_key` stays unique among active drinks. A duplicate is
  409 `duplicate_drink_name`.

**Realtime**

- **SD18 — A `config` message, and `active` on drinks.**
  - **The message.** After every committed live config write, the server broadcasts
    `config {revision, run: RunInfo + name, drinks: [{drink_id, name, active}], params}` in
    the seq log. `params` holds the client-relevant subset, as in the snapshot.
  - **The snapshot.** `snapshot.drinks` lists every drink of the run with `active`.
    `prices` and `bars` cover active drinks only. `earnings` covers every drink with sales.
  - **The client:**
    - replaces `drinks` and `params` from `config`;
    - sends `resync_request` when the active `drink_id` set or the candle interval changed;
    - **koers** shows active drinks only;
    - **bar** drops a removed drink's button, and lists its sales in the panel as
      "{name} (verwijderd): {qty}× — € x,xx". Totals include them.
  - **Go-live** reaches clients as a snapshot (SD3), not as `config`.
- **SD19 — No compatibility shim.** Server and web ship together from one origin. A stale tab
  drops an unknown `config` frame (`client.ts:133`) and catches up on its next snapshot.

**Manipulation page (`/manipulation`)**

- **SD20 — v1's sections, with roles.**
  - The sections are 📰 Nieuws, 💥 Market events, ⚡ Price jump and ⏳ Idle.
  - Bar and admin see the first three. **The Idle section is admin-only (D-44):** every
    params write is admin-only, and `GET config` is admin-only too.
  - The page re-renders on every broadcast. Fixed: v1's drink select stayed stale
    (`manipulation.html:405-416`).
- **SD21 — News.**
  - **The list:** newest first, showing level, text and time.
  - **"Toevoegen":** text 1–500 characters and a level select, Info / Succes / Waarschuwing /
    Gevaar, sent lowercase.
  - **"Verwijderen":** a `ConfirmDialog` reading "'{first 40 chars}' verwijderen?".
  - No edit.
- **SD22 — Market events.**
  - **Duration:** "Duur (seconden)", default 30, 1–600.
  - **Buttons:** v1's three — "💥 Market Crash", "🔄 Terug naar start" and "🚀 Price Bubble".
  - **Confirmation:** "Marktcrash starten?", "Terug naar start?" and "Prijsbubbel starten?"
    respectively. These move every price in the room, and a mis-tap is costly.
  - **Status:** "{crash|reset|bubble} gestart!". A running event shows its remaining seconds.
- **SD23 — Price jump (D-46).**
  - **Fields:**
    - a drink select over active drinks;
    - "Doelprijs (€)", required, with the drink's `[p_min, p_max]` shown as a hint;
    - "Duur (seconden)", default 5, 1–1800.
  - "Start jump" stays disabled until every field parses. The server rejects a target
    outside the drink's bounds with 422.
  - No confirmation.
  - v1's saturation of a crash target to `y ≈ −20.7` (Phase 1 plan R8) is unchanged.
- **SD24 — Draining refuses every admin write.** While shutting down, the system answers
  503 `shutting_down` to:
  - every route this phase adds;
  - news, jumps, events and theme writes.

  Today only orders check this (`app/api/orders.py:295-296`).

**Settings page (`/settings`, admin)**

- **SD25 — Sections follow v1's sidebar.** On narrow screens they sit behind
  `MobileSectionNav`.
  - The sections are:
    - Borrel (SD4);
    - 🧹 Systeemacties;
    - ⚙️ Globale instellingen;
    - 🎨 Kleurenschema;
    - 🖼️ Afbeeldingen;
    - 🥤 Drankjes beheren (add form; per drink: rename, bar price, remove);
    - 🔒 Min/Max/Startprijs;
    - 📈 Vraag/Aanbod (the two toggles plus the `a/d/s0/c` table);
    - 🔑 Toegangssleutels.
  - Each section is its own form with its own save button, and sends only its dirty fields.
  - A save with nothing dirty sends no request and shows "Niets te wijzigen" (v1's text).
- **SD26 — System actions are shutdown and anchor-s0. Reset is Phase 7.**
  - **"⛔ Sluit app":** a `ConfirmDialog` reading "Applicatie nu afsluiten?", then
    `POST /api/admin/shutdown`, then "App sluit nu af…" with every control disabled.
  - **No earnings download** (Phase 7's export).
  - **"📌 Zet huidige prijs als evenwicht":** no confirmation, as in v1.
  - **"🧹 Reset spel"** is absent. Phase 7 owns reset semantics within a run
    (`docs/specs/phase-7-analytics.md:16`). That supersedes Phase 3's out-of-scope line.
- **SD27 — Forms follow `docs/design/frontend-architecture.md` "Forms" exactly.**
  - The building blocks are `NumberField` (empty → `null`, never 0), `MoneyField`
    (euros → cents), `Field`, `Select`, `Switch`, `Toast` and `useEditableRecord`.
  - `+x` on form values is banned by lint.
  - On a `config` message or a refetch:
    - a non-dirty section reloads;
    - a dirty section keeps the user's input and shows "Serverwaarden gewijzigd —
      overnemen?". "Overnemen" discards the edits.
  - No form library is added.

**Theme and images**

- **SD28 — One custom theme ("Eigen"), editable over the whole manifest (D-19).**
  - **Storage.** The `theme` row gains:
    - `custom_tokens` (jsonb, exactly the manifest's token names);
    - `custom_font` (`inter` | `garamond`);
    - four image slots (SD29).

    `preset` may be `custom` only once `custom_tokens` exist.
  - **The editor:**
    - starts from any of the five presets, including Oud Geld (v1's select lacked it,
      `settings.html:218-223`);
    - lists **every token in `TOKEN_NAMES`**, each with a colour input and a hex text field;
    - offers the font choice.

    "Opslaan" sends all tokens and the font, selects `custom`, bumps `revision` and
    broadcasts `theme`.
  - **Values must match `^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$`.** Every preset value already
    does, and nothing else can reach `/theme.css`.
  - **The token count.** The manifest has 24 tokens (`app/runtime/theme.py:32-57`). "All 21
    tokens" in ADR 0005 and D-19 means every manifest token, the reading Phase 4 SD6 already
    took. This phase corrects the count in ADR 0005 and in the register.
- **SD29 — Images live in Postgres, are typed by content, and are mapped on the server
  (D-29, D-47, D-48).**
  - **Slots:**
    - `bg` (Achtergrond; `body::before` at opacity 0.12);
    - `header`;
    - `logo` (replaces the bundled logo);
    - `promo` (Promotie tegel; turns on koers' `has-promo` layout,
      `legacy/v1/static/koers.html:76`).
  - **Upload: `POST /api/theme/images/{slot}`** (admin, multipart `file`), in one transaction:
    1. store a new `asset` row (`bytea`, `content_type`, `sha256`, `bytes`; ADR 0004 /
       `data-model.md:47-53`);
    2. point the slot at it;
    3. delete the previous asset of that slot;
    4. bump the theme `revision`.

    It then broadcasts `theme`.
  - **Removal: `DELETE /api/theme/images/{slot}`** deletes the asset, after a confirmation
    reading "'{slot label}' verwijderen?".
  - **There are no orphan uploads.**
  - **Accepted types:** PNG, JPEG, WebP and GIF, decided by **magic bytes**, never by
    extension or the client's content type. SVG and everything else is 415
    `unsupported_media_type`.
  - **Size:** above 5 MB is 413 `too_large`. The server rejects on `Content-Length` before
    reading, and stops reading a body that streams past the limit. It never buffers more
    than 5 MB + one chunk.
  - **Serving: `GET /assets/{asset_id}`** is public like `/theme.css` (the board and the
    login page paint with it), and is added to the public allowlist. It sends:
    - the stored `Content-Type`;
    - `X-Content-Type-Options: nosniff`;
    - `Content-Security-Policy: default-src 'none'`;
    - `Cache-Control: public, max-age=31536000, immutable`, since asset ids are never
      reused.

    An unknown id is 404.
  - **Distribution.** The `theme` message and `/theme.css` carry the four slots' URLs (or
    none). So does `hello`. Every machine shows them (D-48).

**Access keys**

- **SD30 — "🔑 Toegangssleutels" manages keys. The first admin key stays CLI-only.**
  - **The list** shows label, role, created, last used, and status (Actief / Ingetrokken).
  - **"Nieuwe sleutel"** takes a role and a label (1–100 characters). It shows
    `bb_<key_id>_<secret>` once, with "Kopieer" and "Wordt maar één keer getoond". The secret
    is never retrievable again.
  - **"Intrekken"** asks "'{label}' intrekken?".
    - Revocation closes that key's open WebSockets within 1 s, using Phase 3's
      authentication close code.
    - Its sessions get 401 on their next request, as today.
    - Revoking the last unrevoked admin key is 409 `last_admin_key`.
  - **Routes:** `GET/POST /api/keys`, `DELETE /api/keys/{key_id}`, all admin.

**Home hub (`/`, admin) — D-26**

- **SD31 — Tiles plus live health.**
  - **Tiles:** Live koersbord, Bar, Spel mechanica and Instellingen, each with its v1 blurb,
    corrected: drinks and shutdown are on settings.
  - **The "Status" panel shows:**
    - this browser's socket (Verbonden / Verbinden… / Offline) and the age of the last
      message;
    - the run (name, status, `version`, last tick age), or "Geen actieve borrel";
    - server health from `/healthz`, polled every 5 s;
    - connected clients per role, from a new admin-only `GET /api/admin/connections`
      (`[{role, label, connected_at_ms, last_seen_ms}]` from the hub), polled every 5 s.
  - **A warning.** With zero display connections during a live run, the panel shows
    "Koersbord niet verbonden" in the warning colour.
  - `StatusDot` (built and unused, `web/src/components/ui/StatusDot.tsx`) renders each state.
- **SD32 — The correction banner already exists.** Phase 4 delivered it (its spec, line 143).
  AC17 below is kept as a regression check.

**Roles**

- **SD33 — Role summary.**
  - **admin:** everything in this phase.
  - **bar:** news, jumps and market events (unchanged from Phase 3), and `/manipulation`
    without Idle. No config, drinks, theme, keys, runs or connections.
  - **display:** none of it.

  The authorization matrix test gains a row for every new route.

## In scope

- **Server:**
  - run create and in-process go-live (SD1–SD3);
  - config, drinks and anchor-s0 routes (SD5–SD9);
  - candle re-bucketing (SD10);
  - the holder's `config` command and transition (SD7);
  - the `config` message and `active` on drinks (SD18);
  - the order path's `drink_unavailable` (SD13);
  - draining checks (SD24);
  - theme custom tokens and images, the `asset` table, `GET /assets/{id}` (SD28–SD29);
  - key routes and socket close on revocation (SD30);
  - `GET /api/admin/connections` (SD31);
  - regenerated OpenAPI types.
- **Engine:** the active mask (SD14), and the hold-on-bounds-change helper (SD9).
  `engine-guardian` review; golden fixtures green.
- **Persistence (expand-only migrations):**
  - `run.name`;
  - `price_tick.source` gains `config`;
  - theme `custom_tokens`, `custom_font` and the image slots;
  - `asset`;
  - `engine_state` covering removed slots (SD15).
- **Web:**
  - `features/home`, `features/manipulation`, `features/settings` (Phase 4 PD13 moves the
    theme picker there), `features/keys`;
  - the form primitives (SD27);
  - `http.ts` gains `PATCH` and multipart;
  - the koers image slots and `has-promo`;
  - the bar's removed-drink handling (SD13, SD18).
- **Documents:**
  - an ADR 0003 addendum (in-process go-live);
  - ADR 0005's token count;
  - `realtime-protocol.md` (`config`, `active`, theme images);
  - `data-model.md` (`asset`, `run.name`, theme columns, the source value);
  - `architecture.md` (mask scope includes `mean_range`);
  - the Phase 7 spec (create and go-live exist; reset stays there);
  - the defect register (D-44–D-48 added; line drift noted).

## Out of scope

- **Phase 7's lifecycle:**
  - closing or ending a run;
  - reset within a run ("Reset spel");
  - switching between runs, a run list, deleting runs;
  - copying a past run's drinks into a new one.
- Exports and the earnings download, on shutdown or anywhere else (Phase 7).
- Editing `bm_*`, `flow_vol_amp`, `flow_beta`, `y_clip`, `tick_interval_ms` or
  `quote_grace_versions` (SD8).
- Editing news, news expiry or scheduling, or editing or cancelling a running market event or
  jump from the UI.
- Undoing a drink removal (re-add creates a new drink), reordering slots, or drink images.
- **Theming:**
  - more than one custom theme, or per-run themes;
  - a theme import or export, or a live preview beyond applying on save;
  - fonts other than Inter and EB Garamond;
  - SVG or any other image type beyond SD29's four;
  - image cropping or resizing.
- **Access keys:**
  - creating the first admin key from the UI (CLI bootstrap stays);
  - rotating a key in place;
  - per-key permissions finer than the three roles.
- A dedicated admin audit log beyond `run_config_revision`'s `author`.
- Changing the crash-target saturation (Phase 1 R8) or any other pricing behaviour beyond
  SD9 and SD14.
- Fixing v1's code in `legacy/v1/`.
- Concurrency control stronger than per-field last-writer-wins (SD6).
- Service worker, PWA, offline admin edits (an admin write needs the server).

## Acceptance criteria

**The coercion bug class — D-03, D-04, D-46**

- **AC1.** When a numeric field is left untouched, the system shall omit it from the request
  body. *(D-03)*
- **AC2.** When the Vraag/Aanbod section is saved without any edit, the system shall send
  **no request**, show "Niets te wijzigen", and no coefficient of any drink shall change. When
  `PATCH` config or drink is sent an empty body, the system shall change nothing and write no
  revision. *(D-03)*
- **AC3.** When a numeric field is cleared, the field shall hold `null` and the section shall
  not save. When the server receives `null` for any field, it shall return 422 naming that
  field, and shall never store `0`.
- **AC4.** When a drink is added with `a`, `d`, `s0`, `c` and bar price left blank, the request
  shall omit them, and the stored drink shall have `a=10, d=0.6, s0=8, c=0.4` and
  `bar_price_cents = p0_cents`. *(D-04)*
- **AC5.** While a section is dirty, when a `config` message or refetch brings different
  values, the system shall keep the user's input and show "Serverwaarden gewijzigd —
  overnemen?". "Overnemen" shall load the server values.
- **AC6.** When the jump target is empty or unparseable, "Start jump" shall be disabled and no
  request shall be sent. When the server receives a target outside the drink's bounds, it
  shall return 422. *(D-46)*

**Config writes — D-44, D-45**

- **AC7.** When a bar or display session calls any config, drinks, anchor-s0, runs, theme,
  keys or connections route, the system shall return 403. When it opens `/manipulation`, a
  bar session shall see no Idle section. *(D-44)*
- **AC8.** When a drink's `p_min`/`p_max`, or `step_quant`, changes on the live run, every
  affected drink's quoted price shall equal its previous quoted price clamped into the new
  bounds and re-quantised. Every other drink's `y` shall be bitwise unchanged. *(D-45)*
- **AC9.** When a scalar param, `a/d/s0/c`, `p0` or a bar price changes on the live run, no
  drink's `y` shall change in that transition. *(D-45)*
- **AC10.** When a bound change affects a drink with a running jump, the jump shall be
  cancelled in the same transition.
- **AC11.** When a write violates SD8 (a range, `p_min < p0 < p_max` on the resulting row, a
  non-finite number, a non-editable param), the system shall return 422 naming the field, and
  shall change nothing.
- **AC12.** When any live config write commits, the system shall do so in one transaction
  with `version` + 1, a `price_tick` of source `config`, and exactly one new
  `run_config_revision` holding the full config and the author's key label. It shall then
  broadcast one `config` message.
- **AC13.** When two admins concurrently write different fields, both changes shall persist.
  When they write the same field, the later commit shall win. Revision numbers shall be
  consecutive with no collision.

**Drinks — D-02**

- **AC14.** When a drink is added mid-run, every existing drink's `y`, history, `totals`,
  `cum_orders`, `flow_ema`, running jumps, `rng_counter` and earnings shall be bitwise
  unchanged. The new drink shall quote its `p0`. *(D-02)*
- **AC15.** When a drink is removed mid-run, its order lines and revenue shall remain in the
  database and in the earnings totals, and no other drink's price shall change in that
  transition. *(D-02)*
- **AC16.** While a drink is removed, `p_mean`, the `N` in `others_avg_dev`, `mean_range` and
  anchor-s0's mean shall range over active drinks only. With every drink active, the golden
  fixtures shall replay unchanged.
- **AC17.** When removing the last active drink is attempted, the system shall return 409
  `last_active_drink` and change nothing.
- **AC18.** When a drink with a running jump (alone or from a market event) is removed, the
  jump shall be cancelled in the same transition.
- **AC19.** When an order names a removed drink, the system shall return 422
  `drink_unavailable` and charge nothing. The bar shall show "{name} is niet meer
  beschikbaar".
- **AC20.** When the app restarts after drinks have been added and removed, it shall boot,
  and every drink's state, including removed ones, shall equal what was committed.
- **AC21.** When a drink is added or renamed to an active drink's name (case- and
  space-insensitively), the system shall return 409 `duplicate_drink_name`. When a removed
  drink's name is re-added, it shall get a new `drink_id`.
- **AC22.** When a drink in an idle-target list is renamed, the list shall carry the new name.
  When it is removed, the list shall no longer contain it.
- **AC23.** When the active drink set changes, every connected koers and bar client shall show
  the new set without reload. A bar client shall list a removed drink's sales as
  "{name} (verwijderd)", with totals equal to the database's Σ `line_total_cents`.

**Run lifecycle slice**

- **AC24.** When "Nieuwe borrel" is submitted with no live run and no draft, the system shall
  create a draft with the given name, no drinks, and the most recent run's params (or
  defaults). With a live run or a draft present, it shall return 409 `live_run_exists` /
  `draft_exists`.
- **AC25.** When "Live zetten" is confirmed on a draft with at least one drink, the system
  shall make it live without a restart. The ticker shall advance it at its
  `tick_interval_ms`, and every connected client (koers, bar, home) shall show it within 2 s
  without reload.
- **AC26.** When go-live is requested for a draft with no drinks, a non-draft, or while another
  run is live, the system shall return 409 and change nothing.
- **AC27.** When go-live runs with `auto_calibrate_s0`, every drink's `s0` shall be anchored to
  its initial price, and one config revision shall be written, in the go-live transaction.
- **AC28.** When the candle interval is changed on the live run, koers shall redraw from
  server bars at the new interval without reload. When it is not a multiple of 5 in 5–3600,
  the system shall return 422.

**Theme and images — D-19, D-29, D-47, D-48**

- **AC29.** When the theme editor is opened, every token in `TOKEN_NAMES` shall be editable,
  and the test shall derive the list from the manifest, not hard-code it. *(D-19)*
- **AC30.** When the custom theme is saved, every connected client shall apply all its tokens
  and its font, and `/theme.css` shall render them. A token value not matching
  `#rgb`/`#rrggbb` shall be rejected with 422. *(D-19)*
- **AC31.** When an upload is SVG, or any type other than PNG, JPEG, WebP or GIF by magic
  bytes, the system shall return 415 regardless of extension or declared content type, and
  shall store nothing. *(D-29)*
- **AC32.** When any asset is served, the response shall carry its stored content type,
  `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'`.
  *(D-29)*
- **AC33.** When an upload exceeds 5 MB, the system shall return 413, never holding more than
  5 MB + one chunk in memory, whether or not `Content-Length` is sent. *(D-47)*
- **AC34.** When a slot's image is replaced or removed, the previous asset row shall be
  deleted in the same transaction. No asset shall exist that no slot references.
- **AC35.** When an image is set on one machine, every connected client and a fresh load on
  another machine shall show it. The promo slot shall switch koers to the `has-promo` layout.
  *(D-48)*

**Keys**

- **AC36.** When an admin creates a key, the secret shall be shown once and never be
  retrievable again. Only its argon2 hash shall be stored.
- **AC37.** When a key is revoked, its open WebSockets shall be closed within 1 s, and its
  session's next HTTP request shall get 401.
- **AC38.** When revoking the last unrevoked admin key is attempted, the system shall return
  409 `last_admin_key`.

**Safety, shell and roles — D-26**

- **AC39.** When any destructive action is triggered, the system shall show a `ConfirmDialog`
  with the Dutch wording fixed in SD3, SD13, SD21, SD22, SD26, SD29 and SD30, and shall
  never call native `confirm`/`alert`. The actions are remove drink, delete news, start a
  market event, go-live, shutdown, remove image and revoke key.
- **AC40.** While the app is draining, every write route this phase adds, plus news, jumps,
  events and theme, shall return 503 `shutting_down`.
- **AC41.** When the home page loads, it shall show socket status, run status, server health
  and connected clients per role, and shall log no uncaught error or rejection. With no
  display connected during a live run, it shall show "Koersbord niet verbonden". *(D-26)*
- **AC42.** When a "correction" market event is active, koers shall show the calm banner, not
  a pulsing overlay. (Phase 4; regression.)
- **AC43.** Every route this phase adds shall have an explicit authorization dependency and a
  row in the authorization matrix test.

## Verification

- **The D-03 gate, written first as a failing test.** A component test loads a config
  snapshot and clicks save in Vraag/Aanbod without editing. It asserts no request is sent.
  Then it edits one `a` and asserts the body is exactly that one field (AC1–AC2).
- **Vitest:**
  - `NumberField` / `MoneyField` parsing (empty → `null`; "2,50" → 250; three decimals
    invalid);
  - the lint rule against `+x`;
  - dirty-vs-broadcast (AC5);
  - the `config` reducer and the resync trigger (SD18).
- **Component tests:**
  - every section's dirty-only body;
  - add-drink with blanks (AC4);
  - jump disabled when empty (AC6);
  - every `ConfirmDialog` wording (AC39);
  - the theme editor listing the manifest (AC29);
  - the key secret shown once (AC36);
  - home with no display (AC41).
- **Engine (pytest):**
  - mask property tests: an all-active mask equals today's outputs bitwise;
  - aggregates over active only (AC16);
  - the hold-on-bounds helper (AC8);
  - golden `--check` green.

  `engine-guardian` signs off.
- **Integration against real Postgres:**
  - **Add/remove mid-run.** Run a scripted borrel. Snapshot every existing drink's state.
    Add, then remove, a drink. Assert bitwise equality (AC14–AC15) and ledger sums. Restart
    the app and assert rehydrated state equals committed (AC20).
  - **Bounds.** Change bounds and `step_quant` and assert held prices (AC8). Change scalars
    and assert `y` unchanged (AC9).
  - **Concurrency.** Two concurrent PATCHes give consecutive revisions (AC13).
  - **Go-live in-process.** Start the app empty, create a draft, add drinks, go live. Assert
    ticks advance and a connected WS client receives the snapshot without reconnecting
    (AC25).
  - **Uploads.** SVG renamed `.png` → 415. A 6 MB streamed body without `Content-Length` →
    413 with bounded memory. Header assertions (AC31–AC33).
  - **Keys.** Revoke → socket closed within 1 s (AC37).
  - **Draining** → 503 everywhere (AC40).
  - **Authorization.** The matrix is complete (AC7, AC43).
- **Playwright (in the gate):**
  - From an empty database with one CLI-created admin key:
    1. create a borrel;
    2. add three drinks;
    3. set params;
    4. pick a preset and save a custom theme;
    5. upload a logo;
    6. create a display key and a bar key;
    7. go live.

    A second context logged in with the display key sees the board with the custom theme and
    logo, with no reload after go-live.
  - Remove a drink while a bar context is open; its button disappears.
  - Destructive confirmation and cancel paths.
- **Manual (exit check):** on a fresh database, configure a whole borrel through the UI
  alone, from creating it to live on a separate display machine. Then, mid-borrel, add one
  drink and remove another. Confirm no other price moved, and that the bar's totals still
  equal the database.

## Exit condition

An admin can take an empty database to a live, themed borrel through the UI alone, and no form
or drink change can destroy data it was not asked to change.
