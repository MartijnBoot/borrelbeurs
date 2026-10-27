# Plan: B-11 — A faster gate

Spec: [docs/specs/phase-b-11-faster-gate.md](../specs/phase-b-11-faster-gate.md) (Approved; SD1–SD15 settled, none reopened here)

Line references are to the branch `docs/phase-b-11-spec` at `f0c7228` (code identical to `main` `437c505`).

## Approach

Three moves, in the order they unlock each other. **First, make a Postgres server shareable**
(T4–T7): one new helper, `tests/support/pg_gate.py`, owns everything that touches the maintenance
database — the shared/exclusive run lock (SD5), a per-scratch-database ownership lock and the
owner-aware sweep (SD6), and a per-port claim (SD14). `tests/integration/conftest.py`, a thin hook
set in `tests/conftest.py`, `serve.py` and `harness.py` call it; nothing else changes how a test
gets its database. **Second, run in parallel** (T2, T3, T8): `pytest-xdist` with `--dist loadgroup`,
the `serial` marker applied by the SD3 rule, and `check.sh` rebuilt as three stages with stage 2's
steps side by side, each in its own log. **Third, prove it** (T9–T14): measure the connection cap,
tune waits (never bounds), then run the SD9 series. The argon2 swap (T11) is conditional on T1's
profile and independent of the rest.

`--dist loadgroup`, not `loadfile`: `tests/api/test_authorization_matrix.py` alone is 355 tests
(~5 min at 0.85 s), so file-level scheduling would make one worker the long pole. With no
`xdist_group` marks `loadgroup` hands out single tests, which is what balances. Every fixture a
test depends on is function-scoped except `settings` and `scratch_database`, which are per worker
by construction, so test-level distribution is safe.

