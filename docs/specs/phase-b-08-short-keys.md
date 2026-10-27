# Spec: B-08 — Short keys you can read aloud

Status: Approved · Depends on: Phase 3 (SD5 the `auth_key` table and its CLI, SD6 one argon2
verify per login, SD7 the login limiter, SD8 sessions), Phase 6 (SD30 Toegangssleutels and
`last_admin_key`), Phase 8 (SD3 `schema_compat`, SD9 proxy trust, the deploy smoke test), B-05
(SD14 the short code's alphabet and its forgiving reading) · Fixes: D-50 · Amends: Phase 3 SD5
and SD6, Phase 6 SD30, Phase 8 SD9 (its accepted-risk rationale),
[architecture.md](../design/architecture.md) § Authorization, `docs/runbooks/deploy.md`,
`docs/runbooks/venue.md` · Backlog: [B-08](../backlog.md)

Line references are to `main` at `3778ba9`.

## Problem

A key is too long to hand over at a borrel. A crew member who needs a bar or display key gets it
by copy-paste between devices, or not at all; reading one aloud is impossible.

- **A key is about 50 characters.** It is `bb_<key_id>_<secret>` with
  `secret = secrets.token_urlsafe(32)`, 43 characters of `[A-Za-z0-9_-]`
  (`app/api/security.py:3-7`, `:53`, `:69-74`). Upper and lower case differ, and `l`/`1`, `O`/`0`
  and `-`/`_` all appear.
- **Login finds the key by the `key_id` inside it.** `parse_key` splits on `_` and requires an
  all-digit `key_id` (`app/api/security.py:77-86`). `verify_login` loads that row and runs one
  argon2 verify against its per-row-salted hash, or against `dummy_hash()` for an unknown id
  (`:118-120`, `:230-249`; Phase 3 SD6, `docs/specs/phase-3-api-realtime.md:77-82`). The design
  says the same: "Keys are issued as `bb_<key_id>_<secret>`: look up by `key_id`, verify once"
  (`docs/design/architecture.md:197-199`).
- **Minting needs the `key_id` before it can make the key.** `issue_key` inserts the row with a
  placeholder hash, then sets the real one (`app/api/security.py:89-106`). `POST /api/keys`
  parses its own result back to return the `key_id` (`app/api/keys.py:94-98`).
- **The long form is printed everywhere a key is shown.** The CLI prints `bb_<key_id>_<secret>`
  (`app/cli/keys.py:7`; Phase 3 SD5, `phase-3-api-realtime.md:72-76`). The Toegangssleutels
  dialog shows it in a `<code>` once (`web/src/features/keys/KeysSection.tsx:7`, `:181-182`;
  Phase 6 SD30, `phase-6-admin.md:460-470`). The runbooks and the smoke script name the form
  (`docs/runbooks/deploy.md:11-14`, `docs/runbooks/venue.md:19-20`, `scripts/smoke.py:3`).
- **The login page takes free text and trims it** (`web/src/features/auth/LoginPage.tsx:38`,
  `:62-69`). Nothing forgives case or look-alike characters.
- **"Kopieer" throws at the venue (D-50).** It calls `navigator.clipboard.writeText(secret)`
  (`web/src/features/keys/KeysSection.tsx:184`). Browsers provide `navigator.clipboard` only in
  a secure context, and the venue serves plain `http://192.168.8.10/` (Phase 8 SD1). There
  `navigator.clipboard` is `undefined` and the click throws `TypeError`, copying nothing. Like
  D-49, no test can see it: e2e and the image tests use `http://127.0.0.1`, which counts as
  secure.
- **The limiter's rationale assumes a 256-bit secret.** On Render, `TRUSTED_PROXY_IPS=*` lets a
  client choose its own rate-limit bucket through `X-Forwarded-For`, accepted because "the
  limiter guards a 256-bit random secret" (Phase 8 SD9, `phase-8-deploy-cutover.md:187-194`).
  A short key needs that argument made again with its own numbers (SD4).

## Decisions

These were settled at the spec interview on 2026-10-27. Q1–Q6 were put to the owner one at a
time, each with a recommendation, and each answer below is recorded as given. SD2, SD7, SD8 and
SD10 were stated as defaults during the interview and not objected to. The planner must not
reopen any of them.

**The key**

- **SD1 — A key is 9 secret symbols, nothing else (Q1).**
  - The symbols are B-05's Crockford base32 alphabet, `0123456789ABCDEFGHJKMNPQRSTVWXYZ`
    (no I, L, O, U; `app/runtime/wallet_codes.py:21`). Each is drawn independently from
    `secrets`, so a key carries 45 bits.
  - There is no `bb_` prefix and no `key_id` in the key. All 9 symbols are secret.
  - Every role gets the same form: `display`, `bar`, `kassa` and `admin`.
- **SD2 — Shown grouped, read forgivingly (stated default).**
  - Shown as three groups of three, `K7M-4QX-9PR`: by the CLI, in `POST /api/keys`'s response
    and in the Toegangssleutels dialog.
  - Read the way B-05 SD14 reads a short code: surrounding whitespace stripped, case ignored,
    every `-` and space anywhere removed, `O` read as `0`, and `I` and `L` read as `1`. The
    result must be exactly 9 symbols of the alphabet. Anything else (a `U`, an `_`, 8 or 10
    symbols, a long `bb_…` key) is **malformed**.
  - This reading happens on the server. The client sends what was typed, trimmed.

**Finding the key**

- **SD3 — The key is found by its own hash, with one argon2 per login (Q1).**
  - What is stored is an argon2id hash of the key's 9 normalised symbols, with a **fixed salt
    that is a constant in the code**, the same on every deployment. Parameters are the library
    defaults used today (RFC 9106). Neither the key nor any part of it is stored.
  - That hash is unique across every `auth_key` row, revoked ones included.
  - **Login**, in order:
    1. The limiter, unchanged (SD5, Phase 3 SD7), before anything else.
    2. Normalise (SD2). Malformed is 401, with no hash computed (as Phase 3 SD6).
    3. Compute the hash once, in a worker thread, off the event loop.
    4. Look the row up by that hash.
    5. No row, or a revoked row, is 401. The message is the same as today's, for both.
    6. Otherwise, set `last_used_at` and issue the session, as today (Phase 3 SD6, SD8).
  - A well-formed key costs one argon2 and one indexed lookup whether it exists or not, so the
    timing does not tell an attacker whether a key exists. `dummy_hash()` has no remaining use.
  - **Minting** draws 9 symbols, hashes them and inserts the row with that hash. If the hash
    already exists in any row, it draws again. After 5 collisions in a row it gives up and
    writes nothing: the CLI exits 1, and the API returns its generic 500. (At 45 bits and a
    few dozen keys, a single collision is about one in 10¹².) The `key_id` still exists as the
    row's id for the list and for revoking, but it is never part of the key.
- **SD4 — The numbers, and the risks accepted (Q4).** With a fixed salt, one guess is checked
  against every key at once, so every figure below is divided by the number of unrevoked keys,
  `K`.

  | Attack | Rate | Average time to hit one given key | With `K` = 10 unrevoked keys |
  |---|---|---|---|
  | Online, Render (the per-IP bucket can be chosen, Phase 8 SD9) | ~20 argon2/s, a generous ceiling for a Starter instance (50–100 ms per argon2, `architecture.md:196`) | ~28 000 years | ~2 800 years |
  | Online, a much larger server | 1 000/s | ~560 years | ~56 years |
  | Offline, from a leaked database dump | 20 000/s (1 000 cores) | ~28 years | ~2.8 years |

  (2⁴⁵ ≈ 3.5 × 10¹³ keys; on average a hit takes 2⁴⁴ guesses.)
  - **Online guessing is accepted** with no new protection (SD5).
  - **The offline row is accepted** as recorded. A dump of the database already holds every
    order, wallet and run. It does not hold `JWT_SECRET`, so it cannot forge a session. A key
    pepper (an HMAC with a deployment secret) would remove the offline row, but it would tie
    every key to that secret, and it was not chosen.
  - Phase 8 SD9's accepted-risk sentence ("the limiter guards a 256-bit random secret") is
    replaced by a pointer to this table.
- **SD5 — No new guessing protection (Q4).** No lockout, no global failure cap and no change to
  the per-IP limiter or to Phase 8 SD9's proxy trust. A lockout anyone could trigger would let a
  stranger lock the crew out mid-borrel; a global cap the same.

**The switch-over**

- **SD6 — The B-08 migration revokes every existing key (Q2, Q3).**
  - Every `auth_key` row with no `revoked_at` gets one. Rows already revoked keep theirs.
    Nothing is deleted, so the list shows every old key as "Ingetrokken".
  - Their sessions get 401 on their next request, by the existing row check (Phase 3 SD8). No
    WebSocket survives: the new instance boots with none, and the old instance closes its own
    on shutdown.
  - After it, a database has **no usable key and no admin key**. The first admin key is minted
    by CLI, which Phase 6 SD30 already requires.
  - A long key presented after the migration is malformed (SD2) and gets 401 without a hash.
  - **Rollback.** The migration leaves `min_code_revision` unchanged (Phase 8 SD3). A
    pre-B-08 image still boots against the B-08 schema, and its own mint and login still work
    against it, so a rollback stays "run the previous SHA". After a rollback no key works: the
    old keys are revoked and the old code cannot read a short key. The way back in is a long
    key minted with that image's own CLI. The rollback runbook says so.
  - `downgrade()` undoes the schema change only. It does not un-revoke: it cannot tell which
    rows the upgrade revoked.
- **SD7 — The one-time B-08 deploy (stated default).** Done between borrels, never during one.
  - **Render.**
    1. Deploy the B-08 SHA. The smoke test passes `build_sha` and then **fails at login**,
       because `BB_SMOKE_KEY` was revoked. This one failure is expected and is not a reason to
       roll back.
    2. In the Render shell, mint your own admin key and an admin key labelled `smoke`.
    3. Set `BB_SMOKE_KEY` to the new smoke key.
    4. Run the deploy workflow again with the same SHA. It must be green.
  - **Venue.** Same at the next bundle update: after `start.cmd` has migrated, mint the keys
    with the bundle's image (`venue.md` step 6), and hand out new bar, display and kassa keys.
  - `deploy.md` gets this as a one-time section, and its "Smoke fails after the SHA matches:
    roll back" line names it as the exception. These are the owner's steps (Hard stops:
    credentials, deploy).

