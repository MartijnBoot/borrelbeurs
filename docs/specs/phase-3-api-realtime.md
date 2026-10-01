# Spec: Phase 3 — API, authorization, ticker and realtime

Status: Draft · Depends on: Phase 2
Fixes: D-06, D-07, D-08, D-15, D-18, D-28, D-31, D-32, D-33, D-34, D-36
Re-establishes in v2: D-27, D-37, D-38, D-39, D-40, D-41, D-42 — these were closed by the
v1 hotfix ([ADR 0007](../adr/0007-v1-authorization-hotfix.md)), **which is discarded when v2
lands**. v2 must prove them again on its own code, not inherit the fix.

## Problem

v1 has no owner of time. Every payload build advances the engine
(`legacy/v1/backend/api.py:773-778`: idle, jumps, Brownian, snapshot), and the payload is
built from `GET /state` (`api.py:309-311`), from the broadcast loop, from every mutating route
and from the WebSocket (`api.py:913-914`, the literal string `"state"`). So reads mutate, and
any connected tab can force an engine advance.

Because the version must be cheap to build on the read path, it is a timestamp:
`LAST_SNAPSHOT["version"] = engine.last_snapshot_ts_ms` (`api.py:781`). That timestamp only
moves on the `refresh_minutes` gate, so it does not change when orders, jumps or noise move
prices (D-08). The order path compares it **before** taking the lock (`api.py:342` vs `:350`),
then charges from `LAST_SNAPSHOT["p_q"]` (`:364`), which the broadcast loop writes. There is no
idempotency, so a retried order charges twice and moves the price twice (D-06, D-07).

The broadcast is one fat `state` message (`api.py:790-814`). It carries the whole history
deque (`:788`), the full news list and the earnings summary. That summary includes
`series`, one entry per sale (`persistence.py:161,179`), which grows all night (D-31, D-32).
It also carries fields no client reads (D-33). `ConnectionManager.broadcast` awaits each
`send_text` in turn (`api.py:284-293`), so one slow television stalls every client and the
ticker behind it (D-34). The active market event carries only its type (`api.py:506-507`, `:771`).
The client cannot count down, so a 30-second crash overlay stays up until the next scheduled
broadcast (D-15). The ping reply is bare text `"pong"` in a JSON stream (`api.py:912`).

v1's authorization is hotfix-grade (ADR 0007): plaintext keys in `keys.json`, a cookie set
without `Secure` (`api.py:223-228`), `JWT_SECRET` falling back to a per-process random value
(`auth.py:21`), and a second `ADMIN_TOKEN` mechanism for `/shutdown` (`api.py:600-612`). With
an SPA there are no page routes left to gate, so v1's page RBAC (`auth.py:26-30`) would
become nothing at all.

## Decisions

Settled at the spec interview (2026-10-01). The planner must not reopen them.

**Surface**

- **SD1 — Minimal route set.** Phase 3 builds only the routes below. `POST /config`, drinks,
  reset, theme, uploads, run lifecycle and export arrive with the phases that design them
  (6, 7), each with its own authorization test, which SD4 enforces mechanically.

  | Route | Roles |
  |---|---|
  | `POST /api/auth/login`, `GET /healthz`, `GET /readyz`, SPA static assets | public |
  | `POST /api/auth/logout`, `GET /api/auth/me`, `GET /api/state`, `GET /api/news`, `WS /ws` | display, bar, admin |
  | `POST /api/orders`, `POST /api/news`, `DELETE /api/news/{news_id}`, `POST /api/market/jumps`, `POST /api/market/events` | bar, admin |
  | `POST /api/admin/shutdown` | admin |

  Bar keeps v1's manipulation rights (`auth.py:28`: bar sees `/manipulation`).
- **SD2 — Roles are `display`, `bar`, `admin`.** `/api/auth/me` returns `role`, the key's
  `label` and `allowed_routes`. The SPA route list per role is defined once, server-side:
  display → `/koers`; bar → `/bar`, `/manipulation`; admin → all of
  `/`, `/koers`, `/bar`, `/manipulation`, `/settings`. It replaces `ROLE_PAGES` and
  `ROLE_LANDING`.
