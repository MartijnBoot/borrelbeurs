# Plan: B-08 — Short keys you can read aloud

Spec: [docs/specs/phase-b-08-short-keys.md](../specs/phase-b-08-short-keys.md) (`Status: Approved`) · Status: **Audited — PASS (2026-10-27)**
Design: one approved change, `docs/design/architecture.md` § Authorization (SD11, T8). One open question on `docs/design/data-model.md` (PD12, the owner's).
ADRs honoured:
- 0004: one Postgres engine. One migration, `0015`, on the existing `auth_key` table.
- 0007: v1's keys stay unusable. B-08 revokes every v2 long key too (SD6).
- 0009: the deploy is still a manual SHA run. SD7's one-time sequence is a runbook section, not a workflow change.
- 0002 and 0012: `exchange/` is not touched (AC20).

No ADR is reversed. No new dependency: `argon2-cffi` is already a dependency (`pyproject.toml:45-46`), and its `argon2.low_level.hash_secret` takes an explicit salt in every version the bound admits.
Backlog: [B-08](../backlog.md) · Fixes: D-50 · Amends: Phase 3 SD5 and SD6, Phase 6 SD30, Phase 8 SD9, `architecture.md` § Authorization, `deploy.md`, `venue.md`, `rollback.md` (T8)

Line references are to `main` at `3778ba9`.

---

## Approach

**One short-key module, one lookup by hash, and a switch made in one task.**
- **The symbols are B-05's.** B-05 already draws and reads Crockford base32 (`app/runtime/wallet_codes.py:21-49`). Its `ALPHABET`, its draw and its forgiving read move into a leaf, `app/runtime/crockford.py`, parameterised by length. `wallet_codes` keeps its names and calls the leaf with 8, so B-05's behaviour and tests do not change. Keys call it with 9.
- **The key is hashed with a fixed salt and fixed parameters** (`argon2.low_level.hash_secret`, argon2id). Equal symbols always give an equal encoded hash. The existing `auth_key.secret_hash` column gets a `UNIQUE` constraint, and login does one `SELECT … WHERE secret_hash = :h`. No new column: a pre-B-08 image must still mint against this schema (SD6, AC13), and it writes only `secret_hash`.
- **Minting is one atomic insert per draw.** `INSERT … ON CONFLICT (secret_hash) DO NOTHING RETURNING key_id` returns no row on a collision, so the redraw needs no savepoint and no read-then-write race. The `key_id` comes back from the insert, so the placeholder hash and `set_secret_hash` go (`security.py:88-102`).
- **The switch is one task (T4).** Mint and login change together, or a minted key could not log in. Two refactors come first so T4 stays reviewable:
  - T1 adds the pure primitives beside the old ones;
  - T3 makes `issue_key` the only way any code or test mints, returning `{key_id, key}` as a value, while keys are still long.

  After T3, T4 changes what `issue_key` makes and how login finds it, and every test follows without a sweep.

**Web: the dialog and one attribute.**
- `KeysSection` shows the grouped key in a larger monospaced `<code>`. "Kopieer" awaits `writeText` inside `try`. Any failure selects the `<code>`'s text and shows SD9's line. A missing `navigator.clipboard` throws inside the `try`, so it is caught too (D-50).
- The login input gets `autoCapitalize="characters"`. Nothing else on the page changes.
- A new e2e, `keys.spec.ts`, runs the spec's story at `http://keys.test:<port>`, B-06's insecure-origin mapping (`payments.spec.ts:50`).

Rejected:
- **A second column for the new hash** (`key_hash`, nullable): a pre-B-08 image writes only `secret_hash` (NOT NULL), so the row would carry two hash columns with one always meaningless. Reusing the column keeps the rollback guarantee with no extra writes.
- **A partial unique index** (unrevoked rows only): SD3 says unique across every row, revoked ones included.
- **Select-then-insert for collisions:** two round trips and a race, where `ON CONFLICT` is one statement.
- **Following `PasswordHasher()`'s defaults at runtime:** a library upgrade that changed them would silently make every stored key unfindable. The parameters are pinned to today's defaults, and a test fails if they ever drift apart (PD2).
- **Normalising on the client:** SD2 puts the reading on the server.
- **A per-key test helper per test file:** today eight files copy the same create/hash/format sequence. T3 replaces all of them with `issue_key`.

---

## Decisions this plan makes

Rows marked **Confirm** are readings the audit confirms or overrules. **Owner** is a hard stop the audit cannot settle. The rest follow from the spec and the code.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | Where the Crockford reading lives | **`app/runtime/crockford.py`** (new leaf, stdlib only):<br>• `ALPHABET`;<br>• `draw(length) -> str`, each symbol `secrets.choice(ALPHABET)`;<br>• `read(text, length) -> str \| None`: `strip()`, `upper()`, remove every `-` and space, `O→0`, `I→1`, `L→1`, then exactly `length` symbols of `ALPHABET` or `None`.<br>`wallet_codes.py` re-exports `ALPHABET`. Its `new_short_code` and `normalise_short_code` become one-line calls with `SHORT_CODE_LENGTH`. **Confirm** | SD2 is B-05 SD14's reading. One implementation means the two cannot drift. `tests/unit/test_wallet_codes.py` pins B-05's behaviour unchanged. |
| PD2 | The hash | In `app/api/security.py`:<br>• `_KEY_SALT: Final = bytes.fromhex("<32 hex>")`, drawn once by the builder with `secrets.token_hex(16)` and never changed after merge;<br>• `_KEY_PARAMS`: `time_cost=3`, `memory_cost=65536`, `parallelism=4`, `hash_len=32`, `type=Type.ID`;<br>• `key_hash(symbols) -> str` is `argon2.low_level.hash_secret(symbols.encode(), _KEY_SALT, **_KEY_PARAMS).decode("ascii")`, the same `$argon2id$v=19$…` encoding `PasswordHasher` writes.<br>A unit test pins:<br>• `_KEY_PARAMS` equal to `argon2.profiles.RFC_9106_LOW_MEMORY` (the profile `PasswordHasher()` uses today);<br>• one known-answer vector: fixed symbols give a fixed hash string.<br>**Confirm** (pinned, not "the library default at runtime") | SD3: "the library defaults used today (RFC 9106)". "Used today" pinned means a library upgrade cannot change the stored form. The vector catches a changed salt. |
| PD3 | The key's functions | In `app/api/security.py`:<br>• `KEY_LENGTH = 9`;<br>• `new_key_symbols() = crockford.draw(9)`;<br>• `normalise_key(raw) = crockford.read(raw, 9)`;<br>• `display_key(symbols)` gives `"K7M-4QX-9PR"`;<br>• `@dataclass(frozen=True) IssuedKey(key_id: int, key: str)`, where `key` is the grouped form;<br>• `class KeyDrawExhausted(RuntimeError)`. | `wallet_codes`' shape (`new_short_code`, `normalise_short_code`, `display_short_code`). |
| PD4 | Login (SD3's order) | `async def find_login(raw, lookup, *, hasher=key_hash) -> AuthKeyRow \| None`:<br>1. `normalise_key`; `None` returns `None`, with no hash and no lookup;<br>2. `h = await asyncio.to_thread(hasher, symbols)`;<br>3. `row = await lookup(h)`;<br>4. `None` if no row or the row is revoked, else the row.<br>The route passes `hasher=security.key_hash`, read off the module at call time as today (`auth.py:73-74`), so a test counts hashes by monkeypatching `security.key_hash`. The limiter still runs first (`auth.py:58-65`), unchanged. | The spec's Verification asks for counting "through the verifier hook `app/api/auth.py:74` uses today or its replacement". |
| PD5 | Minting | **The repository.** `app/db/keys.py` gains:<br>• `insert_key(conn, *, label, role, secret_hash) -> int \| None`: `ON CONFLICT (secret_hash) DO NOTHING RETURNING key_id`;<br>• `get_key_by_hash(conn, secret_hash) -> AuthKeyRow \| None`.<br>**`issue_key(conn, *, role, label, draw=None) -> IssuedKey`** tries up to 5 times:<br>1. `symbols = (draw or new_key_symbols)()`, with `new_key_symbols` read off the module at call time;<br>2. `h = key_hash(symbols)`;<br>3. `insert_key(...)`. A `key_id` returns `IssuedKey(key_id, display_key(symbols))`.<br>After 5 conflicts it raises `KeyDrawExhausted`. Nothing was inserted, and the caller's transaction rolls back.<br>**On a give-up:** the CLI catches it and exits 1 with `keys: no free key after 5 draws, nothing written`. The API lets it reach the generic 500 (`app/core/errors.py:40-41`).<br>The hash runs on the calling thread, as `issue_key` does today (`security.py:101`). | SD3, AC9. The injected `draw` serves the unit test, and the module lookup serves the API and CLI tests. Keeping the hash where it runs today keeps scope tight (see Risks R7). |
| PD6 | What goes (T4) | **From `security.py`:** `KEY_PREFIX`, `_SECRET`, `ParsedKey`, `mint_secret`, `format_key`, `parse_key`, `_PLACEHOLDER_HASH`, `hash_secret`, `verify_secret`, `dummy_hash`, `verify_login`, `_hasher`, and the `argon2.exceptions` import. `_KEY_ID` stays, because `read_session` uses it (`:165`).<br>**From `app/db/keys.py`:** `create_key` and `set_secret_hash`.<br>**`tests/unit/test_key_format.py`** is deleted. `test_short_keys.py` (T1) replaces it.<br>**`tests/meta/test_no_v1_key_import.py`'s allow-list** becomes `insert_key` and `key_hash` callable only from `issue_key`, and `insert(AuthKey)` allowed only in `insert_key`. Its docstring and planted samples follow. | SD3: "`dummy_hash()` has no remaining use". Dead code would invite a second mint path. |
| PD7 | How tests mint (T3) | Every test that mints calls `issue_key` in a transaction. This replaces the eight hand-written create/hash/format copies (`tests/api/conftest.py:131-133`, `tests/api/ws_fixture.py:129-132`, and six in `tests/integration/`). The `mint_key` fixture still returns `str`. A new `issued_key` fixture in `tests/api/conftest.py` returns `IssuedKey` for the tests that need the `key_id`. Those are the `security.parse_key(raw).key_id` sites in `test_auth.py`, `test_authorization_matrix.py`, `test_ws.py`, `test_ws_revoke.py` and `test_keys.py`. `test_cli_keys.py` still parses in T3 and is rewritten in T4. **Confirm** | One mint path in tests too. After T3, T4's format change reaches every test through `issue_key`. |
| PD8 | The pre-B-08 path in the migration test (AC13) | `tests/integration/test_migration_0015.py` carries a frozen copy of the pre-B-08 behaviour as plain SQL plus `argon2.PasswordHasher()`. `_old_mint` inserts with `'pending'`, then updates to `PasswordHasher().hash(secret)` and returns `bb_<id>_<secret>`. `_old_login` splits on `_`, selects by `key_id` and verifies. A comment says it is frozen from `main` at `3778ba9`, `app/api/security.py:77-120, :230-251`, and must never follow the live code. | After T4 the live code no longer has that path. A frozen copy is this repo's pattern for "the old behaviour" (`tests/engine/v1_reference/`). |
| PD9 | Migration `0015` | `0015_short_keys.py`:<br>• `upgrade()`: `UPDATE auth_key SET revoked_at = now() WHERE revoked_at IS NULL`, then `op.create_unique_constraint("auth_key_secret_hash_key", "auth_key", ["secret_hash"])`;<br>• `min_code_revision = "unchanged"`;<br>• `downgrade()` drops the constraint and un-revokes nothing (SD6).<br>The docstring says why "unchanged" is honest: a pre-B-08 image's insert of `'pending'` is followed by its update in the same transaction, so two concurrent old mints serialise on the constraint and both succeed (T2 tests it). `app/db/models.py` `AuthKey.__table_args__` gains the matching `UniqueConstraint`, so `test_the_models_match_the_migrated_schema` stays green. | SD6, AC10, AC13. |
| PD10 | The dialog (SD8, SD9) | `KeysSection.tsx`:<br>• the key is a `<code className={styles.key}>`: monospaced, `1.75rem`, letter-spaced, `user-select: all`, with a ref;<br>• `copy()`: `try { await navigator.clipboard.writeText(secret); setCopyFailed(false) } catch { window.getSelection()?.selectAllChildren(ref.current); setCopyFailed(true) }`;<br>• `copyFailed` shows "Kopiëren lukt hier niet. De sleutel is geselecteerd: kopieer hem zelf." with `role="status"`;<br>• a new key and "Sluiten" reset `copyFailed`.<br>The text stays in a `<code>` element, so the four existing e2e readers (`keys.locator('code')`) still find it. | SD9. `navigator.clipboard.writeText` on an undefined `clipboard` throws `TypeError` synchronously inside the `async` body, so it becomes a rejection the `catch` sees. |
| PD11 | The Phase 8 SD9 sentence | The original text stays. It gets a `> **Amended by B-08** (…)` note saying the "256-bit random secret" rationale no longer holds and the numbers are B-08 SD4's table. This is the B-02 / B-06 note style (`phase-6-admin.md:472`, `phase-5-bar-orders.md:109`). **Confirm** | SD4 says "replaced by a pointer". The repo's convention is to keep superseded text and point forward. |
| PD12 | `docs/design/data-model.md:35` | It says `argon2id secret_hash`, still true, but it will not mention the new `UNIQUE`. Recommendation: T8 adds **UNIQUE** to that row, beside the column. It is a change to `docs/design/` that SD11 did not approve. **Owner — approved at the audit (2026-10-27, "accept"): T8 adds UNIQUE to that row.** | CLAUDE.md hard stop: "changes anything in `docs/design/`". |
| PD13 | Existing tests that B-08 makes untrue | Each changes in the task that causes it:<br>• `tests/unit/test_key_format.py`: deleted (T4, PD6);<br>• `tests/unit/test_security.py:187-300` (`verify_login`): replaced by `find_login` cases, already in T1's `test_short_keys.py`, so the section is deleted along with its imports (T4);<br>• `tests/api/test_auth.py:131-154`: `format_key(...)` unknown and wrong-secret cases become a fresh 9-symbol key; the malformed case gains `bb_…`, 8 and 10 symbols (T4);<br>• `tests/api/test_v1_keys.py:56-77`: the counter hooks `key_hash`; the anti-vacuity case becomes "a well-formed 9-symbol key reaches the lookup" (T4);<br>• `tests/integration/test_cli_keys.py:18`, `:54-61`: the `KEY_SHAPE` regex becomes `^[0-9A-HJKMNP-TV-Z]{3}(-[0-9A-HJKMNP-TV-Z]{3}){2}$`, and the hash is checked by `key_hash` equality (T4);<br>• `tests/api/test_keys.py:65-70`: `key_id` from the response, the hash equal to `key_hash(normalise_key(key))` (T4);<br>• the e2e `toMatch(/^bb_/)` checks (`admin.spec.ts:78`, `analytics.spec.ts:89`, `payments.spec.ts:141`, `wallets.spec.ts:143`) become the grouped pattern (T6);<br>• `KeysSection.test.tsx:35`'s `SECRET` becomes a grouped key (T5).<br>`tests/integration/test_proxy_keying.py:24`'s `NOT_A_KEY` turns from well-formed to malformed. It asserts only limiter buckets, so it stays. A failure there is a stop-and-ask.<br>Any **other** existing test that fails for a B-08 reason is a stop-and-ask. | Found by a search of `tests/` and `web/` for `bb_`, `parse_key`, `format_key`, `mint_secret`, `hash_secret`, `verify_secret`, `dummy_hash` and `set_secret_hash`. |

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `app/runtime/crockford.py` | Create | PD1 |
| `app/runtime/wallet_codes.py` | Modify | PD1: calls the leaf, names unchanged |
| `app/api/security.py` | Modify | T1: PD2–PD4 added · T3: `IssuedKey` · T4: PD5 internals, PD6 removals, docstring |
| `tests/unit/test_short_keys.py` | Create | T1: AC1 (alphabet, length, provenance), AC2, AC4, AC5 (pure), PD2's pins |
| `db/migrations/versions/0015_short_keys.py` | Create | PD9 |
| `app/db/models.py` | Modify | PD9: the `UniqueConstraint` |
| `app/db/keys.py` | Modify | T2: `insert_key`, `get_key_by_hash` · T4: drop `create_key`, `set_secret_hash`, docstring |
| `tests/integration/test_migration_0015.py` | Create | AC10–AC13, PD8 |
| `tests/integration/test_auth_key_lookup.py` | Create | T2: `insert_key` conflict, `get_key_by_hash` |
| `tests/meta/test_no_v1_key_import.py` | Modify | T2: `insert_key` allowed · T4: PD6's allow-list |
| `app/api/keys.py` | Modify | T3: `{key_id, key}` from `IssuedKey` · T4: docstring |
| `app/cli/keys.py` | Modify | T3: prints `.key` · T4: `KeyDrawExhausted` → exit 1, docstring |
| `tests/api/conftest.py` | Modify | T3: `mint_key` via `issue_key`, new `issued_key` |
| `tests/api/ws_fixture.py` | Modify | T3: via `issue_key` |
| `tests/integration/{test_export_timing,test_heavy_reads,test_profiles_restart,test_wallets_restart,test_wallet_payments_races,test_wallet_payments_restart}.py` | Modify | T3: via `issue_key` |
| `tests/api/{test_authorization_matrix,test_ws,test_ws_revoke}.py` | Modify | T3: `key_id` from `issued_key` |
| `tests/api/test_auth.py` | Modify | T3: `_key_id` from `issued_key` · T4: AC4–AC7 |
| `tests/api/test_keys.py` | Modify | T3: `key_id` from `issued_key` · T4: AC1, AC3, AC8, AC9 (API), AC14 |
| `app/api/auth.py` | Modify | T4: `find_login` + `get_key_by_hash`, docstring |
| `tests/unit/test_key_format.py` | Delete | T4 (PD6) |
| `tests/unit/test_security.py` | Modify | T4: the `verify_login` section and its imports go |
| `tests/api/test_v1_keys.py` | Modify | T4 (PD13) |
| `tests/integration/test_cli_keys.py` | Modify | T4: AC1, AC3, AC8, AC9 (CLI), AC12 |
| `web/src/features/keys/KeysSection.tsx` | Modify | PD10 |
| `web/src/features/keys/KeysSection.module.css` | Modify | PD10: `.key` |
| `web/src/features/keys/KeysSection.test.tsx` | Modify | AC15, AC16 (unit) |
| `web/src/features/auth/LoginPage.tsx` | Modify | SD10 |
| `web/src/features/auth/auth.test.tsx` | Modify | AC17 |
| `web/e2e/keys.spec.ts` | Create | The spec's Playwright story |
| `web/e2e/{admin,analytics,payments,wallets}.spec.ts` | Modify | PD13: the grouped pattern |
| `scripts/smoke.py` | Modify | Docstring (AC18) |
| `tests/integration/test_smoke_script.py` | Modify | AC19 |
| `docs/design/architecture.md` | Modify | SD11 |
| `docs/design/data-model.md` | Modify (PD12, approved) | PD12 |
| `docs/specs/phase-3-api-realtime.md` | Modify | Notes on SD5, SD6 |
| `docs/specs/phase-6-admin.md` | Modify | Note on SD30 |
| `docs/specs/phase-8-deploy-cutover.md` | Modify | Note on SD9 (PD11) |
| `docs/runbooks/deploy.md` | Modify | SD7's one-time section, the key's form, the smoke-failure exception |
| `docs/runbooks/venue.md` | Modify | The key's form; old keys revoked at the first B-08 start |
| `docs/runbooks/rollback.md` | Modify | SD6's rollback note |
| `docs/specs/defect-register.md` | Modify | D-50 "fixed in B-08", the B-08 evidence row |

---

## Tasks

### T1 — The short-key primitives
- **Implements:** AC1 (the draw: 9 symbols of the alphabet, from `secrets`), AC2 and AC4 (the reading), AC5 (one hash off the loop and one lookup, as a pure function). SD1, SD2, SD3; PD1–PD4.
- **Expected output:**
  - `app/runtime/crockford.py` as PD1. `wallet_codes.py` calls it, with every public name unchanged.
  - In `security.py`, **added beside the old functions** (nothing removed, nothing rewired):
    - `KEY_LENGTH`, `new_key_symbols`, `normalise_key`, `display_key`;
    - `key_hash`, with `_KEY_SALT` and `_KEY_PARAMS`;
    - `IssuedKey`, `KeyDrawExhausted`;
    - `find_login`.
  - **`tests/unit/test_short_keys.py`** covers:
    - **the draw:** 200 keys, each 9 symbols of the alphabet, nearly all distinct, every symbol of the alphabet seen;
    - **the reading:** `k7m4qx9pr`, `K7M 4QX 9PR`, ` K7M-4QX-9PR\n`, `K 7 M-4Q X9PR` and `O`→`0`, `I`/`L`→`1` all read as the stored form. Malformed: 8 and 10 symbols, a `U`, an `_`, `bb_12_<43 chars>`, an 8-symbol wallet code;
    - **the display:** `display_key("K7M4QX9PR") == "K7M-4QX-9PR"`;
    - **the hash:** PD2's two pins (the parameters equal `RFC_9106_LOW_MEMORY`; one known-answer vector). The same symbols hash equal; different symbols hash different; the output starts `$argon2id$`;
    - **`find_login`**, with a fake lookup and a counting hasher:
      - malformed: zero hashes, zero lookups;
      - unknown, revoked, valid: exactly one hash, on a thread that is not the loop's, and one lookup with that hash;
      - only the valid one returns a row;
    - **provenance (AC1):** an AST scan of `crockford.py` and `security.py` finds no `random` import and `secrets.choice` in `draw`. The same scan, run on a planted `import random` / `random.choice` source, reports it, so the scan can fail (as B-06's `walletCode.provenance.test.ts`).
- **Verification:**
  - `uv run pytest tests/unit/test_short_keys.py tests/unit/test_wallet_codes.py`;
  - `uv run mypy app/runtime/crockford.py app/api/security.py app/runtime/wallet_codes.py`.
- **Depends on:** —
- **Autonomy note:** The builder may choose internal names, the test layout, and how the AST scan is written. It draws `_KEY_SALT` once and commits it. Stop and ask if:
  - `argon2.low_level.hash_secret`'s encoding differs from what `PasswordHasher` writes;
  - `RFC_9106_LOW_MEMORY` is not what `PasswordHasher()` uses in the locked version (PD2's "used today" would then need re-reading);
  - B-05's `test_wallet_codes.py` needs any change.

### T2 — Migration 0015 and the repository lookup
- **Implements:** AC10, AC11, AC12, AC13. SD3 (uniqueness), SD6; PD5 (repository half), PD8, PD9.
- **Expected output:**
  - `0015_short_keys.py`, `models.py` and `insert_key` / `get_key_by_hash` as PD5 and PD9. `insert_key` is not yet called by `app/`.
  - `test_no_v1_key_import.py` allows `insert(AuthKey)` in `insert_key` and `insert_key` only from `issue_key`.
  - **`tests/integration/test_auth_key_lookup.py`:**
    - `insert_key` with a taken hash returns `None` and inserts nothing, revoked rows included;
    - `get_key_by_hash` finds a revoked row and returns `None` for an unknown hash.
  - **`tests/integration/test_migration_0015.py`**, on `empty_database` at `0014` (as `test_0013_admits_…`, `test_migrations.py:477`):
    1. `_old_mint` two keys (PD8) and revoke one. Note its `revoked_at`.
    2. Hold a session for the other: a cookie from `security.issue_session` on its `key_id`.
    3. Upgrade to head.
    4. **AC10:** both rows exist and both are revoked; the earlier `revoked_at` is unchanged; `GET /api/keys` lists both as revoked.
    5. **AC11:** the held cookie's `GET /api/auth/me` is 401, through a `create_app(run_migrations=False)` client on that database (as `test_wallets_restart.py:64`). The old key's long form at login is 401.
    6. **AC12:** `app.cli.keys create --role admin` with no unrevoked admin left exits 0. Its printed line logs in through the same client. The test reads the line as printed and assumes no format, so it holds before and after T4.
    7. **AC13:**
       - `schema_compat.min_code_revision` is the value it had at `0014`;
       - `_old_mint` then `_old_login` succeed against head;
       - two `_old_mint`s on two connections, the second started before the first commits, both commit.
    - A downgrade to `0014` drops the constraint and leaves every `revoked_at` as it was.
- **Verification:** `uv run pytest tests/integration/test_migration_0015.py tests/integration/test_auth_key_lookup.py tests/integration/test_migrations.py`; `uv run pytest tests/meta`.
- **Depends on:** —
- **Autonomy note:** The builder may choose fixtures, and how the concurrent old mints are driven (two `AsyncConnection`s with an explicit ordering). It is a **hard stop** (a broken cross-phase invariant, the rollback floor) if two concurrent pre-B-08 mints cannot both commit under the constraint. That would make `"unchanged"` false. Stop and ask if `create_app` against a scratch database needs more than `test_wallets_restart.py`'s setup.

### T3 — One way to mint a key, still long
- **Implements:** AC3 (the `key_id` is the new row's id, not parsed back out of the key). It is the prerequisite that lets T4 change the key in one place (PD7). SD8.
- **Expected output:**
  - **The app:**
    - `issue_key` returns `IssuedKey(key_id, key)`, still `bb_<key_id>_<secret>` for now;
    - `post_key` returns `CreatedKey(key_id=issued.key_id, key=issued.key)`, so `parse_key` is no longer imported by `keys.py`;
    - the CLI prints `issued.key`.
  - **The tests:**
    - the eight hand-written mint copies call `issue_key` (PD7);
    - `tests/api/conftest.py` gains `issued_key`;
    - the `parse_key(raw).key_id` sites in `test_auth.py`, `test_authorization_matrix.py`, `test_ws.py`, `test_ws_revoke.py` and `test_keys.py` use it;
    - no assertion changes meaning.
  - No behaviour changes. The OpenAPI schema is unchanged, so the API-types drift step stays green.
- **Verification:**
  - `uv run pytest tests/unit tests/meta`;
  - `uv run pytest tests/api`;
  - `uv run pytest tests/integration` (separately, MEMORY: pytest api+integration split).
- **Depends on:** T1 (both write `security.py`)
- **Autonomy note:** A mechanical refactor. The builder may choose the fixture's name and where the integration helpers' `issue_key` call sits. Stop and ask if any test's assertion must change for it to pass: in this task that means a behaviour change crept in.

### T4 — The switch: 9-symbol keys, found by their hash
- **Implements:** AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC14, and AC11/AC12 re-run on the new format. SD1–SD3, SD5, SD8; PD4–PD6, PD13.
- **Expected output:**
  - **`issue_key` as PD5:** 9 symbols, the fixed-salt hash, `insert_key`, up to 5 draws. It returns the grouped key.
  - **`auth.py` login:** `find_login(body.key, lookup, hasher=security.key_hash)`, where `lookup` is `get_key_by_hash` on a fresh connection. Then `touch_last_used` and the cookie, as today.
  - **The CLI** catches `KeyDrawExhausted` and exits 1 (PD5).
  - **PD6's removals** and the meta test's new allow-list.
  - **Docstrings** of `security.py`, `auth.py`, `keys.py`, `app/cli/keys.py` and `app/db/keys.py` describe the 9-symbol key and the hash lookup. No `bb_<…>` is left under `app/`.
  - **Tests, by AC:**
    - **AC1, AC3:**
      - CLI `create` prints one line matching the grouped pattern;
      - `POST /api/keys` returns `key` grouped and `key_id` equal to the new row's;
      - neither contains `bb_` or the `key_id` as a group.
    - **AC2:** the API logs in with each forgiving spelling of one minted key.
    - **AC4, AC5:** `test_auth.py` counts hashes through `security.key_hash`:
      - malformed (PD13's shapes): 0 hashes, 401;
      - unknown, revoked, valid: 1 hash each;
      - unknown and revoked have byte-equal 401 bodies.
    - **AC6:** `last_used_at` is set, and the cookie and `allowed_routes` are as today.
    - **AC7:** the existing limiter tests pass unchanged. One more: the 11th attempt is 429 with zero hashes counted.
    - **AC8:**
      - after a mint, no column of the row holds the grouped or the normalised key;
      - `caplog` over mint and login holds neither;
      - `GET /api/keys` holds neither, and none of its three groups. The groups are not checked against `secret_hash`: a 3-character match in base64 is a ~10⁻³ coincidence, so that check could flake.
    - **AC9:**
      - **unit:** an injected `draw` that returns a taken key 4 times and then a free one makes 5 draws;
      - **unit:** 5 taken draws raise `KeyDrawExhausted` with the row count unchanged;
      - **API:** `security.new_key_symbols` monkeypatched to a taken key gives a 500 `internal_error` with the count unchanged;
      - **CLI:** the same gives exit 1, the message, and no row.
    - **AC14:** `test_keys.py`'s `last_admin_key` test passes unchanged.
    - **AC11, AC12:** `test_migration_0015.py` passes unchanged on the new format.
- **Verification:**
  - `uv run pytest tests/unit tests/meta`;
  - `uv run pytest tests/api`;
  - `uv run pytest tests/integration` (separately);
  - `grep -rn "bb_<\|bb_<key_id>" app/` finds nothing.
- **Depends on:** T1, T2, T3
- **Autonomy note:** The builder may lay out the tests, keep or merge `test_auth.py`'s existing cases, and word the CLI message. Stop and ask if:
  - any test outside PD13's list fails for a B-08 reason;
  - the 401 bodies for unknown and revoked cannot be made byte-equal;
  - a hash cannot be kept off the event loop at login.

### T5 — The dialog and the login field
- **Implements:** AC15, AC16 (unit), AC17. SD8, SD9, SD10; PD10; D-50.
- **Expected output:**
  - `KeysSection.tsx` and `.module.css` as PD10. The header comment describes the grouped key and the fallback.
  - The login input carries `autoCapitalize="characters"`. Nothing else in `LoginPage.tsx` changes.
  - **`KeysSection.test.tsx`** (`SECRET` becomes `'K7M-4QX-9PR'`):
    - the key is shown once in a `<code>` with the `key` class;
    - "Sluiten" removes it from the DOM (existing);
    - **resolving `writeText`:** called with the grouped key, and no hint shown;
    - **rejecting `writeText`:** no throw (no unhandled rejection), the hint shown, and `getSelection().toString()` equal to the key;
    - **`navigator` with no `clipboard`:** the same as rejecting;
    - "Sluiten" after a failure, then a new key: no hint.
  - **`auth.test.tsx`:**
    - the `Toegangscode` input has `autocapitalize="characters"`;
    - label, button and "Ongeldige toegangscode." are unchanged;
    - a malformed key answered 401 shows "Ongeldige toegangscode.".
- **Verification:** `pnpm -C web vitest run src/features/keys/KeysSection.test.tsx src/features/auth/auth.test.tsx`; `pnpm -C web lint`.
- **Depends on:** —
- **Autonomy note:** The builder may choose the exact size and spacing within "larger than body text, monospaced", and the hint's markup. Stop and ask if jsdom cannot report the selection. The fallback is then asserted by a spy on `selectAllChildren`, and T6's e2e is the real check. Say so in the commit.

### T6 — The Playwright story at an insecure origin
- **Implements:** AC2, AC4 (the long key), AC16, AC17 end to end; the spec's e2e steps 1–6. D-50.
- **Expected output:**
  - **`web/e2e/keys.spec.ts`** has its own `startServer('keys', ['--empty'])`, serial, with `--host-resolver-rules=MAP keys.test 127.0.0.1` (as `payments.spec.ts:50`). Every context runs at `http://keys.test:<port>`, and `isSecureContext` is asserted false. The steps:
    1. log in as admin with the server's CLI-minted key, typed lowercase with spaces between groups;
    2. under Toegangssleutels, create a bar key;
    3. "Kopieer": no `pageerror`, the hint visible, `getSelection().toString()` equal to the grouped key;
    4. in a second context, type it without dashes, and land on `/bar`;
    5. revoke the bar key: the second context's `GET /api/auth/me` is 401;
    6. `bb_1_` plus 43 characters at login shows "Ongeldige toegangscode.".
  - The four existing `toMatch(/^bb_/)` checks become the grouped pattern (PD13).
- **Verification:** `pnpm -C web exec playwright test e2e/keys.spec.ts e2e/admin.spec.ts e2e/analytics.spec.ts e2e/payments.spec.ts e2e/wallets.spec.ts`.
- **Depends on:** T4, T5
- **Autonomy note:** The builder may choose selectors and helpers, following `payments.spec.ts`. Stop and ask if Chromium at `http://keys.test` does expose `navigator.clipboard`. That would mean the spec's D-50 premise does not reproduce, and the owner must hear it.

### T7 — The smoke script with a short key
- **Implements:** AC19, and AC18 for `scripts/`.
- **Expected output:**
  - `scripts/smoke.py`'s docstring names `BB_SMOKE_KEY=K7M-4QX-9PR`. Its code is unchanged: it sends the key as given, and the server reads it.
  - `test_smoke_script.py` adds two cases against the real app: the minted key grouped, and the same key without dashes. Each passes every step, and neither output holds the key.
- **Verification:** `uv run pytest tests/integration/test_smoke_script.py`.
- **Depends on:** T4
- **Autonomy note:** Trivial. Stop and ask if `smoke.py`'s code needs any change: the spec says the server does the reading.

### T8 — The documents, the register, and the closing check
- **Implements:** AC18, AC20. SD4 (the pointer), SD6 (the rollback note), SD7, SD11; D-50's evidence.
- **Expected output:**
  - **`architecture.md:197-201`** (SD11): a key is 9 secret symbols with no `key_id`, found by its fixed-salt argon2 hash. One hash per login, no iterating over keys, the limiter still first.
  - **Notes**, each `> **Amended by B-08** ([phase-b-08-short-keys.md](phase-b-08-short-keys.md)) …`:
    - Phase 3 SD5 and SD6 (`phase-3-api-realtime.md:72-82`);
    - Phase 6 SD30 (`phase-6-admin.md:460-470`);
    - Phase 8 SD9 (`phase-8-deploy-cutover.md:187-194`, PD11).
  - **`deploy.md`:**
    - line 15's form becomes `K7M-4QX-9PR`;
    - a section "Once: the B-08 key switch-over", with SD7's four Render steps verbatim in meaning;
    - line 59 names that section as the one expected smoke failure.
  - **`venue.md`:** step 6 shows the key's form, and says the first start of a B-08 bundle revokes every old key, so all keys are minted again (SD7, venue).
  - **`rollback.md`:** SD6's note. After rolling back past B-08 no key works; the way in is a long key minted with that image's own CLI.
  - **`defect-register.md`:** D-50's Phase column reads "fixed in B-08 (…; evidence below)". A `### B-08 evidence` table holds `D-50 | AC16 | T5 (…), T6 (…)`.
  - **`data-model.md:35`** gains **UNIQUE** (PD12, approved at the audit).
- **Verification:**
  - `grep -rn "bb_<\|bb_<key_id>" app/ web/src/ scripts/ docs/runbooks/` finds nothing;
  - `grep -c "Amended by B-08" docs/specs/phase-3-api-realtime.md docs/specs/phase-6-admin.md docs/specs/phase-8-deploy-cutover.md` gives 2, 1 and 1;
  - `git diff main --stat -- exchange/ tests/engine/golden/fixtures/` is empty (AC20);
  - `./scripts/check.sh`, 13/13, output pasted.
- **Depends on:** T6, T7
- **Autonomy note:** The builder may word the notes and the runbook prose. It must not edit any `docs/design/` file beyond SD11's bullet and PD12's word (approved). It must not run any SD7 step: minting the Render, smoke and venue keys is the owner's.

---

## AC coverage

| AC | Tasks |
|---|---|
| AC1 | T1, T4 |
| AC2 | T1, T4, T6 |
| AC3 | T3, T4 |
| AC4 | T1, T4, T6 |
| AC5 | T1, T4 |
| AC6 | T4 |
| AC7 | T4 |
| AC8 | T4 |
| AC9 | T4 |
| AC10 | T2 |
| AC11 | T2, T4 |
| AC12 | T2, T4 |
| AC13 | T2 |
| AC14 | T4 |
| AC15 | T5 |
| AC16 | T5, T6 |
| AC17 | T5, T6 |
| AC18 | T4, T7, T8 |
| AC19 | T7 |
| AC20 | T8 |

---

## Task graph

```
T1 ── T3 ──┐
T2 ────────┴── T4 ──┬── T6 ──┐
T5 ─────────────────┘        ├── T8
                    └── T7 ──┘
```

| Group | Tasks | Files they touch |
|---|---|---|
| G1 | T1, T2, T5 | T1: `app/runtime/{crockford,wallet_codes}.py`, `app/api/security.py`, `tests/unit/test_short_keys.py` · T2: `db/migrations/versions/0015_short_keys.py`, `app/db/{models,keys}.py`, `tests/integration/{test_migration_0015,test_auth_key_lookup}.py`, `tests/meta/test_no_v1_key_import.py` · T5: `web/src/features/keys/KeysSection{.tsx,.module.css,.test.tsx}`, `web/src/features/auth/{LoginPage.tsx,auth.test.tsx}` |
| G2 | T3 | `app/api/{security,keys}.py`, `app/cli/keys.py`, `tests/api/{conftest,ws_fixture,test_auth,test_authorization_matrix,test_ws,test_ws_revoke,test_keys}.py`, six `tests/integration/` mint helpers |
| G3 | T4 | `app/api/{security,auth,keys}.py`, `app/cli/keys.py`, `app/db/keys.py`, `tests/unit/{test_key_format,test_security}.py`, `tests/api/{test_auth,test_v1_keys,test_keys}.py`, `tests/integration/test_cli_keys.py`, `tests/meta/test_no_v1_key_import.py` |
| G4 | T6, T7 | T6: `web/e2e/{keys,admin,analytics,payments,wallets}.spec.ts` · T7: `scripts/smoke.py`, `tests/integration/test_smoke_script.py` |
| G5 | T8 | `docs/design/architecture.md` (+ `data-model.md` if PD12), three phase specs, three runbooks, `docs/specs/defect-register.md` |

No two tasks in one group write the same file:
- `security.py` is T1 (G1), then T3 (G2), then T4 (G3);
- `test_no_v1_key_import.py` is T2 (G1), then T4 (G3);
- `app/db/keys.py` is T2 (G1), then T4 (G3);
- `test_auth.py` and `test_keys.py` are T3, then T4.

T3 waits on T1 only because both write `security.py`.

---

## Data changes

**Migration `0015_short_keys` (PD9).**
- **Backfill:** `UPDATE auth_key SET revoked_at = now() WHERE revoked_at IS NULL`. Every long key is revoked; rows already revoked keep theirs; nothing is deleted.
- **Constraint:** `UNIQUE (secret_hash)`, named `auth_key_secret_hash_key`. Existing hashes carry per-row random salts, so they are already distinct.
- **Compatibility:** `min_code_revision = "unchanged"`. A pre-B-08 image boots, mints (`'pending'`, then its hash, in one transaction) and logs in against this schema (AC13, T2).
- **`downgrade()`:** drops the constraint. It does not un-revoke, so it cannot bring a revoked key back (SD6).

This is not purely additive: the backfill revokes keys, and nothing reverses that. That is SD6's decision, recorded as Q2/Q3. After it, a database has no usable key until the owner mints one by CLI (SD7).

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | The unique constraint could break a rolled-back pre-B-08 image's mint. Its `'pending'` placeholder is the same value in every concurrent insert. | Postgres makes the second insert wait for the first transaction. That transaction updates its row before committing, so no live `'pending'` remains and the second insert proceeds. T2 tests exactly this with two connections. A failure is a hard stop (T2's autonomy note). |
| R2 | A fixed salt means the encoded hash is a stable lookup key, and the salt sits in the repository. | Accepted by the owner (SD4: the offline row; SD3: "a constant in the code"). The salt is not a secret. Only the 45 bits are. |
| R3 | A future `argon2-cffi` could change `PasswordHasher`'s defaults. | PD2 pins the parameters and calls the low-level function, so the stored form cannot drift. A test notices if the pinned set and the library profile part ways. That needs a human decision, not a silent follow. |
| R4 | T3 touches many test files, which strains the ≤10-files guide. | It is a mechanical refactor with three source files (`security.py`, `keys.py`, `cli/keys.py`). The size limit counts source lines (MEMORY: task-size-limit-excludes-tests). Its autonomy note makes any changed assertion a stop. |
| R5 | `tests/image` (not run by `check.sh`) mints keys through the CLI. | It reads the printed line without a format (`test_boot_image.py:62`, `test_kill_drill.py:52`, `test_venue.py:251`), and a grep finds no `bb_` in `tests/image`. The owner's next image drill exercises it. |
| R6 | `tests/meta/test_repo_hygiene.py:106` bans committed `bb_<id>_<secret>` literals. No pattern can ban a 9-symbol key without flagging ordinary text. | Out of scope. A committed short key would be a leaked credential like any other. Keys are minted at runtime in every test and e2e, and `serve.py` writes them under the OS temp dir. |
| R7 | `issue_key` hashes on the event loop, as it does today (`security.py:101`). With up to 5 draws, a worst-case `POST /api/keys` blocks the loop up to ~0.5 s. | A collision has odds near 10⁻¹², so one hash (50–100 ms) is the real case, the same as today. Moving it to a thread is a separate change, not asked for. |
| R8 | jsdom may not implement `Selection.selectAllChildren`/`toString` faithfully. | T5's autonomy note: fall back to a spy, and T6 checks the real selection in Chromium. |
| R9 | AC8's "any part of the key" cannot be checked against `secret_hash` by substring without flaking. | T4 checks the full forms everywhere, and the groups everywhere except the base64 hash (PD13 / T4). |

---

## Out of scope for this plan

- Everything in the spec's Out of scope. In particular: limiter or lockout changes (SD5), a pepper (SD4), keeping long keys (SD6), login wording or auto-formatting (SD10), and minting the Render, smoke and venue keys (SD7, the owner's).
- Moving `issue_key`'s hash off the event loop (R7).
- A source scan banning `navigator.clipboard` outside a helper. D-50 is one call site, and T5/T6 pin it.
- A repo-hygiene pattern for short keys (R6).
- Renaming `auth_key.secret_hash`: the whole key is the secret now. The name stays true enough, and renaming would break the pre-B-08 image (AC13).

---

## Uncertain

- **PD12: settled at the audit.** The owner approved adding **UNIQUE** to `data-model.md:35`.
- **PD2's reading of "the library defaults used today": settled at the audit.** The owner accepted the plan's pinning.
- **R1** rests on Postgres's unique-check behaviour for a tuple updated in the same transaction. I am confident, but T2 tests it before anything depends on it.
- **T3's breadth.** About 17 files, almost all tests. If the auditor wants it split, the natural seam is app plus `tests/api` in one task, `tests/integration` in the other.

---

## Audit (plan-auditor — PASS required before implementation starts)
- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible (accepted: the 0015 backfill revokes keys and is not reversible, by SD6; downgrade drops only the constraint)
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting (accepted: T3 ~17 files, almost all tests; T4 ~14 files; T8 is documents only)
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not (SD7's Render/venue key minting stays the owner's; T8 must not run it)
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audited by: Martijn Boot (owner), all lines accepted in one step ("accept and tick all lines")  Date: 2026-10-27