**Where a key is shown**

- **SD8 — The CLI, the API and the dialog show the grouped form once (stated default).**
  - `app.cli.keys create` prints `K7M-4QX-9PR`, once. `list` and `revoke` are unchanged.
  - `POST /api/keys` returns `{key_id, key}` with `key` in the grouped form. `GET` and
    `DELETE` are unchanged.
  - The Toegangssleutels dialog shows the grouped key once, with "Kopieer" and "Wordt maar één
    keer getoond", as Phase 6 SD30. It is set larger and monospaced, so it can be read aloud.
  - "Kopieer" copies the grouped form, dashes included.
  - The list, "Intrekken", its confirm, and `last_admin_key` are unchanged.
- **SD9 — "Kopieer" works without a secure context (Q6, D-50).**
  - When `navigator.clipboard` exists and `writeText` resolves, the key is copied, as today.
  - Otherwise (no `navigator.clipboard`, or `writeText` rejects), "Kopieer" never throws. It
    selects the key's text in the dialog, so it can be copied by hand, and shows the line
    **"Kopiëren lukt hier niet. De sleutel is geselecteerd: kopieer hem zelf."**
  - The key stays on screen until "Sluiten", as today.
- **SD10 — The login page stays as it is, apart from one attribute (stated default).**
  - Same label, button and messages (ported verbatim from v1, Phase 4 PD17). No placeholder,
    no auto-inserted dashes and no length cap in the field.
  - The input gets `autoCapitalize="characters"`, so a phone keyboard opens in capitals.
  - A malformed key and a wrong key show the same "Ongeldige toegangscode." (as today, AC21 of
    Phase 4).