- **SD3 — OpenAPI docs only outside production.** `/docs`, `/redoc` and `/openapi.json` are
  mounted only when `APP_ENV != production`. Phase 4's TypeScript generation reads the schema
  from `create_app().openapi()` in-process, not over HTTP.
- **SD4 — Authorization is checked by a meta test, not by review.** A test enumerates every
  route and WebSocket route on `create_app()`. It fails if one has neither an explicit role
  dependency nor membership in a single, named public allowlist (SD1's public row plus SD3's
  docs routes).

**Keys and sessions**

- **SD5 — Keys are minted by CLI, globally, not per run.** Phase 3 adds an `auth_key` table
  (its own migration): `key_id`, `label`, `role`, argon2id `secret_hash`, `created_at`,
  `revoked_at`, `last_used_at`. `uv run python -m app.cli.keys create --role <r> --label <l>`
  prints `bb_<key_id>_<secret>` **once**. `list` shows id, label, role and status, never a
  secret or hash. `revoke <key_id>` sets `revoked_at`. There is no key UI before Phase 6.
- **SD6 — Login does exactly one argon2 verify, off the event loop.** The key is parsed as
  `bb_<key_id>_<secret>`. A malformed key returns 401 without hashing. For an unknown,
  revoked or well-formed key, the system verifies once, inside `asyncio.to_thread`, against
  the stored hash or, if there is none, a fixed dummy hash, so the response time does not
  reveal whether `key_id` exists. A successful login sets `last_used_at`; no other request
  writes to `auth_key`.
- **SD7 — Login is rate-limited per client IP, in memory, before parsing or hashing.**
  Defaults: 10 attempts per rolling 60 s per IP, a `LOGIN_RATE_PER_MINUTE` setting in
  `app/core/config.py`. Over the limit returns 429 with `Retry-After`. Failed and successful
  attempts both count. Which IP is the client's behind Render's proxy is Phase 8
  (forwarded-allow-ips); Phase 3 uses `request.client.host`.
