# Spec: B-11 — A faster gate

Status: Approved (SD11–SD15 await the owner) · Depends on: Phase 0 (AC4 local and CI run the same checks, the gate
`scripts/check.sh`), Phase 2 (PD15 a scratch database per session, empty tables per test),
Phase 3 (R17 `tests/api` borrows the integration fixtures, T29 the real-process harness),
Phase 4 (T23 the e2e launcher `tests/integration/realapp/serve.py`), Phase 6 (PD15 the second,
`--empty` e2e server), B-08 (PD2 the pinned argon2 parameters) · Fixes: none (no defect in the
register concerns the gate) · Amends: `scripts/check.sh`, `CLAUDE.md` § Commands, `README.md`
§ the gate · Backlog: [B-11](../backlog.md)

Line references are to `main` at `437c505`.

## Problem

`scripts/check.sh` takes over 30 minutes, and every task and phase waits on it. It took about 17
minutes in Phase 7 and about 23 at B-01. In the gate of 2026-10-27, `tests/api` (1126 tests) took
15m56s and `tests/integration` (543) took 11m24s, each in one process on a 16-core machine. Web
e2e took 4m06s, vitest 1m12s and everything else about 2 minutes. Only one gate can run at a
time, and no database test may run beside one.

- **Every step runs one after another, and each pytest directory in a single process.**
  The 13 steps are called in order by `step` (`scripts/check.sh:56-68`, `:104-118`).
  `pytest_each` runs `uv run pytest "$dir"` once per directory, with no parallelism
  (`:86-97`). The database step is `pytest_each tests/integration tests/api` (`:117`). pytest's
  options are `-ra --strict-markers --strict-config` (`pyproject.toml:132-136`). No marker is
  registered and no plugin runs tests in parallel.
- **Every session drops every other session's databases.** `scratch_database` begins with
  `_sweep_leftovers` (`tests/integration/conftest.py:120-130`). That drops every database named
  `bb_test_%`, `WITH (FORCE)` (`:74-87`), including those of a run still in progress. Names are
  `bb_test_<12 hex>` (`:92`) and carry nothing to tell a live run's database from a dead one's.
- **The e2e launcher does the same to e2e databases.** Without `--empty`, `serve.py` drops every
  `borrelbeurs_e2e_%` before creating `borrelbeurs_e2e_<pid>`
  (`tests/integration/realapp/serve.py:69-79`). So two gates' e2e steps would drop each other's
  servers' databases.
- **Postgres itself does not otherwise couple two runs.** Every cluster-wide query in the tests
  is limited to its own database: `pg_terminate_backend` in `test_db_restart.py:92-104`,
  `test_real_process.py:275-280` and `test_boot.py:338-345`, and the `pg_locks` counts in
  `test_advisory_lock.py:20-32` and `test_boot.py:712-718`. The app's advisory lock
  (`app/db/advisory_lock.py:31`) belongs to a single database. `test_db_restart` blackholes a
  proxy; it does not restart Postgres.
- **Real processes are handed a probed port.** `free_port()` binds port 0, reads the number,
  closes the socket and returns it (`tests/integration/realapp/harness.py:39-42`). A subprocess
  then binds that number. Two runs at once can, rarely, get the same port.
- **Some tests assert real elapsed time.** `test_export_timing` holds tick gaps to ≤ 1.5× the
  interval and p95 order latency to ≤ 2× baseline. `test_handover` requires the lock taken
  within 2 s. `test_db_restart` requires ready within 60 s. `test_heavy_reads` runs an export
  with the 60 s heavy-read timeout. `test_real_process`, `test_smoke_script` and others start
  `python -m app.main` on a real clock. Under parallel load, any of these can fail without
  anything being wrong.
- **A test login costs two argon2 hashes at production parameters.** `_KEY_PARAMS` is
  `time_cost=3, memory_cost=64 MiB, parallelism=4` (`app/api/security.py:58-66`). `key_hash`
  runs once at minting and once at login (`:96-98`; `tests/api/conftest.py:122-159`). At about
  72 ms each, that is around 145 ms of a test's ~0.85 s. Nobody has profiled the rest.