- **SD11 — The design document is amended (Q5, owner-approved hard stop).** The Authorization
  bullet at `docs/design/architecture.md:197-199` is rewritten. A key is 9 symbols with no
  `key_id`. It is found by its fixed-salt argon2 hash, with one hash per login, so there is
  still no iterating over keys and the limiter still runs first.

## The interface

- `POST /api/auth/login` `{key}`: the body is unchanged (1–256 characters). Malformed, unknown
  and revoked keys are all 401 `unauthenticated`; over the limit is 429 with `Retry-After`.
- `POST /api/keys` `{role, label}` returns 201 `{key_id, key: "K7M-4QX-9PR"}`.
- `python -m app.cli.keys create --role <r> --label <l>` prints `K7M-4QX-9PR` on one line.
- No other route, message or schema changes. `web/src/api` types change only if `CreatedKey`'s
  generated type does.

## In scope

- Minting, normalising, hashing and looking up 9-symbol keys (`app/api/security.py`), and
  `issue_key` without the placeholder hash.
- The migration: revoke every key, plus whatever index or column the fixed-salt lookup needs,
  with `min_code_revision` unchanged and a test that a pre-B-08 mint and login still run
  against the new schema.
- `app/cli/keys.py` and `POST /api/keys` printing and returning the grouped form.
- The Toegangssleutels dialog: grouped and larger, "Kopieer" with the D-50 fallback.
- The login page's `autoCapitalize`.
- The defect register: D-50 filed (section H) and its evidence row.
- The documents: architecture.md's bullet (SD11); "Amended by B-08" notes in Phase 3 SD5 and
  SD6, Phase 6 SD30 and Phase 8 SD9; `deploy.md` (the one-time section and the smoke-key line);
  `venue.md` (the key's form); `rollback.md` (SD6's rollback note); `scripts/smoke.py`'s and
  `app/cli/keys.py`'s docstrings.