- **SD8 — Session: HS256 JWT in an `HttpOnly` cookie, 24 h (v1's `SESSION_HOURS`).** Claims:
  `key_id`, `role`, `exp`. Every authenticated request also loads its `auth_key` row by
  primary key, so `revoke` takes effect on the next request, not at expiry. Logout clears the
  cookie. The cookie is `SameSite=Strict` and `Secure`. `Secure` is a
  `SESSION_COOKIE_SECURE` setting, default `true`, and boot **refuses** `false` when
  `APP_ENV=production`. **Open risk handed to Phase 8:** phones reaching the offline laptop
  over plain `http://192.168.x.x` will not store a `Secure` cookie. Phase 8 decides between
  TLS at the venue and an offline profile; Phase 3 does not weaken the default.
- **SD9 — CSRF: same-origin `Origin` required on every unsafe request and on the WebSocket
  handshake.** `POST`, `PUT`, `PATCH` and `DELETE` without an `Origin` header, or with one
  whose host is not the request's own `Host`, return 403. The same check on `/ws` blocks
  cross-site WebSocket hijacking, since browsers send cookies on cross-site WS handshakes. No
  CORS middleware is installed at all (architecture: one origin).
- **SD10 — `ADMIN_TOKEN` does not exist.** `POST /api/admin/shutdown` (admin session)
  runs the same graceful path as `SIGTERM`. Readiness goes false, new orders get 503, the
  ticker finishes its current iteration, every WebSocket is closed with 1012, the advisory
  lock is released and the process exits 0. It finalizes no earnings; export is Phase 7.

**Ticker, lock and boot**

- **SD11 — Boot order is ADR 0011's: lock → migrate → rehydrate → ticker → ready.** This
  departs from `architecture.md`'s "migrate → lock" listing, which is updated in this phase.
  The advisory lock (`pg_try_advisory_lock` on a fixed, named constant) is taken on a
  **dedicated connection held for the process lifetime**. If it cannot be acquired, boot fails
  non-zero within 5 s and logs the reason. If that connection is lost while running, the
  process exits non-zero, because it can no longer prove it is the only writer.
- **SD12 — One process-wide `MarketHolder` owns spec, state, ring, earnings, news, active
  market events and one `asyncio.Lock`.** Every mutation follows the same order. Take the
  lock. Compute the candidate with the pure engine. Run **one** database transaction.
  Publish the candidate to memory only after commit. Release the lock. Enqueue broadcasts to
  the hub. Inside the lock there is no file I/O, no `await` on a socket and no hub call (AC14).
- **SD13 — The ticker runs on a monotonic 1 Hz grid with wall-clock stamps.** At start (and
  every re-anchor) it records an anchor pair `(wall_ms, monotonic)`. Grid slot `k` fires at
  `monotonic_anchor + k·interval` and is stamped `now_ms = wall_anchor + k·interval`. Every
  slot calls `advance(orders=None)` and persists the result (UPSERT `engine_state` + INSERT
  `price_tick` with `source='tick'`), even if no price moved: SD10 and SD11 of Phase 2 hold,
  one row per accepted transition, never deduplicated. Missed slots whose total lag is
  ≤ the catch-up budget (30 s, the Phase 2 constant) run back-to-back with their own grid
  stamps. Beyond the budget, the ticker re-anchors and applies the Phase 2 gap rule
  (`app/runtime/gap.py`) to the live state. It writes one `gap` tick and does not evolve
  across the gap. It also re-anchors when wall and monotonic time diverge by more than the
  budget (a clock change); Phase 8 AC13 tests that.
- **SD14 — A failed tick commit is skipped, not retried.** The candidate is discarded, the
  error is logged with the version, memory keeps the last committed state, and the next slot
  computes from it. The ticker loop does not die on a database error.
- **SD15 — `/healthz` reports ticker liveness; `/readyz` reports the database.** `/healthz`
  returns 200 with `last_tick_age_ms` while the ticker loop has completed an iteration
  (committed, failed or idle) within three intervals, and 503 otherwise. This deliberately
  changes `app/api/health.py`'s "never dependent on a downstream" rule: a wedged ticker is a
  wedged process, and restarting it is correct. A database outage alone does not fail
  `/healthz`. It fails `/readyz` and shows as `last_commit_age_ms`, so the platform does
  not restart-loop a healthy process against a dead database.
- **SD16 — No live run is a valid state, not an error.** The app boots, becomes ready, and the
  ticker loops idle. `GET /api/state` and every mutation return 409 `no_live_run`. `/ws`
  accepts, sends `hello` with `run_id: null`, and sends no snapshot. A run is made live with a
  new CLI, `uv run python -m app.cli.runs go-live <run_id>`. It wraps Phase 2's `go_live`,
  first tries the advisory lock and refuses while the app holds it. A run going live therefore
  takes effect at the next boot. Live switching while running is Phase 7's run lifecycle.

**Order path**

- **SD17 — Request shape.** `POST /api/orders` with an `Idempotency-Key` header (required,
  8–128 characters of `[A-Za-z0-9_-]`, else 422) and body
  `{quote_version, lines: [{drink_id, qty, unit_price_cents}]}`. `qty` is an integer 1–99.
  At most one line per `drink_id`; `lines` has 1 to N entries. Every `drink_id` must be an
  active drink of the live run, else 422. `quote_version` greater than the current version
  is 422.
- **SD18 — The grace rule, refining ADR 0008.** Under the lock, for each line, let `live` be
  the drink's current charged price (SD24) in cents and `step` be `step_quant` in cents.
  - `unit_price_cents == live` → charge it, whatever the quote's age. The customer pays
    exactly what was shown, so there is nothing to protect against.
  - `|unit_price_cents − live| ≤ step` **and** `current_version − quote_version ≤ grace` →
    honour the quoted `unit_price_cents`.
  - otherwise the whole order returns 409 `price_changed` with every line's current price and
    the current version. Nothing is charged, written or moved.

  `grace` is a new `run.quote_grace_versions` column, default 2. It is a product parameter,
  as ADR 0008 requires, kept out of the engine's `Params`. The first bullet is the
  refinement: every 1 Hz tick bumps `version` (Phase 1 D9), so a strict reading of ADR 0008
  would 409 any quote held over two seconds even at an unchanged price. That would bring
  back the constant rejections ADR 0008 rejected. An addendum recording this is added to
  ADR 0008 in this phase.
- **SD19 — The engine moves on the order regardless of the honoured price.** The order is
  `advance(orders=qty_vector)` on the live state. `order_line.unit_price_cents` and
  `line_total_cents` are what was charged; `order_line.p_cont` is the live continuous price.
  The receipt is built inside the lock from what was written: `order_id`, `version`,
  `wall_ts_ms`, lines with charged `unit_price_cents`, `line_total_cents`, `total_cents`.
- **SD20 — Idempotency.** A new migration adds `order.actor_key_id` (FK `auth_key`) and
  `order.response` jsonb (the receipt, exactly as returned). The stored key is checked inside
  the lock, before any price is read. A match whose request body is identical returns the
  stored receipt with 200 and changes nothing. A match whose body differs returns 422
  `idempotency_key_reused`. The UNIQUE index is the final arbiter: a unique violation at
  commit is treated as a replay.
- **SD21 — A failed order transaction returns 503 `persistence_unavailable`** and leaves
  memory exactly as before. A client retry with the same key is then safe (SD20).
- **SD22 — Lock hold time is instrumented.** Every lock release logs a warning above 50 ms,
  naming the operation and the duration.

**Manipulation**

- **SD23 — Jumps and market events.**
  - `POST /api/market/jumps {drink_id, target_price_cents, duration_ms}`: `duration_ms` is
    1 000–1 800 000, and the target must lie within the drink's `[p_min, p_max]`, else 422.
    Under the lock it calls `schedule_jump` (version + 1, no `tick_index` move) and persists
    it with `source='jump'`. The price starts moving on the next tick.
  - `POST /api/market/events {kind: crash|bubble|correction, duration_ms}`: `duration_ms` is
    1 000–600 000, default 30 000. It schedules a jump for every active drink to `p_min`,
    `p_max` or `p0`. It writes a `market_event` row (new migration: `event_id`, `run_id`,
    `kind`, `drink_ids`, `t_start_ms`, `t_end_ms`, `ended_at`) and v1's auto news item, with
    v1's Dutch text (`api.py:492-500`) and levels lowercased. Everything happens in one
    transaction.
  - A new event while one is active ends the old one at `now` (its `t_end_ms` is rewritten,
    and a `market_event` end is broadcast). `schedule_jump` already replaces per-drink jumps.
  - The ticker broadcasts the `market_event` end when `now_ms ≥ t_end_ms`.
  - On boot, active events are rehydrated. When the gap rule shifts anchors, it shifts
    `t_start_ms` and `t_end_ms` of active events by the same amount, extending Phase 2 SD2's
    anchor list.
- **SD24 — Two named price tracks.** `price_cents` is the `step_quant` track, used for both
  display and charging; an assertion in the order path checks it is a multiple of `step`.
  `chart_price_cents` is the 0.01 track the candles are drawn from (`prices_disp`'s
  successor). Every price in every message is integer cents. No other price field exists
  (D-28).
- **SD25 — The tick carries the current candle.** A new `run.candle_interval_ms` column,
  default 60 000, is ADR 0005's server parameter, editable from Phase 6. Buckets are aligned
  to wall-clock multiples of the interval. Each tick carries, per drink, the OHLC of the
  current bucket on `chart_price_cents`. The snapshot carries the bucketed bars for the ring's
  window. A `gap` tick closes the open bucket.
- **SD26 — News.** `GET /api/news` returns non-deleted items, newest first. `POST` takes
  `{level, text}`: `level` is one of SD13's lowercase four, and `text` is trimmed, 1–500
  characters. `DELETE` sets `deleted_at` (404 if absent or already deleted). Each change is
  broadcast as `news {op, item}`. The snapshot carries the 50 newest.

**Realtime**

- **SD27 — The envelope's `seq` is global per process, and reconnect is keyed by
  `(boot_id, last_seq)`.** This replaces `hello {last_version}` in `realtime-protocol.md`,
  which is updated in this phase.
  - Each boot draws a random `boot_id`. Every **broadcast** message takes the next `seq`.
  - Unicast messages (`hello`, `snapshot`, `pong`, `error`) carry the current `seq` without
    incrementing it, so a snapshot at `seq = S` means "state as of S", and the next broadcast
    the client sees is `S+1`.
  - The hub keeps a replay log of broadcasts covering `history_window_minutes`. A client that
    sends `hello {boot_id, last_seq}` with a matching `boot_id` and `last_seq` inside the log
    gets every broadcast after it, in order. Otherwise it gets a snapshot.
  - Any gap a client detects in `seq` is repaired by `resync_request`.
- **SD28 — Message models are closed.** Every message in `app/realtime/messages.py` is a
  pydantic model with `extra="forbid"`. D-33's dead fields (`prices_cont`, `expected_demand`,
  `t`, `server_time_wall`) do not exist. `revenue_per_drink` survives as the snapshot's
  per-drink earnings aggregate (`{drink_id: {qty, revenue_cents}}`) and as the `order`
  message's earnings delta. `prices_disp` survives as `chart_price_cents`. `config` and
  `theme` message types are defined by the phases that produce them, not here.