- **Connections are the limit, not cores.** The compose `db` and CI's service container run
  Postgres with the default `max_connections` of 100. CI's `services:` cannot pass a `command:`,
  so CI cannot easily raise it. A running app holds a SQLAlchemy pool (default 5 + 10 overflow),
  the heavy-read engine and the lock connection. The repository is public, so CI's
  `ubuntu-latest` has 4 vCPUs; the owner's machine has 16.
- **E2e already runs one server and one Playwright worker** (`web/playwright.config.ts:12-13`).

## Decisions

These were settled at the spec interview on 2026-10-27. Q1–Q10 were put to the owner one at a
time, each with a recommendation, and each answer below is recorded as given. SD11–SD15 are the
spec writer's defaults. They were not put to the owner, who confirms or corrects them when
approving this spec. The planner must not reopen any of them.

**Running in parallel**

- **SD1 — pytest runs in parallel with `pytest-xdist` (Q1: A).**
  - New dev dependency, in the `dev` group of `pyproject.toml` with a comment, as for its
    neighbours: `pytest-xdist>=3.6,<4`. MIT licence, maintained by the pytest-dev organisation.
  - Why not the stdlib: it has no runner that shares pytest's fixtures and collection across
    processes.
  - Why not hand-rolled sharding in `check.sh`: fixed file lists split unevenly, so the slowest
    shard sets the time, and we would maintain our own collection and reporting.
  - Files are handed to idle workers (`--dist loadfile` or `loadgroup`; the plan picks one).
    Each worker has its own scratch database.
- **SD2 — The worker count is `min(logical cores, cap)` (Q2: B).**
  - The cap is measured. The plan measures one worker's peak Postgres connections and sets the
    cap so that **two full gates together** stay at or below 80 of the 100 connections. That
    count includes their e2e servers and their serial stages.
  - The cap and the measurement behind it are written as a comment beside the cap in
    `check.sh`.
  - One environment variable, read only by `check.sh` (never under `app/` or `db/`), can lower
    the count for a single run. It cannot raise it above the cap.
- **SD3 — Serial tests: a rule and a marker (Q3: A).**
  - **The rule.** A test runs serially if it asserts a bound on real elapsed time (a latency,
    a gap, a deadline such as "ready within 60 s" or "lock taken within 2 s"), or if it starts a
    real `python -m app.main` process.
  - **The marker.** One registered marker, `serial`, declared in `pyproject.toml` because
    `--strict-markers` is on. It is set per module with `pytestmark` where the whole module
    qualifies, per test otherwise.
  - **The run.** `check.sh` runs `-m "not serial"` across the workers, then `-m serial` in one
    plain process.
  - **The guard.** A `tests/meta` test fails if a test module calls the real-app harness
    (`spawn_app`, `start_app`) and is not marked `serial`.
  - **The starting list.** The plan applies the rule to every module under `tests/integration`
    and `tests/api`, and lists the modules it marks and why. The backlog's six are a starting
    point, not the list.
- **SD4 — Three stages; a stage-2 failure lets its siblings finish (Q4: B).**
  - **Stage 1, one after another, stopping at the first failure, as today:** ruff format, ruff
    check, web format, web lint, mypy, tsc, API-types drift, web build, built-output references.
  - **Stage 2, side by side:** pytest `tests/unit tests/meta tests/engine`, vitest, pytest
    database tests `-m "not serial"` across the workers, and web e2e.
    - Each step writes its full output to its own log file (SD11).
    - The terminal shows one line per step when it starts and one when it ends, `passed` or
      `FAILED` with its duration.
    - When a step fails, its siblings run to the end. Then every failed step is named and its
      log printed in full, and stage 3 does not start.
  - **Stage 3, alone and last:** pytest `-m serial` over the database test directories, in
    one process, with nothing else from this gate running.
  - "Stop at the first failure" holds between stages.

**Running beside another run**