**One refinement of SD5 the spec did not see — children inherit the lock, they do not re-take it.**
Postgres queues advisory-lock requests fairly: a *new* shared request waits behind an *exclusive*
request that is already queued. If gate A's `check.sh` holds shared and gate B's serial stage is
queued exclusive, then A's own new xdist workers and `serve.py` — each asking shared — queue behind
B, B waits for A's holder, A's holder waits for its workers: a deadlock. So the holder passes
`BB_GATE_LOCK_HELD=1` to everything it starts and children skip the acquire. A targeted `-n` run
does the same from its xdist controller (the only process that takes the lock, workers skip). This
adds a mechanism and **amends SD5's list of shared holders**: under the gate, workers and `serve.py`
are covered by the holder instead of taking the lock themselves (AC11's effect is unchanged). The
owner acknowledges this with SD11–SD15 when approving the audited plan. It also fixes a second
problem: `serve.py` waiting on a lock would blow Playwright's 120 s `READY_TIMEOUT_MS`; with the
holder taken *before* stage 2 starts, it never waits. The variable is never exported by `check.sh`:
it is passed only to stage-2 children, so stage 3 (and any targeted run) takes its own lock.

**Advisory locks are re-entrant within a session**, so `pg_try_advisory_lock` on a database this
process already owns succeeds. The sweep therefore skips every name in an in-process set kept by
`own`, and takes its try-locks on a separate short-lived connection, never the maintenance one.

**Rejected:** hand-sharded `check.sh` (SD1); an age threshold in the sweep (SD6 says no clock);
a lock file (SD5); passing an open socket to the app for ports — it needs `uvicorn --fd`, a change
under `app/` (SD14's stop-and-ask), so ports use a claim lock plus bind-failure retry instead;
moving `scratch_database` to a plugin module (`pytest_plugins` is not allowed in a non-top-level
conftest, and `tests/api` re-exporting it works).

## Profile (T1 fills this in; no per-test cost is cut before it exists)

| Where `tests/api` time goes, single process | Seconds | Share |
|---|---|---|
| key hashing (mint + login) | 44.6 (792 hashes, 56 ms each; 22.3 inside login requests) | **11.3 %** |
| app boot + shutdown (`create_app` lifespan) | 72.8 (`TestClient` enter 66.6 + exit 6.2, 422 apps) | 18.5 % |
| engine create/dispose in fixtures | 6.7 for every `dispose` (2184); the whole `live_run` fixture (engine, seed, go-live) 45.7 | 1.7 % / 11.6 % |
| `TRUNCATE` | 163.0 (`database_url`: a `NullPool` engine and one `TRUNCATE … CASCADE` of every table, 0.38 s each) | **41.4 %** |
| the request itself | 25.4 (881 requests, 47.6 less the 22.3 of hashing inside login) | 6.4 % |

T1 (2026-10-27): measured on the named sample, `test_authorization_matrix.py`, `test_orders.py`,
`test_keys.py`, `test_ws.py` (424 of 1154 tests), one process, the compose `db`: **424 passed in
394.0 s** (0.93 s a test). Instrumentation was a `-p` plugin in the scratchpad, not committed: a timing
wrapper on `app.api.security.argon2_hash_secret` (what `key_hash` calls), on `TestClient.__enter__`,
`__exit__`, `request` and `AsyncEngine.dispose`, and `pytest_fixture_setup` timers (exclusive per
fixture, since dependencies are set up first). Setup phase 282.1 s, call 103.6 s, teardown 7.3 s.

- **Key hashing is 11.3 % ≥ 10 %: T11 is triggered.**
- **T11 built (2026-10-27), re-measured on the same sample:** 424 passed in **337.4 s**, from 394.0 s,
  a saving of **56.6 s (14.4 %)**; hashing 44.6 s → 0.1 s. The swap is `time_cost=1`, 8 KiB, one lane,
  in `tests/api/conftest.py` only.
- **Candidate amendments (≥ 5 %, not built, need a re-audit):** the per-test `TRUNCATE` (41.4 %, the
  largest single cost: e.g. truncating only the tables a test wrote, or `DELETE` on small tables);
  app boot + shutdown (18.5 %); the `live_run` seed per test (11.6 %); the request itself (6.4 %) is
  what the tests check and is not a cost to cut.

`--durations=30` of that run:

```
3.55s setup    test_authorization_matrix.py::test_the_table_covers_every_served_route
3.46s call     test_ws.py::test_closing_a_session_never_leaks_a_foreign_cancellation
1.68s setup    test_authorization_matrix.py::test_every_route_and_actor[GET-/api/analytics/runs/{run_id}-kassa]
1.41s call     test_orders.py::test_the_limit_admits_exactly_minus_l_and_refuses_one_cent_more
1.11s setup    test_authorization_matrix.py::test_every_route_and_actor[GET-/api/state-kassa]
1.04s call     test_orders.py::test_a_key_first_used_without_a_wallet_resent_with_one_is_422
1.03s setup    test_orders.py::test_bad_lines_are_422[duplicate-drink]
1.01s setup    test_ws.py::test_a_binary_frame_gets_an_error_and_the_connection_stays_open
0.99s setup    test_authorization_matrix.py::test_every_route_and_actor[PATCH-/api/runs/{run_id}/drinks/{drink_id}-admin]
0.98s setup    test_authorization_matrix.py::test_every_route_and_actor[GET-/api/analytics/price-curve-revoked]
0.98s setup    test_authorization_matrix.py::test_every_route_and_actor[DELETE-/api/runs/{run_id}-admin]
0.97s setup    test_authorization_matrix.py::test_every_route_and_actor[POST-/api/runs/{run_id}/go-live-anonymous]
0.97s setup    test_authorization_matrix.py::test_every_route_and_actor[POST-/api/theme/images/{slot}-admin]
0.97s call     test_orders.py::test_a_paid_order_resent_replays_its_bytes_even_after_the_balance_moved
0.94s teardown test_ws.py::test_the_handshake_needs_the_same_origin_even_with_a_valid_session
0.94s call     test_orders.py::test_a_wallet_that_no_longer_resolves_is_404_and_writes_nothing[deleted]
0.93s setup    test_ws.py::test_a_bad_handshake_closes_1008_with_no_frame[missing-origin]
0.89s setup    test_authorization_matrix.py::test_every_route_and_actor[PATCH-/api/runs/{run_id}/config-admin]
0.88s setup    test_authorization_matrix.py::test_every_route_and_actor[GET-/api/runs/current-display]
0.88s setup    test_authorization_matrix.py::test_every_route_and_actor[GET-/api/analytics/runs/{run_id}-bar]
0.88s setup    test_ws.py::test_a_current_hello_gets_exactly_the_missed_broadcasts_and_no_snapshot
0.87s setup    test_authorization_matrix.py::test_every_route_and_actor[PATCH-/api/runs/{run_id}/drinks/{drink_id}-bar]
0.86s setup    test_ws.py::test_resync_request_gets_a_snapshot_and_garbage_gets_an_error
0.86s setup    test_ws.py::test_client_messages_never_touch_the_market_and_six_a_second_close_1008
0.86s setup    test_authorization_matrix.py::test_every_route_and_actor[POST-/api/market/jumps-display]
0.86s setup    test_authorization_matrix.py::test_every_route_and_actor[PATCH-/api/runs/{run_id}/config-display]
0.85s setup    test_ws.py::test_five_a_second_is_allowed
0.85s setup    test_authorization_matrix.py::test_every_route_and_actor[POST-/api/runs/{run_id}/anchor-s0-kassa]
0.85s setup    test_ws.py::test_ping_gets_a_json_pong_and_every_frame_is_json
0.84s setup    test_authorization_matrix.py::test_every_route_and_actor[DELETE-/api/keys/{key_id}-display]
```

Cuts the profile justifies are appended below as **amendments** (T-numbered, with their measured
saving) and need a re-audit before they are built — the plan cannot name them yet.

## Serial list (AC5) — the SD3 rule applied to every module

Rule: asserts a bound on real elapsed time, or starts a real `python -m app.main`. Counts from
`pytest tests/integration tests/api --collect-only -q`: 1710 tests (556 + 1154); **27 serial** (the 9 whole modules hold 22; plus 5 single tests; T3 confirms the
count, plus the two new lock/port test modules from T4 and T7).

| Module / test | Serial | Reason |
|---|---|---|
| `test_db_restart.py` (1) | whole module | `start_app`/`spawn_app`; `< READY_AFTER_RESTORE_S` (60 s) |
| `test_export_timing.py` (1) | whole module | `max(gaps) <= 1.5×`, `p95 <= 2×` on `RealClock` |
| `test_handover.py` (2) | whole module | `start_app`; `takeover_s <= 2.0` |
| `test_heavy_reads.py` (1) | whole module | `perf_counter` bounds 60 s / 10 s / 60 s |
| `test_proxy_keying.py` (2) | whole module | `start_app` |
| `test_real_process.py` (4) | whole module | `start_app`; `< 600` |
| `test_restart_replay.py` (2) | whole module | `start_app` |
| `test_smoke_script.py` (7) | whole module | `start_app` in the module fixture |
| `test_wallet_payments_races.py` (2) | whole module | `asyncio.wait_for(…, 30 s)` *is* the "no deadlock" assertion; generous, but the rule says deadline → serial (cheap, conservative) |
| `test_wallet_cleanup.py::` the test at `:198-213` (`asyncio.wait_for(…, timeout=5)` asserting "skipped, not waited for") | one test | a deadline asserted as behaviour; builder confirms the exact name and marks it |
| `test_advisory_lock.py::test_a_silent_lock_connection_trips_the_watchdog_within_its_timeout` | one test | `took_s < 3` |
| `test_delete_run.py::test_a_thirty_thousand_order_run_deletes_within_the_live_timeout` | one test | `elapsed < 5.0` |
| `test_holder.py::test_a_step_that_outlives_its_timeout_is_persistence_unavailable_and_frees_the_lock` | one test | `< 2` |
| `test_place_order.py::test_a_wallet_held_elsewhere_is_a_503_within_the_lock_timeout` | one test | `1.5 <= waited < 5.0` |
| New: `test_pg_gate.py`, `test_port_claim.py` (T4, T7) | whole module | they sweep, kill and start real apps; they are the verification of the lock itself |

Judged **not** serial, and why — the owner may overrule any row by marking more modules, which only
makes the serial stage longer:
- `test_advisory_lock.py::…dropped_lock_connection…within_one_interval` (`wait_for(…, 10)`), `test_boot.py::…heavy_read_engine…`
  (a 6 s sleep against the 5 s/60 s timeouts) and `test_export_worker`'s `wait_for` 30/60: generous waits for a
  state, then checked; the bound is the setting under test, not a measured elapsed time.
- `test_durability.py` (7): spawns `tests.integration.durability.harness`, not `app.main`; no bound.
- `test_export_worker.py`, `test_boot.py`, `test_health.py`, `test_ticker.py`: poll then check; the
  waits are in the table below. They were on the backlog's list; by the rule they are waits.
- `test_migration_0015.py`: asserts something is *still* blocked after 0.5 s; load can only help.
- all of `tests/api`: `TestClient`, no process, no bound. `test_ws_fixture.py` creates its own
  `bb_test_*` through `_create`, so T5 makes that owned too.

## Waits raised (SD10, AC25) — T10 fills this in

| Test / file | Wait | Old | New |
|---|---|---|---|
| _none yet_ | | | |

## Connection budget (SD2, AC3) — T9 fills this in

Two full gates ≤ 80 of 100. Per gate, the peak is `workers × per-worker peak` + 2 e2e servers + the
stage-2 holder, the serve.py maintenance connections, the unit step (none) and — stage 3 runs alone —
the serial stage. A worker's peak = its `TestClient` app (SQLAlchemy pool 5 + 10 overflow, lock
connection; the heavy-read engine is `NullPool`) + the `_admin` connections (`NullPool`, one at a
time) + its maintenance connection. T9 measures this; `cap = floor((40 − e2e − holder) / per-worker)`.

| Quantity | Measured (T9, 2026-10-27, one gate's steps, `pg_stat_activity` once a second) |
|---|---|
| not-serial database tests, 2 / 4 / 8 workers | peak 19 / 22 / 30 connections (13m28s / 8m04s / 5m32s, 1683 passed each) |
| per-worker peak | about 1.8 (slope 2 → 8); about 15 fixed (controller, maintenance connections, the heaviest test) |
| one e2e server pair (shared + `--empty`) | 15 (alone: 5.1 min, 48 passed) |
| stage-2 holder | 1 |
| serial stage, alone | peak 11; 32 tests, 6m18s |
| cap | `15 + 1.8 × n + 15 + 1 ≤ 40` → **4** (38 measured at 4); two gates ≤ 76 of 80 |

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `docs/plans/phase-b-11-faster-gate.md` | Modify (T1, T9, T10, T11) | the profile, measurements, waits |
| `pyproject.toml` | Modify (T2) | `pytest-xdist` in `dev`; `serial` marker |
| `uv.lock` | Modify (T2) | the lock for it |
| `tests/support/pg_gate.py` | Create (T4) | the run lock, ownership locks, sweep, port claim, `hold` CLI |
| `tests/integration/test_pg_gate.py` | Create (T4) | AC11, AC13, AC14 |
| `tests/integration/conftest.py` | Modify (T5) | scratch databases owned; owner-aware sweep replaces `_sweep_leftovers`; docstring |
| `tests/conftest.py` | Modify (T5) | `pytest_collection_finish`/`sessionfinish`/`configure` hooks: take the lock, the xdist guards |
| `tests/api/ws_fixture.py` | — | no edit: it calls `_create`, which T5 makes owning |
| `tests/integration/realapp/serve.py` | Modify (T6) | owned database, shared lock, owner-aware sweep; docstring |
| `tests/integration/realapp/harness.py` | Modify (T7) | port claim + retry |
| `tests/integration/test_port_claim.py` | Create (T7) | AC17 |
| 14 `tests/integration/test_*.py` modules (9 whole, 5 single tests) | Modify (T3) | `pytestmark`/`@pytest.mark.serial` per the table; two-line edits each |
| `tests/integration/test_db_restart.py` | Modify (T3, then T7) | marker, then the held port claim; T7 depends on T3 |
| `tests/meta/test_no_db_connection.py` | Create (T5) | AC16: a subprocess pytest on `tests/unit` with `BB_GATE_LOCK_HELD` cleared and a `-p` plugin making `MaintenanceConnection` raise |
| `tests/meta/test_serial_marker.py` | Create (T3) | AC4 |
| `scripts/check.sh` | Modify (T8, T9) | three stages, logs, workers, interrupt, lock holder |
| `tests/meta/test_gate_workers.py` | Create (T8) | AC2 |
| `tests/api/conftest.py`, `tests/meta/test_argon2_swap.py` | Modify/Create (T11, conditional) | AC19 |
| test files named by T10's failures | Modify (T10) | waits only; listed in the table above |
| `CLAUDE.md`, `README.md`, `docs/backlog.md` | Modify (T12) | SD15 |

## Tasks

### T1 — Profile `tests/api` in one process
- Implements: AC18
- Expected output: the Profile table above filled in, plus the run's `--durations` top 30. The
  profile is of a single process, as the gate ran it. It may be a representative sample if the whole
  directory (16 min) is too long, but it must include `test_authorization_matrix.py`, `test_orders.py`,
  `test_keys.py`, `test_ws.py`. Instrumentation (a timing wrapper around `app.api.security.key_hash`,
  `cProfile`, fixture timers) is temporary and not committed. States whether key hashing is ≥ 10 % of
  the wall time (T11's trigger), and lists any other per-test cost ≥ 5 % as a candidate amendment.
- Verification: `uv run pytest tests/api -p no:cacheprovider --durations=30` (or the named sample)
  with the timing wrapper; the plan file diff is the artefact.
- Depends on: —
- Autonomy note: the builder chooses the instrumentation and the sample. It stops and asks if the
  profile needs a change under `app/` to measure anything. No code is cut here.

### T2 — `pytest-xdist` and the `serial` marker
- Implements: AC1 (precondition)
- Expected output: `pytest-xdist>=3.6,<4` in the `dev` group with a comment as for its neighbours;
  `uv.lock` updated (`uv lock`, no other package version moves — check the diff); the marker
  `serial: asserts a bound on real elapsed time, or starts a real app (SD3)` under
  `[tool.pytest.ini_options]` `markers`. `addopts` unchanged (SD13).
- **Dependency approval note (spec SD1, owner Q1: A).** What: runs pytest across worker processes
  sharing collection and fixtures. Why not stdlib: no runner shares pytest's collection and
  fixtures across processes; hand-sharding in `check.sh` splits unevenly and reimplements reporting.
  Licence: MIT. Maintenance: pytest-dev organisation, releases within the last year.
  **Transitive: `execnet`** (not yet in `uv.lock`) — xdist's worker transport (spawns and talks to
  worker processes); stdlib `multiprocessing` offers no equivalent channel for it. MIT, pytest-dev
  organisation, maintained. It is part of the owner's Q1 approval of xdist; the PR names it.
- Verification: `uv lock --check`; `uv run pytest tests/unit -n 2 -q` runs; `uv run pytest
  tests/unit --collect-only -q` still collects the same count as on the base commit.
- Depends on: —
- Autonomy note: the version floor is fixed by the spec. `uv lock` adding exactly `pytest-xdist` and
  `execnet` is expected. Any other added or moved package: stop and ask (a hard stop).

### T3 — Mark the serial tests; guard the harness
- Implements: AC4, AC5
- Expected output: `pytestmark = pytest.mark.serial` in the nine whole-module rows, and
  `@pytest.mark.serial` on the five single tests, per the table; a one-line comment at each saying
  which half of the rule it meets. `tests/meta/test_serial_marker.py`: an AST scan of every
  `tests/**/test_*.py` (excluding `tests/image`) that imports or calls `spawn_app`/`start_app`
  and fails, naming the module, unless its module-level `pytestmark` contains `serial`. Plus a test
  that the guard itself catches a planted module (tmp_path file fed to the same function).
- Verification: `uv run pytest tests/meta/test_serial_marker.py`; `uv run pytest tests/integration
  tests/api -m serial --collect-only -q | tail -3` reports 27 selected, plus the two new serial modules once T4 and T7 land.
  Collection needs no database.
- Depends on: T2
- Autonomy note: the builder may place the marker per module or per test as the table says, and
  choose the guard's internals. It stops if it finds a test that meets the rule and is not in the
  table: add it, and say so in the PR, but do not unmark any row.

### T4 — `tests/support/pg_gate.py`: locks, ownership, sweep, port claim
- Implements: AC11, AC12, AC13, AC14
- Expected output: one module, stdlib + asyncpg/SQLAlchemy only, no new import in `app/`:
  - `MaintenanceConnection`: one connection (SQLAlchemy's typed async connection, so mypy strict needs no
    asyncpg override) to the maintenance database, whose URL is **the explicit `base_url` callers pass**
    (`_create`/`_drop`/`sweep`, `serve.py`'s `base_url`, the session `settings.database_url`); it never
    re-reads `os.environ` lazily, since a test may have pointed `DATABASE_URL` at a scratch database, where
    no other process would see the locks. A second, different `base_url` in one process is an error. Owned by a daemon
    thread running its own event loop, so locks outlive any `asyncio.run` and die with the process.
    Created lazily; a process that never asks opens nothing (AC16).
  - `acquire_run_lock(shared|exclusive, *, key=GATE_KEY, announce=print_fn)`: `pg_try_advisory_lock[_shared]`
    first; if refused, `announce("waiting …")`, then the blocking call (fair queue, so a waiting
    serial stage is not starved), then `announce("got the lock after N s")` (AC12). `release_run_lock()`.
    Skips entirely when `BB_GATE_LOCK_HELD` is set (the refinement above). `GATE_KEY` is
    `hashtextextended('bb-gate', 0)`, not `ADVISORY_LOCK_KEY`. `key` is a parameter so the lock's
    own tests can use a private key, because they run inside a session that already holds the real one.
  - `own(database)`: `pg_advisory_lock(hashtextextended('bb-owner:'||name, 0))` on the maintenance
    connection, **taken before** `CREATE DATABASE` so a sweeper can never see an unowned live database.
  - `sweep(base_url, prefixes=("bb_test_", "borrelbeurs_e2e_"))`: for each match **not in this
    process's owned set** (kept by `own`), `pg_try_advisory_lock` on its owner key **on a separate
    short-lived connection** (locks are re-entrant per session, so the maintenance connection would
    succeed on its own databases); only if it is taken is the database dropped (`WITH (FORCE)`), then
    unlocked. A live owner's database is never touched (AC13); a killed run's is dropped at the next
    start (AC14). `release(database)` (owner lock and set entry) runs **after** the drop, from `_drop`,
    so ownership locks do not pile up per `empty_database`.
  - `claim_port(port)` / `release_port(port)`: a try-lock on `hashtextextended('bb-port:'||port, 0)`,
    for T7.
  - `python -m tests.support.pg_gate hold [shared|exclusive]`: acquires, prints `held`, blocks until
    stdin closes (the stage-2 holder; a dead parent closes the pipe, a dead process drops the lock).
- `tests/integration/test_pg_gate.py` (module-level `serial`; private lock keys), the spec's four
  steps: (1) two sessions each `own` + create — the second a **separate child process** that owns, creates and blocks on stdin, so the lock check (not the in-process set) is what protects it; (2) one sweeps, the other's survives; (3) a third
  process creates a database and is killed, the next sweep drops it; (2b) one process owns two
  databases, sweeps, and both survive; (4) a shared holder blocks an
  exclusive one, an exclusive holder blocks a new shared one, the waiter gets it after release, and
  the "waiting"/"got it" lines are announced.
- Verification: `uv run pytest tests/integration/test_pg_gate.py -v` (needs the compose `db`; source
  `.env.local`).
- Depends on: T2 (the `serial` marker)
- Autonomy note: names, the thread plumbing and the CLI's exact shape are the builder's. It must not
  use the app's `ADVISORY_LOCK_KEY`, add a clock-based rule to the sweep, or read `os.environ` under
  `app/`/`db/` (it reads it here, in `tests/`, which `test_config_boundary` does not scan). Stop and
  ask if concurrent `CREATE DATABASE` from `template1` fails ("being accessed by other users") in a
  way a short retry cannot cure.

### T5 — Wire scratch databases and the run lock into pytest
- Implements: AC1, AC11, AC12, AC13, AC14, AC16
- Expected output:
  - `tests/integration/conftest.py`: `_create` calls `own()` then `CREATE DATABASE` (so `scratch_database`,
    `empty_database` and `ws_fixture` are all owned); `scratch_database` calls the owner-aware `sweep`
    instead of `_sweep_leftovers` (deleted); the docstring's "next session sweeps those first" rewritten.
    `_admin`, `_drop`, `run_alembic`, `scratch_url` keep their names and signatures (`serve.py` and
    `ws_fixture.py` import them).
  - `tests/conftest.py`: `pytest_collection_finish(session)` — if any selected item lives under
    `tests/integration` or `tests/api`, acquire the run lock: **exclusive** if any selected item
    carries `serial`, shared otherwise (announced through the terminal reporter);
    `pytest_sessionfinish` releases. **Items elsewhere (`unit`, `meta`, `engine`) open no connection.**
    `-n 0` is a plain run; the release hook is `trylast=True` so scratch databases drop first.
    Skipped when `config.option.collectonly` is set (collection steps must not queue on a gate).
    On an xdist **worker** (`workerinput` present), `pytest_collection_finish` raises `UsageError` if
    any selected item is `serial` — a serial test under `-n` could never hold the lock exclusively,
    and this catches a `-n` run with no `-m` at all. On the xdist **controller** (`-n` given, no
    `workerinput`) the lock is taken at `pytest_configure`-time from the path arguments (any is, or
    contains, a DB directory) as shared, and `BB_GATE_LOCK_HELD=1` is set in its environment so its
    workers skip. Workers started under the gate inherit the variable from the holder's children
    (T8 passes it), not from an export.
- Verification: `uv run pytest tests/meta/test_no_db_connection.py` (AC16: a subprocess pytest on `tests/unit`, `BB_GATE_LOCK_HELD`
  cleared, `MaintenanceConnection` made to raise by a `-p` plugin, expecting a pass);
  `uv run pytest tests/integration/test_pg_gate.py`;
  `uv run pytest tests/integration/test_schema.py tests/api/test_keys.py -n 2 -m "not serial" -q`
  green with two workers and two scratch databases each (both dirs' `scratch_database` instances);
  killing a worker mid-run and starting another leaves no `bb_test_%` in `pg_database` afterwards.
- Depends on: T3, T4
- Autonomy note: how the hooks find "selected items under a DB dir" and the exact messages are the
  builder's. The two scratch databases per worker (one per defining conftest) are accepted, not fixed
  here. Stop and ask if any behaviour of a plain `uv run pytest <path>` (no `-n`) changes other than
  taking the lock (SD13).

### T6 — `serve.py`: owned database, shared lock, owner-aware sweep
- Implements: AC13, AC14, AC11 (e2e side)
- Note: outside the gate, a standalone `pnpm --dir web run e2e` takes the lock twice (shared, then the
  `--empty` server's); the second could queue behind another gate's waiting exclusive and hit the 120 s
  ready timeout. Documented in `serve.py`'s docstring, not solved (outside AC15). Its final cleanup goes through `_drop`, not `_admin`.
- Expected output: `serve.py` takes the shared run lock (skipped under `BB_GATE_LOCK_HELD`), owns
  `borrelbeurs_e2e_<pid>` before creating it, and replaces its `LIKE` sweep with `pg_gate.sweep` (the
  `--empty` flag still skips the sweep, Phase 6 PD15; the database is owned either way). The leading
  docstring updated (step 1 and the `--empty` paragraph).
- Verification: `uv run python -m tests.integration.realapp.serve --out <tmp> ` started twice at once
  (once `--empty`) both print `ready`, both databases exist, and closing both stdins leaves no
  `borrelbeurs_e2e_%`; a third started after killing the first leaves none either (AC14).
- Depends on: T5
- Autonomy note: the builder may keep `_pid` in the name. It stops if serve.py's stdout protocol
  (`ready`, stdin-close stop) would have to change, since `web/e2e/serverProcess.ts` depends on it.

### T7 — A real app never loses its port to another run
- Implements: AC17
- Expected output: `spawn_app` claims its port with `pg_gate.claim_port` (released on `kill`/`wait`),
  so two runs of the harness cannot hand out the same number. A squatter that is not the harness is
  caught by the child failing to bind: uvicorn binds only after startup and, on a failed bind, logs
  the OSError and exits 3 (`uvicorn/server.py:180-191`); on success it logs `Uvicorn running on
  http://0.0.0.0:<port>` through `uvicorn.error` into the app's JSON stdout (`app/main.py:317`
  `log_config=None`, `app/core/logging.py`, `LOG_LEVEL=INFO` from `harness.py:52`). So `start_app`
  does **not poll `/readyz` at all** until this child's listening line for its own port appears,
  reading `stderr_path` **from the byte offset recorded at spawn** (the file is append-mode and shared
  across `test_db_restart`'s restarts); if the child exits 3 first, retry on a new port. A foreign
  process on the port is therefore never sent a request. `free_port` also probes `0.0.0.0`, the
  address the app binds (Windows may allow both binds at once). `test_db_restart.py` holds its port
  claim for the whole test, and its restart loop treats exit 3 *with a bind error for this port in the log*
  as a lost port and moves to a new claimed port (a few retries, then fail with the log; exit 3 alone,
  uvicorn's code for any startup failure, is not retried).
  `tests/integration/test_port_claim.py` (module-level `serial`): `free_port` monkeypatched to return a
  port a squatter holds on the first call; the squatter binds `127.0.0.1`, the address the harness connects to (if the app's `0.0.0.0` bind then succeeds beside it on Windows, **stop and ask**). The squatter runs `accept()` with a timeout and records any
  connection → the app comes up on another port, the test is green, and the squatter saw none.
- Verification: `uv run pytest tests/integration/test_port_claim.py tests/integration/test_real_process.py
  tests/integration/test_db_restart.py -q`, run on Windows (the owner's platform).
- Depends on: T3, T4
- Autonomy note: the listening line is uvicorn's existing one; no change under `app/`. If the line's
  format differs from the above, match what the app actually prints; if none identifies the port,
  **stop and ask** — SD14's only door under `app/`.

### T8 — `check.sh`: three stages, side by side, logs, workers, interrupt
- Implements: AC1, AC2, AC6, AC7, AC8, AC9, AC10, AC11 (gate side), AC12, AC16
- Expected output: the rewritten script, header comment included.
  - Before `require uv`: read `BB_GATE_WORKERS`; reject (exit non-zero, naming it) anything not a
    positive integer or above `CAP`; `WORKERS = min(nproc, CAP, BB_GATE_WORKERS if set)` (an override only lowers); the gate prints the count and where it came from before stage 1. `CAP` is
    **provisional** here (value 4, flagged `# provisional until T9 measures`).
  - **Stage 1** — the nine static steps, one after another, stop at first failure (AC6), as today.
  - `check.sh` `unset`s `BB_GATE_LOCK_HELD` at the top and **never exports it**.
  - **Stage 2** — acquire the shared run lock first (`python -m tests.support.pg_gate hold shared` in
    the background, its stdin pipe owned by the script). **Wait for its `held` line before starting
    any step**; if the holder exits first (DB down, bad URL), the gate fails with a named line. Then
    start side by side, each writing to `${TMPDIR:-/tmp}/bb-gate-<UTC stamp>-<pid>/<step>.log`
    (SD11, via `mktemp -d`): `pytest_each tests/unit tests/meta tests/engine`
    (unchanged semantics, `ALLOW_EMPTY` kept), `pnpm … test --run`, `uv run pytest tests/integration
    tests/api -n $WORKERS --dist loadgroup -m "not serial"`, and `web_e2e`. Only these children get
    `BB_GATE_LOCK_HELD=1` (`BB_GATE_LOCK_HELD=1 <cmd>` or a subshell with `export`; **not** `env`, which cannot run the bash functions `pytest_each` and `web_e2e`). **This merges `tests/integration` and
    `tests/api` into one invocation** (today `pytest_each` runs them apart because two session
    scratch databases in one process used to sweep each other; R1's fix makes this safe). One line on start, one on end with `passed`/`FAILED` and duration (AC8).
    Siblings of a failure run to the end; then every failed step is named and its log printed in full
    (AC7); no stage 3. Green removes the log dir; red keeps it and prints its path last (AC9). The holder
    is released before stage 3.
  - **Stage 3** — `uv run pytest tests/integration tests/api -m serial`, plain, to the terminal,
    **without** `BB_GATE_LOCK_HELD`, so it takes its own exclusive lock and prints the "waiting" /
    "got the lock after N s" lines (checked in T8's verification: the stage-3 output contains the
    acquisition line).
  - **Interrupt** (SD12): a `trap` on INT/TERM kills the stage-2 process trees as far as Git Bash can
    (on Windows `taskkill //F //T` on the Windows pid, otherwise `kill` the group), prints an
    "interrupted" line, exits non-zero.
  - `tests/meta/test_gate_workers.py`: runs `bash scripts/check.sh` with `BB_GATE_WORKERS=abc`, `0`, `-1`,
    `9999`: non-zero, message names the variable, **and returns in under a few seconds** (it fails
    before stage 1; assert nothing from stage 1 was printed). `bash` found with `shutil.which("bash")`
    as `tests/image/test_venue.py:93` does (avoids WSL's bash), skipped, named, if absent; the
    subprocess has a hard timeout so a wrongly accepted value cannot start a nested full gate.
- Verification: `uv run pytest tests/meta/test_gate_workers.py`; `bash -n scripts/check.sh`; a dry run
  of stage 2 alone (builder-added temporary `BB_GATE_ONLY_STAGE=2` is **not** allowed; run the real
  script on a branch with the cheap steps passing). The full-gate timing is T9/T10's.
- Depends on: T3, T5, T6, T7
- Autonomy note: bash structure, log naming inside the dir and message wording are the builder's.
  It must not change which commands the gate runs beyond the stage split, `-n/--dist/-m` and the
  integration+api merge named above; must keep
  `ALLOW_EMPTY`/the exit-5 rule for the unit directories; and must not touch `ci.yml`. Stop and ask if
  a step cannot be run side by side because it writes a file another reads (e.g. a tracked output).

### T9 — Measure the connection cap and set it
- Implements: AC3 (the cap), SD2
- Expected output: a sampler (scratch, uncommitted) polling `pg_stat_activity` once a second while one
  gate runs with `BB_GATE_WORKERS` 2, 4, 8 (above the provisional cap by temporarily raising `CAP` in a
scratch copy of `check.sh`, never committed): the per-worker peak, the e2e pair, the holder, the serial
  stage. The Connection budget table filled in; `CAP` in `check.sh` set to `floor((40 − e2e − holder) /
  per-worker)` (or the measured equivalent), with the figures in a comment beside it (spec requires
  this). The `# provisional` marker removed.
- Verification: the sampler's peak for a 2-worker run is consistent with the per-worker figure
  (±1); `uv run pytest tests/meta/test_gate_workers.py` still green with the new cap.
- Depends on: T8, T11
- Autonomy note: the builder picks the sampling method. If the cap measured is below 4 workers, **stop
  and ask** — the 12-minute bar (AC22) is then unlikely and the owner decides (e.g. fewer connections
  per worker via the test fixtures, which is a design change, not a tune).

### T10 — First full gates: fix what load breaks, waits only
- Implements: AC25, AC24 (groundwork)
- Expected output: at least two consecutive green full gates on the local machine. Every failure is
  investigated to its cause. A **wait** that was too short under load is raised and recorded in the
  Waits table (test, old, new); a failure that is not a wait — a real race between workers, shared
  state, a bound — is fixed at the cause, or is a stop-and-ask. The serial stage's duration is
  recorded (the 12-minute bar depends on it).
- Verification: `./scripts/check.sh`, output pasted (not piped through `tail`); `git diff <T9's tip> --
  tests web` shows only waits, new `serial` marks and named cause fixes, each listed, and nothing under `exchange/`, `app/`, `db/`.
- Depends on: T8, T9, T11 (T11 settles before the full gates, and orders the plan-file edits:
  T1 → T11 → T9 → T10; each task edits only its own table in the plan file)
- Autonomy note: raise waits only (Playwright `expect` timeouts, polling deadlines). **Never loosen a
  bound** (tick gap, p95, 2 s takeover, 60 s ready, 60 s heavy-read). A flaky test that is a bound
  and flakes only in the parallel stage means the rule missed it: mark it `serial` and say so. If the
  serial stage alone makes the 12 minutes unreachable, stop and ask.

### T11 — Conditional: cheaper argon2 in `tests/api` only
- Implements: AC19 (only if T1 finds key hashing ≥ 10 % of `tests/api`'s single-process wall time)
- Expected output: **if triggered:** an autouse fixture in `tests/api/conftest.py` that monkeypatches
  `app.api.security._KEY_PARAMS` to `time_cost=1`, a few KiB, one lane for the test; the same
  fixture's docstring says why only here; `tests/meta/test_argon2_swap.py` fails on any occurrence of
  the swap anywhere but `tests/api/conftest.py`, with a planted-file test. `tests/unit/test_short_keys.py`
  (the pinned parameters and known-answer hash, `:102-129`) passes unchanged. **If not triggered:**
  the task is closed with T1's number and nothing is built.
- Verification: `uv run pytest tests/unit/test_short_keys.py tests/meta/test_argon2_swap.py`; a
  re-measure of the same sample as T1, saving written into the plan.
- Depends on: T1
- Autonomy note: the threshold is the spec's; the builder does not weigh it. Nothing is swapped in
  `tests/unit`, `tests/integration`, the harness, e2e or `app/`.

### T12 — The documents
- Implements: SD15 (no numbered AC; spec "In scope")
- Expected output: `CLAUDE.md` § Commands (stages instead of "13 steps", the `serial` rule, "gates
  and targeted runs may run at the same time"); `README.md:30-33`; `check.sh`'s header; the
  docstrings of `tests/integration/conftest.py`, `serve.py` (checked, already updated by T5/T6, not rewritten), and `tests/api/conftest.py` if T11 built;
  `docs/backlog.md` B-11 status. `memory/` notes made obsolete by this work are the owner's to prune.
- Verification: `uv run pytest tests/meta -q`; `grep -n "13 steps" CLAUDE.md README.md` empty.
- Depends on: T10, T11
- Autonomy note: wording is the builder's. Statements about timing use T10's measured numbers, not the target.

### T13 — Proof of shape (AC20, AC21, AC10, AC26)
- Implements: AC20, AC21, AC10, AC26
- Expected output, pasted into the PR description draft: (1) for each of `tests/integration`,
  `tests/api`, `tests/unit`, `tests/meta`, `tests/engine`: the node ids of `--collect-only -q` on the
  base commit versus the union of `-m "not serial"` and `-m serial` on this branch — identical, no id
  in both, none missing, and no test newly skipped (compare `-rs` output); (2) six planted failures,
  one at a time, reverted after: a stage-1 step, a unit test, a vitest file, a non-serial DB test, an
  e2e spec, a serial test — the gate goes red and names that step each time; (2b) one gate run with `BB_GATE_WORKERS=2` showing `-n 2` (AC2's below-cap half); (3) a gate killed with
  Ctrl-C/`kill` in stage 2, exiting non-zero with the interrupt line, then a clean gate green with no
  manual clean-up; (4) `git diff --stat main` shows nothing under `exchange/`, `tests/engine/`, `app/`, `db/`.
- Verification: the commands above, output saved under the scratchpad and quoted. Each planted failure is
  reverted with `git checkout -- <file>` and `git status` is clean before the next.
- Depends on: T10, T11
- Autonomy note: planted failures are the builder's to choose, in a throwaway commit-free working tree
  (never committed). An unexpectedly green gate on a planted failure is a stop-and-ask.

### T14 — The stability series (AC3, AC15, AC22, AC24)
- Implements: AC3, AC12 (observed), AC15, AC22, AC24
- Expected output, all on one unchanged commit, timings and step durations recorded: (1) five full
  gates in a row, each ≤ 12 min and green; (2) two rounds of two gates started together in two
  worktrees, all four green, `pg_stat_activity` sampled (combined peak ≤ 80) and in at least one round
  a serial stage's "waiting" line in the log; (3) during one gate's stage 2, `uv run pytest
  tests/api/test_keys.py` in another terminal: both green. Any red is run to its cause, fixed, and
  the series restarts (AC24); "it passed on re-run" does not count.
- Verification: the gate logs and sampler output; `scripts/check.sh` exit codes. The agent runs
  these; the CI part is below.
- Depends on: T11, T12, T13
- Autonomy note: a miss against 12 minutes is a stop-and-ask, not a pass (SD8). Worktrees go under the
  scratchpad or a sibling directory; per the standing memory, never stop the owner's other stack and
  note the port-5432 conflict if `mvr-intake-db-1` holds it.

### Owner steps after T14 (hard stops; not tasks)
- **AC23 / SD9.3:** push, open the PR, and run the 3 CI runs; compare each `Run the gate` step with the
  same step in the base commit's Actions run (read with `gh run view`). Pushing is the owner's.
- The manual exit check: one gate on the owner's machine, watched.

## Task graph

```
T1 ─► T11 ──────────────────────────────┐
T2 ─► T3 ─► T5 ─► T6 ─┐                  ├─► T9 ─► T10 ─► T12, T13 ─► T14
T2 ─► T4 ─► T5        ├─► T8 ────────────┘
T3, T4 ─► T7 ─────────┘
```

Levels: 0 T1, T2 · 1 T3, T4, T11 · 2 T5, T7 · 3 T6 · 4 T8 · 5 T9 · 6 T10 · 7 T12, T13 · 8 T14.

| Group | Tasks | Files they touch |
|---|---|---|
| A | T1, T2 | the plan file; `pyproject.toml`, `uv.lock` |
| B | T3, T4, T11 | the 14 `test_*.py` marker edits, `tests/meta/test_serial_marker.py`; `tests/support/pg_gate.py`, `tests/integration/test_pg_gate.py`; `tests/api/conftest.py`, `tests/meta/test_argon2_swap.py` (T11, plan-file amendment) |
| C | T5, T7 | `tests/integration/conftest.py`, `tests/conftest.py`, `tests/meta/test_no_db_connection.py`; `harness.py`, `test_port_claim.py`, `test_db_restart.py` (after T3) |
| D | T6 | `serve.py` |
| E | T8 | `scripts/check.sh`, `tests/meta/test_gate_workers.py` |
| F | T9 → T10 | `scripts/check.sh` (T9), the plan file and named test files (T10) — serial chain |
| G | T12 | docs (T12 also edits the three docstrings in files T5/T6/T11 finished) |
| H | T13 → T14 | no source files |

Within a group no file is written twice (T1 and T11 both touch the plan file but T11 depends on T1;
T9/T10 both touch the plan file but are chained).

## Data changes

None. No migration, no schema change, nothing under `db/`. Postgres gains only advisory locks held by
test sessions, on the maintenance database, which write nothing.

## Risks and unknowns

| Risk | Mitigation |
|---|---|
| **Connection cap too low to reach 12 min.** The app's pool is 5 + 10 overflow and is created per test by `TestClient`; two gates under 80 connections may allow only 2–3 workers. The app's pool size is under `app/` and out of reach. | T9 measures first; below 4 workers it is a stop-and-ask. An owner-approved alternative would be a smaller pool in tests/api's fixtures (a design change). |
| **The serial stage may be most of the 12 minutes.** 27 tests include `test_db_restart` (a 30 s outage plus a 60 s wait), `test_handover`, `test_heavy_reads` (a 30 000-order seed) and `test_real_process`, run alone after stage 2. Unknown duration. | T10 records it; the gate also pays stage 1 (~2 min). If the sum misses, SD8 says stop-and-ask. |
| **Deadlock between holder and queued exclusive** (the fairness trap described in Approach). | `BB_GATE_LOCK_HELD` inheritance; T4's lock test covers the queue behaviour; T14's concurrent rounds exercise it. |
| **`CREATE DATABASE` from `template1` under concurrent workers** may fail with "being accessed by other users". | T4/T5 verification with two workers; a short retry is allowed; anything worse is a stop-and-ask. |
| **Windows interrupt handling.** MSYS signals do not reach grandchildren (`uv` → `python`, `pnpm` → `node` → Chromium). | `taskkill //F //T`; AC10 only demands a clean next run, which a dead connection's lock release gives regardless. T13 tests it. |
| **Port retry cannot tell a foreign `/readyz`.** | T7 waits for the child's own listening log line, not just a 200. If none exists, stop-and-ask (SD14). |
| **Load-sensitive tests that are not serial by the rule** (`test_boot` ≥ 3 s waits, `test_ticker.settle`, `test_export_worker` spawned build, `test_health` through the proxy). | They are waits: T10 raises them, never bounds. If one is really a bound it moves to `serial`. |
| **`EXPORT_DIR` in `.env.local`** would make every app's workbooks land in one folder, colliding between workers (run ids restart at 1). Not verifiable from here. | T5/T10: the builder checks `.env.local` for `EXPORT_DIR`; if set, it is stripped in the DB tests' environment (tests/ side) — otherwise a stop-and-ask. |
| **Parallel stage-2 steps contend for CPU and the repo**: vitest, Playwright's Chromium and N pytest workers on 16 cores; stage-2 steps writing a path another reads (e.g. `web/test-results`, tracked-file hygiene tests). | T8 checks `tests/meta/test_repo_hygiene.py` and friends for reads of untracked/generated files; T10's first runs show contention. |
| **The `settings` fixture and the root logger are process-global** (`create_app` reconfigures logging each time). | Per worker each is its own process; nothing crosses workers. Within a worker the order is now random across modules; the analyst found no test that leaks, T10 would show one. |
| **Two scratch databases per worker** (the `tests/api` re-export registers a second session fixture). | Accepted; owned and swept like any other. Dedup is optional in T5. |
| **`test_handover` compares clocks across processes** and under-measures slow takeovers when the test process is late (found while reading). | Out of scope (no change to a bound); noted for the owner. |
| **CI has 4 vCPUs.** `WORKERS = min(nproc, CAP)` is 4 there. | AC23 only demands "no slower"; owner's step. |

## Uncertain

- Whether the cap leaves enough workers (T9), and whether stage 3 plus stage 1 leave room for 12 minutes (T10). Both are measurable only by building.
- Whether `python -m app.main` prints a line that identifies "listening" (T7). I did not read `app/main.py`'s logging.
- Whether `.env.local` sets `EXPORT_DIR`; I could not read it.
- The refinement of SD5 (children inherit the lock) is mine. It changes no decision but adds a mechanism the owner has not seen.
- The argon2 swap and any other per-test cost cut cannot be planned until T1; amendments will need a re-audit.

## Out of scope for this plan

Everything the spec excludes, and: moving `scratch_database` to one shared fixture (dedup), fixing the
other defects the read found (`issue_key` hashing on the event loop in `app/api/security.py:117`;
`test_export_worker` killing all of its process's children; `test_handover`'s cross-process clock),
a committed pg_stat_activity sampler, and any tuning of vitest or Playwright beyond waits.

## Acceptance map

| AC | Task(s) | AC | Task(s) |
|---|---|---|---|
| 1 | T2, T5, T8 | 14 | T4, T5, T6 |
| 2 | T8 | 15 | T4, T14 |
| 3 | T9, T14 | 16 | T5, T8 |
| 4 | T3 | 17 | T7 |
| 5 | T3 | 18 | T1 |
| 6–9 | T8 (shown by T13) | 19 | T11 |
| 10 | T8, T13 | 20 | T13 |
| 11 | T4, T5, T6, T8 | 21 | T13 |
| 12 | T4, T8, T14 | 22 | T14 |
| 13 | T4, T5, T6 | 23 | owner steps after T14 |
| 24 | T10, T14 | 25 | T10 |
| 26 | T13 (every task keeps to it) | | |

T12 implements SD15, which the spec states in "In scope" but gives no AC. Every other task cites at
least one AC.

## Audit (plan-auditor — PASS required before implementation starts)
- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans; T12 maps to SD15)
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note (T2 carries it)
- [x] Data changes additive and reversible (none)
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audited by: plan-auditor (agent), 2026-10-27 — first audit FAIL (R1–R4), plan revised; re-audit **PASS**.
Re-audit mediums 1–5 and lows 6–14, 16 are folded in above. Still the owner's before `/build`: acknowledge the
SD5 amendment (holders cover their children via `BB_GATE_LOCK_HELD`), and note T3 touches 15 files (two-line edits).

Human audit (/audit b-11): Martijn Boot, 2026-10-27 — all lines accepted and ticked in one answer. This
includes the SD5 amendment (`BB_GATE_LOCK_HELD`), SD11–SD15 as written, and T3's 15 files. Noted, not
changed: AC23 is an owner step after T14, and AC19/T11 are conditional on T1. T4, T8 and T10 are the
tasks most likely to near the size limit; the builder stops and asks if one passes ~400 source lines.