- Tests: unit, API, integration, web unit, and e2e over an insecure origin for D-50.

## Out of scope

- Usernames, passwords, PINs, a QR code or a login link (backlog "Not this").
- Any change to the roles, to `ROLE_ROUTES`, or to what each key opens.
- Any change to sessions: 24 hours, the cookie, its attributes, logout.
- Lockouts, a global failure cap, per-key limits, CAPTCHAs, or a change to the limiter's numbers
  or its IP bucket (SD5). Phase 8 SD9's proxy trust stays `*` on Render.
- A key pepper or HMAC tied to `JWT_SECRET` or to a new secret (SD4).
- Changing argon2's parameters.
- Keeping long keys working, or converting them: they are revoked (SD6).
- Showing any part of a key in the list (a last-three hint, a fingerprint), regenerating a key
  in place, editing a key's label or role, or key expiry.
- Different lengths per role.
- Auto-formatting the login field, a placeholder, or new login wording (SD10).
- A deploy workflow change that skips or relaxes the smoke test for this deploy (SD7 is a manual
  sequence).
- Minting the new Render, smoke and venue keys: the owner's (SD7).
- Wallet short codes and their reading (B-05). B-08 shares the alphabet, nothing else.
- The pricing engine (`exchange/`), the golden fixtures and anything that feeds them.
- The existing risk that a login flood of argon2 hashes exhausts a small instance's CPU or
  memory. It is unchanged by B-08 and not addressed.

## Acceptance criteria

**The key — SD1, SD2, SD8**