- **SD5 — A shared/exclusive lock on the Postgres server (Q5: B).**
  - The lock is a pair of advisory locks (`pg_advisory_lock_shared` / `pg_advisory_lock`) on
    the database `DATABASE_URL` names: the server's maintenance database, the one scratch
    databases are created from. So it works the same locally and in CI, with no lock file and
    no extra tool. Its key is not the app's `ADVISORY_LOCK_KEY`.
  - **Shared holders:** a gate's whole stage 2, and every pytest run that uses a scratch
    database and is not a serial run, including targeted runs (`uv run pytest tests/api/...`)
    and each xdist worker. `serve.py` also holds it shared for its life.
  - **Exclusive holders:** a serial run. A plain pytest run that selects any `serial` test holds
    the lock exclusive.
  - **The effect.** A serial stage waits until no other run is in its parallel stage, and no
    parallel run starts while it holds the lock. Postgres queues waiters in order, so a waiting
    serial stage is not starved. A dead process's connection drops, and its lock with it.
  - **Not covered:** another gate's stage 1 (static checks and the web build, about 2 minutes),
    and load from outside the gate (editor, browser). The stability series (SD9) runs gates
    concurrently, so it exercises this.
  - **The maintenance database, amended.** Today it is used only for `CREATE DATABASE` and
    `DROP DATABASE` (`tests/integration/conftest.py:3-9`). Now it also carries these advisory
    locks and SD6's, which write nothing.
- **SD6 — A sweep drops only databases whose owner is dead (Q6: B).**
  - **Ownership.** For as long as a run lives, its maintenance connection (SD5's) also holds an
    advisory lock named after each scratch database it created. That covers `bb_test_*` and
    `borrelbeurs_e2e_*` databases alike.
  - **The sweep.** It drops a `bb_test_*` or `borrelbeurs_e2e_*` only if it can take that
    database's lock, which means its owner is dead. A killed run's leftovers are dropped at the
    next run's start, with no age threshold and no clock.
  - **Where it applies.** The same rule replaces `_sweep_leftovers` and `serve.py`'s own
    sweep. `serve.py --empty` still skips the sweep (Phase 6 PD15), but its database is owned
    the same way.
  - **Names.** Names stay unique per creation (`bb_test_<hex>`). The plan may change their
    shape to fit the lock key, but the prefixes stay.
- **SD7 — Cheaper argon2 in `tests/api` only, and only if the profile pays for it (Q7: B,
  conditional).**
  - **The profile comes first.** The plan's first task profiles `tests/api` in one process:
    where a typical test's time goes (hashing, app boot and shutdown, engine creation and
    disposal, TRUNCATE, the request itself). Its numbers go into the plan.
  - **The swap.** If key hashing is at least 10 % of `tests/api`'s single-process wall time,
    `tests/api/conftest.py` swaps `_KEY_PARAMS` for minimal parameters (`time_cost=1`, a few
    KiB, one lane) in a fixture. Below 10 %, no swap is made.
  - **What is never swapped:** `tests/unit` (the pin and known-answer hash in
    `tests/unit/test_short_keys.py:102-129` stay on the real parameters), `tests/integration`
    (real processes and the CLI hash with real parameters), the real-app harness, e2e and
    `app/`.
  - **The guard.** A meta test fails if the swap appears anywhere but `tests/api/conftest.py`.
  - **Other per-test costs** the profile shows (fixture engines built and disposed per test,
    for example) may be cut too, under the same rule: what a test checks does not change.
    Each cut is a named plan task with its measured saving.

**Proof**

- **SD8 — The bar: at most 12 minutes, the same verdict (Q8: A).**
  - **Local.** The full gate takes at most 12 minutes wall time, first line to last, on the
    owner's 16-core machine, with the compose `db` running and dependencies installed. It is
    measured on the plan's base commit plus this work. A miss is a stop-and-ask, not a pass.
  - **CI.** CI's `Run the gate` step is no slower than on the base commit, read from that
    commit's Actions run.
  - **The verdict.** Each pytest directory collects the same test node ids as the old gate,
    split between `not serial` and `serial` with none in both and none left out. Every test
    that ran before runs, and none is newly skipped.