- **SD29 — Per-connection backpressure.**
  - Each connection has a bounded queue of 64 messages and one writer task. Enqueueing never
    awaits.
  - On overflow, every queued `tick` is dropped and one `resync` is enqueued. If the queue is
    still full of non-tick messages, the connection is closed with 1013.
  - A single send that takes longer than 10 s closes that connection. Neither the ticker nor
    another client ever awaits a slow socket.
- **SD30 — Client messages are validated and rate-limited.**
  - Accepted messages are `hello`, `ping` (answered with a JSON `pong` carrying server
    `ts_ms`) and `resync_request`.
  - Anything else, or invalid JSON, gets an `error {code}` frame and the connection stays
    open.
  - More than 5 client messages per second closes the connection with 1008.
  - No client message calls the engine (D-36).
- **SD31 — WebSocket auth happens at the handshake, and expiry is enforced while open.** A
  handshake without a valid session, with a revoked key, or failing SD9's `Origin` check is
  closed with 1008 before accept. An open connection is closed with 4401 when its session's
  `exp` passes. Revoking a key does not kill sockets already open. That is accepted for
  Phase 3, and closing them is Phase 6's key-management concern.

**Engineering**

- **SD32 — Time and randomness are injected.** The ticker, holder and hub take a clock
  (`wall_ms()`, `monotonic()`, `sleep_until()`), so tests drive a fake clock. Nothing under
  `app/runtime/` or `app/realtime/` calls `time` directly except the one real-clock
  implementation.
