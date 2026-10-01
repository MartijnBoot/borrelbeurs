# Plan: Phase 3 — API, authorization, ticker and realtime

Spec: [docs/specs/phase-3-api-realtime.md](../specs/phase-3-api-realtime.md) · Status: **header still reads Draft**; approval ticked in [manual-checklist.md](manual-checklist.md), to be flipped by MartijnBoot
Design: [architecture.md](../design/architecture.md) (module layout, boot sequence), [realtime-protocol.md](../design/realtime-protocol.md), [data-model.md](../design/data-model.md)
ADRs honoured: 0003 (single writer owns time, advisory lock, catch-up budget), 0004 (Postgres everywhere), 0005 (server-side bucketing), 0008 (honour the quoted price — refined by SD18, addendum in T23), 0009/0010 (hard stops: new dependency, data model, `docs/design/`), 0011 (lock → migrate → serve; a failed migration fails boot)
Fixes: D-06, D-07, D-08, D-15, D-18, D-28, D-31, D-32, D-33, D-34, D-36
Re-establishes on v2's own code: D-27, D-37, D-38, D-39, D-40, D-41, D-42

---

## Approach

Bottom-up, as in Phase 2, but with the one shared seam named first. Every mutation (tick,
order, jump, market event, news) goes through **one `MarketHolder.mutate`** (T13). It takes
the lock, hands a pure compute step the current in-memory view, runs that step's single
database transaction, publishes the candidate to memory only after commit, releases the lock,
logs the hold time (SD22), and only then hands the step's domain events to a sink. The sink is
injected. In production it is a publisher (T19) that turns domain events into the closed
message models (T11) and enqueues them on the hub (T14). In tests it is a recorder that fails
if it is called while the lock is held (AC14). So AC14, SD12 and SD22 are enforced once, in one
place, and every feature task (orders T18, news T22, manipulation T25, the ticker T16) is a
compute-plus-transaction step plugged into it, not its own locking. Time comes from an
injected clock (T4, SD32), so the ticker, hub, rate limiter and session expiry run on a fake
clock in tests, and nothing under `app/runtime/` or `app/realtime/` imports `time`. The pure
pieces come first with unit tests: grace rule, candles, market-event table, gap shift and clock.
Then the repositories and holder against scratch databases (Phase 2's fixtures). Then the boot
wiring in `app/main.py` (lock → migrate → rehydrate → ticker → ready). Then the HTTP and
WebSocket surfaces, tested in-process through FastAPI's `TestClient` (`tests/api/`). Last, the
real-process proofs: SIGKILL (AC18d), a second instance, and a dropped lock connection (AC18).
These run the real entrypoint `python -m app.main` (`docker/Dockerfile:72`) as a subprocess,
reusing Phase 2's durability harness.

Rejected: **one lock per feature, or locking in the routes.** That is v1's shape, where the
check sat outside the lock (`api.py:342` vs `:350`), and AC14 would then need proving per
route. **The hub serialising inside the holder's lock**, which is exactly D-34's stall.
**Migrating in-process on the event loop:** `db/migrations/env.py` calls `asyncio.run`, which
cannot nest inside the lifespan's running loop, so migration runs in `asyncio.to_thread` (PD3).
**Restructuring `env.py` to accept a passed connection**, which is a larger change to a file
the gate already exercises, for no gain. **`pytest-asyncio`**: the `asyncio.run` pattern stays
for integration tests, and `TestClient` (SD33's `httpx`) drives the API tests. **Real-time
sleeps in tests**: AC18a and AC22 say "on the fake clock", and a 120 s backpressure test must
not take 120 s. **A request-hash column for idempotency**, which is not in SD20's column list;
PD6 gets the same strictness from the receipt instead.

---

## Decisions this plan makes

Choices the spec and design leave open. **PD1 (dependencies) is a hard stop before T1 is
built.** PD6, PD7 and PD12 change a contract the spec names, so they need confirming at the
audit.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | SD33's three dependencies | One task, T1, adds `argon2-cffi` and `PyJWT` to `[project.dependencies]` and `httpx` to the dev group, with the approval notes under Files. **It stops for explicit human approval before `uv add`** | ADR 0009/0010 list a new dependency as a hard stop. SD33 names them, but says "approved before install" |
| PD2 | Where auth code lives | `app/api/security.py`: key format, argon2 hash/verify, JWT, rate limiter, the role → SPA-routes table, the `require_role` dependency, and the Origin middleware. `app/api/auth.py`: routes. `app/db/keys.py`: the `auth_key` repository. No new top-level package | `architecture.md:43` lists `api/ … auth` and has no `security/` or `auth/` package. Adding one would change the design's module layout (`docs/design/` is a hard stop) |
| PD3 | Boot migration inside the lifespan | `await asyncio.to_thread(alembic.command.upgrade, cfg, "head")` with the repo's `db/alembic.ini`. `env.py` keeps calling `get_settings()`, which the lifespan has already populated | `env.py` runs `asyncio.run(...)`, which raises inside a running loop. A worker thread has no loop. No migration file changes |
| PD4 | Advisory lock key | `ADVISORY_LOCK_KEY: Final = 0x6262_7633` (`"bbv3"`), a named constant in `app/db/advisory_lock.py`, used by the app and `app.cli.runs` | SD11 asks for "a fixed, named constant". One definition, imported by both holders of the lock |
| PD5 | Lock-loss detection (SD11) | A watchdog task runs `SELECT 1` on the dedicated lock connection once per tick interval (injected clock). On any error it logs `advisory_lock_lost` and calls an injected `on_lock_lost`, which in production is `os._exit(70)` | The process can no longer prove it is the single writer, so a graceful shutdown that might write would be wrong. `os._exit` skips every finaliser, which is the point. Exit code 70 is `EX_SOFTWARE`, distinct from uvicorn's startup-failure 3 |
| PD6 | "Identical body" for idempotency (SD20, AC9) | The stored receipt includes `quote_version` alongside SD19's fields. A replay matches when `quote_version` and the set of `(drink_id, qty, unit_price_cents)` equal the receipt's. Any difference returns 422 `idempotency_key_reused` | No request is stored, and SD20 adds exactly two columns. Under SD18, the charged price **is** the quoted `unit_price_cents` (either equal to live, or honoured), so the receipt determines the body exactly once it carries `quote_version`. **Confirm at the audit**: it adds one field to the receipt. The alternative is a `request_hash` column in 0006, which is a data-model change |
| PD7 | Byte-identical receipt (AC9) | The receipt is one pydantic model, `Receipt`. The first response and every replay are produced by `Receipt.model_validate(stored).model_dump_json()`, so key order is the model's, not jsonb's. The route returns the bytes as `Response(media_type="application/json")`. **A replay returns 200, and the first response returns 201** | `jsonb` reorders keys, so returning the stored value as-is would not be byte-identical. **Confirm at the audit**: SD20 says a replay is 200 but does not fix the first status. 201 is the REST-conventional status for a created order, and AC9 compares bodies, not statuses. Choosing 200 for both is equally consistent |
| PD8 | Errors with extra fields (SD35) | `AppError` gains an optional `extra: Mapping[str, JsonValue]`, rendered inside the existing `{"error": {"code", "message", …}}` envelope. `PriceChanged(409, price_changed)` carries `version` and `prices: [{drink_id, price_cents}]` | `app/core/errors.py:27` is the one error shape. The wrapper is kept, so Phase 0's existing callers keep their shape |
| PD9 | New error codes, all `AppError` subclasses next to their raiser (Phase 2 PD10) | `unauthenticated` 401, `forbidden` 403, `origin_mismatch` 403, `rate_limited` 429, `no_live_run` 409, `price_changed` 409, `idempotency_key_reused` 422, `persistence_unavailable` 503, `shutting_down` 503, `news_not_found` 404. FastAPI's own validation 422 is re-rendered into the same envelope with code `invalid_request` | SD35: one shape. Codes named in the spec are used verbatim. `shutting_down` is SD10's unnamed 503 |
| PD10 | Clock seam (SD32) | `app/runtime/clock.py`: a `Clock` protocol (`wall_ms() -> int`, `monotonic() -> float` in seconds, `async sleep_until(monotonic_deadline)`), and `RealClock`, the only `time` user. `tests/support/clock.py`: `FakeClock` with `advance(ms)`, waking sleepers in deadline order | SD32 names the three methods. Seconds for `monotonic` match `time.monotonic`. The fake lives under `tests/`, so production cannot import it |
| PD11 | The holder's emission seam | `MarketHolder(…, sink: Callable[[Sequence[DomainEvent]], None])`. Domain events are frozen dataclasses defined in `holder.py`: `TickCommitted`, `OrderCommitted`, `NewsChanged`, `MarketEventStarted`, `MarketEventEnded`. The sink is synchronous and never awaits (hub enqueue is non-blocking, SD29) | The holder never imports the hub or the messages (AC14 by construction). The publisher (T19) is the only place that knows both |
| PD12 | Which message carries an order's new prices | The `order` message carries `order_id`, `lines`, `total_cents`, the earnings delta **and** every drink's `price_cents` / `chart_price_cents` after the order, with the envelope's `version` | AC18e needs the broadcast for an order to carry the new version and prices. `realtime-protocol.md:46` lists `order` without prices. T23 updates the doc. **Confirm at the audit** |
| PD13 | A jump's broadcast | A jump writes its `jump` tick (version + 1) and broadcasts nothing. The price moves on the next `tick`, which carries a higher version | SD23: "The price starts moving on the next tick". The jump changes the schedule, not a price, so there is no new price vector to send. `seq`, not `version`, is the client's gap detector (SD27) |
| PD14 | Chart track | `chart_price_cents = round(p_cont * 100)` (Python's round-half-even, as `np.round`, which v1's `prices_disp` used), in `app/runtime/candles.py`. `price_cents` reuses `cents_from_quantised` (`app/db/mapping.py`) | SD24 names the two tracks. One function per track, each defined once |
| PD15 | Docs routes outside production (SD3) | `create_app()` builds `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`. The lifespan adds `/openapi.json`, `/docs` and `/redoc` with FastAPI's `get_swagger_ui_html` / `get_redoc_html` when `settings.app_env != "production"` | `create_app()` must not read settings (`app/main.py:8`, the `test_importing_the_app_reads_no_environment` test). `create_app().openapi()` still works for Phase 4 with `openapi_url=None` |
| PD16 | The test seam into `create_app` | `create_app(*, clock: Clock | None = None, run_migrations: bool = True, request_shutdown: Callable[[], None] | None = None)`. `tests/api` passes a `FakeClock` and `run_migrations=False`, since the scratch database is migrated once per session (Phase 2 PD15). Migrate-at-boot is proven in T20 and T29 | Running the lifespan per API test against the real ticker clock would make versions race the assertions. Running an alembic upgrade per test costs about 1 s × hundreds of tests |
| PD17 | Self-shutdown (SD10) | `app.main.main()` builds `uvicorn.Server` itself and passes `request_shutdown = lambda: setattr(server, "should_exit", True)`. Under `uvicorn app.main:app` (dev) the fallback is `signal.raise_signal(SIGINT)`. The route sets draining (orders → 503 `shutting_down`), responds 202, then calls `request_shutdown`. The lifespan's shutdown half does the rest of SD10 in order | `should_exit` is uvicorn's own graceful path (lifespan shutdown, exit 0) on every OS. `SIGTERM` via `raise_signal` on Windows terminates without handlers |
| PD18 | Key format | `bb_<key_id>_<secret>`, with `secret = secrets.token_urlsafe(32)` (43 chars of `[A-Za-z0-9_-]`). Parsed by `split("_", 2)` and a `key_id` of digits, so a `_` inside the secret is safe. Hashing uses `argon2.PasswordHasher()` defaults (argon2id) | stdlib `secrets` is the CSPRNG. `PasswordHasher` defaults are argon2id per RFC 9106 |
| PD19 | Hygiene literal (AC6c) | `tests/meta/test_repo_hygiene.py` scans every `git ls-files` path for a file named `keys.json` and for `\bbb_\d+_[A-Za-z0-9_-]{32,}`. Tests never commit a key literal: they mint keys at runtime, and the detector's own self-test builds its sample by concatenation | A test fixture holding a key literal would trip the very check that guards against one |
| PD20 | Session-to-role binding | The `auth_key` row loaded per request (SD8) is authoritative: a revoked row → 401, and a claim role differing from the row → 401 | SD8 makes the row load mandatory, so the row is the fresher source |
| PD21 | `StaleState` under the holder | Treated as a persistence failure: logged at `error` with both versions, 503 `persistence_unavailable`, memory unchanged | With the advisory lock held, it cannot happen without a bug or a second writer. Failing closed is SD21's behaviour |

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `pyproject.toml`, `uv.lock` | Modify (T1) | `argon2-cffi`, `PyJWT`; dev `httpx` |
| `db/migrations/versions/0004_auth_key.py` … `0007_run_grace_and_candles.py` | Create (T2) | The four migrations of In scope 1 |
| `app/db/models.py` | Modify (T2) | `AuthKey`, `MarketEvent`, `Order.actor_key_id/response`, `Run.quote_grace_versions/candle_interval_ms` |
| `tests/integration/test_schema.py` | Modify (T2) | New columns, FKs and CHECKs; AC6c's "no secret column" |
| `app/core/config.py`, `.env.example`, `tests/unit/test_config.py` | Modify (T3) | `LOGIN_RATE_PER_MINUTE`, `SESSION_COOKIE_SECURE` + production refusal; AC4, AC6a (boot half) |
| `app/runtime/clock.py`, `tests/support/__init__.py`, `tests/support/clock.py` | Create (T4) | PD10 |
| `tests/meta/test_clock_seam.py` | Create (T4) | SD32: no `time` import under `app/runtime/`, `app/realtime/` except `clock.py` |
| `app/runtime/grace.py`, `tests/unit/test_grace.py` | Create (T5) | SD18 judge, pure |
| `app/runtime/candles.py`, `tests/unit/test_candles.py` | Create (T6) | SD25 buckets, PD14 |
| `app/runtime/market_events.py`, `app/runtime/gap.py`, `tests/unit/test_market_events.py`, `tests/unit/test_gap.py` | Create / Modify (T7) | Event kinds, targets, Dutch news text; the gap shift extended to events |
| `tests/meta/test_repo_hygiene.py` | Modify (T8) | PD19 |
| `app/db/advisory_lock.py`, `app/cli/runs.py`, `tests/integration/test_advisory_lock.py`, `tests/integration/test_cli_runs.py` | Create (T9) | PD4; SD16's `go-live` CLI |
| `app/db/keys.py`, `app/api/security.py`, `app/cli/keys.py`, `tests/unit/test_key_format.py`, `tests/integration/test_cli_keys.py` | Create (T10) | SD5; AC6c |
| `app/realtime/__init__.py`, `app/realtime/messages.py`, `tests/unit/test_messages.py` | Create (T11) | SD28 closed models; AC20, AC20a, AC23 |
| `app/db/market_events.py`, `app/runtime/rehydrate.py`, `tests/integration/test_market_events_repo.py`, `tests/integration/test_rehydrate.py` | Create / Modify (T12) | Events repository; rehydrate events + run columns; AC19a |
| `app/runtime/holder.py`, `tests/integration/test_holder.py` | Create (T13) | SD12, SD22; AC14 |
| `app/realtime/hub.py`, `tests/unit/test_hub.py` | Create (T14) | SD27, SD29; AC21, AC22 (hub half) |
| `app/api/security.py`, `tests/unit/test_security.py` | Modify / Create (T15) | JWT, limiter, Origin, roles |
| `app/runtime/ticker.py`, `tests/integration/test_ticker.py` | Create (T16) | SD13, SD14; AC18a, AC18b, AC19 (end) |
| `app/core/errors.py`, `app/api/deps.py`, `app/api/auth.py`, `app/main.py`, `scripts/check.sh`, `tests/api/__init__.py`, `tests/api/conftest.py`, `tests/api/test_auth.py`, `tests/meta/test_route_authorization.py` | Create / Modify (T17) | Login/logout/me, the harness, SD4's audit, PD8, PD15 |
| `app/db/orders.py`, `app/runtime/orders.py`, `tests/integration/test_orders.py`, `tests/integration/test_place_order.py` | Modify / Create (T18) | The order domain |
| `app/realtime/publish.py`, `tests/unit/test_publish.py` | Create (T19) | Domain events → messages → hub |
| `app/runtime/boot.py`, `app/main.py`, `app/api/health.py`, `tests/unit/test_app_shell.py`, `tests/integration/test_health.py`, `tests/integration/test_boot.py` | Create / Modify (T20) | SD11, SD15, SD16 boot; AC17, AC18c |
| `tests/integration/test_order_concurrency.py` | Create (T21) | AC8, AC18e |
| `app/api/state.py`, `app/api/news.py`, `app/db/news.py`, `app/main.py`, `tests/api/test_state.py`, `tests/api/test_news.py` | Create / Modify (T22) | AC15, AC18c, AC28 |
| `docs/design/architecture.md`, `docs/design/realtime-protocol.md`, `docs/design/data-model.md`, `docs/adr/0008-honour-the-quoted-price.md`, `CLAUDE.md` | Modify (T23) | In scope 8 |
| `app/api/orders.py`, `app/main.py`, `tests/api/test_orders.py` | Create / Modify (T24) | The HTTP order surface |
| `app/runtime/manipulation.py`, `app/api/market.py`, `app/main.py`, `tests/integration/test_manipulation.py`, `tests/api/test_market.py` | Create / Modify (T25) | AC19, AC26, AC27 |
| `app/realtime/ws.py`, `app/main.py`, `tests/api/test_ws.py` | Create / Modify (T26) | AC3, AC16, AC21, AC24, AC25 |
| `app/api/admin.py`, `app/main.py`, `app/runtime/boot.py`, `tests/api/test_admin.py` | Create / Modify (T27) | AC6d |
| `tests/api/test_authorization_matrix.py`, `tests/api/test_static.py` | Create (T28) | AC1, AC2, AC6f |
| `tests/integration/realapp/__init__.py`, `tests/integration/realapp/harness.py`, `tests/integration/test_real_process.py` | Create (T29) | AC18, AC18d |

### New dependencies (approval notes, PD1)

| Package | What it does | Why not stdlib | Licence | Maintenance |
|---|---|---|---|---|
| `argon2-cffi` (runtime) | argon2id hashing and verification of access-key secrets (SD5, SD6) | stdlib has `hashlib.scrypt`, not argon2. `data-model.md:33` and SD5 name argon2id | MIT | Hynek Schlawack, the reference Python binding, released regularly, wheels for CPython 3.12 on Windows, macOS and Linux |
| `PyJWT` (runtime) | HS256 encode/decode with `exp` validation (SD8) | No JWT in stdlib. Hand-rolling HMAC, base64url and claim validation is exactly where auth bugs live | MIT | jpadilla/pyjwt, active, the most-used Python JWT library. Pure Python |
| `httpx` (dev only) | Required by FastAPI's `TestClient` (SD33) | `TestClient` imports it, and there is no stdlib substitute | BSD-3-Clause | encode/httpx, active. Pulled in as a dev dependency only, so it is not in the runtime image |

Not added: `pytest-asyncio`, `freezegun` (PD10's fake clock replaces it), a WebSocket client
(`websockets` 17.1 is already locked via `uvicorn[standard]`), and any CORS or rate-limit
library (SD7, SD9).

---

## Tasks

Every task leaves `./scripts/check.sh` green. Branches follow `feature/phase-3-tN-<slug>`.
Integration tests use Phase 2's fixtures (`tests/integration/conftest.py`: `database_url`,
`settings`, `alembic`) and the `asyncio.run` pattern. Nothing touches `exchange/`, and the
golden replay stays green (`uv run pytest tests/engine`). `engine-guardian` runs on T7, T13,
T16, T18 and T25, since they feed the engine. Reuse, by name: `exchange.advance`,
`schedule_jump`, `prices_from_y`; `app/db/engine_state.py` (`compare_and_set`, `insert_tick`,
`save_transition`, `StaleState`); `app/db/orders.py` (`write_order`, `earnings_by_drink`);
`app/db/news.py` (`create_news`, `NEWS_LEVELS`); `app/db/runs.py` (`go_live`,
`active_drinks`); `app/db/mapping.py` (`cents_from_quantised`, `spec_from_rows`);
`app/db/codec.py` (`tick_prices`); `app/runtime/{gap,history,earnings,rehydrate}.py`;
`app/core/errors.py` (`AppError`); and `tests/integration/durability/harness.py`.

### T1 — Approved dependencies

- **Implements:** SD33; PD1. It enables AC5, AC6, AC6a and AC6c (argon2, JWT) and every `tests/api` test (httpx)
- **Expected output:**
  - `uv add argon2-cffi PyJWT` and `uv add --dev httpx`, with `uv.lock` regenerated.
  - Nothing else changes.
  - The PR body carries the three approval notes from the Files section.
- **Verification:**
  - `uv run python -c "import argon2, jwt, httpx"`.
  - `uv run pytest tests/meta`.
  - `./scripts/check.sh`.
- **Depends on:** —
- **Autonomy note:**
  - **Must stop and ask before running `uv add`.** A new dependency is a hard stop (ADR 0009). The user approves each of the three explicitly.
  - Also stop if resolution pulls a new transitive runtime dependency other than `argon2-cffi-bindings`/`cffi`/`pycparser`.

### T2 — The four migrations

- **Implements:** SD5 (table), SD18 (`quote_grace_versions`), SD20 (columns), SD23 (table), SD25 (`candle_interval_ms`); AC6c (schema half)
- **Expected output:** four revisions, each its own file, chained `0003 → 0004 → 0005 → 0006 → 0007`, each with a full `downgrade()`.
  - `0004_auth_key`: `auth_key(key_id BIGINT identity PK, label TEXT NOT NULL CHECK length 1–100, role TEXT NOT NULL CHECK IN ('display','bar','admin'), secret_hash TEXT NOT NULL, created_at timestamptz DEFAULT now(), revoked_at NULL, last_used_at NULL)`.
  - `0005_market_event`: `market_event(event_id BIGINT identity PK, run_id FK run, kind TEXT CHECK IN ('crash','bubble','correction'), drink_ids JSONB NOT NULL, t_start_ms BIGINT, t_end_ms BIGINT, ended_at timestamptz NULL, CHECK t_end_ms > t_start_ms)`, indexed on `(run_id) WHERE ended_at IS NULL`.
  - `0006_order_actor_response`: `"order".actor_key_id BIGINT NULL REFERENCES auth_key`, `"order".response JSONB NULL`. Both are nullable, because Phase 2's imported or test orders have neither.
  - `0007_run_grace_and_candles`: `run.quote_grace_versions INTEGER NOT NULL DEFAULT 2 CHECK ≥ 0`, `run.candle_interval_ms INTEGER NOT NULL DEFAULT 60000 CHECK > 0`.
  - `app/db/models.py` mirrors all of it column for column.
- **Verification:**
  - `uv run pytest tests/integration/test_migrations.py tests/integration/test_schema.py -v`: round trip `upgrade head` / `downgrade base` / `upgrade head`; the CHECKs reject bad rows; `auth_key` has no column named or typed for a plaintext secret (AC6c).
  - `uv run pytest tests/meta/test_migration_scaffolding.py` (one head).
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** index and constraint names, the CHECK on `label` length.
  - **Must stop and ask about:** any column not listed here. This is the data model, a hard stop.
  - Phase 2's migrations are never edited (`scripts/hooks/guard_migrations.py`).

### T3 — Settings for login rate and cookie security

- **Implements:** AC4; AC6a (boot half); SD7, SD8 settings
- **Expected output:**
  - `Settings.login_rate_per_minute: int = Field(10, ge=1)`.
  - `Settings.session_cookie_secure: bool = True`.
  - A model validator that raises `ConfigError` naming `SESSION_COOKIE_SECURE` when `app_env == "production"` and it is false.
  - Both added to `.env.example` with their defaults.
  - AC4 already holds (`jwt_secret: Field(min_length=32)`, `tests/unit/test_config.py:80`). This task adds the missing-variable case for `JWT_SECRET` if it is not already covered, and asserts the message names it.
- **Verification:**
  - `uv run pytest tests/unit/test_config.py -v`.
  - `uv run pytest tests/meta/test_compose_matches_env_example.py tests/meta/test_config_boundary.py`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** validator placement and message wording.
  - **Must stop and ask about:** changing any existing setting's default.

### T4 — The clock seam

- **Implements:** SD32; PD10. It enables AC18a, AC22, AC25 and AC5's window
- **Expected output:**
  - `app/runtime/clock.py`: `Clock` (Protocol) and `RealClock`, the only `import time` under `app/runtime` and `app/realtime`.
  - `tests/support/clock.py`: `FakeClock(wall_start_ms, monotonic_start=0.0)`. It has `advance(ms)`, which wakes every `sleep_until` whose deadline has passed, in deadline order. It also has `set_wall(ms)` to model a wall-clock jump (SD13 re-anchor).
  - `tests/meta/test_clock_seam.py`: an AST walk in the `test_no_file_io.py` shape, with a `MUST_SEE` that names `clock.py`. It fails on `import time` / `from time import` in any other file under the two roots, and has a detector self-test.
- **Verification:**
  - `uv run pytest tests/meta/test_clock_seam.py tests/unit/test_fake_clock.py -v`. The fake clock gets its own small unit test, in `tests/unit/test_fake_clock.py`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the fake's internals.
  - **Must stop and ask about:** adding a method to `Clock` beyond SD32's three.

### T5 — The grace rule, pure

- **Implements:** AC10, AC11 (pure halves); SD18; SD24's step assertion
- **Expected output:** `app/runtime/grace.py`:
  - `judge(lines: Sequence[QuotedLine], live_cents: Mapping[int, int], *, step_cents: int, current_version: int, quote_version: int, grace_versions: int) -> Charged | PriceChanged`.
  - The whole order is judged: one line outside grace rejects all of them.
  - `Charged.lines` carries the charged unit price per line, which is always the quoted one.
  - `PriceChanged` carries every line's live cents and `current_version`.
  - It asserts each `live_cents` value is a multiple of `step_cents`.
  - `step_cents_from(step_quant) -> int` rejects a `step_quant` that is not a whole number of cents.
- **Verification:** `uv run pytest tests/unit/test_grace.py -v`. A table over (delta ∈ {0, ±step, ±step+1, ±2·step}) × (age ∈ {0, grace, grace+1, 1000}) asserts each SD18 branch. Delta 0 is charged at any age, a mixed order is rejected whole, and a non-multiple `live` trips the assertion.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** type names.
  - **Must stop and ask about:** any reading of SD18 other than the three bullets. This is the pricing contract.

### T6 — Candles, pure

- **Implements:** SD25; AC20 (candle half); PD14
- **Expected output:** `app/runtime/candles.py`:
  - `chart_cents(p_cont) -> int`.
  - `bucket_start(ts_ms, interval_ms)` aligned to wall-clock multiples.
  - `Candle(t_ms, o, h, l, c)`.
  - `CandleBook(interval_ms)` with `update(ts_ms, source, {drink_id: chart_cents}) -> {drink_id: Candle}` for the current bucket. A `gap` source closes the open bucket, so the next update opens a fresh one even in the same interval.
  - `bars_from_ring(entries, interval_ms)` for the snapshot. It reuses `TickEntry` from `app/runtime/history.py`.
- **Verification:** `uv run pytest tests/unit/test_candles.py -v`. Covers bucket alignment, OHLC across a bucket boundary, a gap closing a bucket mid-interval, `bars_from_ring` agreeing with incremental `update`, and half-even rounding at x.xx5.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** internal representation.
  - **Must stop and ask about:** bucketing on anything other than `chart_price_cents`.

### T7 — Market-event rules and the gap shift for events, pure

- **Implements:** AC19a (pure half); SD23 (targets, text, levels, gap anchors)
- **Expected output:**
  - `app/runtime/market_events.py`:
    - `EventKind = Literal["crash","bubble","correction"]`.
    - `ActiveEvent(event_id, kind, drink_ids, t_start_ms, t_end_ms)`.
    - `target_cents(kind, drink_row)`: `p_min` / `p_max` / `p0`.
    - `NEWS_FOR_KIND` with v1's three Dutch texts verbatim (`legacy/v1/backend/api.py:492-500`) and levels `danger` / `warning` / `info`.
    - `shift_events(events, shift_ms)`.
  - `app/runtime/gap.py`: factor out `gap_shift_ms(*, last_wall_ts_ms, now_ms, budget_ms) -> int | None`, the same `gap − budget` arithmetic, used by `apply_gap_rule` unchanged in behaviour, so the ticker (T16) and rehydrate (T12) shift events by exactly the jump amount.
- **Verification:** `uv run pytest tests/unit/test_gap.py tests/unit/test_market_events.py -v`. Phase 2's gap tests stay unmodified and green. A new test asserts `shift_events` and `apply_gap_rule` move by the same `gap_shift_ms`. The text table is compared to the v1 source lines.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** helper names.
  - **Must stop and ask about:** any change to `apply_gap_rule`'s output (Phase 2 PD1).

### T8 — Repository hygiene: no keys file, no key literal

- **Implements:** AC6c (hygiene half); PD19
- **Expected output:** `tests/meta/test_repo_hygiene.py` gains two checks over `git ls-files`: no tracked path whose name is `keys.json`, and no tracked text file matching PD19's regex. Each has a detector self-test (an in-memory path list, and a sample built by concatenation). The existing `.dockerignore` checks are unchanged.
- **Verification:** `uv run pytest tests/meta/test_repo_hygiene.py -v`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** binary-file skipping.
  - **Must stop and ask about:** exempting any tracked path. `legacy/v1/` holds no keys file today (verified), so no exemption is needed.

### T9 — Advisory lock and the `runs go-live` CLI

- **Implements:** SD11 (lock half), SD16 (CLI); AC18 (lock half)
- **Expected output:**
  - `app/db/advisory_lock.py`:
    - `ADVISORY_LOCK_KEY` (PD4).
    - `async acquire(engine) -> AsyncConnection | None`, which opens a dedicated connection, runs `pg_try_advisory_lock`, returns the open connection or closes it and returns `None`.
    - `async release(conn)`.
    - `async watchdog(conn, *, clock, interval_ms, on_lost)` (PD5).
  - `app/cli/runs.py` (`main(argv) -> int`, the `import_v1` shape): `go-live <run_id>`.
    - It takes the lock first and, if the lock is held, exits 2 with "the app is running; stop it first".
    - Otherwise it calls `go_live(engine, run_id, now_ms=…)`, prints the run, releases the lock, and maps `RunNotDraft` / `RunNotReady` / `LiveRunExists` to exit 1 with their messages.
- **Verification:** `uv run pytest tests/integration/test_advisory_lock.py tests/integration/test_cli_runs.py -v`:
  - A second `acquire` while the first holds the lock returns `None`.
  - `pg_terminate_backend` on the holder's pid makes `watchdog` call `on_lost` within one interval (fake clock).
  - `go-live` is refused while the lock is held, and succeeds otherwise.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** CLI output wording and the exit codes other than 0.
  - **Must stop and ask about:** any lock other than session-level `pg_try_advisory_lock`.

### T10 — Access keys: repository, format, CLI

- **Implements:** SD5; AC6c (storage half, `list` prints no secret); AC6e (CLI half); PD18
- **Expected output:**
  - `app/db/keys.py`: `create_key(conn, *, label, role, secret_hash) -> int`, `list_keys`, `revoke_key` (sets `revoked_at`; `LookupError` if absent), `get_key(conn, key_id)`, `touch_last_used(conn, key_id)`.
  - `app/api/security.py` (first slice): `mint_secret()`, `format_key(key_id, secret)`, `parse_key(raw) -> ParsedKey | None` (no hashing), `hash_secret`, `verify_secret`, and a lazily built `DUMMY_HASH` (not computed at import).
  - `app/cli/keys.py`: `create --role --label` inserts the row with a placeholder hash, then updates it with the real one, all in one transaction (the `key_id` is needed in the printed key, not in the hash). It prints `bb_<key_id>_<secret>` once. `list` prints id, label, role and status (`active`/`revoked`). `revoke <key_id>`.
- **Verification:**
  - `uv run pytest tests/unit/test_key_format.py tests/integration/test_cli_keys.py -v`:
    - Parse round trip, malformed forms rejected (prefix, non-digit id, empty secret).
    - After `create`, the stored `secret_hash` starts with `$argon2id$` and no column equals the secret.
    - `list` output contains neither the secret nor the hash.
    - `revoke` sets `revoked_at`.
  - `uv run pytest tests/meta/test_import_side_effects.py`.
- **Depends on:** T1, T2
- **Autonomy note:**
  - **May decide alone:** CLI table formatting.
  - **Must stop and ask about:** storing any secret-derived value other than the argon2id hash.

### T11 — Closed message models

- **Implements:** SD24, SD27 (envelope), SD28; AC20, AC20a, AC23 (model half); PD12
- **Expected output:** `app/realtime/messages.py`, every model `ConfigDict(extra="forbid", frozen=True)`:
  - `Envelope[T]` with `{v, type, seq, ts_ms, run_id: int | None, version: int | None, data}`.
  - `DrinkPrice{price_cents, chart_price_cents}`, `TickData{drinks: {drink_id: DrinkPrice + candle}}`.
  - `Snapshot{run, drinks, params, prices, bars, news (≤50), earnings {drink_id: {qty, revenue_cents}}, market_events}`.
  - `OrderData` (PD12), `MarketEventData{op: start|end, event_id, kind, drink_ids, t_start_ms, t_end_ms}`, `NewsData{op: add|delete, item}`, `Hello{boot_id, run_id, tick_interval_ms, protocol, role}`, `Pong{server_ts_ms}`, `Resync`, `ErrorData{code}`.
  - Client messages: `ClientHello{boot_id, last_seq}`, `ClientPing`, `ClientResyncRequest`, as a discriminated union on `type`.
  - Every price field is `int`.
- **Verification:** `uv run pytest tests/unit/test_messages.py -v`:
  - A six-drink `tick` serialises to ≤ 600 bytes (AC20).
  - A recursive walk over every model's JSON schema finds none of `prices_cont`, `expected_demand`, `t`, `server_time_wall`, `prices_quant`, `history` or `series` (AC20a).
  - The snapshot schema has `earnings`.
  - Every price-typed field is an integer and named `price_cents`, `chart_price_cents` or a candle's `o/h/l/c` (AC23).
  - Extra keys are rejected.
- **Depends on:** T6, T7
- **Autonomy note:**
  - **May decide alone:** model class names, the `v` protocol number (1).
  - **Must stop and ask about:** adding any field the spec or `realtime-protocol.md` does not name, beyond PD12's prices. Also stop if the 600-byte bound needs shortened keys (R6).

### T12 — Market-event repository and rehydrate

- **Implements:** SD23 (persist, rehydrate, gap shift on boot); AC19a
- **Expected output:**
  - `app/db/market_events.py`: `insert_event`, `end_event(conn, event_id, *, t_end_ms)` (rewrites `t_end_ms`, sets `ended_at`), `active_events(conn, run_id)`, `shift_active_events(conn, run_id, shift_ms)`.
  - `app/runtime/rehydrate.py`: `RehydratedRun` gains `market_events: tuple[ActiveEvent, ...]`, `quote_grace_versions` and `candle_interval_ms`.
  - When the gap rule fires, the gap write moves the jump anchors and the active events' `t_start_ms`/`t_end_ms` by the same `gap_shift_ms` (T7) **in one transaction**: CAS + gap tick + event shift, composed from `compare_and_set` and `insert_tick`.
  - Events whose shifted `t_end_ms ≤ now` stay active and are ended by the ticker's first slot (AC19).
- **Verification:**
  - `uv run pytest tests/integration/test_market_events_repo.py tests/integration/test_rehydrate.py -v`. Phase 2's rehydrate tests are unchanged and green. A new test: a live event with a gap beyond the budget, after `rehydrate`, has `t_start_ms` and `t_end_ms` shifted by exactly the amount the jump `t0_ms`/`t1_ms` moved (AC19a).
  - An injected failure on the event UPDATE leaves neither the tick nor the state written.
- **Depends on:** T2, T7
- **Autonomy note:**
  - **May decide alone:** whether `save_transition` gains an optional in-transaction hook or the gap path composes the primitives.
  - **Must stop and ask about:** changing the shift amount.

### T13 — `MarketHolder`

- **Implements:** SD12, SD22; AC14; PD11, PD21. It is the base for AC8
- **Expected output:** `app/runtime/holder.py`:
  - `MarketHolder.from_rehydrated(r, *, engine, clock, sink)` and `MarketHolder.empty(...)` for SD16.
  - Read-only properties: `run_id`, `spec`, `state`, `drink_ids`, prices, ring, earnings, news, active events, `quote_grace_versions`, `candle_interval_ms`, `last_commit_wall_ms`.
  - `async mutate(op: str, step) -> T`: lock → `step(view)` returns `Outcome(result, new_view, events)` after doing its one transaction → publish `new_view` → release → log `lock_hold_ms` warning above 50 ms naming `op` → `sink(events)`.
  - If the step raises, memory is unchanged, the lock is released, and the error propagates. `StaleState` is re-raised as `PersistenceUnavailable` (PD21), and other `SQLAlchemyError`/`OSError` likewise.
  - A `NoLiveRun` 409 for every mutate on an empty holder.
  - Domain-event dataclasses per PD11.
- **Verification:** `uv run pytest tests/integration/test_holder.py -v`:
  - A sink that asserts `not holder.lock.locked()` on every call (AC14).
  - A step whose transaction sleeps 60 ms on the fake clock and real `pg_sleep(0.06)` produces exactly one `lock_hold_ms` warning naming the op (AC14, SD22, via `caplog`).
  - A step that raises leaves `holder.state is before`.
  - Mutations queued behind the lock run in arrival order.
  - `uv run pytest tests/meta/test_no_file_io.py tests/meta/test_clock_seam.py`. `app/runtime/holder.py` is added to `MUST_SEE` in `test_no_file_io.py`.
- **Depends on:** T4, T12
- **Autonomy note:**
  - **May decide alone:** the `step` signature details, and whether `view` is a dataclass or the holder itself, read-only.
  - **Must stop and ask about:** any path that publishes before commit or calls the sink under the lock.

### T14 — The hub

- **Implements:** SD27, SD29; AC21, AC22 (hub half)
- **Expected output:** `app/realtime/hub.py`:
  - `Hub(*, clock, replay_window_ms, boot_id=secrets.token_hex(8))`.
  - `broadcast(envelope)` assigns the next `seq`, serialises once and appends to the replay log (trimmed by `ts_ms` to the window). It enqueues to every connection without awaiting.
  - `unicast(conn, envelope)` stamps the current `seq`.
  - `connect(socket) -> Connection` has a bounded queue of 64 and one writer task. On overflow it drops every queued `tick`, then enqueues one `resync`. If it is still full, it closes with 1013. A send exceeding 10 s closes that connection.
  - `replay_after(boot_id, last_seq) -> list[bytes] | None`.
  - `close_all(code)`.
  - The socket is a small Protocol (`send_text`, `close(code)`), so tests use fakes.
- **Verification:** `uv run pytest tests/unit/test_hub.py -v` on the fake clock:
  - A never-reading fake socket plus a healthy one, over 120 fake seconds of ticks at 1 Hz. The healthy one receives all 120 in order. The stuck one gets `resync` after overflow, then closes. `broadcast` never awaits.
  - The replay log returns exactly the frames after `last_seq`, `None` for a foreign `boot_id` or a trimmed seq.
  - Unicast does not move `seq`.
  - A 10 s send closes only that connection.
- **Depends on:** T4, T11
- **Autonomy note:**
  - **May decide alone:** the writer-task structure.
  - **Must stop and ask about:** any await in `broadcast`.

### T15 — Security primitives

- **Implements:** SD2 (route table), SD6, SD7, SD8, SD9 (the pure parts); AC5, AC6, AC6a (cookie attributes), AC6b (predicate)
- **Expected output:** `app/api/security.py` gains:
  - `ROLE_ROUTES: Final = {"display": ("/koers",), "bar": ("/bar", "/manipulation"), "admin": ("/", "/koers", "/bar", "/manipulation", "/settings")}`.
  - `issue_session(key_id, role, *, secret, now_ms) -> (token, exp_ms)` and `read_session(token, *, secret, now_ms) -> Claims | None` (HS256, 24 h, `exp` checked against the injected time, not PyJWT's wall clock).
  - `LoginLimiter(rate_per_minute, clock)` with `check(ip) -> retry_after_s | None`, counting every attempt.
  - `same_origin(origin, host) -> bool`.
  - `async verify_login(raw_key, lookup, *, verifier) -> AuthKeyRow | None`: parse, look up, then exactly one `await asyncio.to_thread(verifier, hash_or_dummy, secret)` for any well-formed key, and zero for a malformed one.
  - `cookie_kwargs(settings)` with `httponly=True, samesite="strict", secure=settings.session_cookie_secure`.
- **Verification:** `uv run pytest tests/unit/test_security.py -v`:
  - The 11th attempt in 60 fake seconds is limited, with the right `Retry-After`. The window rolls.
  - The verifier is called once for unknown, revoked and valid keys, with 1 and 50 keys present, and zero times for malformed keys. A thread-identity check proves it runs off the loop thread (AC6).
  - An expired token is `None`. A tampered token is `None`.
  - `same_origin` rejects scheme-less, port-differing and absent origins.
- **Depends on:** T3, T10
- **Autonomy note:**
  - **May decide alone:** the claims encoding.
  - **Must stop and ask about:** any session lifetime other than 24 h, and any additional cookie.

### T16 — The ticker

- **Implements:** SD13, SD14, SD23 (event end); AC18a, AC18b, AC19 (end half), AC17 (liveness timestamps)
- **Expected output:** `app/runtime/ticker.py`:
  - `Ticker(holder, *, clock, interval_ms, budget_ms=DEFAULT_CATCH_UP_BUDGET_MS)`.
  - It records the anchor `(wall_ms, monotonic)`, and slot `k` fires at `monotonic_anchor + k·interval`, stamped `wall_anchor + k·interval`.
  - Each slot runs `holder.mutate("tick", step)` with `advance(orders=None)` and `save_transition(source="tick")`, even with no price move. Then, if any active event has `t_end_ms ≤ now_ms`, it ends that event in a second mutate and emits `MarketEventEnded`.
  - Lag ≤ budget runs the missed slots back to back with their own stamps.
  - Lag > budget, or |Δwall − Δmonotonic| > budget, re-anchors. It then applies `gap_shift_ms` / `apply_gap_rule` plus T12's event shift as one `gap` mutate, with no `advance` across the gap.
  - A failed commit is logged with the version, and the slot is skipped (SD14).
  - It exposes `last_iteration_monotonic` and `last_commit_wall_ms` for `/healthz`.
  - It idles when the holder is empty (SD16).
  - `stop()` finishes the current iteration.
- **Verification:** `uv run pytest tests/integration/test_ticker.py -v` on the fake clock and a scratch database:
  - 60 fake seconds produce exactly 60 `tick` rows with grid stamps and gap-free versions (AC18a).
  - A 20 s stall followed by catch-up produces 20 rows with their own stamps.
  - A 45 s stall produces one `gap` row, and `p_cont` before equals `p_cont` after the gap row.
  - A failing commit (injected via an engine event listener) is followed by memory = last committed row and a normal next slot (AC18b).
  - An event with `t_end_ms` inside the next interval emits `MarketEventEnded` on that slot (AC19).
  - `stop()` during a slot lets that slot commit.
- **Depends on:** T13
- **Autonomy note:**
  - **May decide alone:** the loop structure.
  - **Must stop and ask about:** deduplicating idle ticks, or any retry of a failed commit.

### T17 — Auth routes, the API harness, and the route audit

- **Implements:** SD1 (auth rows), SD3, SD4, SD6–SD9, SD35; AC1 (meta half), AC4 (boot path), AC5, AC6, AC6a, AC6b, AC6e (HTTP half); PD8, PD9, PD15, PD16
- **Expected output:**
  - `app/core/errors.py`: PD8's `extra`, and the validation-error handler (PD9).
  - `app/api/deps.py`: `require_role(*roles)` loads the session cookie, checks it with `read_session`, loads the `auth_key` row by PK (`get_key`) and rejects revoked keys (401). It also provides `current_holder` and `db_engine` from `app.state`.
  - An `OriginGuard` pure-ASGI middleware: unsafe methods without a same-origin `Origin` get 403 `origin_mismatch`.
  - `app/api/auth.py`:
    - `login`: the limiter first, then `verify_login`, then `touch_last_used`. It sets the cookie and returns `{role, label, allowed_routes}`.
    - `logout`: clears the cookie.
    - `me`.
  - `app/main.py`: `create_app(*, clock, run_migrations, request_shutdown)` (PD16), the engine created and disposed in the lifespan, docs routes per PD15, no CORS middleware.
  - `tests/api/conftest.py`:
    - Reuses `scratch_database`/`database_url` by importing them from `tests.integration.conftest`.
    - Points `DATABASE_URL` at the scratch database and clears `get_settings`' cache.
    - Builds `TestClient(create_app(clock=FakeClock(...), run_migrations=False), base_url="https://testserver")`. https is needed so the `Secure` cookie round-trips.
    - Provides a `login(role)` helper that mints a key through `app/db/keys.py` and `hash_secret`.
  - `scripts/check.sh`: the integration step becomes `pytest_each tests/integration tests/api`.
  - `tests/meta/test_route_authorization.py` walks `create_app().routes`, including WebSocket routes and `Mount`s. Every route has a `require_role` in its dependant tree or is in `PUBLIC_ROUTES`, the single named allowlist: login, `/healthz`, `/readyz`, the SPA mount, and SD3's three docs paths.
- **Verification:**
  - `uv run pytest tests/api/test_auth.py tests/meta/test_route_authorization.py -v`:
    - The cookie has `Secure`, `HttpOnly`, `SameSite=Strict`.
    - The 11th login gets 429 with `Retry-After`, and the patched verifier counts zero calls for it (AC5).
    - The patched verifier counts exactly 1 call for each well-formed outcome and 0 for malformed (AC6).
    - An unsafe request without, or with a foreign, `Origin` gets 403.
    - The app's middleware stack holds no `CORSMiddleware` (AC6b).
    - After `app.cli.keys revoke`, `/api/auth/me` gets 401 (AC6e).
    - `/me` returns SD2's routes per role.
    - The audit fails on a fixture app with an unguarded route.
  - `uv run pytest tests/unit/test_app_shell.py`, still green.
  - `./scripts/check.sh` runs `tests/api`.
- **Depends on:** T1, T15
- **Autonomy note:**
  - **May decide alone:** the cookie name (`bb_session`), fixture layout.
  - **Must stop and ask about:** adding any route not in SD1, or any entry in `PUBLIC_ROUTES` beyond SD1 and SD3.

### T18 — The order domain

- **Implements:** SD17 (domain checks), SD18–SD21, SD24; AC7, AC9, AC10, AC11, AC12, AC13, AC14a (domain half), AC23 (charge half); PD6, PD7, PD21
- **Expected output:**
  - `app/db/orders.py`:
    - `write_order` gains `actor_key_id` and `response`. The receipt is written by an UPDATE on the order row after `order_id` is known, still inside the same transaction.
    - New `find_order_by_key(conn, key) -> StoredOrder | None`.
    - Phase 2's statement-count pin in `tests/integration/test_orders.py` is updated to the new count, so the AC2 failure injection still covers every statement.
  - `app/runtime/orders.py`, `async place_order(holder, request, *, actor_key_id, now_ms) -> PlacedOrder`:
    - Inside `holder.mutate("order", …)`, in this order:
      - Look up the idempotency key; on a match, return the stored receipt per PD6.
      - Check `quote_version > current`, and that each line's drink is active (422).
      - `judge` (T5) against `cents_from_quantised` of the live `p_q`.
      - `advance(orders=qty_vector)`.
      - `write_order`.
      - Build the `Receipt` (PD7) and emit `OrderCommitted` with the earnings delta (reusing `EarningsAggregate.add_lines`).
    - A unique violation on `order_idempotency_key_key` at commit re-reads and replays (SD20).
    - `Receipt` lives here.
- **Verification:** `uv run pytest tests/integration/test_orders.py tests/integration/test_place_order.py -v`:
  - AC7: a tick is forced to take the lock between parse and lock (the order coroutine waits on a lock the test holds while it runs a tick), and the order is judged at the post-tick version.
  - AC9: a sequential replay returns identical bytes with one order row and one price move. `asyncio.gather` of two identical requests gives the same result. A changed `qty`, price or `quote_version` gets 422 and changes nothing.
  - AC10/AC11: grace accepted and rejected on a real run, and on rejection there are no new rows and `engine_state` and memory are unchanged.
  - AC12: the receipt matches `order_line`.
  - AC13: a failure injected at each statement gives 503 and unchanged memory, `engine_state` and ledger.
  - AC14a: an inactive drink and `quote_version` > current give 422 and no rows.
- **Depends on:** T5, T13
- **Autonomy note:**
  - **May decide alone:** the `PlacedOrder` shape.
  - **Must stop and ask about:** charging anything other than the judged price, or moving the engine by anything other than the ordered `qty`.

### T19 — The publisher

- **Implements:** SD24, SD25, SD26 (broadcast shape), SD28; AC19 (start/end message), AC20, AC23, AC18e (broadcast half)
- **Expected output:** `app/realtime/publish.py`:
  - `Publisher(hub, candle_book)` is the holder's sink.
  - It maps `TickCommitted` → `tick` (prices plus the current candle from `CandleBook.update`), `OrderCommitted` → `order` (PD12), `NewsChanged` → `news`, and `MarketEventStarted/Ended` → `market_event`.
  - Every envelope carries the committed `version`.
  - `snapshot(holder) -> Snapshot` is shared by `GET /api/state` and `/ws`. It is built purely from holder memory: 50 newest news, earnings, `bars_from_ring`, active events.
- **Verification:** `uv run pytest tests/unit/test_publish.py -v`:
  - Each domain event yields exactly one message of the right type.
  - The `gap` tick closes the candle.
  - Every price in every produced message is `int`, and `price_cents` is a multiple of the step.
  - The snapshot carries earnings and no dead fields.
- **Depends on:** T6, T11, T13, T14
- **Autonomy note:**
  - **May decide alone:** the mapping structure.
  - **Must stop and ask about:** reading the database in `snapshot`.

### T20 — Boot wiring and health

- **Implements:** SD11, SD15, SD16 (boot); AC17, AC18 (in-process half), AC18c (boot half), AC4 (boot fails)
- **Expected output:**
  - `app/runtime/boot.py`: `async start_runtime(app, settings, *, clock, run_migrations, on_lock_lost)`, an async context manager.
    - Startup: `create_engine` → `acquire` the lock or raise `BootFailure("advisory lock held by another instance")`, logged → `to_thread(upgrade head)` when `run_migrations` (PD3), whose failure fails boot → `rehydrate` → `MarketHolder` (or empty) → `Hub` → `Publisher` → `Ticker` task → lock watchdog task → `ready = True`.
    - Shutdown: `ready = False`, draining, `ticker.stop()`, `hub.close_all(1012)`, release the lock, dispose the engine.
  - `app/main.py`'s lifespan delegates to it.
  - `main()` builds `uvicorn.Server` and wires `request_shutdown` (PD17).
  - `app/api/health.py`:
    - `/healthz`: 200 `{status, last_tick_age_ms, last_commit_age_ms}` while the ticker completed an iteration within 3 intervals, else 503.
    - `/readyz`: 503 unless `ready` and a `SELECT 1` succeeds within 1 s.
  - `tests/unit/test_app_shell.py` is updated to pass a no-op runtime. Its existing assertions keep their meaning.
- **Verification:**
  - `uv run pytest tests/integration/test_boot.py tests/integration/test_health.py tests/unit/test_app_shell.py -v`:
    - A boot with the lock held elsewhere raises within 5 s, and the log names the lock, before the migration step runs (a spy on `upgrade`).
    - Boot order is recorded by spies.
    - With no live run, the app is ready, the ticker idles and `/readyz` is 200 (AC18c).
    - The fake clock is advanced past 3 intervals with the ticker task paused, and `/healthz` gets 503 with `last_tick_age_ms`.
    - The engine is pointed at a closed port, giving `/healthz` 200 and `/readyz` 503 (AC17).
    - A failing migration fails boot.
  - `uv run pytest tests/meta`.
- **Depends on:** T9, T16, T17, T19
- **Autonomy note:**
  - **May decide alone:** the `BootFailure` type, log keys.
  - **Must stop and ask about:** any boot order other than SD11's, or serving before migration.

### T21 — Concurrency proof

- **Implements:** AC8, AC18e; Verification "Concurrency"
- **Expected output:** `tests/integration/test_order_concurrency.py`:
  - 50 concurrent `place_order` calls (distinct keys, random lines) are `gather`ed while the ticker runs on the fake clock.
  - Jumps are interleaved (via `schedule_jump` through `holder.mutate`, a test-local step).
- **Verification:** `uv run pytest tests/integration/test_order_concurrency.py -v`:
  - `price_tick.version` per run is gap-free and strictly increasing.
  - Each order's `version` has a `price_tick` row with `source='order'`.
  - `holder.state` equals `load_state` of the committed row.
  - Ledger totals equal the receipts' sums.
  - No two distinct `prices` vectors share a version.
  - The recorded sink's message versions are strictly increasing (AC18e).
- **Depends on:** T16, T18
- **Autonomy note:**
  - **May decide alone:** the randomisation seed.
  - **Must stop and ask about:** relaxing any of the asserted invariants.

### T22 — State and news routes

- **Implements:** SD1 (rows), SD16, SD26; AC15, AC18c (HTTP half), AC28
- **Expected output:**
  - `app/db/news.py`: `list_news(…, newest_first=True, limit=None)` excludes `deleted_at IS NOT NULL`, and `soft_delete_news(conn, run_id, news_id) -> NewsItem | None`. Phase 2's ascending callers keep their order via the flag.
  - `app/api/state.py`: `GET /api/state` returns `publish.snapshot(holder)` and never calls the engine. With no live run it is 409 `no_live_run`.
  - `app/api/news.py`:
    - `GET` returns non-deleted items, newest first.
    - `POST {level, text}`: `level` is the lowercase four only, and `text` is trimmed to 1–500 characters (422 otherwise). It persists through `holder.mutate("news", …)` and emits `NewsChanged(op="add")`.
    - `DELETE /{news_id}` returns 404 `news_not_found` if absent or already deleted, and emits `op="delete"`.
  - The routes are registered in `app/main.py`.
- **Verification:** `uv run pytest tests/api/test_state.py tests/api/test_news.py tests/integration/test_news.py -v`:
  - 100 × `GET /api/state` leaves `engine_state` (whole row, including `rng_counter` and `version`) and every table's row count unchanged (AC15).
  - No live run gives 409 on `GET /api/state` and `POST /api/news` (AC18c).
  - News: the happy path broadcasts `news {op, item}` (a hub spy), the two 422s write nothing, and deleting twice gives 404 (AC28).
- **Depends on:** T20
- **Autonomy note:**
  - **May decide alone:** pagination (none; the snapshot caps at 50).
  - **Must stop and ask about:** accepting mixed-case levels over the API. SD26 says the lowercase four, unlike Phase 2's import (PD13).

### T23 — Design documents and the ADR 0008 addendum

- **Implements:** In scope 8 (no AC); SD11, SD18, SD27, SD28, PD12
- **Expected output:**
  - `architecture.md:59,122`: boot is lock → migrate → rehydrate → ticker → ready.
  - `realtime-protocol.md`:
    - `hello {boot_id, last_seq}` replaces `hello {last_version}`.
    - The envelope `seq` semantics are SD27's (broadcast increments, unicast stamps).
    - `order` carries prices (PD12).
    - `news` ops are `add|delete`.
    - `config`/`theme` are deferred to their phases.
  - `data-model.md`: the `order`, `market_event`, `auth_key` and `run` rows match T2.
  - `0008-honour-the-quoted-price.md`: an "Addendum (Phase 3, SD18)" recording the equal-price rule and `run.quote_grace_versions`.
  - `CLAUDE.md`: two Commands lines (`app.cli.keys`, `app.cli.runs go-live`).
- **Verification:** `uv run pytest tests/meta`, for any doc-link checks. A reviewer diff against the listed content.
- **Depends on:** T20
- **Autonomy note:** `docs/design/` and ADR edits are hard stops. They are authorised here by In scope 8 for exactly the content listed. Any other wording stops.

### T24 — Order route

- **Implements:** SD17, SD20, SD21; AC9 (HTTP bytes), AC11 (409 shape), AC13 (503 shape), AC14a; PD7, PD8
- **Expected output:** `app/api/orders.py`, `POST /api/orders` (`require_role("bar","admin")`):
  - The `Idempotency-Key` header is validated against `^[A-Za-z0-9_-]{8,128}$`.
  - Body model: `quote_version: int ≥ 0`, `lines: list[Line]` with 1..N entries, `qty` 1–99, unique `drink_id`.
  - A draining process gets 503 `shutting_down`.
  - It calls `place_order` with `actor_key_id` from the session.
  - It returns the receipt bytes: 201, or 200 on replay.
  - Registered in `app/main.py`.
- **Verification:** `uv run pytest tests/api/test_orders.py -v`:
  - A missing key, a short key and a bad character each get 422.
  - `qty` 0 and 100 get 422. A duplicate `drink_id` gets 422.
  - A 409 body has `error.code == "price_changed"`, `version` and `prices`.
  - An injected DB failure gives 503 `persistence_unavailable`, and a retry with the same key then succeeds once.
  - A replay's `response.content` is identical to the first, byte for byte.
  - `actor_key_id` is stored.
- **Depends on:** T18, T22
- **Autonomy note:**
  - **May decide alone:** the response model naming in OpenAPI.
  - **Must stop and ask about:** accepting an order without an `Idempotency-Key`.

### T25 — Jumps and market events

- **Implements:** SD23; AC19 (start, replace), AC26, AC27
- **Expected output:**
  - `app/runtime/manipulation.py`:
    - `schedule(holder, drink_id, target_cents, duration_ms)`: `schedule_jump` plus `save_transition(source="jump")`.
    - `start_event(holder, kind, duration_ms)`: one transaction that ends any active event at `now` (emitting its end), schedules a jump per active drink to `target_cents`, writes the `jump` tick, `insert_event` and `create_news` with `NEWS_FOR_KIND`. It emits `MarketEventStarted` and `NewsChanged`.
  - `app/api/market.py`: `POST /api/market/jumps` (`duration_ms` 1 000–1 800 000, target within `[p_min_cents, p_max_cents]`, active drink, else 422) and `POST /api/market/events` (`kind`, `duration_ms` 1 000–600 000, default 30 000).
  - Registered in `app/main.py`.
- **Verification:** `uv run pytest tests/integration/test_manipulation.py tests/api/test_market.py -v`:
  - Each 422 bound writes nothing.
  - A valid jump writes one `jump` row at version + 1, with `tick_index` unchanged, and the price differs from the no-jump path after the next tick (AC26).
  - An event writes the event row, the jump state and lowercase Dutch news, and a failure injected on the news INSERT writes none of them (AC27).
  - The hub spy sees `market_event` with absolute times and `news`.
  - A second event first broadcasts the end of the first, with its rewritten `t_end_ms` (AC19).
- **Depends on:** T22, T24
- **Autonomy note:**
  - **May decide alone:** request model names.
  - **Must stop and ask about:** any target other than `p_min`/`p_max`/`p0`, and any change to `schedule_jump`.

### T26 — The `/ws` endpoint

- **Implements:** SD27, SD30, SD31, SD16 (ws); AC3, AC16, AC18c (ws half), AC21 (endpoint half), AC24, AC25
- **Expected output:** `app/realtime/ws.py`, `WS /ws` with `require_role` applied at the handshake (so SD4's audit sees it):
  - **Handshake.** Origin and session are checked before `accept`; any failure closes with 1008 and no data. On accept it sends a `hello` unicast (`run_id` null with no live run). It then waits up to one interval for a client `hello` and, per `hub.replay_after`, either replays or sends a `snapshot` (no snapshot with no live run).
  - **Client messages** are parsed with the T11 union:
    - `ping` is answered with `pong{server_ts_ms}`.
    - `resync_request` gets a `snapshot`.
    - Anything else, or invalid JSON, gets `error{code}`.
    - More than 5 messages in a rolling second closes with 1008.
    - The handler never calls the engine or the holder's `mutate`.
  - **Expiry.** A timer on the injected clock closes with 4401 at `exp`.
  - Registered in `app/main.py`.
- **Verification:** `uv run pytest tests/api/test_ws.py -v` with `TestClient.websocket_connect`:
  - No cookie, a revoked key, a foreign `Origin` and a missing `Origin` each close with 1008 and no frame (AC3).
  - 6 messages in a second close with 1008. Every client message type, valid or not, leaves `engine_state` unchanged, and `holder.mutate` is spied to zero calls (AC16).
  - A `hello` with a current `boot_id` and `last_seq` inside the log receives exactly the later broadcasts and no snapshot; a foreign `boot_id` gets one snapshot whose `seq` is current (AC21).
  - `ping` gets a JSON `pong`, and every received frame `json.loads` (AC24).
  - Advancing the fake clock past `exp` closes with 4401 (AC25).
  - No live run gives `hello.run_id is None`.
- **Depends on:** T25
- **Autonomy note:**
  - **May decide alone:** how long to wait for the client `hello`.
  - **Must stop and ask about:** accepting before the session check.

### T27 — Admin shutdown

- **Implements:** SD10; AC6d; PD17
- **Expected output:**
  - `app/api/admin.py`: `POST /api/admin/shutdown` (`require_role("admin")`) sets draining, responds 202 and then schedules `request_shutdown`.
  - `app/runtime/boot.py`'s shutdown path is the same function SIGTERM reaches.
  - Registered in `app/main.py`.
- **Verification:** `uv run pytest tests/api/test_admin.py -v`:
  - An admin call invokes a spy `request_shutdown` once.
  - An order after the call gets 503 `shutting_down`.
  - Leaving the `TestClient` context runs the lifespan shutdown: `/readyz` 503 first, the ticker's current slot committed, the ws client closed with 1012, and the lock released (a second `acquire` succeeds).
  - bar and display get 403.
  - A grep-style test asserts no `ADMIN_TOKEN` in `app/`, `Settings` fields or `.env.example` (AC6d).
- **Depends on:** T26
- **Autonomy note:**
  - **May decide alone:** the 202 body.
  - **Must stop and ask about:** finalising earnings or writing anything on shutdown.

### T28 — Authorization matrix and static assets

- **Implements:** SD1, SD4; AC1, AC2, AC6d (403 half re-checked), AC6f; Verification "Authorization matrix"
- **Expected output:**
  - `tests/api/test_authorization_matrix.py`:
    - SD1's table is written out **in the test** as data, independent of the app's code.
    - It is parametrised over every (route, actor ∈ {anonymous, display, bar, admin, revoked}). Anonymous and revoked get 401, a role not in the row gets 403, and a permitted role gets not-401/403.
    - A completeness assertion compares the table's routes to `create_app().routes` minus `PUBLIC_ROUTES`, so a new route without a table row fails.
  - `tests/api/test_static.py`, with a built `web/dist` fixture as in `test_app_shell.py`:
    - Unauthenticated `GET /`, `/koers` and an asset return only files from `web/dist`.
    - Every route returning run data is under `/api` or `/ws` (a route walk).
    - `/api/unknown` is a JSON 404, not the SPA (AC6f).
- **Verification:** `uv run pytest tests/api/test_authorization_matrix.py tests/api/test_static.py -v`.
- **Depends on:** T27
- **Autonomy note:**
  - **May decide alone:** the parametrisation layout.
  - **Must stop and ask about:** any matrix entry that disagrees with SD1. Fix the code, not the table.

### T29 — Real-process proofs

- **Implements:** AC18, AC18d; SD34; Verification "Kill test", "Second instance"
- **Expected output:** `tests/integration/realapp/harness.py`, reusing `tests/integration/durability/harness.py`'s spawn/kill helpers:
  - It starts `python -m app.main` with `DATABASE_URL` on the scratch database and a free `PORT`, and waits for `/readyz` via `urllib.request`.
  - It mints keys and seeds a live run through the CLIs.
  - It drives orders over `urllib` with a session cookie and the `Origin` header.

  `tests/integration/test_real_process.py`:
  - **AC18d:** at five or more kill points (mid-order stream, right after an acknowledged order, mid-tick), `Popen.kill()` then a restart. Every acknowledged order is present, `price_tick` lost at most one tick, and `version`/`rng_counter` continue from the last committed row.
  - **AC18:** a second instance against the held lock exits non-zero within 5 s, logs the lock reason, and never ran a migration (checked by the alembic version table, unchanged on a database one revision behind).
  - **AC18:** `pg_terminate_backend` on the first instance's lock connection makes it exit non-zero.
- **Verification:** `uv run pytest tests/integration/test_real_process.py -v`, under 90 s.
- **Depends on:** T27
- **Autonomy note:**
  - **May decide alone:** kill-point timing, and the port-picking helper.
  - **Must stop and ask about:** reducing kill points below five, or using `curl`/`TestClient` here. It must be the real process over stdlib `urllib`.

---

## Task graph

```
T1, T2, T3, T4, T5, T6, T7, T8, T9      (no dependencies)
T10 ← T1, T2        T11 ← T6, T7        T12 ← T2, T7
T13 ← T4, T12       T14 ← T4, T11       T15 ← T3, T10
T16 ← T13           T17 ← T1, T15       T18 ← T5, T13       T19 ← T6, T11, T13, T14
T20 ← T9, T16, T17, T19                 T21 ← T16, T18
T22 ← T20           T23 ← T20
T24 ← T18, T22
T25 ← T22, T24
T26 ← T25
T27 ← T26
T28 ← T27           T29 ← T27
```

Critical path: T2 → T12 → T13 → T16 → T20 → T22 → T24 → T25 → T26 → T27 → T28/T29.

T22 → T24 → T25 → T26 → T27 is a chain partly because each registers its router in
`app/main.py` (one file). T25 also reuses T22's news path, and T27's shutdown closes T26's
sockets. T15 follows T10, and T17 follows T15, because they extend `app/api/security.py` in
turn.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1–T9 | T1: `pyproject.toml`, `uv.lock` · T2: `db/migrations/versions/0004…0007`, `app/db/models.py`, `tests/integration/test_schema.py` · T3: `app/core/config.py`, `.env.example`, `tests/unit/test_config.py` · T4: `app/runtime/clock.py`, `tests/support/*`, `tests/meta/test_clock_seam.py`, `tests/unit/test_fake_clock.py` · T5: `app/runtime/grace.py`, `tests/unit/test_grace.py` · T6: `app/runtime/candles.py`, `tests/unit/test_candles.py` · T7: `app/runtime/market_events.py`, `app/runtime/gap.py`, `tests/unit/test_gap.py`, `tests/unit/test_market_events.py` · T8: `tests/meta/test_repo_hygiene.py` · T9: `app/db/advisory_lock.py`, `app/cli/runs.py`, `tests/integration/test_advisory_lock.py`, `tests/integration/test_cli_runs.py` |
| 2 | T10, T11, T12 | T10: `app/db/keys.py`, `app/api/security.py`, `app/cli/keys.py`, `tests/unit/test_key_format.py`, `tests/integration/test_cli_keys.py` · T11: `app/realtime/__init__.py`, `app/realtime/messages.py`, `tests/unit/test_messages.py` · T12: `app/db/market_events.py`, `app/runtime/rehydrate.py`, `tests/integration/test_market_events_repo.py`, `tests/integration/test_rehydrate.py` |
| 3 | T13, T14, T15 | T13: `app/runtime/holder.py`, `tests/integration/test_holder.py`, `tests/meta/test_no_file_io.py` · T14: `app/realtime/hub.py`, `tests/unit/test_hub.py` · T15: `app/api/security.py`, `tests/unit/test_security.py` |
| 4 | T16, T17, T18, T19 | T16: `app/runtime/ticker.py`, `tests/integration/test_ticker.py` · T17: `app/core/errors.py`, `app/api/deps.py`, `app/api/auth.py`, `app/main.py`, `scripts/check.sh`, `tests/api/{__init__,conftest,test_auth}.py`, `tests/meta/test_route_authorization.py` · T18: `app/db/orders.py`, `app/runtime/orders.py`, `tests/integration/test_orders.py`, `tests/integration/test_place_order.py` · T19: `app/realtime/publish.py`, `tests/unit/test_publish.py` |
| 5 | T20, T21 | T20: `app/runtime/boot.py`, `app/main.py`, `app/api/health.py`, `tests/unit/test_app_shell.py`, `tests/integration/test_health.py`, `tests/integration/test_boot.py` · T21: `tests/integration/test_order_concurrency.py` |
| 6 | T22, T23 | T22: `app/db/news.py`, `app/api/state.py`, `app/api/news.py`, `app/main.py`, `tests/api/test_state.py`, `tests/api/test_news.py`, `tests/integration/test_news.py` · T23: `docs/design/{architecture,realtime-protocol,data-model}.md`, `docs/adr/0008-…md`, `CLAUDE.md` |
| 7 | T24 | `app/api/orders.py`, `app/main.py`, `tests/api/test_orders.py` |
| 8 | T25 | `app/runtime/manipulation.py`, `app/api/market.py`, `app/main.py`, `tests/integration/test_manipulation.py`, `tests/api/test_market.py` |
| 9 | T26 | `app/realtime/ws.py`, `app/main.py`, `tests/api/test_ws.py` |
| 10 | T27 | `app/api/admin.py`, `app/main.py`, `app/runtime/boot.py`, `tests/api/test_admin.py` |
| 11 | T28, T29 | T28: `tests/api/test_authorization_matrix.py`, `tests/api/test_static.py` · T29: `tests/integration/realapp/*`, `tests/integration/test_real_process.py` |

No two tasks in one group write the same file. `app/api/security.py` (T10 → T15),
`app/main.py` (T17 → T20 → T22 → T24 → T25 → T26 → T27), `app/runtime/boot.py` (T20 → T27) and
`tests/integration/test_news.py` (Phase 2 → T22) are each ordered by dependency across groups.
Builders run one at a time (ADR 0010 §1), so the groups give the merge order.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main` and in CI, with the output pasted, including `tests/api`.
- `uv run pytest tests/integration/test_real_process.py -v` output pasted (AC18, AC18d).
- `uv run pytest tests/engine` green, so the golden fixtures are untouched.
- The spec's manual run: `docker compose up`, `app.cli.keys create` × 3, `app.cli.runs go-live`, an HTTP login and order, `/ws` watched, `docker kill` mid-stream, restart, prices resume. This is the user's step (memory: the user drives the checklist).

---

## Data changes

Four forward-only migrations, chained from `0003`. All are additive: two new tables, two
nullable columns on `"order"`, and two defaulted columns on `run`. There is no backfill, and
existing rows stay valid: Phase 2 orders have NULL `actor_key_id`/`response`, and existing runs
take the defaults. Each migration is reversible by `downgrade`, which T2's round trip
exercises. Phase 2's revisions are not touched.

| Revision | Change | Constraints |
|---|---|---|
| `0004_auth_key` | `auth_key` | PK identity; `role` CHECK in three; `label` length CHECK; `secret_hash NOT NULL` |
| `0005_market_event` | `market_event` | FK `run`; `kind` CHECK in three; `t_end_ms > t_start_ms`; partial index on active events |
| `0006_order_actor_response` | `"order".actor_key_id`, `"order".response` | FK `auth_key`, both NULL-able |
| `0007_run_grace_and_candles` | `run.quote_grace_versions` (default 2), `run.candle_interval_ms` (default 60 000) | `≥ 0` and `> 0` CHECKs |

PD6 places `quote_version` inside `order.response`. That is a field of the receipt, not a
column. If the audit prefers a `request_hash` column instead, it goes into 0006 before T2 is
built.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **PD1: three new dependencies** are a hard stop. Until T1 is approved, T10, T15, T17 and everything after are blocked | T1 is first and tiny. Group 1's other tasks need none of the three |
| R2 | **PD6's body comparison** extends SD19's receipt with `quote_version`. An auditor may read SD20 as requiring a stored request | The alternative (a `request_hash` column) is noted in Data changes and costs one column in 0006. Decide before T2 |
| R3 | `TestClient` runs the app in a portal thread, while `FakeClock.advance` is called from the test thread | `advance` is invoked through `client.portal.call(...)`, so sleepers wake on the app's loop. T4's fake has no thread-safety of its own. T17 establishes the pattern, and T26 depends on it |
| R4 | **Windows has no real SIGKILL**, and `SIGTERM` via `raise_signal` skips handlers | T29 uses `Popen.kill()`, as Phase 2 R6 does; CI on Linux is the evidence. PD17 avoids signals for self-shutdown. A Windows-only T29 pass is not phase-exit evidence |
| R5 | AC18's "exit non-zero within 5 s" while the **database itself** is unreachable at boot depends on asyncpg's connect timeout | T20 sets `connect_args={"timeout": 4}` on the lock connection only. AC18 is about a *held* lock, which `pg_try_advisory_lock` answers immediately. An unreachable database failing boot slower is noted, not tested |
| R6 | AC20's 600-byte bound for six drinks with a candle each is tight with descriptive keys (about 95 bytes per drink) | T11 measures first. If over, it stops and asks, rather than silently using positional arrays: shortened keys are a protocol-contract choice |
| R7 | The SD13 ticker writes 86 400 rows a day, and the replay log covers `history_window_minutes` of broadcasts in memory | Phase 2 SD10/SD11 already accept the row rate. The log stores pre-serialised bytes (about 0.5 KB × 60/min × window), bounded by time |
| R8 | **The lock-loss watchdog uses `os._exit`** (PD5), so logs may not flush | It logs synchronously first; the JSON formatter writes to a stream handler with no buffering beyond the stream. T29 asserts only the exit code |
| R9 | `env.py` calls `get_settings()`. In the boot thread that is the cached settings, but a future change to `env.py` that reads its own environment would break PD3 silently | T20's boot test migrates a scratch database one revision behind and asserts it reached head, through the real `to_thread` path |
| R10 | AC7's "interleave a tick between parsing and lock" needs a seam inside `place_order` | The test holds `holder.lock` from outside, runs a tick step through the lock-free internals, and releases. Alternatively, an injected `before_lock` hook. The builder chooses, and the assertion is fixed |
| R11 | SD15's three-interval rule makes `/healthz` 503 during the boot window before the first tick | The ticker's first iteration runs before `ready = True` (T20), and the Dockerfile `HEALTHCHECK` has `--start-period=5s` (`docker/Dockerfile:64`) |
| R12 | Lowercase-only levels over the API (SD26) differ from Phase 2's case-insensitive import (PD13) | Different boundaries, different rules, as the spec says. T22's autonomy note forbids "helpfully" accepting `Info` |
| R13 | `quantize_step` is `np.round(x/step)*step` (`exchange/pricing.py:32`), so `cents_from_quantised` is a step multiple. The SD24 assertion (T5) relies on that | If a future `step_quant` is not a whole number of cents, `step_cents_from` rejects it at holder construction, not mid-order |
| R14 | SD16's CLI refuses while the app holds the lock, so a run going live needs an app restart | Spec-intended. The manual checklist's step order (go-live before `up`) reflects it |
| R15 | The `main.py` chain (seven tasks) serialises half the phase | Builders are serial anyway (ADR 0010 §1). Splitting routing into a registry file would only move the shared file |
| R16 | T23 edits `docs/design/` and an ADR | Authorised by In scope 8 for exactly the listed content |
| R17 | `tests/api` imports fixtures from `tests.integration.conftest`, which pytest discourages (`pytest_plugins` in a non-root conftest) | Re-export by plain `from … import` of fixture functions in `tests/api/conftest.py`, which works without `pytest_plugins`. If collection complains, move the shared fixtures to `tests/conftest.py` and stop to confirm that move |

---

## Out of scope for this plan

- Everything in the spec's Out of scope: any UI, `POST /config`, drinks, reset, theme,
  uploads, run lifecycle while running, analytics, `GET /api/history`, xlsx export, the key UI
  and closing sockets on revoke, client reconnect, proxy headers, TLS, the Docker image, Render,
  and horizontal scale.
- Setting `correlation_id` per request (`app/core/logging.py`). It is not in any AC; Phase 8.
- Any change under `exchange/`, `legacy/v1/` or `tests/engine/v1_reference/`.
- Editing `docs/plans/manual-checklist.md` (the user's file), or flipping the spec's Status
  header (the user's).
- A `pytest-asyncio` migration of existing tests.

---

## Audit (plan-auditor — PASS required before implementation starts)

- [x] Every AC maps to at least one task:
  - AC1 → T17, T28
  - AC2 → T28
  - AC3 → T26
  - AC4 → T3, T20
  - AC5 → T15, T17
  - AC6 → T15, T17
  - AC6a → T3, T15, T17
  - AC6b → T15, T17
  - AC6c → T2, T8, T10
  - AC6d → T27, T28
  - AC6e → T10, T17
  - AC6f → T28
  - AC7 → T18
  - AC8 → T13, T21
  - AC9 → T18, T24
  - AC10 → T5, T18
  - AC11 → T5, T18, T24
  - AC12 → T18
  - AC13 → T18, T24
  - AC14 → T13
  - AC14a → T18, T24
  - AC15 → T22
  - AC16 → T26
  - AC17 → T16, T20
  - AC18 → T9, T20, T29
  - AC18a → T16
  - AC18b → T16
  - AC18c → T20, T22, T26
  - AC18d → T29
  - AC18e → T19, T21
  - AC19 → T16, T19, T25
  - AC19a → T7, T12
  - AC20 → T6, T11, T19
  - AC20a → T11
  - AC21 → T14, T26
  - AC22 → T14
  - AC23 → T5, T11, T19
  - AC24 → T26
  - AC25 → T26
  - AC26 → T25
  - AC27 → T25
  - AC28 → T22
- [x] Every task maps to at least one AC. T1 (SD33) and T4 (SD32) enable ACs rather than prove them alone. T23 has no AC: it implements In scope 8
- [x] PD1 approved (dependencies, hard stop). PD6, PD7 (201 vs 200) and PD12 confirmed, since they extend named contracts. PD17's self-shutdown mechanism accepted
- [x] Existing modules reused, not reinvented: see the reuse list above the tasks
- [x] No new dependency without an approval note: three, under Files, gated by T1
- [x] Data changes additive and reversible (T2 round trip)
- [x] Errors, empty states and permissions are tasks: no live run (T20, T22, T26), every 4xx/5xx in PD9, authorization matrix (T28), route audit (T17)
- [x] Each task reviewable in one sitting. Largest: T17 (about 9 files, about 400 lines), T18 and T26
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra: scratch databases only, keys minted at runtime, no committed key literal (T8)
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audited by: MartijnBoot  Date: 2026-10-01