- **AC1.** When a key is minted, by the CLI or by `POST /api/keys`, the system shall produce 9
  symbols of `0123456789ABCDEFGHJKMNPQRSTVWXYZ`, each drawn from `secrets`, and show it once as
  `XXX-XXX-XXX`. No key shall contain `bb_` or its `key_id`. *(A provenance test fails on a
  planted `random` in the minting path, as B-06's `walletCode.provenance.test.ts`.)*
- **AC2.** When a valid key is typed in lowercase, without its dashes, with spaces between
  any symbols, with leading or trailing whitespace, or with `O` for `0` or `I`/`L` for `1`, the
  system shall log it in as that key.
- **AC3.** When the CLI prints a key, it shall print only the grouped key on one line. When
  `POST /api/keys` returns one, `key` shall be the grouped form and `key_id` the new row's id.

**Login — SD3, SD5**

- **AC4.** When a malformed key is presented (8 or 10 symbols, a `U`, an `_`, a long
  `bb_<key_id>_<secret>` key, an 8-symbol wallet short code), the system shall return 401 and
  compute no argon2 hash.
- **AC5.** When a well-formed key is presented, whether it is unknown, revoked or valid, the
  system shall compute exactly one argon2 hash, in a worker thread, and run one lookup by that
  hash. Unknown and revoked shall both be 401 with the same body.
- **AC6.** When a valid, unrevoked key logs in, the system shall set its `last_used_at` and
  issue the session cookie exactly as Phase 3 SD6 and SD8 do, with the role's `allowed_routes`.
- **AC7.** When one IP makes its 11th login attempt within 60 s, the system shall return 429
  with `Retry-After` before normalising or hashing, as Phase 3 SD7. *(Regression.)*

**Storage — SD3**

- **AC8.** When a key is minted, the system shall store only its fixed-salt argon2id hash. No
  column, log line or response other than the one create response shall contain the key or
  any part of it. *(Checked on the row, on `caplog`, and on the list response.)*
- **AC9.** When a newly drawn key's hash equals the hash of any stored row, revoked rows
  included, the system shall draw again. After 5 collisions in a row it shall write nothing:
  the CLI exits 1, and the API returns 500. *(Tested with an injected draw.)*

**The switch-over — SD6**

- **AC10.** When the B-08 migration runs on a database holding unrevoked and revoked long keys,
  every unrevoked key shall get a `revoked_at`. Already revoked keys shall keep their
  `revoked_at` unchanged. No row shall be deleted, and the list shall show all of them
  "Ingetrokken".
- **AC11.** When a session issued to a key from before the migration makes a request after it,
  the system shall return 401. When that key's long form is presented at login, the system shall
  return 401 (AC4).
- **AC12.** When the migration has run, a key minted by the CLI shall log in, and with no admin
  key left the CLI shall still mint an admin key.
- **AC13.** When the migration has run, `schema_compat.min_code_revision` shall be unchanged. A
  key minted by the pre-B-08 code path (insert with a placeholder hash, then set the real one)
  shall insert, and log in through the pre-B-08 `parse_key`/`verify_login`, against the new
  schema. *(The rollback guarantee in SD6.)*
- **AC14.** When an admin revokes the last unrevoked admin key, the system shall still return
  409 `last_admin_key`. *(Regression of Phase 6 SD30.)*

**The dialog and the login page — SD8, SD9, SD10**

- **AC15.** When admin creates a key under Toegangssleutels, the dialog shall show the grouped
  key once, monospaced and larger than body text, with "Kopieer" and "Wordt maar één keer
  getoond". "Sluiten" shall remove it from the DOM, as Phase 6 AC36.
- **AC16 (D-50).** When "Kopieer" is pressed in a page where `navigator.clipboard` is
  undefined, or where `writeText` rejects, the system shall not throw. The key's text shall be
  selected, and the line "Kopiëren lukt hier niet. De sleutel is geselecteerd: kopieer hem
  zelf." shall be shown. Where `writeText` resolves, the clipboard shall hold the grouped key.
  *(e2e at `http://keys.test:<port>`, where `isSecureContext` is false, as B-06's
  `payments.spec.ts`.)*
- **AC17.** The login page's key input shall carry `autoCapitalize="characters"`. Its label,
  button and failure messages shall be unchanged, and a malformed key shall show "Ongeldige
  toegangscode.".

**Documents and boundaries — SD4, SD7, SD11**

- **AC18.** When B-08 is merged, `docs/design/architecture.md` shall describe the 9-symbol key
  and its hash lookup (SD11). Phase 3 SD5 and SD6, Phase 6 SD30 and Phase 8 SD9 shall each
  carry an "Amended by B-08" note pointing here. `deploy.md` shall hold SD7's one-time
  sequence, `rollback.md` SD6's rollback note, and `venue.md` the new key form. No file under
  `app/`, `web/src/`, `scripts/` or `docs/runbooks/` shall still describe a key as `bb_<…>`.
- **AC19.** `scripts/smoke.py` shall log in with a 9-symbol key given in `BB_SMOKE_KEY`, grouped
  or not. *(Against a locally running app.)*
- **AC20.** The diff shall touch nothing under `exchange/` or `tests/engine/golden/fixtures/`.

## Verification

- **API and integration (pytest):**
  - minting through the CLI and the API, and the grouped form (AC1, AC3);
  - every forgiving reading, and every malformed shape with a zero hash count (AC2, AC4);
  - exactly one hash for unknown, revoked and valid keys, counted through the verifier hook
    `app/api/auth.py:74` uses today or its replacement, and identical 401 bodies (AC5);
  - session and `last_used_at` (AC6), the limiter (AC7);
  - storage, logs and responses free of the key (AC8);
  - collision redraw and give-up, with an injected draw (AC9);
  - `last_admin_key` (AC14).
- **Migration (integration):** on a scratch database at the pre-B-08 head:
  1. Mint two long keys with the old path and revoke one.
  2. Hold a session for the other.
  3. Upgrade.
  4. Assert AC10 and AC11.
  5. Mint a short admin key by the CLI and log in with it (AC12).
  6. Assert `min_code_revision`, and run the pre-B-08 mint and login against the new schema
     (AC13).
- **Web (vitest):** the dialog's grouped display, "Kopieer" with a resolving, a rejecting and a
  missing clipboard (AC15, AC16); the login input's attribute and strings (AC17).
- **e2e (Playwright), the whole story at an insecure origin** (`http://keys.test:<port>`):
  1. Log in as admin with a CLI-minted key typed in lowercase with spaces (AC2).
  2. Under Toegangssleutels, create a bar key.
  3. Press "Kopieer": no error, the key is selected and the hint is shown (AC16).
  4. In a second browser context, type the key as read aloud, without dashes, and land on
     `/bar`.
  5. Revoke the bar key: the second context's next request is 401.
  6. A long `bb_…` key at login shows "Ongeldige toegangscode.".
- **Smoke:** `scripts/smoke.py` against a local app with a short `BB_SMOKE_KEY` (AC19).
- **Docs:** a grep of `app/`, `web/src/`, `scripts/` and `docs/runbooks/` for `bb_<` and for
  `bb_<key_id>` finds nothing (AC18); the amendment notes are present.
- **The gate:** `./scripts/check.sh`, 13/13, output pasted. The engine is untouched (AC20), so
  `golden_linux.sh` and `engine-guardian` are not required. The diff's `exchange/` emptiness is
  evidence enough.
- **Manual exit check (the owner's):** SD7's Render sequence, ending in a green deploy run; and
  at the next venue bundle, a bar key read aloud to someone and typed on their phone over
  `http://192.168.8.10/`.

## Exit condition

Every key is 9 symbols that can be read aloud and typed on a phone, admin keys included. Each
login still costs one argon2 and finds the key without iterating over keys. Every long key is
revoked, and "Kopieer" works at the venue.
