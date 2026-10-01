# Plan: Phase 2 — Data model and persistence

Spec: [docs/specs/phase-2-persistence.md](../specs/phase-2-persistence.md) · Status: Approved (by MartijnBoot, 2026-10-01)
Design: [data-model.md](../design/data-model.md), [architecture.md §Durability](../design/architecture.md#durability), [§Where blocking I/O goes](../design/architecture.md#where-blocking-io-goes)
ADRs honoured: 0003 (catch-up budget, gap marker, single writer), 0004 (Postgres everywhere, one DSN), 0009/0010 (hard stops: pricing-maths ambiguity, `docs/design/`, new dependency), 0011 (boot migration is Phase 3's — not wired here)
Defects fixed: D-01, D-09, D-10, D-11, D-12, D-16, D-24, D-30, D-35

---

## Approach

Schema first, in two forward-only migrations, then the code on top of it, bottom-up: pure
functions with unit tests (the gap rule, the `EngineState` codec, the in-memory ring and
earnings aggregate, the v1 file parser), then repositories with integration tests against
scratch databases on the compose `db` (SD16), then `rehydrate`, and finally the two
end-to-end proofs: the import CLI against the real v1 files and the SIGKILL durability
harness (SD1). Every atomic operation the spec names (go-live, a state transition with its
tick, an order with its lines, state and tick, the gap write) is **one function that owns one
`engine.begin()` transaction**, so atomicity belongs to the repository and not to whoever
calls it. Smaller repository primitives take an `AsyncConnection` and never begin or commit,
so the import can compose them inside its single transaction (SD15). Concurrency safety before
Phase 3's lock comes from compare-and-set on `version` (SD9). It is tested by racing two real
transactions, not by mocking.

Rejected: **one migration for all eight tables.** That one task would exceed the size limit,
and `run`/`drink` are needed a whole group earlier than the ledger tables. **One migration
per table**, which would give six serial tasks for no review benefit. **Vertical slices that
each add their own migration**, because two migrations in one parallel group create two
Alembic heads (`tests/meta/test_migration_scaffolding.py:68` fails), which would turn the
whole graph into a chain. **Transaction-rollback test isolation**, because the durability
harness and the concurrency test need committed data visible across connections and
processes. Tests TRUNCATE between cases instead. **`pytest-asyncio`**, which would be a new
dependency. The repo's pattern is a sync test that calls `asyncio.run` on a scenario
(`tests/integration/test_health.py:59-72`), and every test here follows it.

---

## Decisions this plan makes

Choices the spec and design leave open. **PD1 needs explicit confirmation before T2.** It is
a pricing-over-time ambiguity, which is on the hard-stop list (R1). PD3–PD5 change what
`data-model.md` says, so they also need confirming at the audit.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | AC6's formula vs SD2's shift | **SD2 and AC5 win.** Anchors move by exactly `gap − budget`. AC6 is tested as: the first `advance(now)` after rehydrate at `R` puts the jump at elapsed `(wall_ts_ms − t0) + budget + (now − R)`. That is AC6's "(kill − t0) + (now − R)" with "kill" read as the last commit plus the budget Phase 3's ticker will catch up. "No jump completes during the gap" is asserted for a jump whose remaining time exceeds `budget` | SD2 and AC5 both say `gap − budget` explicitly. AC6 is the only statement that disagrees, by exactly `budget`. See R1 |
| PD2 | Drink identity type | `drink_id BIGINT GENERATED ALWAYS AS IDENTITY`. JSON keys are its decimal string | Integer keys are readable in SQL and JSON. No `uuid` extension is needed |
| PD3 | Are `p_min`/`p_max`/`p0` "money columns" (AC9)? | **Yes:** `p_min_cents`, `p_max_cents`, `p0_cents`, `bar_price_cents`, all `INTEGER`. `MarketSpec` gets `cents / 100` | They are euro amounts, and SD7/AC10 name a drink and *field* on inexact cents. `k / 100` is the correctly rounded double of the decimal `repr(v)`, so a value that converts exactly comes back as the identical float (AC19) |
| PD4 | `order` columns in Phase 2 | `order_id`, `run_id`, `idempotency_key` (UNIQUE), `version`, `wall_ts_ms`, `created_at`. **No `total_cents`, `response` or `actor_key_id`.** Phase 3 adds `response` and `actor_key_id` additively when receipts and `auth_key` exist | AC11 says revenue lives only in `order_line`, and `total_cents` would be a second, denormalised copy (D-10's exact shape). The receipt and the actor are Phase 3 behaviour (spec Out of scope) |
| PD5 | News scope | `news.run_id` NOT NULL: news belongs to a run | AC19/AC20 attach imported news to *the* new draft run, and two imports must be independent |
| PD6 | SD14's comparison | A `name_key TEXT NOT NULL` column computed in Python as `name.strip().casefold()`, with a unique index on `(run_id, name_key) WHERE removed_at IS NULL` | Postgres `lower()` under the compose `--locale=C` lowercases ASCII only, so `É`/`é` would collide on Render and not locally (R4) |
| PD7 | Float storage in `engine_state` | Per-drink values and jumps go in **`json`** (text-preserving) columns written with `repr` floats, and non-finite values are rejected. `price_tick.prices`, `run.params` and `run_config_revision.config` are `jsonb` | `jsonb` stores numbers as `numeric`, which drops the sign of `-0.0` and cannot hold NaN. `json` keeps the exact text, so AC3's "bit-exact" holds by construction (R5) |
| PD8 | `source` and `level` enums | `TEXT` plus a `CHECK`, not a Postgres `ENUM` type | SD13 says CHECK. A CHECK is also simpler to extend and to drop in `downgrade` |
| PD9 | Where code lives | Models and repositories in `app/db/` ([architecture.md:54](../design/architecture.md#L54)). Migrations stay in `db/migrations/` (Phase 0, [README.md:39](../../README.md)). Ring, earnings, gap and rehydrate in `app/runtime/` ([architecture.md:51-53](../design/architecture.md#L51-L53)). The import CLI in `app/cli/` | The module layout the design already names |
| PD10 | Typed errors | Defined next to the code that raises them, as `AppError` subclasses (`app/core/errors.py:27`): `DuplicateDrinkName`, `RunNotDraft`, `LiveRunExists`, `StaleState`, `StateDrinkMismatch` | Same idiom as `ConfigError` in `config.py`. It also means no shared `errors.py` that every task would have to edit |
| PD11 | Bar-price precedence (SD15) | `p0`, overridden by the config's `bar_price` key, overridden by `bar_prices.json` | That is what `api.py:167-190` does (the sidecar "takes final precedence", `:174`), and SD15 says "precedence is v1's" (R9) |
| PD12 | Unknown drink names in `bar_price` / `bar_prices.json` | **Rejected**, naming the key. v1 ignores them silently (`api.py:183,186`) | Every external input is validated. A typo should fail the import, not price a drink at `p0` (R11) |
| PD13 | News level input casing | The four levels are accepted case-insensitively (`Info`, `info`, `INFO`), stored lowercase, and anything else is rejected | AC16 rejects "any other value". An already-lowercase level is the same value, not another one |
| PD14 | Go-live with `auto_calibrate_s0: true` | Rejected with a typed error naming the parameter | `initial_state` leaves calibration to the caller (`exchange/state.py:216-218`), and doing it here would rewrite `drink.s0` (an admin edit, Phase 6). Rejecting means it never silently diverges (R10) |
| PD15 | Integration-test isolation | A session-scoped scratch database `bb_test_<hex>`, migrated by running `python -m alembic` as a **subprocess** with `DATABASE_URL` overridden, and TRUNCATE of every table in `Base.metadata` before each test | `env.py` reads the DSN through the cached `get_settings()`. A subprocess sees exactly the scratch URL. Truncating from metadata means T4 needs no conftest edit |
| PD16 | Gap version | The gap transition bumps `version` by 1 and leaves `tick_index` and `rng_counter` alone | It is an accepted transition with a tick row (AC5: "the next `version`"), not a scheduled tick (Phase 1 D9) |

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `db/migrations/versions/0002_runs_and_drinks.py` | Create (T1) | `run`, `run_config_revision`, `drink`, the single-live-run index, the name-key index |
| `db/migrations/versions/0003_state_ledger_news.py` | Create (T4) | `engine_state`, `price_tick`, `order`, `order_line`, `news`, with their CHECKs and UNIQUE |
| `app/db/__init__.py` | Create (T1) | Package marker |
| `app/db/models.py` | Create (T1), Modify (T4) | SQLAlchemy 2.0 declarative models (`Mapped[...]`) for the eight tables |
| `tests/integration/conftest.py` | Create (T1) | Scratch database, migrate-by-subprocess, per-test TRUNCATE (PD15) |
| `tests/integration/test_migrations.py` | Create (T1) | AC23 round-trip; AC22 and SD14 indexes at the SQL level |
| `tests/integration/test_schema.py` | Create (T4) | AC9 money-column inspection; AC11 "no other revenue column"; AC16 CHECK; source CHECK; UNIQUE |
| `app/runtime/__init__.py`, `app/runtime/gap.py` | Create (T2) | Pure SD2 gap rule, `DEFAULT_CATCH_UP_BUDGET_MS = 30_000` |
| `tests/unit/test_gap.py` | Create (T2) | AC4/AC5/AC6 on the pure function |
| `app/cli/__init__.py`, `app/cli/v1_files.py` | Create (T3) | Pydantic models for the three v1 files; exact-cents conversion (SD7); level mapping; bar-price precedence |
| `tests/unit/test_v1_files.py` | Create (T3) | AC10, AC16 and PD11–PD13 without a database |
| `app/db/session.py` | Create (T5) | `create_engine(settings) -> AsyncEngine` |
| `app/db/runs.py` | Create (T5), Modify (T8) | `create_draft_run`, `add_drink`, `set_bar_price`, `append_config_revision`, `active_drinks`; later `go_live` |
| `app/db/mapping.py` | Create (T5) | Active drink rows (by slot) ↔ `MarketSpec` and `drink_ids`; `cents_from_quantised(p_q)` (SD7) |
| `tests/integration/test_runs.py`, `tests/unit/test_mapping.py` | Create (T5) | AC15; AC12 (set half); mapping exactness |
| `app/db/codec.py` | Create (T6) | `EngineState` ↔ `drink_id`-keyed JSON (SD8, PD7); key-mismatch detection |
| `tests/unit/test_codec.py` | Create (T6) | AC3 (codec half); AC14 (codec half) |
| `app/runtime/history.py`, `app/runtime/earnings.py` | Create (T7) | `HistoryRing` (SD11) and `EarningsAggregate` (SD12) |
| `tests/unit/test_history_ring.py`, `tests/unit/test_earnings.py` | Create (T7) | AC21 (window logic), AC17 (pure in-memory reads) |
| `app/db/engine_state.py` | Create (T8), Modify (T12) | `load_state`, `save_transition` (CAS + tick), `load_ticks_in_window` |
| `tests/integration/test_engine_state.py` | Create (T8) | AC3, AC13 (CAS half), AC14, AC22 (via `go_live`) |
| `app/db/news.py`, `tests/integration/test_news.py` | Create (T9) | `create_news`, `list_news`; AC16 |
| `tests/meta/test_no_file_io.py` | Create (T10) | AC18 |
| `docs/design/data-model.md` | Modify (T11) | SD4, SD8, SD10, PD3–PD7 |
| `app/db/orders.py`, `tests/integration/test_orders.py` | Create (T12) | `write_order`, `earnings_by_drink`; AC2, AC11, AC13 |
| `app/cli/import_v1.py`, `tests/integration/test_import_v1.py` | Create (T13) | The SD15 CLI; AC19, AC20, AC10/AC16 end-to-end |
| `CLAUDE.md` | Modify (T13) | One line under Commands: the import CLI |
| `app/runtime/rehydrate.py`, `tests/integration/test_rehydrate.py` | Create (T14) | `rehydrate`; AC4–AC8, AC12, AC14, AC17, AC21 |
| `tests/integration/durability/__init__.py`, `harness.py` | Create (T15) | The SD1 subprocess harness |
| `tests/integration/test_durability.py` | Create (T15) | AC1, AC5, AC6 across a hard kill |

**No new dependency.** Everything uses `sqlalchemy[asyncio]`, `asyncpg`, `alembic`,
`pydantic` and `numpy`, already approved in `pyproject.toml:18-38`, plus the standard
library (`decimal`, `json`, `subprocess`, `secrets`). Not added: `openpyxl` (SD5),
`pytest-asyncio` (the `asyncio.run` pattern above) and testcontainers (SD16; it is already a
dev dependency and stays unused).

---

## Tasks

Every task leaves `./scripts/check.sh` green. Branches follow `feature/phase-2-tN-<slug>`.
Integration tests use the T1 fixtures and the `asyncio.run` pattern of
`tests/integration/test_health.py:59-72`. Nothing touches `exchange/`, so `engine-guardian`
has no diff to guard. The golden replay stays green (`uv run pytest tests/engine`).

### T1 — Scratch-database harness and the run/drink schema

- **Implements:** AC23; AC22 (database half); AC15 (index half); SD4 (3 of 8 tables); PD2, PD6, PD15
- **Expected output:**
  - `0002_runs_and_drinks` with `down_revision = "0001"`. Tables:
    - `run(run_id identity PK, status TEXT CHECK IN ('draft','live','ended') DEFAULT 'draft', run_seed BIGINT NOT NULL CHECK ≥ 0, tick_interval_ms INTEGER NOT NULL DEFAULT 1000, params JSONB NOT NULL, created_at, started_at NULL, ended_at NULL)`, plus partial unique index `run_one_live ON run ((true)) WHERE status = 'live'` (SD6).
    - `run_config_revision(run_id FK, revision INTEGER ≥ 1, config JSONB, author TEXT, created_at; PK (run_id, revision))`.
    - `drink(drink_id identity PK, run_id FK, slot INTEGER ≥ 0, name TEXT, name_key TEXT, p_min_cents / p0_cents / p_max_cents INTEGER with CHECK p_min_cents < p0_cents < p_max_cents, a / d / s0 / c DOUBLE PRECISION, bar_price_cents INTEGER ≥ 0, added_at, removed_at NULL; UNIQUE (run_id, slot))`, plus `drink_name_live ON drink (run_id, name_key) WHERE removed_at IS NULL` (SD14).
  - `downgrade()` drops all of it, so `downgrade base` returns to an empty schema.
  - `app/db/models.py`: `Base(DeclarativeBase)` and the three models, column-for-column with the migration.
  - `tests/integration/conftest.py`: a session fixture that creates `bb_test_<hex>` through an AUTOCOMMIT connection on `settings.database_url`, runs `[sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"]` with the scratch URL in the child's environment, yields the scratch DSN, and drops the database `WITH (FORCE)` afterwards. At session start it also drops `bb_test_%` leftovers from killed runs. A per-test fixture TRUNCATEs `Base.metadata.sorted_tables` `RESTART IDENTITY CASCADE`. The module docstring explains why the env is overridden in a subprocess (PD15) and why that does not violate AC3 of Phase 0 (`tests/` is not a scanned root, `tests/meta/test_config_boundary.py:62`).
- **Verification:** `uv run pytest tests/integration/test_migrations.py -v`:
  - On a *second*, separate scratch database: `upgrade head`, then `downgrade base`, then `upgrade head`, each exiting 0, with the table set checked after each step (AC23).
  - Setting a second run to `'live'` by direct SQL raises `IntegrityError` (AC22).
  - Inserting two non-removed drinks with one `name_key` raises; one removed and one live does not.
  - The gate runs this file in step 9 (`scripts/check.sh:84`), which is AC23's "the gate shall run this". `uv run pytest tests/meta/test_migration_scaffolding.py` (one head).
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** fixture names, the scratch-name scheme, index names, `created_at` defaults (`now()`), and whether the AC23 database is created by the same helper.
  - **Must stop and ask about:** any column, type or constraint other than those listed. That is the data model, and it is a hard stop. Also stop if the compose or CI user cannot `CREATE DATABASE` (R7). Never point any test at the developer's own `borrelbeurs` database.

### T2 — The gap rule, pure

- **Implements:** AC4, AC5, AC6 (pure halves); SD2; PD1, PD16
- **Expected output:** `app/runtime/gap.py`:
  - `apply_gap_rule(state, *, last_wall_ts_ms, now_ms, budget_ms) -> EngineState | None`.
  - It returns `None` when `now_ms − last_wall_ts_ms ≤ budget_ms`, including a negative gap.
  - Otherwise it returns a new state where `last_order_ts` (every drink), `last_idle_ms`, `last_bm_ms` and every jump's `t0_ms` and `t1_ms` are moved by exactly `gap − budget_ms`, and `version` is +1. `y`, `cum_orders`, `flow_ema`, `rng_counter`, `tick_index` and `t_round` stay bitwise unchanged.
  - `DEFAULT_CATCH_UP_BUDGET_MS = 30_000` cites ADR 0003. The function takes the budget as a parameter (SD2: "not a literal in the function").
- **Verification:** `uv run pytest tests/unit/test_gap.py -v`:
  - `None` at `gap = budget` and at `gap < 0`.
  - At `gap = budget + 1` and at hours of gap, every anchor is `+ (gap − budget)` and every other field is `np.array_equal` or `==`.
  - `prices_from_y` gives the same prices before and after.
  - **AC6:** with a 120 s jump started 40 s before `last_wall_ts_ms` and a 10-minute gap, the first `advance(now_ms=R + 5 000)` after the shift gives the `y` that `apply_jumps` gives at elapsed `40 000 + budget + 5 000` (PD1), and the jump is still in `state.jumps`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the function and constant names, and whether `None` or the input state signals "no change". The caller must be able to tell the two apart.
  - **Must not** bump `tick_index` or touch `y`. If PD1 is rejected at the audit, **do not start until the audit records the replacement formula**: this is pricing over time, a hard stop.

### T3 — v1 file parsing and exact-cents conversion, pure

- **Implements:** AC10, AC16 (import-mapping halves); SD7, SD13, SD15 (validation); PD11–PD13
- **Expected output:** `app/cli/v1_files.py`:
  - Pydantic models for `exchange_config.json`: `names` and the seven arrays of equal length, `params` going through `Params.from_dict` so an unknown key is an error, and an optional `bar_price` map. Also models for `news.json` (a list of `{id, ts_ms, level, text}`) and `bar_prices.json` (a map from name to euros).
  - `euro_to_cents(value, *, drink, field) -> int` via `Decimal(str(value)) * 100`. It raises `InexactCents` naming the drink and the field when the result is not integral.
  - `resolve_bar_prices(config, sidecar) -> dict[name, cents]` (PD11, PD12).
  - `normalise_level(raw) -> Literal["info","success","warning","danger"]` (PD13).
  - `ImportPlan`, a frozen value holding everything the writer needs: drinks in slot order with cents and coefficients, params, bar cents and news. The file reads happen here; this module is the one place outside `tests/` allowed to read a file (AC18).
- **Verification:** `uv run pytest tests/unit/test_v1_files.py -v`:
  - Parsing the real `legacy/v1/config/exchange_config.json` and `legacy/v1/static/news.json` succeeds.
  - `2.6 → 260`, `0.1 → 10`, `1.005 → InexactCents` naming drink and field, and `2.675`, `1e-3` likewise.
  - Each precedence layer wins over the one below it.
  - An unknown sidecar name is rejected.
  - `Danger`/`danger` → `danger`, while `Critical` and `""` are rejected.
  - Arrays of unequal length and an unknown params key are rejected.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** model and function names, error message wording (it must name the drink and the field), and whether `InexactCents` subclasses `ValueError`.
  - **Must stop and ask about:** relaxing any rejection, which would change what the import accepts. Never edit anything under `legacy/v1/`.

### T4 — The state, ledger and news schema

- **Implements:** AC9, AC11 (schema half), AC16 (database half); SD4 (5 of 8 tables), SD8, SD10, SD13; PD4, PD5, PD7, PD8
- **Expected output:**
  - `0003_state_ledger_news` with `down_revision = "0002"`. Tables:
    - `engine_state(run_id PK FK, y / cum_orders / flow_ema / last_order_ts / jumps JSON NOT NULL, last_idle_ms / last_bm_ms / rng_counter / version / tick_index / t_round / wall_ts_ms BIGINT NOT NULL, updated_at)`.
    - `price_tick(run_id FK, version BIGINT, source TEXT CHECK IN ('tick','order','jump','idle','reset','gap'), prices JSONB NOT NULL, wall_ts_ms BIGINT NOT NULL, created_at; PK (run_id, version))`.
    - `"order"(order_id identity PK, run_id FK, idempotency_key TEXT NOT NULL UNIQUE, version BIGINT NOT NULL, wall_ts_ms BIGINT NOT NULL, created_at)`.
    - `order_line(order_line_id identity PK, order_id FK ON DELETE CASCADE, drink_id FK, qty INTEGER > 0, unit_price_cents INTEGER ≥ 0, line_total_cents INTEGER, p_cont DOUBLE PRECISION, CHECK line_total_cents = qty * unit_price_cents, UNIQUE (order_id, drink_id))`.
    - `news(news_id identity PK, run_id FK, ts_ms BIGINT, level TEXT CHECK IN ('info','success','warning','danger'), text TEXT NOT NULL, created_at, deleted_at NULL)`.
  - `downgrade()` drops these five.
  - The models are added to `app/db/models.py`.
- **Verification:** `uv run pytest tests/integration/test_schema.py -v`:
  - **AC9:** reading `information_schema.columns` for the eight tables, every `*_cents` column is `integer` or `bigint`. Every `real` / `double precision` / `numeric` / `money` column is in an explicit non-money allowlist (`drink.a`, `.d`, `.s0`, `.c`, `order_line.p_cont`). The test fails on any column not in either list, so a future `price NUMERIC` cannot slip in. A self-test shows the detector flags an injected `NUMERIC` column.
  - **AC11:** no column anywhere matches `revenue|total|earn` except `order_line.line_total_cents`.
  - **AC16:** inserting level `'Info'` raises `IntegrityError`.
  - Source `'bogus'` raises, a duplicate `idempotency_key` raises, and `line_total_cents ≠ qty × unit` raises.
  - `uv run pytest tests/integration/test_migrations.py` still round-trips.
- **Depends on:** T1
- **Autonomy note:** Same as T1. Index names and whether `order_line.drink_id` gets an index are the builder's. If `"order"` quoting causes friction anywhere, **stop and ask** rather than renaming the table (R8).

### T5 — Run and drink repositories, and the spec mapping

- **Implements:** AC15; AC12 (set half); AC14 (mapping half); SD6 (draft creation), SD7 (`cents_from_quantised`), SD14; PD3, PD6, PD10
- **Expected output:**
  - `app/db/session.py`: `create_engine(settings) -> AsyncEngine`, the one place an engine is built from `Settings`.
  - `app/db/runs.py`. Every function takes an `AsyncConnection` and never begins or commits a transaction:
    - `create_draft_run(conn, *, params, run_seed) -> run_id`.
    - `add_drink(conn, run_id, *, name, slot, p_min_cents, …, bar_price_cents) -> drink_id`. It computes `name_key` (PD6) and raises `DuplicateDrinkName` (409), translated from the unique-index violation and naming the clashing name.
    - `set_bar_price(conn, drink_id, cents)`.
    - `append_config_revision(conn, run_id, *, config, author) -> revision`, which takes `max + 1`.
    - `active_drinks(conn, run_id)`, returning rows with `removed_at IS NULL` ordered by `slot`.
  - `app/db/mapping.py`:
    - `spec_from_rows(drinks, params) -> tuple[MarketSpec, tuple[int, ...]]`, the spec plus `drink_ids` in slot order, using `MarketSpec.from_drinks` and `Params.from_dict` from `exchange/` (reuse, not re-implement).
    - `params_to_json(params)`.
    - `cents_from_quantised(p_q) -> int`, which returns `round(p_q * 100)` (SD7).
- **Verification:**
  - `uv run pytest tests/integration/test_runs.py -v`:
    - AC15: `Bier` then ` bier ` is rejected with `DuplicateDrinkName`. `Bier` is accepted again once the first is soft-removed. The same name in two different runs is accepted.
    - AC12 (set half): `set_bar_price` persists the new value.
    - The revision numbers run 1, 2, 3.
  - `uv run pytest tests/unit/test_mapping.py -v`:
    - `spec_from_rows` over the live config's cents equals `tests/engine/golden/replay.py:41` `spec_from_config(live)`, field by field with `np.array_equal`. `MarketSpec` is `eq=False`, so the comparison needs a helper.
    - Rows given out of slot order come back in slot order with matching `drink_ids` (AC14).
    - `cents_from_quantised` is exact on every multiple of 0.1 in `[0, 50]`.
- **Depends on:** T1
- **Autonomy note:**
  - **May decide alone:** Core statements vs ORM, row return types, and the helper names.
  - **Must not** add update or delete paths for drinks beyond `set_bar_price`. Soft removal in tests is a direct `UPDATE`, because the real operation is Phase 6.
  - **Stop and ask** if `MarketSpec` built from the database is not bitwise equal to the one built from the file: that would be a pricing-input divergence.

### T6 — The engine-state codec, pure

- **Implements:** AC3, AC8, AC14 (codec halves); SD8; PD7
- **Expected output:** `app/db/codec.py`:
  - `encode_state(state, drink_ids) -> EncodedState`, mapping column name to JSON text for the five per-drink and jump columns, plus the seven integers. Per-drink arrays become `{str(drink_id): value}` objects. Jumps become `[{drink_id, y0, y1, t0_ms, t1_ms}]`, carrying the drink id rather than the index. It writes with `json.dumps(..., allow_nan=False)`, so a non-finite value raises.
  - `decode_state(encoded, drink_ids) -> EngineState` rebuilds the positional arrays in `drink_ids` order. If the stored key sets differ from `drink_ids`, or a jump names a drink that is not in them, it raises `StateDrinkMismatch` (`AppError`, 500), listing the missing and extra ids.
  - `tick_prices(spec, state, drink_ids) -> dict`, the SD10 shape `{drink_id: {"p_cont", "p_q"}}` via `prices_from_y`.
- **Verification:** `uv run pytest tests/unit/test_codec.py -v`:
  - The round trip is bit-identical (compare `.view(np.uint64)`), including `-0.0`, `5e-324`, `0.1 + 0.2`, `1e308` and `-20.72` (a saturated jump `y1`).
  - `advance(decoded)` and `advance(original)` are `np.array_equal` across a tick and an order.
  - NaN raises.
  - Encoding with `drink_ids = (7, 3)` and decoding with `(3, 7)` gives each drink its own values back, in the new order (AC14).
  - Missing, extra and jump-orphan ids each raise and name the ids.
- **Depends on:** T1 (the `app/db/` package marker only)
- **Autonomy note:**
  - **May decide alone:** the type `EncodedState` takes, and helper names.
  - **Must not** round, normalise or quantise any float. If a value cannot round-trip through `json`, **stop and ask**; do not switch to `jsonb` or to strings without the audit's say (PD7).

### T7 — History ring and earnings aggregate, in memory

- **Implements:** AC17 (structures), AC21 (window logic); SD11, SD12
- **Expected output:**
  - `app/runtime/history.py`: `HistoryRing(window_ms)` holding `TickEntry(version, wall_ts_ms, source, prices)`.
    - `load(entries)` requires strictly ascending `version`.
    - `append(entry)` requires `version >` the last one. It is documented as "call only after the transaction committed" (SD11).
    - Both trim to `wall_ts_ms >= latest.wall_ts_ms − window_ms`, where "latest" is the highest version.
    - `window()` returns a tuple.
  - `app/runtime/earnings.py`: `EarningsAggregate`, a map from `drink_id` to `(qty, revenue_cents)`.
    - `from_rows(rows)`.
    - `add_lines(lines)`, documented as post-commit.
    - `snapshot()` returns an immutable mapping.
  - Neither module imports `sqlalchemy` or opens a file.
- **Verification:**
  - `uv run pytest tests/unit/test_history_ring.py -v`: the window boundary is inclusive at exactly `window_ms` and excluded at +1 ms; trimming happens on `append`; out-of-order `load` or `append` raises; the order is by version.
  - `uv run pytest tests/unit/test_earnings.py -v`: `add_lines` accumulates; a fresh `from_rows` equals the incremental result; the snapshot cannot be mutated.
- **Depends on:** T2 (`app/runtime/__init__.py` is created there; no logical dependency)
- **Autonomy note:**
  - **May decide alone:** whether the ring is a `deque` or a list, and the type names.
  - **Must not** dedupe identical consecutive prices. That is D-28 and Phase 3's (spec Out of scope).

### T8 — Engine-state persistence: load, compare-and-set save, go-live

- **Implements:** AC3, AC13 (compare-and-set half), AC14, AC22 (repository path); SD6 (go-live), SD9, SD10; PD14
- **Expected output:**
  - `app/db/engine_state.py`:
    - `load_state(conn, run_id, drink_ids) -> (EngineState, wall_ts_ms) | None` through `decode_state`.
    - `save_transition(engine, *, run_id, expected_version, state, spec, drink_ids, source, wall_ts_ms)`, which opens **one** `engine.begin()`. Inside it, `UPDATE engine_state … WHERE run_id = :r AND version = :expected`; a row count other than 1 raises `StaleState` (409) and rolls back. Then it inserts the `price_tick` at `state.version` with `tick_prices(...)`.
    - `load_ticks_in_window(conn, run_id, window_ms) -> list[TickEntry]`, ordered by `version`.
  - `app/db/runs.py` gains `go_live(engine, run_id, *, now_ms) -> EngineState`. In one transaction it:
    - requires `status = 'draft'` (`RunNotDraft`), at least one active drink, and `auto_calibrate_s0` false (PD14);
    - sets `status = 'live'` and `started_at`, translating the SD6 index violation to `LiveRunExists` (409);
    - inserts `engine_state` from `exchange.initial_state(spec, now_ms=now_ms)`;
    - inserts the `reset` tick at version 0.
- **Verification:** `uv run pytest tests/integration/test_engine_state.py -v`:
  - **AC3:** go live, then `advance` with `save_transition` ×20 (ticks, one order vector, one `schedule_jump`), then `load_state`. Every float is bit-identical (`.view(np.uint64)`), and the next `advance` from loaded and from in-memory states is equal.
  - **AC14:** swap two drinks' `slot` by direct SQL between save and load. Every drink keeps its own `y`, `cum_orders`, `flow_ema` and `last_order_ts`.
  - **AC22:** `go_live` of a second run raises `LiveRunExists`, and the first stays live.
  - **SD9:** two `save_transition` calls racing with the same `expected_version` (`asyncio.gather` on two connections): exactly one commits, the other raises `StaleState`, and there is exactly one new tick.
  - A stale `expected_version` writes no tick.
  - `go_live` on a live run, with zero drinks, or with `auto_calibrate_s0` all raise and write nothing.
- **Depends on:** T4, T5, T6
- **Autonomy note:**
  - **May decide alone:** UPDATE vs `INSERT … ON CONFLICT DO UPDATE WHERE`, provided the compare-and-set is in the statement and not in a prior SELECT. Also return types.
  - **Must not** read-then-write the version in two statements.
  - **Stop and ask** if Postgres' default READ COMMITTED does not give the race result above. Changing the isolation level is a design change.

### T9 — News repository

- **Implements:** AC16 (create path); SD13
- **Expected output:** `app/db/news.py`:
  - `create_news(conn, run_id, *, ts_ms, level: NewsLevel, text) -> news_id`. `NewsLevel` is the lowercase `Literal` from SD13, and a value outside it raises `ValueError` before any SQL.
  - `list_news(conn, run_id) -> tuple[NewsItem, ...]`, excluding `deleted_at`, ordered by `ts_ms`, then `news_id`.
- **Verification:** `uv run pytest tests/integration/test_news.py -v`: the level is stored lowercase; `"Danger"` passed to `create_news` raises before SQL; a soft-deleted item is excluded; news from another run is excluded.
- **Depends on:** T4, T5 (`session.py`)
- **Autonomy note:** **May decide alone:** names and types. **Must not** add update or delete operations (Phase 3/6) or a length limit on `text` (undecided).

### T10 — No synchronous file I/O in the repository layer or rehydrate

- **Implements:** AC18; D-35
- **Expected output:** `tests/meta/test_no_file_io.py`, an AST walk modelled on `tests/meta/test_config_boundary.py`:
  - It scans every `.py` under `app/db/` and `app/runtime/`.
  - It fails on `open(`, `io.open`, `os.open`, any `openpyxl` import, `json.load` / `json.dump` (not `loads` / `dumps`), and `.read_text` / `.read_bytes` / `.write_text` / `.write_bytes` / `.open` on anything.
  - It carries the same two safeguards as that file: the scan reaches real files, including `app/db/runs.py` and `app/runtime/gap.py`; and the detector flags each banned form in a snippet.
  - The docstring states that `app/cli/` is deliberately outside the scan, because only the import reads files (AC18).
- **Verification:** `uv run pytest tests/meta/test_no_file_io.py -v`
- **Depends on:** T2, T5 (so both scanned roots hold real files)
- **Autonomy note:** **May decide alone:** the detector's internal structure. A new root may only ever be added, never removed. If a banned name collides with a legitimate call in those modules, **stop and ask** rather than allowlisting it.

### T11 — Bring `data-model.md` in line

- **Implements:** spec In scope 7 ("Updating `docs/design/data-model.md` to match SD4, SD8 and SD10"). No AC; see the audit note.
- **Expected output:** `docs/design/data-model.md` changed so that:
  - the Tables section marks `auth_key`, `market_event`, `theme` and `asset` as "arrives with Phase 3/3/4+/4+" (SD4);
  - the `engine_state` row lists `last_idle_ms` and `last_bm_ms` and says per-drink values are `json` objects keyed by `drink_id`, with jumps carrying `drink_id` (SD8, PD7);
  - `price_tick.prices` is shown as `{drink_id: {"p_cont", "p_q"}}`, with one row per accepted transition (SD10);
  - the `drink` row uses `*_cents` for the four euro columns and adds `name_key` (PD3, PD6);
  - the `order` row drops `total_cents` and notes that `response` and `actor_key_id` arrive with Phase 3 (PD4);
  - `news` gains `run_id` (PD5).

  Nothing else changes.
- **Verification:** `git diff main -- docs/design/data-model.md` touches only the rows named above. Every table and column it names exists in `0002`/`0003` (checked by reading both migrations side by side). `./scripts/check.sh` green.
- **Depends on:** T4
- **Autonomy note:** The content is fixed by this plan. **Any wording that changes a design claim beyond the list above is a hard stop** (`docs/design/` is on ADR 0009/0010's list), so stop and ask instead.

### T12 — The atomic order write and the earnings `GROUP BY`

- **Implements:** AC2, AC11 (query half), AC13; D-10, D-12; SD12 (boot query)
- **Expected output:** `app/db/orders.py`:
  - `write_order(engine, *, run_id, idempotency_key, expected_version, state, spec, drink_ids, lines: Sequence[OrderLineInput], wall_ts_ms) -> OrderWritten(order_id, version)`. It runs **one** `engine.begin()`, which does the `engine_state` compare-and-set, the `"order"` insert, the `order_line` inserts (`line_total_cents = qty * unit_price_cents`, computed here) and the `price_tick` insert (`source = 'order'`).
  - It reuses `save_transition`'s compare-and-set and tick insert as connection-level helpers extracted in T8's module. The import only needs to go one way: `orders.py` imports from `engine_state.py`.
  - A line naming a drink outside `drink_ids` raises before SQL.
  - `earnings_by_drink(conn, run_id) -> list[(drink_id, qty, revenue_cents)]`: one `GROUP BY` over `order_line JOIN "order"`.
- **Verification:** `uv run pytest tests/integration/test_orders.py -v`:
  - **AC2:** parametrised over every statement `write_order` issues. A `before_cursor_execute` listener raises on the Nth statement, and afterwards the `order`, `order_line` and `price_tick` counts and the `engine_state` row are identical to before. The statement count is asserted too, so a new statement cannot skip injection.
  - **AC13:** two `write_order` calls from the same `expected_version` via `asyncio.gather` on two connections. One commits with all its lines; the loser raises `StaleState` and leaves no order, line or tick. Ten sequential orders are all present with their lines.
  - **AC11:** `earnings_by_drink` equals a Python sum of `line_total_cents` per `drink_id` read row by row.
  - A duplicate `idempotency_key` raises `IntegrityError` and writes nothing. Replay behaviour is Phase 3's.
- **Depends on:** T8
- **Autonomy note:**
  - **May decide alone:** the statement order inside the transaction, a single `executemany` vs one insert per line, and the helper extraction in `engine_state.py` (T8's file, now merged).
  - **Must not** compute prices or apply ADR 0008's grace; the caller supplies `unit_price_cents`.
  - **Must not** catch the `IntegrityError` and return an existing order. That is replay, Phase 3.

### T13 — The import CLI

- **Implements:** AC19, AC20; AC10, AC15, AC16 (end-to-end); SD5, SD6 (draft only), SD15
- **Expected output:** `app/cli/import_v1.py`, run as `uv run python -m app.cli.import_v1 --config <path> [--news <path>] [--bar-prices <path>]`. It:
  - builds the `ImportPlan` (T3), so everything is validated before connecting;
  - opens `create_engine(get_settings())` and runs **one** `engine.begin()` doing `create_draft_run` (with `run_seed = secrets.randbits(63)`), then `add_drink` per slot, then `create_news` per item, then `append_config_revision(revision 1, config = the validated plan as JSON, author = "import_v1")`;
  - prints the new `run_id`.
  - It exits 2 with the validation message on bad input and 1 on a database error, and writes nothing in either case. It never touches an existing run and never calls `go_live`. `main(argv) -> int` is importable, so tests and T15 call it in-process.
  - `CLAUDE.md` Commands gains the invocation line.
- **Verification:** `uv run pytest tests/integration/test_import_v1.py -v`:
  - **AC19:** against the real `legacy/v1/config/exchange_config.json` and `legacy/v1/static/news.json` there is exactly one `draft` run. Its drinks, slots, `*_cents`, coefficients and params equal the file. Bar prices equal `p0` (the live file has no `bar_price` key and the repo has no sidecar), and news equals the file (empty). Revision 1 holds that config. `spec_from_rows(...)` is field-equal to `spec_from_config(live)`.
  - The same again with tmp-path fixtures that have a `bar_price` key, a sidecar and capitalised news. Precedence and lowercasing hold end to end.
  - **AC20:** two runs give two draft runs, and the first run's rows are byte-identical before and after the second.
  - An inexact cent, a duplicate name (`Bier` / ` bier`), an unknown level, and a database failure injected after the drinks insert each leave every table's row count unchanged.
- **Depends on:** T3, T5, T9
- **Autonomy note:**
  - **May decide alone:** exit codes beyond 0/1/2, the output format, the JSON shape of the revision (it must hold params plus every drink field and bar price), and whether `--news` defaults to absent.
  - **Must not** add options SD15 does not list, and must not import keys (SD3) or earnings workbooks (SD5).
  - **Stop and ask** if the real v1 config fails validation.

### T14 — Rehydrate

- **Implements:** AC4, AC5, AC7, AC8, AC12, AC14, AC17, AC21 (end-to-end); D-01, D-30; spec In scope 4
- **Expected output:** `app/runtime/rehydrate.py`, `async def rehydrate(engine, *, now_ms, budget_ms=DEFAULT_CATCH_UP_BUDGET_MS) -> RehydratedRun | NoLiveRun`.
  - It works in the spec's order:
    1. Load the live run (`NoLiveRun` if there is none, nothing written, no raise: AC7).
    2. `active_drinks`, then `spec_from_rows`, then `load_state`. `decode_state` raises `StateDrinkMismatch` naming the ids, and nothing is written (AC8).
    3. `load_ticks_in_window` into `HistoryRing`.
    4. `earnings_by_drink` into `EarningsAggregate`.
    5. `list_news`.
    6. `apply_gap_rule`. Only when it returns a state, `save_transition(source = 'gap', wall_ts_ms = now_ms)`, and only after that commits, `ring.append` the gap tick.
  - `RehydratedRun` is frozen and holds `run_id`, `run_seed`, `spec`, `state`, `drink_ids`, per-drink `bar_price_cents`, `wall_ts_ms`, `ring`, `earnings` and `news`.
  - The reads happen in one read transaction. The gap write is a separate compare-and-set transaction, so a concurrent writer surfaces as `StaleState`, not as silent corruption.
- **Verification:** `uv run pytest tests/integration/test_rehydrate.py -v`:
  - **AC4:** `now = wall_ts + budget` gives a state equal to the stored one, every table's row count unchanged, and `version` unchanged.
  - **AC5:** `now = wall_ts + budget + 600 000` shifts every anchor by exactly 600 000 while `y` and prices are bitwise unchanged, and leaves exactly one new `price_tick` with `source = 'gap'` and `version = old + 1`, whose `engine_state` row has the same version. Injecting a failure on the tick insert leaves neither change.
  - **AC7:** with no live run (empty database, and a database holding only drafts) the result is `NoLiveRun` and the counts are unchanged.
  - **AC8:** after an extra active drink is inserted by SQL, the call raises naming that `drink_id` and writes nothing.
  - **AC12:** `set_bar_price`, then 10 `save_transition`s, then rehydrate, returns the set price.
  - **AC14:** slots are swapped, then rehydrate; values stay with their `drink_id`s and `spec.names` follow the new order.
  - **AC17:** after rehydrate, with a `before_cursor_execute` counter attached and `builtins.open`, `io.open`, `os.open` and `pathlib.Path.open` monkeypatched to raise, reading `ring.window()`, `earnings.snapshot()` and `news` makes 0 queries and 0 opens.
  - **AC21:** ticks spread over 20 minutes with a 15-minute window give a ring that is exactly the in-window ones in version order. A tick inserted in a rolled-back transaction is absent.
- **Depends on:** T2, T7, T8, T9, T12
- **Autonomy note:**
  - **May decide alone:** the result type names, whether `NoLiveRun` is a singleton, and the read isolation (READ COMMITTED or REPEATABLE READ).
  - **Must not** take an advisory lock or run migrations (Phase 3, ADR 0011), start a ticker, or advance the engine.
  - **Stop and ask** if the gap rule appears to need to move a price.

### T15 — The durability harness

- **Implements:** AC1; AC5, AC6 across a real kill; SD1; spec Verification
- **Expected output:**
  - `tests/integration/durability/harness.py`, run as `python -m tests.integration.durability.harness --start-ms <t> --script <name> [--hold-in-tx <n>]`:
    - It imports the live config via `app.cli.import_v1.main` and `go_live`s it.
    - It plays a deterministic script: 1 Hz ticks, scripted orders, and one 120 s `schedule_jump` through a fake clock. Each step calls `advance`, then `save_transition` or `write_order`, then `ring.append` / `earnings.add_lines` after the commit.
    - It prints one JSON line per commit `{"kind", "version", "orders_committed", "state": <encoded>}` and flushes.
    - With `--hold-in-tx n`, a harness-only `after_cursor_execute` listener prints `{"kind": "in_tx"}` after the first statement of transaction `n` and sleeps. There is no production hook.
  - `tests/integration/test_durability.py` spawns the harness on the scratch DSN and `Popen.kill()`s it at **five points**: after commit k, for 3 values of k, and inside transaction k, for 2 values of k, one of them an order. Each time it rehydrates in the test process.
- **Verification:** `uv run pytest tests/integration/test_durability.py -v`:
  - **AC1:** for each kill point, the rehydrated state equals the harness's last printed committed state, field by field and bitwise across all eleven fields. The `"order"` row count equals the last `orders_committed`. The next `advance` from the rehydrated state equals the next `advance` from an in-process pure replay of the same script up to that version, which proves `rng_counter` continuity.
  - **AC5/AC6 pass:** kill while the jump is in flight, then rehydrate at `last wall_ts + budget + 10 min`. AC5's shift and gap tick hold, and the first `advance` matches PD1's elapsed time with the jump still active.
  - The assertion output is the phase's durability evidence.
- **Depends on:** T13, T14
- **Autonomy note:**
  - **May decide alone:** script length, kill points (at least the five above), JSON field names, timeouts, and harness CLI flags.
  - **Must not** use wall-clock time in the harness's pricing calls, or a production code hook for the in-transaction pause.
  - If a kill-mid-transaction run leaves a partial write, that is a correctness failure to report, **not** a test to loosen.

---

## Task graph

```
T1, T2, T3            (no dependencies)
T4  ← T1              T5  ← T1              T6  ← T1              T7  ← T2
T8  ← T4, T5, T6      T9  ← T4, T5          T10 ← T2, T5          T11 ← T4
T12 ← T8              T13 ← T3, T5, T9
T14 ← T2, T7, T8, T9, T12
T15 ← T13, T14
```

Critical path: T1 → T4 → T8 → T12 → T14 → T15.

T7 depends on T2 only because T2 creates `app/runtime/__init__.py`; there is no logical
dependency. T12 follows T8 because it reuses T8's compare-and-set helpers, not just to avoid
a file clash.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T2, T3 | T1: `db/migrations/versions/0002_*.py`, `app/db/__init__.py`, `app/db/models.py`, `tests/integration/conftest.py`, `tests/integration/test_migrations.py` · T2: `app/runtime/__init__.py`, `app/runtime/gap.py`, `tests/unit/test_gap.py` · T3: `app/cli/__init__.py`, `app/cli/v1_files.py`, `tests/unit/test_v1_files.py` |
| 2 | T4, T5, T6, T7 | T4: `db/migrations/versions/0003_*.py`, `app/db/models.py`, `tests/integration/test_schema.py` · T5: `app/db/session.py`, `app/db/runs.py`, `app/db/mapping.py`, `tests/integration/test_runs.py`, `tests/unit/test_mapping.py` · T6: `app/db/codec.py`, `tests/unit/test_codec.py` · T7: `app/runtime/history.py`, `app/runtime/earnings.py`, `tests/unit/test_history_ring.py`, `tests/unit/test_earnings.py` |
| 3 | T8, T9, T10, T11 | T8: `app/db/engine_state.py`, `app/db/runs.py`, `tests/integration/test_engine_state.py` · T9: `app/db/news.py`, `tests/integration/test_news.py` · T10: `tests/meta/test_no_file_io.py` · T11: `docs/design/data-model.md` |
| 4 | T12, T13 | T12: `app/db/orders.py`, `app/db/engine_state.py` (helper extraction), `tests/integration/test_orders.py` · T13: `app/cli/import_v1.py`, `tests/integration/test_import_v1.py`, `CLAUDE.md` |
| 5 | T14 | `app/runtime/rehydrate.py`, `tests/integration/test_rehydrate.py` |
| 6 | T15 | `tests/integration/durability/__init__.py`, `tests/integration/durability/harness.py`, `tests/integration/test_durability.py` |

No two tasks in one group write the same file. T5 → T8 (`runs.py`) and T8 → T12
(`engine_state.py`) are in different groups and ordered by dependency. Builders run one at a
time (ADR 0010 §1); the groups give the merge order.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main` and in CI, its output pasted.
- `uv run pytest tests/integration/test_durability.py -v` output pasted (AC1, AC5, AC6).
- `uv run python -m app.cli.import_v1 --config legacy/v1/config/exchange_config.json --news legacy/v1/static/news.json` against the compose `db`, printing a run id, with T13's AC19 test output as the diff evidence.
- `uv run pytest tests/engine` green, so the golden fixtures are untouched.

---

## Data changes

Two forward-only migrations chained from `0001`. Both are purely additive: new tables only,
no existing table, no backfill. v2 holds no data yet, so there is no expand/contract
sequence. Both are fully reversible by `downgrade`, which AC23 exercises.

| Revision | Creates | Constraints and indexes |
|---|---|---|
| `0002_runs_and_drinks` | `run`, `run_config_revision`, `drink` | `run.status` CHECK; `run_one_live` partial unique index (SD6); `drink` CHECK `p_min_cents < p0_cents < p_max_cents`, `bar_price_cents ≥ 0`; UNIQUE `(run_id, slot)`; `drink_name_live` partial unique index on `(run_id, name_key)` (SD14, PD6) |
| `0003_state_ledger_news` | `engine_state`, `price_tick`, `"order"`, `order_line`, `news` | `price_tick` PK `(run_id, version)` and `source` CHECK; `"order".idempotency_key` UNIQUE; `order_line` CHECKs (`qty > 0`, `line_total_cents = qty * unit_price_cents`) and UNIQUE `(order_id, drink_id)`; `news.level` CHECK (SD13) |

Full column lists are in T1 and T4. Every euro amount is an `INTEGER` `*_cents` column (AC9,
PD3). The float columns are `drink.a/d/s0/c` and `order_line.p_cont`, which are coefficients
and a diagnostic continuous price, not money. The other floats live in JSON: engine state
(PD7), tick prices (SD10) and params. Phase 3 adds `auth_key` and `market_event` as new
tables, and `"order".response` / `actor_key_id` as nullable columns, each additively in its
own migration.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **AC6 disagrees with SD2/AC5 by exactly `budget`.** Shifting anchors by `gap − budget` means the jump progresses `budget` ms "during" the gap (the time Phase 3's ticker will catch up). AC6's formula has no budget term, and "no jump completes during the gap" is false for a jump with less than `budget` remaining | PD1 follows SD2/AC5, which say `gap − budget` twice. **Needs a human decision before T2**: pricing over time is a hard stop. If AC6 wins instead, the shift becomes `gap` and AC5's "exactly `gap − budget`" must be amended in the spec |
| R2 | SD10 stores `p_cont`/`p_q` as floats in `price_tick.prices`, while AC9 says "any euro amount is integer cents" | AC9's test is about **columns**, per its own wording ("any money column"). SD10 is the spec's explicit decision for the engine price track, and charged money lives only in `order_line` as cents. Confirm at the audit |
| R3 | PD4 drops `order.total_cents`, which `data-model.md:29` lists | It is a second copy of revenue (AC11, D-10). T11 updates the doc. If the audit wants it kept, AC11's test needs an explicit exemption, and nothing else changes |
| R4 | Postgres `lower()` is collation-dependent: compose uses `--locale=C` (`docker-compose.yml:32`), Render probably does not | PD6 computes `name_key` in Python. The unit test uses a non-ASCII pair (`Café` / `CAFÉ`) |
| R5 | `jsonb` loses `-0.0` and rejects NaN | PD7 uses text-preserving `json` for `engine_state` and `allow_nan=False`. T6 tests both |
| R6 | "SIGKILL" on Windows: `Popen.kill()` is `TerminateProcess`, not a signal | Both are uncatchable hard kills that drop the socket, and Postgres aborts the open transaction either way. CI on Linux exercises real SIGKILL. A Windows-only pass is not phase-exit evidence |
| R7 | Scratch databases need `CREATEDB`. A killed test run leaves `bb_test_*` behind | The compose and CI users are `POSTGRES_USER`, i.e. superuser (`docker-compose.yml:27`, `ci.yml:41`). The session fixture sweeps leftovers at start. If either is ever not a superuser, T1 stops and asks |
| R8 | `order` is a reserved word | SQLAlchemy quotes it. Raw SQL in tests must write `"order"`. The table name is the design's (`data-model.md:29`), so renaming it is a hard stop, not a builder's call |
| R9 | SD15's "config's `bar_price` key, then `bar_prices.json`, else `p0`" reads as an ambiguous order | PD11 follows the cited code, where the sidecar wins (`api.py:174`). T3 tests each layer |
| R10 | `auto_calibrate_s0: true` cannot go live (PD14) | The live config has `false`. The calibrated go-live arrives with admin config editing (Phase 6) |
| R11 | PD12 rejects input v1 accepted (unknown names in bar-price maps) | The repo holds no sidecar, and the live config has no `bar_price` key, so AC19's real-file import is unaffected. A real sidecar with stale names would fail loudly, naming the key |
| R12 | Integration time grows: alembic subprocesses plus about 6 durability subprocesses | One migrated scratch database per session, TRUNCATE between tests. T15 budgets < 60 s. Kill points may not drop below five |
| R13 | T11 edits `docs/design/`, which is a hard stop for an autonomous builder | Authorised by the spec (In scope 7), with content fixed by T11's list. Any other wording stops |
| R14 | The manual checklist's Phase 2 exit ("restart the app, prices are unchanged", `manual-checklist.md:182`) needs boot-time rehydrate in `app/main.py`, which is Phase 3 (spec Out of scope; ADR 0011) | The Phase 2 exit evidence is T15's kill-and-rehydrate test. The checklist line is the user's to reword; this plan does not edit it |
| R15 | Before Phase 3's advisory lock, two processes could rehydrate together | Every write is compare-and-set (SD9), so the second gap write raises `StaleState` rather than corrupting anything. T8 and T12 race real transactions |
| R16 | D-16 says "migration must normalise historical rows" | SD13 settles it: v2 has no historical rows, and the import is the only entry point, where it normalises |

---

## Out of scope for this plan

- Routes, the ticker and running catch-up, the advisory lock, boot-time migrate and
  rehydrate in `app/main.py`, realtime, any UI (spec Out of scope; Phase 3).
- Order **behaviour**: quoted-price grace, 409s, idempotent replay and the stored receipt
  (`order.response`), the actor (`actor_key_id`). Phase 2 has only the UNIQUE constraint and
  the atomic write.
- `auth_key`, `market_event`, `theme`, `asset` (SD4); key import (SD3); workbook import and
  xlsx export (SD5).
- Run end, `bar_price_total` / D-20 (Phase 7). Drink add or remove mid-run, and any drink
  edit beyond `set_bar_price` (Phase 6). Calibrating `s0` at go-live (PD14).
- The display price track and the dedupe for rendering (D-28, Phase 3).
- Defect-register resolution notes for D-01 … D-35. The spec does not ask for them; the
  phase digest records what was fixed.
- Anything in `exchange/`. No pricing change; the golden fixtures stay green.

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task:
  - AC1 → T15
  - AC2 → T12
  - AC3 → T6, T8
  - AC4 → T2, T14
  - AC5 → T2, T14, T15
  - AC6 → T2, T15
  - AC7 → T14
  - AC8 → T6, T14
  - AC9 → T4
  - AC10 → T3, T13
  - AC11 → T4, T12
  - AC12 → T5, T14
  - AC13 → T8, T12
  - AC14 → T5, T6, T8, T14
  - AC15 → T1, T5, T13
  - AC16 → T3, T4, T9, T13
  - AC17 → T7, T14
  - AC18 → T10
  - AC19 → T13
  - AC20 → T13
  - AC21 → T7, T14
  - AC22 → T1, T8
  - AC23 → T1
- [x] Every task maps to at least one AC (no orphans). T11 has no AC: it implements spec In scope 7. T6's header gained AC8 at the audit (it already tested the key mismatch)
- [x] Each task's expected output is what we actually need. **PD1 (R1) confirmed as written at the audit: SD2/AC5 win, anchors shift by exactly `gap − budget`; AC6 is tested per PD1.** PD3–PD7 confirmed (they change `data-model.md`). R2 (tick prices as floats in JSON; AC9 is about columns) and R3 (no `order.total_cents`) confirmed as the plan resolves them
- [x] Existing patterns reused; nothing reinvented: `Params.from_dict`, `MarketSpec.from_drinks`, `initial_state`, `prices_from_y`, `spec_from_config` (tests), the `test_config_boundary.py` AST-walk shape, the `test_health.py` `asyncio.run` shape, `AppError`, `get_settings`
- [x] No new dependency without an approval note. None is added
- [x] Data changes additive and reversible (AC23 tests it)
- [x] Errors, empty states and permissions are tasks, not afterthoughts: no live run (T14), key mismatch (T6/T14), stale state (T8/T12), duplicate name (T5), inexact cents (T3/T13), zero-drink go-live (T8). There are no permissions in this phase
- [x] Each task reviewable in one sitting. Largest: T14 and T15, about 400 lines across 2–3 files
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not. Only scratch databases on the local or CI server
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audited by: MartijnBoot (human audit, `/audit 2`)  Date: 2026-10-01