- **SD33 — New dependencies, each to be justified in its PR and approved before install:**
  `argon2-cffi` (MIT; stdlib has no argon2), `PyJWT` (MIT; stdlib has no JWT), and dev-only
  `httpx` (BSD; FastAPI's `TestClient` requires it). WebSocket tests use `websockets`,
  already present via `uvicorn[standard]`. New settings go through `app/core/config.py` and
  `.env.example` (`tests/meta/test_compose_matches_env_example.py` keeps them aligned).
- **SD34 — Integration tests run against the compose `db`** (Phase 2 SD16), not
  testcontainers. The kill test runs the real app as a `uvicorn` subprocess and SIGKILLs it;
  `docker kill` of the compose `app` service is a manual verification step.
- **SD35 — Errors are one JSON shape** through `app/core/errors.py`: `{code, message}` plus
  typed extra fields where an AC names them (409's prices and version). Codes named in this
  spec are part of the contract.

## In scope

- Migrations, each its own: `auth_key`; `market_event`; `order.actor_key_id` +
  `order.response`; `run.quote_grace_versions` + `run.candle_interval_ms`.
- `app/runtime/holder.py`, `ticker.py`, the clock seam (SD32), and the gap rule extended to
  market events (SD23).
- Boot wiring in `app/main.py` per SD11. Graceful shutdown per SD10.
- `app/api/`: auth, state, orders, news, market, admin; the routes of SD1 with pydantic
  request/response models and generated OpenAPI.
- `app/realtime/`: `messages.py`, `hub.py` (queues, writers, replay log), the `/ws` endpoint.
- `app/cli/keys.py` (SD5) and `app/cli/runs.py go-live` (SD16).
- Settings: `LOGIN_RATE_PER_MINUTE`, `SESSION_COOKIE_SECURE`.
- Document updates: `architecture.md` (boot order), `realtime-protocol.md` (SD27, SD28),
  `data-model.md` (new tables and columns), and an addendum to ADR 0008 (SD18).
- `tests/api`, plus integration and meta tests for everything below.

## Out of scope

- Any UI. This phase is exercised by integration tests and an HTTP/WS client.
- `POST /config`, params editing, drink add/remove, reset (Phase 6; D-02, D-03, D-04).
- Theme, `/theme.css`, uploads, the `theme` and `config` messages (Phases 4, 6).
- Run lifecycle while running: open/close a run, end a run, switching live runs (Phase 7).
- Analytics endpoints, `GET /api/history`, the bucketed earnings series, xlsx export
  (Phase 7).
- Key management UI, and closing open sockets on key revocation (Phase 6).
- Client-side reconnect, backoff, half-open detection and countdown rendering (Phase 4; D-17).
- Proxy-header trust, TLS or the offline cookie profile, the Docker image, Render (Phase 8).
- Horizontal scale, Redis, any second writer (ADR 0003).
- Any change to pricing behaviour. Golden fixtures stay green.

## Acceptance criteria

**Authorization**

- **AC1.** When a request without a valid session reaches any route not on SD4's public
  allowlist, the system shall return 401; the meta test of SD4 shall fail if any route lacks
  both a role dependency and allowlist membership. *(D-37)*
- **AC2.** When a session's role is not permitted for a route by SD1's table, the system shall
  return 403; a parametrised test shall cover every (route, role) pair in the table.
- **AC3.** When a WebSocket handshake carries no valid session, a revoked key, or a foreign or
  missing `Origin`, the system shall close it with 1008 before accept and send no data.
- **AC4.** When `JWT_SECRET` is absent or shorter than 32 characters at boot, the system shall
  fail to start, naming the variable. *(D-39)*
- **AC5.** When login is attempted more than `LOGIN_RATE_PER_MINUTE` times in 60 s from one
  IP, the system shall return 429 with `Retry-After` **before** parsing the key or performing
  an argon2 verification; a test shall assert zero verify calls for the rejected attempts.
- **AC6.** When a login attempt is made with a well-formed key, the system shall perform
  exactly one argon2 verification, off the event loop, whether `key_id` exists, is revoked or
  is valid, and regardless of how many keys exist; a malformed key shall perform none.
- **AC6a.** When a session cookie is issued, the system shall set `Secure`, `HttpOnly` and
  `SameSite=Strict`; if `APP_ENV=production` and `SESSION_COOKIE_SECURE=false`, then boot
  shall fail. *(D-40)*
- **AC6b.** When an unsafe request has no `Origin` header, or one not matching its `Host`, the
  system shall return 403; and the app shall install no CORS middleware. *(D-41)*
- **AC6c.** When access keys are stored, the system shall store only argon2id hashes; a test
  shall assert no `auth_key` column holds the secret and `keys list` prints none, and the
  repository hygiene meta test shall fail on a committed `keys.json` or `bb_<id>_<secret>`
  literal. *(D-42)*
- **AC6d.** When an admin session calls `POST /api/admin/shutdown`, the system shall perform
  SD10's graceful shutdown; a bar or display session shall get 403, and no route or setting
  shall accept an `ADMIN_TOKEN`. *(D-27)*
- **AC6e.** When a key is revoked by the CLI, the next HTTP request bearing a session for it
  shall return 401.
- **AC6f.** When any static asset is requested without a session, the system shall serve only
  the SPA build, and every route returning run data shall be under `/api` or `/ws` and
  authorized (AC1). *(D-38)*

**Order path**

- **AC7.** When an order arrives, the system shall acquire the state lock **before** reading
  any price, version or stored idempotency key; a test shall interleave a tick between
  request parsing and lock acquisition and assert the order is judged against the post-tick
  state. *(D-07)*
- **AC8.** When orders are submitted concurrently with each other and with ticks, the system
  shall serialise them so that `price_tick.version` is gap-free and strictly increasing per
  run, every committed order's `version` matches the tick row written in its transaction, and
  the in-memory state equals the last committed row. *(D-07)*
- **AC9.** When the same `Idempotency-Key` with the same body is submitted twice (sequentially
  or concurrently), the system shall create one `order`, move the price once, and return a
  byte-identical receipt both times; with a different body it shall return 422
  `idempotency_key_reused` and change nothing. *(D-06)*
- **AC10.** When a line's `unit_price_cents` equals the live charged price, the system shall
  charge it regardless of `quote_version` age; when it differs by at most one `step_quant`
  and `current_version − quote_version ≤ run.quote_grace_versions`, the system shall charge the
  quoted price. *(ADR 0008, SD18)*
- **AC11.** When any line falls outside SD18's grace, the system shall return 409
  `price_changed` carrying each line's current `price_cents` and the current `version`, and
  shall write no row and leave `engine_state` and memory unchanged.
- **AC12.** When an order is accepted, every `unit_price_cents` in the receipt shall equal the
  stored `order_line.unit_price_cents`, and `total_cents` shall equal the sum of
  `line_total_cents`. *(D-05 server half)*
- **AC13.** If the order's database transaction fails at any statement (injected), then the
  system shall return 503 `persistence_unavailable`, discard the candidate, and leave prices,
  memory and the ledger unchanged.
- **AC14.** While the state lock is held, the system shall perform no file I/O, no socket
  send and no hub call; a test shall fail if the hub is invoked while the lock is held, and a
  test with an injected 60 ms transaction shall observe the SD22 warning.
- **AC14a.** When an order's `drink_id` is not an active drink of the live run, `qty` is
  outside 1–99, a `drink_id` repeats, the `Idempotency-Key` is missing or malformed, or
  `quote_version` exceeds the current version, the system shall return 422 and write nothing.

**Ticker and state**

- **AC15.** When `GET /api/state` is called any number of times, the system shall not change
  `engine_state`, `version`, `rng_counter` or any row. *(D-18)*
- **AC16.** When a client sends any WebSocket message, valid or not, the system shall not call
  the engine; and more than 5 messages in one second shall close that connection with 1008.
  *(D-36)*
- **AC17.** When the ticker loop has not completed an iteration for three intervals,
  `/healthz` shall return 503 with `last_tick_age_ms`; when only the database is unreachable,
  `/healthz` shall stay 200 and `/readyz` shall return 503.
- **AC18.** When a second instance starts against a database whose advisory lock is held, it
  shall exit non-zero within 5 s, before migrating or serving, logging the lock as the reason;
  and when the lock-holding connection is dropped, the running instance shall exit non-zero.
- **AC18a.** While running for 60 s on the fake clock, the ticker shall write exactly 60
  `tick` rows stamped on the grid; when the loop is stalled by ≤ 30 s it shall catch up every
  missed slot with its own grid stamp; when stalled by more than 30 s it shall write one `gap`
  tick, re-anchor, and move no price across the gap.
- **AC18b.** If a tick's commit fails, then the system shall keep the last committed state in
  memory, log the failure, and commit the next slot normally.
- **AC18c.** When there is no live run, the system shall boot ready, `GET /api/state` and every
  mutation shall return 409 `no_live_run`, and `/ws` shall send `hello` with `run_id: null`.
- **AC18d.** When the real app is SIGKILLed while orders and ticks are flowing and restarted,
  the system shall lose zero acknowledged orders and at most one tick, and continue
  `version` and `rng_counter` from the last committed row. *(Phase 2 SD1, as the real app)*
- **AC18e.** When a price changes for any reason (tick, order, jump), the corresponding
  `price_tick` row and broadcast shall carry a `version` greater than every earlier one; a
  test shall assert no two distinct price vectors ever share a `version`. *(D-08)*

**Protocol**

- **AC19.** When a market event starts, the system shall broadcast `market_event` with `kind`,
  `drink_ids`, absolute `t_start_ms` and `t_end_ms`; when `now_ms ≥ t_end_ms` the ticker
  shall broadcast its end within one interval; and a new event shall end an active one first.
  *(D-15)*
- **AC19a.** When the app restarts during a market event with a gap beyond the budget, the
  event's `t_start_ms` and `t_end_ms` shall shift by the same amount as the jump anchors.
- **AC20.** When a tick is broadcast, it shall carry only `version`, `ts_ms`, per-drink
  `price_cents`, `chart_price_cents` and the current candle, and no history, news list or
  per-sale series; a test shall bound a six-drink tick at 600 bytes serialised. *(D-31, D-32)*
- **AC20a.** When the snapshot or any message is built, its fields shall be exactly those of
  its closed model; a test shall assert none of `prices_cont`, `expected_demand`, `t`,
  `server_time_wall`, `prices_quant`, `history` or `series` appears in any message, and that
  per-drink earnings are present in the snapshot. *(D-33)*
- **AC21.** When a client sends `hello {boot_id, last_seq}` with the current `boot_id` and
  `last_seq` inside the replay log, the system shall send exactly the broadcasts after
  `last_seq`, in order, with no snapshot; otherwise it shall send one snapshot whose `seq` is
  the current `seq`.
- **AC22.** When a client's queue overflows, the system shall drop its queued ticks and enqueue
  one `resync`, and the ticker and every other client shall keep their cadence; a test with
  one client that never reads shall assert the ticker writes on the grid and a healthy client
  receives every tick. *(D-34)*
- **AC23.** While broadcasting, every price shall be integer cents in exactly two fields,
  `price_cents` (shown and charged, a multiple of `step_quant`) and `chart_price_cents`
  (0.01 track), and an accepted order's charged prices shall come from `price_cents`.
  *(D-28)*
- **AC24.** When `ping` is received, the system shall answer with a JSON `pong` frame
  carrying server `ts_ms`; no non-JSON frame shall ever be sent.
- **AC25.** When an open connection's session expires, the system shall close it with 4401.

**Manipulation**

- **AC26.** When a jump is requested with a target outside `[p_min, p_max]`, a `duration_ms`
  outside 1 000–1 800 000 or an inactive `drink_id`, the system shall return 422; a valid one
  shall persist a `jump` tick with the next `version` and move the price from the next tick.
- **AC27.** When a market event is started, the system shall write the `market_event` row, the
  jumps' state, and its Dutch news item (lowercase level) in one transaction, and broadcast
  `market_event` and `news`.
- **AC28.** When news is created or deleted, the system shall persist it, broadcast
  `news {op, item}`, and reject a level outside the four or text outside 1–500 characters
  with 422; deleting an absent item shall return 404.

## Verification

- `./scripts/check.sh` green with its output pasted: unit, meta (SD4's route audit, AC6c
  hygiene) and `tests/api` + `tests/integration` against the compose `db`.
- **Authorization matrix:** every route × {anonymous, display, bar, admin, revoked} asserting
  SD1's table, plus a happy path, a validation failure and a not-found per endpoint.
- **Concurrency:** 50 concurrent orders interleaved with a running ticker on the fake clock,
  asserting AC8's gap-free version sequence, ledger totals and memory = last committed row.
- **Idempotency:** the same key replayed sequentially and concurrently, and with a changed
  body (AC9).
- **Grace:** a table-driven test over (price delta, version age) covering every SD18 branch.
- **Backpressure:** one WebSocket client that never reads plus one healthy client, for 120
  fake seconds (AC22).
- **Kill test (AC18d):** a `uvicorn` subprocess SIGKILLed mid-stream at several points,
  restarted, state compared with the last committed row.
- **Second instance (AC18):** start a second app against the same database and assert it
  exits non-zero on the lock.
- **Manual:** `docker compose up`, mint keys with `app.cli.keys`, `app.cli.runs go-live`, log
  in with an HTTP client, place an order over the API, watch `/ws` with a WebSocket client,
  `docker kill` the app mid-stream, restart, and confirm prices resume.
- Golden fixtures still replay (`uv run pytest tests/engine`).

## Exit condition

Integration tests are green against a real Postgres, with an authorization test for every
route and the handshake. One ticker owns time. An order is charged exactly the price it was
judged on, exactly once.