- **SD9 — The stability series (Q9: A).** All on one unchanged commit:
  1. 5 full gates in a row, locally, all green.
  2. 2 rounds of two gates started together, in two worktrees, all four green. In at least one
     round, the log shows a serial stage waiting on SD5's lock.
  3. 3 green CI runs.

  Any red in the series is investigated to its cause and fixed, and then the series starts over.
  "Re-ran and it passed" does not count. The runs' timings and step durations go into the PR.
- **SD10 — Waits may be raised; bounds never (Q10: B).**
  - **A bound** is a time limit a spec or a test asserts as behaviour: tick gap ≤ 1.5×
    interval, p95 ≤ 2× baseline, lock within 2 s, ready within 60 s, the 60 s heavy-read
    timeout. Bounds are never loosened, and the tests that assert them are `serial` (SD3).
  - **A wait** is how long a test polls for something it then checks: Playwright's `expect`
    timeout, "until the row appears", "until `/readyz`". A wait may be raised. The plan names
    each one with its old and new value, and the PR lists every test that needed it.

**Defaults (the spec writer's; confirm or correct when approving)**

- **SD11 — Logs.**
  - Stage 2's step logs go to a per-run directory under the OS temp directory, named
    `bb-gate-<UTC stamp>-<pid>`, never inside the repository.
  - On green the directory is removed. On red it is kept, and its path is printed on the last
    line with the failed steps.
  - Stage 1 and stage 3 print straight to the terminal, as today.
- **SD12 — Interrupt.**
  - Ctrl-C, or a kill of `check.sh`, stops the gate's child processes as far as Git Bash can,
    and the gate exits non-zero with a line saying it was interrupted.
  - Whatever survives holds no lock that blocks the next run, because a dead connection
    releases it (SD5, SD6).
  - The next gate starts and passes with no manual clean-up.
- **SD13 — Targeted runs stay plain.**
  - `uv run pytest <path>` with no `-n` still runs in one process, as today. `-n` is passed
    by `check.sh`, not by `addopts`.
  - A targeted run never needs the gate's environment variable, and joins SD5's lock on its
    own.
  - A run that touches no scratch database (`tests/unit`, `tests/meta`, `tests/engine`) opens
    no connection and takes no lock.
- **SD14 — Ports.**
  - A real app started by a test or by `serve.py` serves on a port nobody else can be handed
    between probe and bind. A collision with another run's process makes the harness pick
    another port and retry; it is never a red test, and never a request to another run's app.
  - The mechanism is the plan's, inside `tests/` and `serve.py`. If it needs a change under
    `app/`, that is a stop-and-ask.
- **SD15 — The documents.**
  - `CLAUDE.md` § Commands: the gate's stages instead of "13 steps", the `serial` rule, and
    that gates and targeted runs may now run at the same time.
  - `README.md`'s gate paragraph (`README.md:30-33`).
  - `check.sh`'s header comment.
  - The docstrings of `tests/integration/conftest.py`, `tests/api/conftest.py` (if SD7 swaps)
    and `serve.py`.

## In scope

- `scripts/check.sh`: three stages, side-by-side stage 2 with per-step logs, the worker count
  and its override, interrupt handling, the step lines.
- `pytest-xdist` in `pyproject.toml` and `uv.lock`.
- The `serial` marker in `pyproject.toml`, applied to every module or test the rule covers.
- Scratch databases: one per xdist worker, ownership locks, the owner-aware sweep, in
  `tests/integration/conftest.py` and `serve.py`.
- The shared/exclusive lock, taken by pytest database sessions, `serve.py` and `check.sh`'s
  stage 2.
- The port fix in `tests/integration/realapp/harness.py` and `serve.py`.
- The profile, and the argon2 swap in `tests/api/conftest.py` only if SD7's threshold is met.
  Other per-test cost cuts the profile justifies.
- Raised waits, named (SD10).
- Meta tests: real-app harness implies `serial`, and the argon2 swap stays in its one place.
- The stability series and the timing evidence, in the PR.
- The documents (SD15), and this item's backlog status.

## Out of scope

- Dropping, skipping, merging or weakening any check or test. Loosening any bound (SD10).
- The pricing engine (`exchange/`), the golden fixtures, `tests/engine/v1_reference/`, and
  `scripts/golden_linux.sh`. The golden tests stay skipped on Windows, as today.
- Running stage 1's static steps side by side, or caching mypy, tsc or the web build.
- Vitest's per-file start-up cost (~8.75 s a file). Vitest runs in stage 2, off the critical
  path.
- More than one Playwright worker, or more than the two e2e servers there are today.
- Splitting CI's `check` job across several jobs or runners, larger runners, or any change to
  `ci.yml` beyond what calling the same script needs. CI keeps running `./scripts/check.sh`.
- Postgres server settings: `max_connections`, `fsync`, `shared_buffers`, or any change to the
  compose `db` or CI's service container.
- `-n` in pytest's `addopts`. Targeted runs stay single-process unless asked (SD13).
- `tests/image`, the image drills, the venue drill and the deploy workflow.
- Any change under `app/` or `db/` (SD14's stop-and-ask is the only door).
- The order of the `/build` workflow, and when the gate is run during a phase.

## Acceptance criteria

**Parallel and serial — SD1, SD2, SD3**

- **AC1.** When the gate runs the database tests, the system shall run every `not serial` test
  across `min(logical cores, cap)` xdist workers, each on its own scratch database, and every
  `serial` test afterwards in a single process.
- **AC2.** When the gate's worker override is set below the cap, the system shall use that
  count. When it is set above the cap, or to something that is not a positive integer, the gate
  shall fail before stage 1 and name the variable.
- **AC3.** While two full gates run together, the system shall hold at most 80 Postgres
  connections at their combined peak. *(Measured in the stability series' concurrent rounds by
  sampling `pg_stat_activity`. The cap comment in `check.sh` gives the per-worker figure.)*
- **AC4.** When a test module calls `spawn_app` or `start_app` from the real-app harness and is
  not marked `serial`, a `tests/meta` test shall fail and name the module.
- **AC5.** When any test asserts a bound on real elapsed time (SD10's sense), the system shall
  run it in the serial stage. *(The plan's list of marked modules, each with its reason, is the
  evidence. The reviewer checks it against the rule.)*

**Stages and output — SD4, SD11, SD12**

- **AC6.** When a stage-1 step fails, the gate shall stop there, name the step, and run nothing
  further.
- **AC7.** When a stage-2 step fails, the system shall let the other stage-2 steps finish, then
  name every failed step, print each failed step's log in full, not start stage 3, and exit
  non-zero.
- **AC8.** While stage 2 runs, the terminal shall show one line when each step starts and one
  when it ends, with `passed` or `FAILED` and its duration.
- **AC9.** When the gate ends green, its stage-2 log directory shall be removed. When it ends
  red, the directory shall remain under the OS temp directory and its path shall be printed on
  the final lines.
- **AC10.** When the gate is interrupted (Ctrl-C or a kill), it shall exit non-zero with a line
  saying so. The next gate, started with no manual clean-up, shall pass on an unchanged commit.

**Running beside another run — SD5, SD6, SD13, SD14**

- **AC11.** While a gate is in stage 2, or any non-serial pytest run with a scratch database is
  running, the system shall not start a serial run until they have finished. While a serial run
  holds the lock, no stage 2 and no non-serial database run shall start.
- **AC12.** When a serial stage waits on the lock, the gate shall print a line saying it is
  waiting, and one with how long it waited once it has the lock.
- **AC13.** When a pytest session or `serve.py` sweeps, the system shall drop only `bb_test_*`
  and `borrelbeurs_e2e_*` databases whose owner no longer holds their ownership lock, and never
  one whose owner is alive.
- **AC14.** When a run is killed and the next run starts, the killed run's scratch databases
  shall be dropped by that next run's sweep.
- **AC15.** When two gates run at the same time, or a gate and a targeted `uv run pytest
  tests/api`, both shall finish with the verdict each would have had alone.
- **AC16.** When `uv run pytest <path>` is run without `-n`, the system shall run it in one
  process, as today. When the path holds no database test, the run shall open no Postgres
  connection.
- **AC17.** When a real app's port has been taken by another process between probe and bind,
  the harness shall retry on another port. It shall not report a red test, and shall not send a
  request to the other process.

**Cost — SD7**

- **AC18.** The plan shall record the profile of `tests/api` (SD7) before any per-test cost is
  cut, and each cut shall carry its measured saving.
- **AC19.** If the argon2 swap is made, it shall exist only in `tests/api/conftest.py`, and a
  `tests/meta` test shall fail on any other occurrence. `tests/unit/test_short_keys.py`'s pinned
  parameters and known-answer hash shall pass unchanged.

**The bar — SD8, SD9, SD10**

- **AC20.** For the same commit, the new gate shall collect, in each pytest directory, exactly
  the node ids `uv run pytest <dir> --collect-only -q` lists. Each id shall be in exactly one of
  `not serial` and `serial`, and no test shall be skipped that the old gate ran.
- **AC21.** When a deliberate failure is planted in each of: a stage-1 step, the unit pytest, a
  vitest file, a non-serial database test, an e2e spec and a serial test, the gate shall go red
  and name that step. *(Six planted failures, one at a time, reverted after. The output of each
  goes into the PR.)*
- **AC22.** Each of SD9's 5 sequential local gates shall take at most 12 minutes wall time on
  the owner's machine.
- **AC23.** Each of SD9's 3 CI runs' `Run the gate` step shall take no longer than the same
  step on the base commit's CI run.
- **AC24.** Every run of SD9's series shall be green, with no re-run counted.
- **AC25.** The diff shall loosen no bound (SD10), and every raised wait shall be listed in the
  plan and the PR with its old and new value.
- **AC26.** The diff shall touch nothing under `exchange/`, `tests/engine/`, `app/` or `db/`.

## Verification

- **Meta and unit (pytest):**
  - the real-app harness without `serial` fails, on a planted module (AC4);
  - the argon2 swap outside `tests/api/conftest.py` fails, on a planted file (AC19, if
    swapped);
  - the override variable's validation (AC2).
- **Locks and sweep (integration, in the serial stage itself):**
  1. Two sessions each create and own a scratch database.
  2. One sweeps. The other's database survives (AC13).
  3. A third process creates a database and is killed. The next sweep drops it (AC14).
  4. A shared holder blocks an exclusive one, and an exclusive holder blocks a new shared one.
     The waiter gets the lock after release (AC11).
- **Ports:** a planted collision, with a port taken between probe and bind, ends in a retry and
  a green test (AC17).
- **The gate's shape:**
  1. The collection comparison on the base commit plus this work (AC20).
  2. The six planted failures (AC21).
  3. An interrupted gate followed by a clean one (AC10).
- **The stability series (SD9), whose log and timings go into the PR:**
  1. 5 sequential local gates, each ≤ 12 min (AC22, AC24).
  2. 2 concurrent rounds in two worktrees, with `pg_stat_activity` sampled for the connection
     peak (AC3). The serial stage's wait lines appear (AC12). Both gates of each round are
     green (AC15).
  3. During one sequential gate's stage 2, a targeted `uv run pytest tests/api/test_keys.py` in
     another terminal: both green (AC15).
  4. 3 CI runs, each compared with the base commit's `Run the gate` duration (AC23).
- **The gate:** `./scripts/check.sh`, the new stage lines, output pasted. The engine is untouched
  (AC26), so `golden_linux.sh` and `engine-guardian` are not required.

## Exit condition

The gate runs the same tests with the same verdict in at most 12 minutes on the owner's machine,
no slower in CI. Two gates, or a gate and a targeted test run, can run at the same time without
disturbing each other. It came through the stability series green with no re-run.
