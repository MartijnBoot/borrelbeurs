# Plan: Phase 8 — Deploy and cutover

Spec: [docs/specs/phase-8-deploy-cutover.md](../specs/phase-8-deploy-cutover.md) (`Status: Approved`, rewritten 2026-10-10; **uncommitted** on `docs/phase-8-plan` at planning time) · Status: Audited — PASS (2026-10-10; amendment A1 re-audited 2026-10-11)
Design: [architecture.md](../design/architecture.md) ("Shape", "Durability", "Tick model"), [data-model.md](../design/data-model.md), [realtime-protocol.md](../design/realtime-protocol.md)
ADRs honoured: 0003 (one writer; standby and the app clock are written as an addendum in T21, accepted by the human at approval of the spec), 0004 (Postgres is the persistence layer; the host export is a *copy*, never read back), 0006 (no CDN; AC7 re-checks the built assets inside the image), 0007 (v1 is retired, not kept as a fallback: SD17 withdrawn by A1), 0009/0010 (hard stops: ADR text, `docs/design/`, credentials and external accounts, `borrelbeurs-v1`), 0011 (migrate at boot; SD3 is the expand/contract mechanism it assumed, and its overlap paragraph is superseded in T21)
Fixes: D-42, D-43

---

## Approach

**Make the two failure environments explicit in the server, then prove the image in CI.** The
server work is small and lives where the problems are:
- `app/core/config.py` learns `venue`, `BUILD_SHA`, `TRUSTED_PROXY_IPS` and `EXPORT_DIR`, and
  `app/main.py` passes proxy trust to uvicorn explicitly (T1);
- the SPA mount sets `Cache-Control` (T2);
- one additive migration adds `schema_compat`, and boot decides between "migrate", "schema ahead
  but compatible" and "refuse" before it migrates (T3);
- a single **app clock**, `AppClock` in `app/runtime/clock.py`, wraps the clock every runtime and
  API caller already shares through `app.state.clock`. Every commit stamps
  `max(app_now, last_commit)` (T4), and the ticker turns a backward step beyond the budget into
  an offset and a zero-shift `gap` tick (T5);
- a booting instance that cannot take the lock serves `/healthz` in **standby** instead of exiting
  (T6). A two-process test proves the handover (T7);
- the export worker copies every finished export to `EXPORT_DIR`, and every 15 minutes writes a
  row-less `auto` export there (T8).

Nothing in `exchange/` changes. Time still enters the engine only as `now_ms`
(`exchange/advance.py:32-36`), so the golden fixtures stay green by construction.

**Everything image-shaped is a script or a pytest module that a builder can run locally against a
`docker build`, and one late task wires them into CI.** These are:
- the contents and size check (`scripts/ci/check_image.py`, T11);
- the Trivy scan (`scripts/ci/scan_image.sh`, T12);
- the image boot drill, the kill drill and the venue drill (`tests/image/`, T13, T14, T16);
- the venue stack and its `.cmd` wrappers (`deploy/venue/`, T15);
- the bundle (`scripts/make_bundle.sh`, T16);
- the smoke test (`scripts/smoke.py`, T10);
- `render.yaml` and the deploy workflow (T17).

T18 then edits `.github/workflows/ci.yml` once. Image tests are pytest, not shell, so they reuse
`tests/integration/realapp/harness.py`'s `Client` and order-stream helpers. They live in
`tests/image/`, which `check.sh` never collects, because it names its test directories
explicitly (`scripts/check.sh:104-118`). The human tasks (H1–H4, in `phase-8-human-steps.md`) carry the criteria only a person
at a router or a Render dashboard can meet.

Rejected:
- **Retrying the lock inside the lifespan.** uvicorn binds no socket until the lifespan yields
  (`uvicorn/server.py:106-154`), so `/healthz` could never answer and SIGTERM would not stop the
  loop. Standby yields first and boots in a task (PD1).
- **Reading "Can't locate revision" out of `alembic upgrade`'s `CommandError`.** It cannot tell
  "ahead and compatible" from "ahead and incompatible". Boot reads `alembic_version` and
  `schema_compat` directly, before it migrates (PD2).
- **An offset kept beside the ticker only.** Orders, jumps, events, drink edits and live config
  all stamp `clock.wall_ms()` raw (`orders.py:208`, `manipulation.py:78,129`,
  `drinks.py:194,317,387`, `runtime/config.py:445,475`), and the API hands them
  `app.state.clock` (`api/deps.py:64`). Wrapping that one object reaches every site; a ticker-only
  offset would leave six (PD4).
- **Writing the host copy from `app/jobs/`.** The spec assumes this keeps
  `tests/meta/test_no_file_io.py` green. Phase 7 put `app/jobs` in its scanned roots (`:39`), and
  roots may only be added (`:20`). PD5 puts the one file-writing function outside those roots.
- **Shell drills.** Kill and venue drills need order streams, acknowledgement bookkeeping and
  database assertions that `test_real_process.py` already has in Python.
- **One CI task per drill.** Every drill would edit `ci.yml`, and they would all conflict. T18
  wires them all once they exist.
- **`hypothesis` for AC16.** It is not a dependency (`pyproject.toml`, `uv.lock`), and SD20 adds
  none. A seeded `random.Random` loop that prints its failing seed is the property test (T4).

---

## Decisions this plan makes

Rows marked **Confirm** change behaviour the spec left open, or bend its wording. The audit
confirms or overrules them. No row is a hard stop except where marked.

| # | Question | Decision | Reason |
|---|---|---|---|
| PD1 | How standby fits uvicorn's lifecycle | `start_runtime` tries `acquire` **once**, as today. **Granted:** boot runs synchronously in the lifespan, unchanged, so a migration failure still raises out and uvicorn exits 3 (AC8). **Not granted:** set `app.state.standby = True`, start a background task, and yield at once. The task retries `acquire` every 1 s on `clock.monotonic`/`sleep_until`, and logs `lock_wait` (WARNING, `waited_s`) on entry and every 30 s. Once it holds the lock it runs the same `_boot(...)` as the fast path, then clears `standby` and sets `ready`. A failure **after** standby (migration, `schema ahead of image`) logs `boot_failed` and calls `exit_process(BOOT_FAILED_EXIT)`, which is `os._exit(3)`, the same code uvicorn uses for a startup failure. `acquire` *raising* (the database is unreachable) is not standby: it fails as today, with exit 3. `exit_process` gains a `code` parameter, and `LOCK_LOST_EXIT = 70` is unchanged. Shutdown during standby cancels the task. If the task got as far as booting, the same stop path as today runs. **Confirm** | uvicorn serves nothing until the lifespan yields. Exit 3 on both paths keeps `restart: on-failure` and Render's restart identical for "boot failed" |
| PD2 | `schema_compat` shape and the boot rule | Table `schema_compat(id smallint PRIMARY KEY CHECK (id = 1), min_code_revision text NOT NULL)`, seeded `(1, '0011')` by `0011_schema_compat`. **`'0011'` is the rollback floor (SD3).** Every later migration declares a module-level `min_code_revision` that is either the string `"unchanged"` or a revision id. When it is an id, its `upgrade()` calls `db/migrations/compat.py: set_min_code_revision(op, rev)`. Boot, under the lock and before migrating: read `alembic_version` and `schema_compat` with raw SQL (`app/db/schema_compat.py`), and look the revision up in `ScriptDirectory` (built from `MIGRATIONS_DIR`, beside `upgrade_to_head`). A pure function `decide(known, db_rev, min_code) -> Migrate \| Ahead \| Refuse` is unit-tested. `Ahead` logs `schema_ahead` at WARNING with `db_revision` and `min_code_revision`. `Refuse` logs `boot_failed` with reason `schema ahead of image` and raises `BootFailure`, having written nothing. A database with no `alembic_version` table is `Migrate` | SD3 verbatim. Raw SQL works for any image ≥ 0011, which all know the table. The pure decision is the part worth a table of cases |
| PD3 | AC9's "previous release" and "previous image" in CI | **New image on the old schema:** the drill migrates a fresh database to `head-1` with the image's own alembic (`docker run … alembic -c db/alembic.ini upgrade <down_revision of head>`), then boots the image, which must migrate and pass smoke. **Old image on the new schema:** no SD3 image older than this one exists, since this one is the floor. So the drill makes the *database* one contract-free revision ahead: it migrates to head, then stamps `alembic_version` to the fixture id `ci_ahead_fixture`, leaving `min_code_revision='0011'`. The same image must log `schema_ahead` and pass smoke. It then sets `min_code_revision='ci_ahead_fixture'` and asserts the refusal (AC10 at image level). The drill accepts an optional `--previous-image` and boots that against head as well; CI does not pass it until a previous SHA is in GHCR (R3). **Confirm** | The spec allows "a fixture image one contract-free revision behind". A stamped database is the same situation seen from the other side, and it needs no second build |
| PD4 | The app clock (SD15) | `AppClock(inner)` in `app/runtime/clock.py`: `wall_ms() = inner.wall_ms() + offset`; `monotonic`/`sleep_until` delegate; `raise_to(target_ms)` sets `offset = max(offset, target_ms − inner.wall_ms())`, so it never decreases; `offset_ms` is a read-only property. `create_app` stores `AppClock(clock or RealClock())` as `app.state.clock` (`main.py:205`). Tests that pass a `FakeClock` still drive it, because the wrapper delegates. `commit_stamp_ms(clock, view) = max(clock.wall_ms(), view.last_commit_wall_ms or 0)` replaces the raw read at every commit site: `orders.py:208`, `manipulation.py:78,129`, `drinks.py:194,317,387`, `runtime/config.py:445,475`, `api/news.py:68` (amended after audit); `close.py:56` already does this and switches to the helper. **Ticker (T5):** when `now_wall < last_commit − budget`, it calls `clock.raise_to(last_commit)`, writes one `gap` tick with zero shift (version + 1, same prices, no anchor shift), logs `clock_stepped_back` with `step_ms` and `offset_ms`, then re-anchors from the raised clock so the drift check sees no second step. **Rehydrate (T5):** when the wall clock is behind the stored last commit by any amount, boot calls `raise_to(run.wall_ts_ms)` and writes no gap, because no time evolved | One object already reaches every caller. A backward step within the budget keeps ADR 0003's hold through `commit_stamp_ms`. The offset is not persisted: the next boot recomputes it from the last commit |
| PD5 | Where the host-file write lives | New module `app/hostdir.py`: `write_atomic(directory, name, data)` writes `.<name>.partial` and then `os.replace`s it, and `prune(directory, pattern, keep)` deletes the oldest matches. It is the only new file-writing code. It sits outside `test_no_file_io.py`'s roots, which stay as they are, so `app/jobs` keeps calling no `open`. **Confirm**: the spec text says "the export worker (`app/jobs/`) … keeping `test_no_file_io.py` green", and that cannot hold literally (`test_no_file_io.py:39,45`) | The meta test guards persistence paths. The host copy is deliberate file I/O and should be one small, named module, not a loophole inside a guarded root |
| PD6 | Scheduling the auto export and the slot | `run_worker` waits for `wakeup` **or** the next auto due time (`clock.sleep_until`, whichever comes first). When an auto export is due, all of these must hold: `export_dir` is set; a `run` has `status='live'` (read from the database, so the worker needs no holder); and no `export` row is `queued` or `running`. If so, it builds the run through the same `BuildProcess` and writes it **only** to the host. Otherwise it skips the auto export. Either way the next one is due 15 minutes later (`AUTO_EXPORT_INTERVAL_MS`, a constant). A manual request arriving *during* an auto build waits for that one build. **Confirm**: the reading of "never delays a manual or final export" is "an auto export never starts ahead of a queued export". The alternative, killing the auto build when a request arrives, is possible (`BuildProcess` already survives a dead child, Phase 7 review) but more machinery | Bounded by one build, a few seconds at venue sizes (Phase 7 T11's timings). Skipped, not queued, as SD14 says |
| PD7 | Host file names and retention | `borrel-<slug>-<yyyymmdd-hhmm>-<kind>.xlsx`, where `kind` is `manual`, `final` or `auto`. The slug and stamp rules (Phase 7 PD10) move from `app/api/exports.py:61-66` into `app/jobs/naming.py`, which `app/api/exports.py` imports. The download name is unchanged, with no `-<kind>`. The stamp is the row's `created_at` (UTC), or the build time for `auto`. A same-name collision (two manual exports in one minute) is replaced by the later one. Auto retention keeps the newest 8 `borrel-<slug>-*-auto.xlsx` files. Runs with the same slug share those 8. Manual and final copies are never pruned on the host. **Confirm** | SD14's names. One slug function, not two |
| PD8 | Where the image drills live | `tests/image/` (pytest, typed, ruff-checked), with a `conftest.py` that adds `--image <ref>`. It skips the whole directory when the option is absent. It reuses `tests/integration/realapp/harness.py` (`Client`, `mint_key`) and the order-stream helper from `test_real_process.py:63-85`, moved into the harness by T14 if it must be shared. Postgres is the digest in `docker-compose.yml`, run on a throwaway docker network. `check.sh` does not collect `tests/image`; CI's image jobs do (T18) | Reuse over a second, shell-only order client |
| PD9 | What AC2's names match | The check reads `docker export` of a created container as a tar stream and matches **path components**, not substrings: `*.tar`, `*.tar.gz`, `.git`, `.env*`, `keys.json`, `.jwt_secret`, a directory named `tests` or `legacy` or `node_modules`, a package directory or `*.dist-info` named `pip`, `setuptools` or `uv`, and `bin/pip*` / `bin/uv`. The scope is **image-wide**, including `site-packages`. So the Dockerfile also deletes vendored `*/site-packages/*/tests` directories (for example greenlet's) and `ensurepip/_bundled/*.whl`. **Confirm** | "`pipes.py`" must not match "pip". Image-wide is the strict reading of AC2 |
| PD10 | CI layout | `ci.yml` gains these jobs: **`image`** builds with `--build-arg BUILD_SHA=${{ github.sha }}`, runs `check_image.py`, Trivy and the SBOM, extracts and checks the assets, and uploads `docker save` as an artifact. **`image-drill`** (needs `image`) runs `pytest tests/image/test_boot_image.py tests/image/test_kill_drill.py`. **`venue`** (needs `image`) runs `pytest tests/image/test_venue.py`. **`push`** (needs `check`, `secret-scan`, `image`, `image-drill`, `venue`) runs only `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`, has `permissions: packages: write` (job-level, nowhere else), loads the artifact, and pushes `ghcr.io/martijnboot/borrelbeurs:${{ github.sha }}`. Concurrency becomes `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`, so a merge never cancels a push (`ci.yml:25-27` today). Action pinning stays by tag (out of scope) | SD6 "built once": the push job pushes the artifact, never a rebuild |
| PD11 | The deploy workflow | `.github/workflows/deploy.yml`, `workflow_dispatch` with input `sha` (validated as 40 lower-hex characters), `concurrency: deploy` (never cancelled), `permissions: contents: read, packages: read`. Steps: (1) `docker manifest inspect ghcr.io/martijnboot/borrelbeurs:<sha>`, which fails the run on a missing tag; (2) POST `${{ secrets.RENDER_DEPLOY_HOOK_URL }}&imgURL=<url-encoded image ref>`; (3) `python scripts/smoke.py ${{ vars.RENDER_URL }} --expect-sha <sha> --wait-seconds 600` with `BB_SMOKE_KEY: ${{ secrets.BB_SMOKE_KEY }}`. The workflow references only secrets the human creates (H1) | AC28. `curl` on a GitHub runner is not the subagent `curl` deny (memory note), but `smoke.py` uses urllib anyway |
| PD12 | `render.yaml`'s image tag | The web service is `runtime: image` with `image.url: ghcr.io/martijnboot/borrelbeurs:<sha>`. The builder cannot know the first deployed SHA, so T17 commits the literal tag `REPLACE_WITH_FIRST_DEPLOY_SHA`, and H1 replaces it with the first pushed SHA. The meta test accepts a 40-hex SHA or that one placeholder, never `latest`. `plan:` fields carry SD10's recommendation (web `starter`; Postgres paid `basic-256mb`), which H1 confirms before applying the Blueprint, since applying it costs money. **Confirm** | Render needs a tag. The cost decision stays the human's (SD10) |
| PD13 | How `smoke.py` re-saves the theme unchanged | There is no `GET /api/theme`. The current preset is in `/theme.css`'s `ETag`, `"theme-<rev>-<preset>"` (`app/api/theme.py:113`). Smoke parses it and sends `PUT /api/theme {"preset": <preset>}`. For `custom`, `{"preset":"custom"}` with no tokens re-sends the stored custom theme (`theme.py:133-138`). T10's test pins the ETag shape, so a change to it fails loudly. **Confirm**: the alternative is a new `GET /api/theme` route, which adds API surface, a matrix row and `schema.d.ts` churn the spec does not ask for | SD12's "re-saves the current theme unchanged" with no new route |
| PD14 | The venue stack's details | `deploy/venue/.env.example` holds: `BB_IMAGE_SHA`, `BB_HTTP_PORT=80`, `BB_DATA_DIR=C:/BorrelBeurs/data`, `BB_PUBLIC_URL=http://192.168.8.10/` (the router's reserved IP, which the human sets), `BB_BACKUP_INTERVAL_S=300` and `JWT_SECRET=` (empty; `start.cmd` fills it). Services: **`db`** (digest-pinned, no `ports:`, `restart: unless-stopped`); **`app`** (`pull_policy: never`, `restart: on-failure`, `depends_on: db healthy`, bind `${BB_DATA_DIR}/exports:/exports`); **`backup`** (the same Postgres image, `pull_policy: never`, `restart: unless-stopped`, runs `deploy/venue/backup.sh` mounted read-only, bind `${BB_DATA_DIR}/backups:/backups`). Every container name, the volume and the network are prefixed `borrelbeurs-venue-`. `restore.cmd` asks the operator to type `HERSTEL`. It then stops `app` and `backup`, and runs `restore.sh <file or newest>` inside `db`, which runs `dropdb`, `createdb` and `pg_restore`. Finally it starts the stack. **Confirm** (the confirmation word and the default IP) | AC19, AC22–AC24. `pull_policy: never` makes "without pulling" a property of the file, not a promise |
| PD15 | The v1-key meta test | `tests/meta/test_no_v1_key_import.py` scans `app/`, `db/` and `scripts/` for: the string `keys.json`; the identifier `ADMIN_TOKEN`; and any call that inserts an `AuthKey` or calls `hash_secret` outside `app/api/security.py: issue_key`. The AC32 login test uses v1-shaped keys (free strings of 1–256 characters, `legacy/v1/backend/auth.py:40-48`) | v1 keys have no format, so the test is "no path in", plus "a v1-shaped key is 401" |

---

## Files

| Path | Create/Modify | Purpose | Task |
|---|---|---|---|
| `app/core/config.py`, `.env.example` | Modify | `venue`; `build_sha`, `trusted_proxy_ips`, `export_dir` | T1 |
| `app/main.py` | Modify | Docs hidden for `venue`; explicit proxy args in `main()`; `build_sha` in the start log (T1) · `Cache-Control` on the SPA mount (T2) · `AppClock` wrap (T4) · standby middleware registration (T6) | T1, T2, T4, T6 |
| `app/api/health.py` | Modify | `build_sha` in `/healthz` (T1); `status: standby` (T6) | T1, T6 |
| `tests/unit/test_config.py`, `tests/unit/test_app_shell.py`, `tests/api/test_auth.py`, `tests/integration/test_health.py` | Modify | Venue, proxy, docs and health payload tests | T1 (T6 for health/app shell) |
| `tests/integration/test_proxy_keying.py` | Create | Real-process limiter keying (AC26) | T1 |
| `tests/api/test_static.py` | Modify | Cache headers (AC27) | T2 |
| `db/migrations/versions/0011_schema_compat.py` | Create | `schema_compat` | T3 |
| `db/migrations/compat.py` | Create | `set_min_code_revision(op, rev)` | T3 |
| `db/migrations/script.py.mako` | Modify | `min_code_revision = ...` line the author must fill | T3 |
| `app/db/models.py` | Modify | `SchemaCompat` | T3 |
| `app/db/schema_compat.py` | Create | Raw reads and `decide()` | T3 |
| `app/runtime/boot.py` | Modify | SD3 boot rule (T3); rehydrate offset (T5); standby split (T6) | T3, T5, T6 |
| `tests/integration/conftest.py` | Modify | `_truncate_all` skips `schema_compat` | T3 |
| `tests/integration/test_migrations.py`, `tests/integration/test_schema.py` | Modify | 0011 round trip, table set | T3 |
| `tests/integration/test_boot.py` | Modify | SD3 cases (T3); hard-coded `0009`/`0010` made head-relative (T3); standby in process (T6) | T3, T6 |
| `tests/integration/test_real_process.py` | Modify | `:191` revision literal (T3); second-instance test inverted to standby (T6) | T3, T6 |
| `tests/unit/test_schema_compat.py`, `tests/meta/test_schema_compat_coverage.py` | Create | `decide()` table; AC11 | T3 |
| `app/runtime/clock.py` | Modify | `AppClock`, `commit_stamp_ms` | T4 |
| `app/runtime/{orders,manipulation,drinks,config,close}.py`, `app/api/news.py` | Modify | Commit sites use `commit_stamp_ms` | T4 |
| `tests/unit/test_app_clock.py`, `tests/integration/test_stamp_monotonic.py` | Create | AppClock unit; AC16 property test | T4 |
| `app/runtime/ticker.py`, `app/runtime/gap.py` | Modify | Backward step → offset + zero-shift gap | T5 |
| `tests/integration/test_ticker.py`, `tests/integration/test_rehydrate.py`, `tests/unit/test_gap.py` | Modify | AC14, AC15, boot offset | T5 |
| `app/api/standby.py` | Create | ASGI gate: `/api/*` → 503 `standby` | T6 |
| `app/realtime/ws.py` | Modify | Standby → accept, close 1013 | T6 |
| `app/db/advisory_lock.py` | Modify | Module docstring ("fail fast" → standby) | T6 |
| `tests/api/test_standby.py` | Create | Gate, health, ws | T6 |
| `tests/integration/test_handover.py`, `tests/integration/realapp/harness.py` | Create / Modify | Two real processes (AC13); graceful-stop and order-stream helpers | T7 (harness also T14) |
| `app/hostdir.py` | Create | `write_atomic`, `prune` (PD5) | T8 |
| `app/jobs/naming.py` | Create | Slug and file names (PD7) | T8 |
| `app/jobs/export_xlsx.py` | Modify | Host copy; auto export timer (PD6) | T8 |
| `app/api/exports.py` | Modify | Import naming from `app/jobs/naming.py` | T8 |
| `tests/integration/test_export_hostdir.py`, `tests/unit/test_hostdir.py` | Create | AC21 export half | T8 |
| `tests/api/test_v1_keys.py`, `tests/meta/test_no_v1_key_import.py` | Create | AC32 | T9 |
| `scripts/smoke.py`, `tests/integration/test_smoke_script.py` | Create | SD12 | T10 |
| `docker/Dockerfile` | Modify | `ARG/ENV BUILD_SHA`; strip `pip`/`setuptools`/`wheel`/ensurepip and vendored `tests/`; pnpm pinned to CI's `9.15.9`; HEALTHCHECK comment corrected | T11 |
| `pyproject.toml`, `uv.lock` | Modify | `uvicorn` + `websockets`, `httptools`, `uvloop; sys_platform != 'win32'` instead of `[standard]` | T11 |
| `scripts/ci/check_image.py`, `tests/unit/test_check_image.py`, `tests/meta/test_dockerfile.py` | Create | AC1–AC3 | T11 |
| `scripts/ci/scan_image.sh`, `.trivyignore`, `tests/meta/test_trivyignore.py` | Create | AC4 | T12 |
| `tests/image/{__init__,conftest,test_boot_image}.py` | Create | AC6, AC7, AC9, AC10 against the image | T13 |
| `tests/image/test_kill_drill.py`, `tests/integration/test_db_restart.py` | Create | AC17, AC18 | T14 |
| `deploy/venue/{compose.yml,.env.example,backup.sh,restore.sh,LEESMIJ.md}`, `deploy/venue/{start,stop,status,backup-now,restore,logs}.cmd` | Create | The venue stack (SD11, SD13) | T15 |
| `tests/meta/test_venue_stack.py`, `tests/meta/test_no_latest.py` | Create | AC24 shape, AC5 | T15 |
| `scripts/make_bundle.sh`, `tests/image/test_venue.py`, `.gitignore` | Create / Modify | Bundle (SD11); venue drill; ignore `bundle/` | T16 |
| `render.yaml`, `.github/workflows/deploy.yml`, `tests/meta/test_render_blueprint.py` | Create | SD6–SD9, AC28 | T17 |
| `.github/workflows/ci.yml` | Modify | PD10 | T18 |
| `docs/runbooks/{deploy,rollback,restore,venue,incident,v1-fallback}.md`, `docs/runbooks/rehearsals/README.md` | Create | SD16, SD19 (`v1-fallback.md` is deleted by T22, A1) | T19 |
| `README.md`, `CLAUDE.md`, `docker-compose.yml` (header only), `docs/specs/defect-register.md`, `docs/plans/manual-checklist.md` | Modify | Commands, R4, Phase 8 evidence, checklist | T20 |
| `docs/adr/0003-*.md`, `docs/adr/0011-*.md`, `docs/adr/0001-*.md`, `docs/design/architecture.md` | Modify | Addenda; deploy topology (**hard stop**) | T21 |
| `docs/runbooks/rehearsals/<date>-*.md` | Create | Human-performed records | H1–H4 |

---

## Tasks

### T1 — Settings: the venue profile, build SHA, proxy trust, export directory

- **Implements:** AC6 (app half), AC25, AC26; SD1, SD7, SD9, SD14 (setting only)
- **Expected output:**
  - `AppEnv` adds `"venue"`. `_refuse_insecure_cookie_in_production` is unchanged, so `venue`
    accepts `SESSION_COOKIE_SECURE=false` and `production` still refuses it.
  - New settings:
    - `build_sha: str = "unknown"`;
    - `trusted_proxy_ips: str = ""`, a comma-separated list or `*`, validated as such;
    - `export_dir: Path | None = None`.

    All three go in `.env.example` with comments. Its `APP_ENV` comment lists four values.
    `tests/unit/test_config.py: ENV_VARS` covers every variable, including the two timeouts it
    misses today.
  - `main.py:138`: docs are mounted only for `local` and `ci`, an allowlist, so `venue` and
    `production` hide them.
  - `main()` passes `proxy_headers=bool(settings.trusted_proxy_ips)` and
    `forwarded_allow_ips=settings.trusted_proxy_ips or None`. With `proxy_headers=False`, uvicorn
    never reads `FORWARDED_ALLOW_IPS`.
  - `/healthz` gains `build_sha` in every branch. `"application started"` logs `build_sha`.
- **Verification:**
  - `uv run pytest tests/unit/test_config.py tests/unit/test_app_shell.py tests/api/test_auth.py tests/integration/test_health.py tests/integration/test_proxy_keying.py -v`:
    - **AC25:** `venue` with insecure cookie boots and `/docs` is 404; `production` with insecure
      cookie is `ConfigError`;
    - **AC26:** `test_app_shell`'s captured `Config` has the explicit proxy args in both cases;
    - **AC26:** `test_proxy_keying.py` spawns the app with the realapp harness:
      - with `TRUSTED_PROXY_IPS=*`, eleven logins from distinct `X-Forwarded-For` addresses are
        never 429;
      - with it empty **and** `FORWARDED_ALLOW_IPS=*` in the child's environment, the eleventh
        login is 429;
    - **AC6:** `/healthz` has `build_sha` equal to the env value; `test_health.py:168`'s exact dict
      is updated.
  - `./scripts/check.sh`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the validator's exact accepted forms for `trusted_proxy_ips` (IPs,
    CIDRs, `*`), and test layout.
  - **Must stop and ask if:** uvicorn 0.54 still reads `FORWARDED_ALLOW_IPS` with
    `proxy_headers=False`. That would mean AC26 needs a different mechanism.

### T2 — Cache-Control on the SPA

- **Implements:** AC27
- **Expected output:**
  - `SpaStaticFiles` (`main.py:99-115`) sets `Cache-Control: no-store` on `index.html`, both for
    `/` and for the SPA-route fallback.
  - Files under `/assets/` get `public, max-age=31536000, immutable`.
  - The `{asset_id:int}` upload route keeps its own header (`app/api/assets.py:27`).
  - Other root files are unchanged.
- **Verification:** `uv run pytest tests/api/test_static.py -v` asserts the header on `/`,
  `/login`, one `ROLE_ROUTES` path, and one `/assets/*.js` from the built `web/dist`. Then
  `./scripts/check.sh`.
- **Depends on:** T1 (`main.py`)
- **Autonomy note:**
  - **May decide alone:** whether to override `file_response` or `get_response`.
  - **Must stop and ask if:** a 304 path (ETag) drops the header and fixing it needs more than
    the subclass.

### T3 — `schema_compat` and the SD3 boot rule

- **Implements:** AC8, AC9 (in-process half), AC10, AC11; SD3; PD2
- **Expected output:**
  - Migration `0011_schema_compat` (revises `0010`, expand-only) creates and seeds the table.
    `downgrade()` drops it.
  - `SchemaCompat` model.
  - `app/db/schema_compat.py`: `read_db_state(conn)` and `decide(...)`.
  - `boot.py` replaces the bare `upgrade_to_head` call with: read → decide → migrate, log
    `schema_ahead`, or `BootFailure("schema ahead of image")`, all under the lock.
  - `db/migrations/compat.py: set_min_code_revision`.
  - `script.py.mako` emits `min_code_revision = ...  # "unchanged" or a revision id`. The
    `Ellipsis` fails the meta test until the author fills it.
  - `tests/meta/test_schema_compat_coverage.py`, by AST:
    - every migration after `0011` assigns `min_code_revision` to `"unchanged"` or to a revision
      at or before its own;
    - when that is an id, its `upgrade()` calls `set_min_code_revision`.
  - Existing tests fixed:
    - `_truncate_all` leaves `schema_compat`;
    - `test_schema.py`'s table set;
    - `test_real_process.py:191` and `test_boot.py:315,338` become head-relative, via
      `ScriptDirectory.get_current_head()` and its `down_revision`.
- **Verification:**
  - `uv run pytest tests/unit/test_schema_compat.py tests/meta/test_schema_compat_coverage.py tests/integration/test_migrations.py tests/integration/test_schema.py tests/integration/test_boot.py tests/integration/test_real_process.py -v`:
    - **AC8:** a database at `0010` boots, migrates to `0011` and becomes ready; a failing
      migration still exits non-zero with `/readyz` never 200 (existing test kept);
    - **AC9 / AC10:**
      - `alembic_version='ci_ahead_fixture'` with `min_code_revision='0011'` boots, logs
        `schema_ahead` and leaves `alembic_version` as it was;
      - with `min_code_revision` unknown, or the row missing, it refuses with `boot_failed` /
        `schema ahead of image`;
      - in the refusal case, row counts in every table are unchanged and no `price_tick` exists;
    - **AC11:** the meta test fails on a scratch copy holding a migration with no
      `min_code_revision` (`test_migration_scaffolding.py`'s copy-to-scratch pattern).
  - `./scripts/check.sh`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the fixture revision id, the `decide` return type, and whether to read
    `ScriptDirectory` once per boot.
  - **Must stop and ask if:** `compare_metadata` cannot be satisfied without
    `schema_compat` in `Base.metadata`, *and* keeping it there breaks unrelated fixtures beyond
    `_truncate_all`.
  - **Must stop and ask if:** `0011` needs anything but an additive change.

### T4 — The app clock: every commit stamps `max(app_now, last_commit)`

- **Implements:** AC16; SD15 (stamping half); PD4
- **Expected output:**
  - `AppClock` and `commit_stamp_ms` in `app/runtime/clock.py`.
  - `create_app` wraps the clock (`main.py:205`).
  - The nine call sites listed in PD4 use `commit_stamp_ms`, including `app/api/news.py:68`
    (amended after audit).
  - `place_order` records the stamp it used as the last commit (`orders.py:292`), unchanged in
    shape.
  - `tests/meta/test_clock_seam.py` stays green (`AppClock` imports nothing new).
- **Verification:**
  - `uv run pytest tests/unit/test_app_clock.py tests/integration/test_stamp_monotonic.py tests/integration/test_place_order.py tests/integration/test_manipulation.py tests/integration/test_drink_lifecycle.py tests/integration/test_config_live.py tests/integration/test_close_in_process.py -v`.
  - **AC16:** `test_stamp_monotonic.py` runs a seeded `random.Random` property loop. It does at
    least 30 seeds × 40 steps, each step one of: advance; `set_wall` back or forward by up to
    ±2 h; place an order; schedule a jump. Afterwards it asserts that `price_tick.wall_ts_ms` is
    non-decreasing by `version`, and that every `order.wall_ts_ms` ≥ the stamp of the commit
    before it. A failure prints its seed.
  - `./scripts/check.sh`, including the golden fixtures (`tests/engine`).
- **Depends on:** T2 (`main.py`)
- **Autonomy note:**
  - **May decide alone:** the seed and step counts, as long as they stay within about 20 s of
    test time.
  - **May decide alone:** whether `commit_stamp_ms` takes the view or the holder.
  - **Must stop and ask if:** any call site needs a stamp *other* than the max rule, for example
    a jump `t0` that must stay in the past.
  - **Must stop and ask if:** a golden fixture moves.
  - Engine-guardian review applies (the stamp feeds `advance`'s `now_ms`).

### T5 — Backward clock steps: offset, zero-shift gap, rehydrate

- **Implements:** AC14, AC15; SD15 (ticker and boot half); PD4
- **Expected output:**
  - `_iterate` (`ticker.py:162-182`) detects a step back beyond the budget against
    `view.last_commit_wall_ms`, and applies PD4's sequence. That means a new zero-shift gap step:
    `_gap_step`'s shape with `shift = 0`, one `gap` tick, and no `shift_active_events`.
  - `clock_stepped_back` is logged.
  - `gap_shift_ms` keeps returning `None` for a negative gap; the backward logic lives in the
    ticker.
  - `boot.py` calls `clock.raise_to(run.wall_ts_ms)` after `rehydrate` when the wall clock is
    behind it.
  - The `_tick_step` docstring (`ticker.py:204-205`) is corrected.
- **Verification:**
  - `uv run pytest tests/integration/test_ticker.py tests/integration/test_rehydrate.py tests/unit/test_gap.py tests/integration/test_boot.py -v`:
    - **AC14:** on FakeClock, `set_wall(+1 h)` mid-run gives exactly one `gap` tick and a
      re-anchor. Ticks then resume at the interval, and every drink's `p_cont` on the first tick
      after the gap equals its value on the last tick before it;
    - **AC15:** `set_wall(−1 h)` gives exactly one `gap` tick, stamps non-decreasing, and a new
      tick within 2 s of fake time whose stamp is 1 s after the previous one. Over the next 10
      ticks, at least one drink's `p_cont` changes, where today it would freeze;
    - **boot:** rehydrating with the wall clock 1 h behind the stored commit leaves
      `clock.offset_ms ≈ 1 h`, and the first tick stamps after the stored commit.
  - `./scripts/check.sh`.
- **Depends on:** T3 (`boot.py`), T4
- **Autonomy note:**
  - **May decide alone:** how the ticker reaches `raise_to`. It can type the ticker's clock as
    `AppClock` (tests wrap their `FakeClock`) or pass a narrow protocol.
  - **Must stop and ask if:** the zero-shift gap needs an `exchange/` change, or AC15's
    "prices do not freeze" needs Brownian or idle parameters other than the seeded run's.
  - Engine-guardian review applies.

### T6 — Standby instead of exit when the lock is held

- **Implements:** AC12, AC8 (regression on both paths), AC29 (server half); SD4, SD5; PD1
- **Expected output:**
  - `start_runtime` is split into `_boot(...)`, the synchronous fast path, and the standby task,
    per PD1.
  - `BOOT_FAILED_EXIT = 3`; `exit_process(code=LOCK_LOST_EXIT)`.
  - `app/api/standby.py`: a pure ASGI middleware. While `app.state.standby` is set, any `http`
    scope under `/api` gets 503 with the error envelope and code `standby` (via
    `app/core/errors.py`).
  - `/ws` accepts and then closes with 1013 while in standby, checked before
    `require_ws_role`.
  - `/healthz` in standby returns 200
    `{"status":"standby","build_sha":…,"last_tick_age_ms":null,"last_commit_age_ms":null}`.
    `/readyz` returns 503 `not_ready`, unchanged.
  - The module docstring of `advisory_lock.py` is updated.
- **Verification:**
  - `uv run pytest tests/api/test_standby.py tests/integration/test_boot.py tests/integration/test_real_process.py tests/integration/test_health.py tests/api/test_authorization_matrix.py tests/api/test_draining.py -v`:
    - **AC12, in process:** a test holds the lock on its own connection, then boots. It asserts:
      - no migration ran: `alembic_version` stays at a stamped older revision;
      - no tick and no write;
      - `/healthz` 200 `standby`, `/readyz` 503;
      - `GET /api/state` and `POST /api/orders` 503 `standby`;
      - `/ws` closed with 1013;
      - `lock_wait` logged on entry and again after 30 s of fake time.

      The test then releases the lock, and the instance migrates, rehydrates and becomes ready.
    - **AC12, real process:** `test_a_second_instance_exits_fast…` becomes
      `test_a_second_instance_waits_in_standby`. It asserts that the process is alive after 5 s,
      `/healthz` reports `standby`, and the first instance's ticks continue alone.
    - **AC8:** a migration failure *after* standby exits 3 with `/readyz` never 200.
  - `./scripts/check.sh`.
- **Depends on:** T1 (`health.py`), T2 (`main.py`), T5 (`boot.py`)
- **Autonomy note:**
  - **May decide alone:** the task and helper structure inside `boot.py`, and where the
    middleware is registered.
  - **Must stop and ask if:** standby needs the WebSocket protocol to change (a new frame or
    code beyond 1013).
  - **Must stop and ask if:** an existing test's contract (not its revision literal) has to
    change other than the second-instance test.
  - **Must stop and ask if:** the source change exceeds about 400 lines (memory note: tests
    excluded).

### T7 — Handover between two real processes

- **Implements:** AC13, AC29 (test half)
- **Expected output:**
  - `tests/integration/test_handover.py`, with the harness helpers it needs:
    - a graceful stop (`POST /api/admin/shutdown`, or the process's own SIGTERM where the OS
      supports it);
    - the order stream from `test_real_process.py:63-85`, moved into the harness, with its old
      call site updated.
  - Two cases:
    - **(a) graceful.** A is live and B is in standby. Orders stream to A. A is stopped
      gracefully. B takes the lock within 2 s of A's exit and becomes ready. Orders that A
      refused during the switch are retried against B with the same `Idempotency-Key`.
    - **(b) death.** The same, but A is killed.
  - Both assert, across the handover:
    - `price_tick` versions are contiguous (`list(range(n))`);
    - there are no duplicate `wall_ts_ms` among `tick`-source rows;
    - every acknowledged `order_id` is stored;
    - only one process ever wrote ticks at a time (no interleaving of the two processes' tick
      versions).
- **Verification:** `uv run pytest tests/integration/test_handover.py tests/integration/test_real_process.py -v`,
  then `./scripts/check.sh`.
- **Depends on:** T6
- **Autonomy note:**
  - **May decide alone:** the graceful-stop mechanism on Windows.
  - **May decide alone:** how to attribute ticks to a process, for example by log lines or by
    timing windows.
  - **Must stop and ask if:** the 2 s takeover is not met, and the cause is the standby retry
    cadence or Postgres releasing the lock late after a kill. Report the timings; do not loosen
    the bound.

### T8 — Exports on the host, and the 15-minute auto export

- **Implements:** AC21 (export half); SD14; PD5, PD6, PD7
- **Expected output:**
  - `app/hostdir.py`, as in PD5.
  - `app/jobs/naming.py`, with the slug rule moved out of `app/api/exports.py`. The download
    name is unchanged and its tests are untouched.
  - `build_next` writes a finished export's bytes to `export_dir` after `finish` commits, as
    `…-<kind>.xlsx`. A write failure logs `export_host_write_failed` and leaves the row `done`.
  - `run_worker` runs PD6's timer.
  - Host retention as in PD7.
  - Without `export_dir`, behaviour is identical to today, and no auto export is ever built.
- **Verification:**
  - `uv run pytest tests/unit/test_hostdir.py tests/integration/test_export_hostdir.py tests/integration/test_export_worker.py tests/integration/test_export_queue.py tests/api/test_exports.py tests/meta/test_no_file_io.py -v`.
  - The tests use FakeClock and `tmp_path`:
    - a manual and a final export each appear on the host with the right name;
    - with a live run, 15 fake minutes produce one `auto` file and no new `export` row;
    - with a `queued` row at the due time, the auto export is skipped and the queued row is built;
    - nine auto exports leave eight;
    - a partial write, simulated by failing between write and rename, leaves no final-named file;
    - no live run means no auto export;
    - `export_dir` unset means no file at all.
  - `./scripts/check.sh`.
- **Depends on:** T1 (`export_dir`)
- **Autonomy note:**
  - **May decide alone:** the timer mechanics, and whether `hostdir` uses `pathlib` or `os`.
  - **Must stop and ask if:** the auto build cannot share `BuildProcess` without changing its
    failure semantics (Phase 7 review), or PD6's skip rule needs a schema change.

### T9 — v1 keys grant nothing in v2

- **Implements:** AC32 (test half); D-42; PD15
- **Expected output:** `tests/api/test_v1_keys.py` and `tests/meta/test_no_v1_key_import.py`.
  There is no production change: v2 already rejects these keys (`security.py:77-86`). This task
  pins that behaviour.
- **Verification:**
  - `uv run pytest tests/api/test_v1_keys.py tests/meta/test_no_v1_key_import.py -v`.
  - Six v1-shaped keys each give 401 with no verify and no lookup:
    - `TestTest`;
    - a UUID;
    - `bar-key-2024`;
    - a 64-hex string;
    - `bb_admin_secret`, which is wrongly prefixed;
    - a 256-character string.
  - The meta test fails on a scratch file containing `keys.json`.
- **Depends on:** —
- **Autonomy note:**
  - **May decide alone:** the key list, and the scan's exact patterns.
  - **Must stop and ask if:** a v1-shaped key under 257 characters gets anything but 401.

### T10 — The smoke test

- **Implements:** SD12; AC6, AC9, AC28 (the tool they use)
- **Expected output:** `scripts/smoke.py <base_url> [--expect-sha SHA] [--wait-seconds N]`,
  stdlib only.
  - It reads the key from `BB_SMOKE_KEY`, or from stdin when that is unset.
  - Steps:
    1. `/healthz` returns 200. When `--expect-sha` is given, `build_sha` must equal it; it polls
       until `--wait-seconds` runs out.
    2. `/readyz` returns 200.
    3. Login, with the same-origin `Origin`.
    4. `/api/auth/me`, which must be the admin role.
    5. `GET /api/runs/current`; 200 or 404 `no_current_run` both pass.
    6. The theme re-save per PD13.
    7. Logout.
  - It prints one line per step and exits 0 or 1.
  - It never prints the key.
- **Verification:**
  - `uv run pytest tests/integration/test_smoke_script.py -v`, using the realapp harness and a
    minted admin key:
    - with the right SHA, exit 0, and the theme revision goes up by one with the preset
      unchanged;
    - with a wrong SHA and `--wait-seconds 1`, exit 1;
    - with a bar key, exit 1 at the `me` step;
    - the stdout and stderr of every case never contain the key.
  - `./scripts/check.sh`.
- **Depends on:** T1 (`build_sha`)
- **Autonomy note:**
  - **May decide alone:** argument names beyond the three above, and the output format.
  - **Must stop and ask if:** the theme re-save visibly changes a screen, for example because
    custom images are dropped.

### T11 — The image: trimmed, labelled, checked for contents and size

- **Implements:** AC1, AC2, AC3; D-43; SD7 (image half); PD9
- **Expected output:**
  - Dockerfile:
    - `ARG BUILD_SHA=unknown` and `ENV BUILD_SHA=$BUILD_SHA` in the runtime stage;
    - after `uv sync`, removes uv, then `pip`, `setuptools`, `wheel`, `ensurepip/_bundled` and
      `site-packages/*/tests`;
    - pnpm pinned to `9.15.9`;
    - the HEALTHCHECK comment made true: `/healthz` is 503 when stale.
  - `pyproject.toml` replaces `uvicorn[standard]` with `uvicorn`, `websockets`, `httptools` and
    `uvloop; sys_platform != 'win32'`, all already in the lock. `uv.lock` is regenerated.
  - `scripts/ci/check_image.py <image> --max-mb 300`:
    - prints the uncompressed size from `docker image inspect`, and every forbidden path;
    - exits 1 on any forbidden path or on a size over the limit;
    - keeps the pure matcher separate, so it can be unit-tested.
  - `tests/meta/test_dockerfile.py` (AC1):
    - every `FROM` is `@sha256:`;
    - there are at least two stages;
    - the final `USER` is numeric and non-zero;
    - `ARG BUILD_SHA` is present.
- **Verification:**
  - `uv run pytest tests/unit/test_check_image.py tests/meta/test_dockerfile.py -v`.
  - `docker build -f docker/Dockerfile --build-arg BUILD_SHA=$(git rev-parse HEAD) -t borrelbeurs:local .`
    then `uv run python scripts/ci/check_image.py borrelbeurs:local --max-mb 300`. Paste the
    size line; it goes into the Phase 8 evidence (T20).
  - `docker run --rm borrelbeurs:local python -c "import uvicorn, websockets, httptools, uvloop"`.
  - `./scripts/check.sh`.
- **Depends on:** T1
- **Autonomy note:**
  - **May decide alone:** the removal commands.
  - **Must stop and ask if:** the image exceeds 300 MB after trimming.
  - **Must stop and ask if:** any runtime import needs a removed package.
  - **Must stop and ask if:** `uv lock` changes any version other than dropping `watchfiles`,
    `python-dotenv` and `pyyaml`.
  - Removing packages is not a new dependency.

### T12 — Trivy scan, SBOM, `.trivyignore`

- **Implements:** AC4; SD20, SD21
- **Expected output:**
  - `scripts/ci/scan_image.sh <image> <sbom-out>` runs `aquasec/trivy@sha256:<digest>`, with the
    digest pinned in the script, against the local image through the docker socket. It runs it
    twice:
    - `image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 --ignorefile .trivyignore`;
    - `image --format cyclonedx --output <sbom-out>`.
  - `.trivyignore` starts empty, apart from a header comment that states the format: each entry
    is `<ID> exp:<yyyy-mm-dd>` preceded by a `# reason:` line.
  - `tests/meta/test_trivyignore.py` fails on an entry without both.
- **Verification:**
  - `uv run pytest tests/meta/test_trivyignore.py -v`, with fixtures for a good entry, a missing
    reason and a missing expiry.
  - `bash scripts/ci/scan_image.sh borrelbeurs:local sbom.cdx.json` exits 0, and `sbom.cdx.json`
    parses as JSON with `bomFormat == "CycloneDX"`.
- **Depends on:** T11
- **Autonomy note:**
  - **May decide alone:** the Trivy digest (the current release) and the cache mount.
  - **Must stop and ask if:** the scan finds a fixable CRITICAL or HIGH that a base-digest bump
    cannot clear. Waiving one is a human decision, with a reason and an expiry.

### T13 — Image boot drill: SHA, assets, both schema directions

- **Implements:** AC6, AC7, AC9, AC10 (image level); PD3, PD8
- **Expected output:**
  - `tests/image/conftest.py`:
    - `--image`, skipping when absent;
    - a network, Postgres and app container fixture, all with unique names, torn down even on
      failure;
    - helpers that seed keys and runs through `docker run <image> python -m app.cli.…`.
  - `test_boot_image.py`:
    - **AC6:** the smoke test passes with `--expect-sha` equal to the image's
      `BUILD_SHA` label/env, and the container log has `build_sha`;
    - **AC7:** `docker cp` of `/app/web/dist` to `tmp_path`, then `scripts/check_built_assets.py`
      exits 0;
    - **AC9 first half:** `head-1`, then boot, then migrated, then smoke;
    - **AC9 second half:** the stamped-ahead database gives `schema_ahead`, then smoke;
    - **AC10:** incompatible, so a non-zero exit, `boot_failed` / `schema ahead of image`, and
      `alembic_version` unchanged;
    - an optional `--previous-image` case.
- **Verification:**
  - `uv run pytest tests/image/test_boot_image.py --image borrelbeurs:local -v` passes.
  - `uv run pytest tests/image -v` with no `--image` reports every test as skipped.
  - `./scripts/check.sh` (lint and types cover `tests/image`).
- **Depends on:** T3, T10, T11
- **Autonomy note:**
  - **May decide alone:** the fixture structure and the timeouts.
  - **Must never** stop, remove or reuse the dev stack's containers, volume or port, nor another
    project's (memory: the port-5432 conflict). Use no host port for Postgres and a random host
    port for the app.
  - **Must stop and ask if:** Docker is not available to the builder.

### T14 — Kill drill and Postgres restart

- **Implements:** AC17, AC18
- **Expected output:**
  - `tests/image/test_kill_drill.py`:
    - **AC17:** a live run, and an order stream on a thread that records acknowledged
      `order_id`s. Mid-stream, `docker kill -s KILL` the app **and** Postgres. Start Postgres,
      then the app (`--restart on-failure` is set on the app container), and wait for `/readyz`.
      Assert:
      - every acknowledged order is stored;
      - `price_tick` versions are contiguous;
      - the rehydrated `/api/state` prices equal the last pre-kill tick's (the gap rule moves
        anchors, not prices);
      - ticking resumes.
    - **AC18:** kill Postgres alone and start it again. The app, running under
      `--restart on-failure`, exits 70, restarts and is ready within 60 s with no command issued.
      No acknowledged order is lost.
  - `tests/integration/test_db_restart.py` covers **AC18** in `check.sh`. It runs the app through
    `tests/support/proxy.py`'s `BlackholeProxy`:
    - the proxy goes dark, and the app exits 70;
    - a harness supervisor loop restarts the app on a non-zero exit, as `restart: on-failure`
      would, with exponential backoff capped at 5 s;
    - the proxy is restored, and the app is ready within 60 s;
    - orders acknowledged before the outage are present.
- **Verification:**
  - `uv run pytest tests/image/test_kill_drill.py --image borrelbeurs:local -v`.
  - `uv run pytest tests/integration/test_db_restart.py -v`.
  - `./scripts/check.sh`.
- **Depends on:** T7 (harness helpers), T13 (`tests/image/conftest.py`)
- **Autonomy note:**
  - **May decide alone:** the stream rate and the kill timing.
  - **Must stop and ask if:** the app needs an in-process reconnect to meet the 60 s in AC18,
    which would be a behaviour change beyond the spec.
  - **Must stop and ask if:** a kill loses an acknowledged order. That is a durability defect:
    report it with evidence.

### T15 — The venue stack

- **Implements:** AC19 (stack half), AC21 (backup half), AC22 (restore script), AC23, AC24, AC5 (meta); SD11, SD13, SD16 (`LEESMIJ.md`); PD14
- **Expected output:**
  - **`deploy/venue/compose.yml`**, per SD11 and PD14:
    - `name: borrelbeurs-venue`;
    - the app uses `image: ghcr.io/martijnboot/borrelbeurs:${BB_IMAGE_SHA:?}` with no `build:`;
    - `APP_ENV=venue`, `SESSION_COOKIE_SECURE=false`, `EXPORT_DIR=/exports`;
    - `TRUSTED_PROXY_IPS` unset.
  - **`backup.sh`**:
    - it loops every `BB_BACKUP_INTERVAL_S`, or runs once with `once`;
    - it writes `pg_dump -Fc` to `.borrelbeurs-<stamp>.dump.partial`, then `mv`s it to the final
      name;
    - it keeps 288 dumps;
    - it logs a failure and continues.
  - **`restore.sh`**, per PD14.
  - **A failed restore never starts the app** (amended after audit). If `restore.sh` exits
    non-zero (`dropdb`, `createdb` or `pg_restore` failing, or no dump found), `restore.cmd`:
    - prints in Dutch that the restore failed and that the app was left stopped;
    - leaves `app` and `backup` stopped, and does not run `up`;
    - exits non-zero.

    `LEESMIJ.md` and `restore.md` (T19) say what to do next: retry with the previous dump.
  - **Six `.cmd` files** that call `docker compose -f "%~dp0compose.yml" --env-file "%~dp0.env"`:
    - `start.cmd` loads `images.tar` when `docker image inspect` fails;
    - on first run, `start.cmd` writes `JWT_SECRET` into `.env` with PowerShell's RNG (the v1
      `run.bat:49-53` pattern);
    - `start.cmd` creates `%BB_DATA_DIR%\{backups,exports}`, runs `up -d`, polls `/readyz` for up
      to 120 s, and prints `BB_PUBLIC_URL`.
  - **`LEESMIJ.md`**: a one-page card in Dutch, per SD16.
  - **`tests/meta/test_venue_stack.py`**, line-based like `test_compose_matches_env_example.py`.
    It checks:
    - the `name`;
    - that there is no `build:`;
    - that `db` has no `ports:`;
    - the restart policies;
    - `pull_policy: never`;
    - the `borrelbeurs-venue-` prefixes;
    - that the Postgres digest equals the dev compose's and `ci.yml:39`'s;
    - that each `.cmd` exists and references `compose.yml`.
  - **`tests/meta/test_no_latest.py` (AC5)**:
    - it scans `.github/workflows/`, `render.yaml` (when present), `deploy/`, `docker/` and
      `scripts/` for an image reference with tag `latest`, or one with no tag;
    - it ignores `ubuntu-latest` runner labels;
    - it excludes `legacy/`.
- **Verification:**
  - `uv run pytest tests/meta/test_venue_stack.py tests/meta/test_no_latest.py -v`.
  - `docker compose -f deploy/venue/compose.yml --env-file deploy/venue/.env.example config`
    exits 0, with `BB_IMAGE_SHA` set in the shell.
  - `./scripts/check.sh`.
  - The `.cmd` files themselves are exercised by the human in H2. T16 runs the stack and scripts
    on Linux.
- **Depends on:** T1 (`venue`)
- **Autonomy note:**
  - **May decide alone:** the `.cmd` wording and structure.
  - **May decide alone:** the Dutch phrasing of `LEESMIJ.md`, keeping SD16's seven topics.
  - **Must stop and ask if:** Docker Desktop's Windows bind mounts need a `user:` override for
    uid 1001 to write `/exports` (R7).

### T16 — The bundle and the venue drill

- **Implements:** AC20, AC19 (no-pull half), AC21 (dump half, and the independence of the two
  paths), AC22, AC23, AC24
- **Expected output:**
  - **`scripts/make_bundle.sh <sha> [--local <image-ref>]`** writes `bundle/borrelbeurs-<sha>/`,
    which is gitignored. The bundle holds:
    - `images.tar` (`docker save` of the app image and the pinned Postgres, both `linux/amd64`;
      it uses `docker pull --platform linux/amd64`, or retags `--local` as the GHCR name);
    - `compose.yml`, `.env.example` (with `BB_IMAGE_SHA` filled in), `backup.sh`, `restore.sh`;
    - the six `.cmd` files and `LEESMIJ.md`;
    - `SHA256SUMS`.
  - **`tests/image/test_venue.py`**, driven by `--image`. It makes a bundle with `--local`, and
    on CI only (`CI=true`) removes both images and `docker load`s `images.tar`. It runs the
    bundle's compose with `BB_DATA_DIR=tmp_path`, `BB_HTTP_PORT=<random>` and
    `BB_BACKUP_INTERVAL_S=5`. It asserts:
    - **AC20 / AC19:** the stack comes up with `--pull never`, and the image digests equal the
      saved ones;
    - **AC24:** `docker compose port db 5432` fails, and every name carries the prefix;
    - **AC21:**
      - dumps accrue every interval;
      - with `app` stopped, dumps continue;
      - with `backup` stopped, a manual export still lands in `exports/`;
      - no `*.partial` file has a final name;
    - **AC22:** the newest dump is restored into a fresh volume (`down -v`, `restore.sh`), the
      stack starts, and the order count equals the count at dump time;
    - **AC22, failure (amended after audit):** `restore.sh` on a truncated dump exits non-zero,
      and the drill's restore sequence (the same as `restore.cmd`'s) leaves `app` not running;
    - **AC23:**
      - `POST /api/admin/shutdown` (exit 0) leaves `app` exited and not restarting after 20 s;
      - `pg_terminate_backend` on the lock connection (exit 70) gets `app` restarted and ready
        again.
- **Verification:**
  - `uv run pytest tests/image/test_venue.py --image borrelbeurs:local -v`.
  - `bash scripts/make_bundle.sh $(git rev-parse HEAD) --local borrelbeurs:local` produces a
    bundle whose `sha256sum -c SHA256SUMS` passes.
  - `./scripts/check.sh`.
- **Depends on:** T8 (host exports), T13 (fixtures), T14 (shared `tests/image/conftest.py`), T15
- **Autonomy note:**
  - **Locally:** never `docker rmi` an image a running container uses. The dev `borrelbeurs-db`
    shares the Postgres digest. The rmi and load steps run only under `CI=true`.
  - **May decide alone:** the bundle directory layout inside the spec's list.
  - **Must stop and ask if:** `docker save` of a multi-platform pull cannot be pinned to
    `linux/amd64` on the builder's machine.

### T17 — `render.yaml` and the deploy workflow

- **Implements:** AC28 (workflow), AC5 (no `:latest`); SD6, SD8, SD9, SD10 (recorded); PD11, PD12
- **Expected output:**
  - **`render.yaml`**:
    - the web service `borrelbeurs-web` is `runtime: image`, in region `frankfurt`, with
      `numInstances: 1` and `healthCheckPath: /healthz`;
    - its `envVars` are:
      - `DATABASE_URL` (`sync: false`);
      - `JWT_SECRET` (`generateValue: true`);
      - `APP_ENV=production`;
      - `TRUSTED_PROXY_IPS=*`;
      - `LOG_LEVEL=INFO`;
    - there is no `EXPORT_DIR`;
    - the database is `borrelbeurs-db`, Postgres 16, region `frankfurt`;
    - plans follow PD12.
  - **`.github/workflows/deploy.yml`**, per PD11.
  - **`tests/meta/test_render_blueprint.py`**, line-based, checks those fields, the image tag rule
    (PD12), and that `deploy.yml` has the SHA validation, the manifest check and the smoke step.
- **Verification:**
  - `uv run pytest tests/meta/test_render_blueprint.py tests/meta/test_no_latest.py -v`.
  - `./scripts/check.sh`.
  - Running the workflow is H1's step; the builder never triggers it.
- **Depends on:** T10 (`smoke.py`'s interface), T15 (`test_no_latest.py` exists)
- **Autonomy note:**
  - **Hard stop:** creating Render services, GHCR settings or secrets, and triggering the
    workflow. The builder writes files only.
  - **May decide alone:** step names and the YAML layout.

### T18 — CI: the image gate, the drills, push on `main`

- **Implements:** AC2, AC3, AC4, AC5, AC7, AC9, AC17 (each in CI); SD6; PD10
- **Expected output:** `ci.yml` per PD10.
  - The SBOM is uploaded as an artifact (`actions/upload-artifact`).
  - The `image` job prints the size line (AC3).
  - The image jobs install `uv` (as the `check` job does) to run `tests/image`.
  - The existing `docker` job is replaced; nothing else in `check` and `secret-scan` changes.
- **Verification:**
  - Each script is run locally against `borrelbeurs:local`, with its output pasted: the T11–T16
    commands in sequence.
  - The YAML parses: `uv run python -c "import json,sys; …"` is not available for YAML, so the
    check is `docker run --rm -v "$PWD":/repo rhysd/actionlint@sha256:<digest> -color`. That
    tool runs as a container and is not added to the repo (R11). If the human declines it, the
    PR's own CI run is the check.
  - **The PR's CI run is the evidence for this task.** Pushing the branch is the human's step
    (memory: the user runs outward-facing commands).
- **Depends on:** T11, T12, T13, T14, T16
- **Autonomy note:**
  - **May decide alone:** job names, artifact retention, and step order inside PD10.
  - **Must stop and ask if:** GHCR push needs anything beyond `GITHUB_TOKEN` with
    `packages: write`. Package visibility and settings are H1's.

### T19 — Runbooks and the rehearsal template

- **Implements:** SD16, SD19; AC30, AC31 (procedures the human follows); SD17 (`v1-fallback.md`)
- **Expected output:** six runbooks in English, each with prerequisites, numbered steps, the
  exact commands, how to verify, and what to do when a step fails.
  - **`deploy.md`**: the workflow, the smoke key, the first deploy, and Render's internal URL with
    its scheme changed (SD8).
  - **`rollback.md`**: "run the previous SHA" on Render and at the venue; ≤ 5 min. It states
    the SD3 floor plainly (amended after audit): once a database is at `0011` or later, no image
    older than the one that introduced `0011` can boot against it, and there is no
    downgrade-and-roll-back path. The fallback for anything older is v1 (`v1-fallback.md`).
  - **`restore.md`**: venue dump restore, including what to do when it fails (T15: the app stays
    stopped; retry with the previous dump), and moving data between Render and the venue with
    `pg_dump`/`pg_restore` (SD10).
  - **`venue.md`**: laptop preparation (Docker Desktop, the bundle from USB, power plan, lid
    settings), the router's DHCP reservation and no uplink, the QR code, during the event, and
    afterwards (copy `data/` to USB).
  - **`incident.md`**: stale `/healthz`, standby that never takes over, `schema ahead of image`,
    a full disk, and where the logs are.
  - **`v1-fallback.md`**:
    - the v1 fallback folder that H5 produces, and its checksum check;
    - the exact steps (amended after audit): stop v2's `app` (`stop.cmd`; Postgres and backup may
      keep running), then double-click the folder's own `run.bat`. It `docker load`s
      `bierbeurs-image.tar` when present and publishes port 8000
      (`legacy/v1/run.bat:9,31-33,57`). Then point the phones at `http://<fixed-ip>:8000/`;
    - the keys are the folder's `config/keys.json`, generated on the laptop in H5, never
      committed and never copied from `borrelbeurs-v1`;
    - that live prices are lost, and where revenue so far lives;
    - ≤ 5 min.
  - **`rehearsals/README.md`**: the SD19 template.
- **Verification:** `./scripts/check.sh` (repo hygiene). Every command named in a runbook exists
  in the repo or is a documented docker or compose command; the builder lists them in the report.
- **Depends on:** T15, T16, T17, T18
- **Autonomy note:**
  - **May decide alone:** structure and wording.
  - **Must stop and ask if:** a runbook needs a step the code does not support. That is a gap in
    an earlier task, not something to describe around.

### T20 — Repo documents: README, CLAUDE.md, compose header, register, checklist

- **Implements:** spec "In scope: Documents" (except ADRs and design); AC3 (measured size recorded)
- **Expected output:**
  - **README**: the stale Phase 0 banner fixed; a short "Deploy and venue" section linking the
    runbooks; `scripts/` in the layout.
  - **CLAUDE.md commands**: `scripts/make_bundle.sh`, `scripts/smoke.py`, `pytest tests/image
    --image …`, and the deploy workflow (one line each).
  - **`docker-compose.yml` header**: R4 resolved, pointing to `deploy/venue/compose.yml`, the
    header comment only.
  - **Defect register**:
    - D-42 and D-43 rows get their Phase 8 status. Section E's table gets a `Phase` column,
      matching the other sections;
    - a `### Phase 8 evidence` table: D-42 → T9, H4; D-43 → T11, T18, with T11's measured size.
  - **`manual-checklist.md`'s Phase 8 section**: the task list, H1–H5, and the `AC17` → `AC32`
    reference fixed.
- **Verification:** `./scripts/check.sh`.
- **Depends on:** T11 (size), T16, T17, T18, T19 (links)
- **Autonomy note:**
  - **May decide alone:** wording.
  - **Must stop and ask if:** the register's section E format change conflicts with how earlier
    phases cite it.

### T21 — ADR addenda, SDR and architecture (hard stop)

- **Implements:** spec "In scope: Documents" (ADRs, SDR, `architecture.md`); SD4 and SD15's ADR
  conflict
- **Expected output:**
  - **`## Addendum (Phase 8, SD4, SD15)` to ADR 0003**, in the existing addendum style with a date
    line:
    - decision 4 now reads "waits in standby", and single-writer holds because a standby never
      writes;
    - the app clock;
    - a backward step beyond the budget is an offset plus a zero-shift gap.
  - **ADR 0011 addendum**: SD3's `schema_compat` and the rollback floor; the overlap paragraph
    (`:71-74`) superseded by standby.
  - **SDR**:
    - §3 "Deploys" becomes manual workflow dispatch;
    - the venue profile and the travel router;
    - §8's tier note points at SD10.
  - **`architecture.md`**: a "Deploy topology" section covering Render, the venue stack, the
    image flow (CI → GHCR → Render and the bundle), and standby.
- **Verification:** `./scripts/check.sh`, and the human's approval before commit.
- **Depends on:** T3, T5, T6, T17
- **Autonomy note:**
  - **Hard stop: the builder must stop for approval before committing.** Product ADR text
    (0001, 0003) and `docs/design/` are hard stops (ADR 0009, ADR 0010).
  - **May decide alone:** wording inside each addendum.

### T22 — Remove the v1 fallback from the runbooks (amendment A1)

- **Implements:** the spec's Amendment A1 ("Changes this amendment requires"); SD16 (as amended)
- **Expected output:**
  - `docs/runbooks/v1-fallback.md` deleted;
  - `rollback.md`: the two v1 sentences (the floor paragraph and "When it fails") replaced by the
    consequence A1 states: no older image has served a real database, and past a later floor the
    way out is a newer image or a restore (`restore.md`);
  - `venue.md` step 7 removed (and the steps renumbered if any follow);
  - `deploy/venue/LEESMIJ.md`, "Niets werkt en de bar moet door": the administrator decides on a
    rollback or a restore, no v1 (Dutch, one line);
  - `docs/runbooks/rehearsals/README.md`: "rollback v1 fallback" becomes "rollback";
  - `README.md` line 57: the v1 fallback link dropped;
  - ADR 0011 line 98: the v1 sentence dropped, in the text the human approves;
  - `docs/design/architecture.md:267-268` ("Rollback and fallback": "Below it, v1 runs from its
    own saved image beside the bundle"): the v1 sentence replaced by A1's consequence. Found at
    the A1 re-audit; A1's change table omits it. `docs/design/` is a hard stop, so the human
    approves this text too.
- **Verification:** `./scripts/check.sh`, and
  `grep -rniE "v1[- ]fallback|fallback (is|for).*v1|v1 runs from|saved image" docs deploy README.md`
  finds only the spec's amendment, this plan, `phase-8-human-steps.md`, and history (ADR 0007,
  the rehearsal records). The human's approval of the ADR and design text before commit.
- **Depends on:** nothing built after T19; T19 and T20 are already merged.
- **Autonomy note:**
  - **Hard stop: the builder must stop for approval before committing**, because ADR text and
    `docs/design/` are hard stops (ADR 0009, ADR 0010).
  - **May decide alone:** wording elsewhere. **Must stop and ask if** a runbook step cannot be
    reworded without a code change.

### H1–H4 — moved (amendment A1)

The human tasks are in [phase-8-human-steps.md](phase-8-human-steps.md), written to be walked
through by an agent (`/human 8`). H5 (the v1 fallback folder) and H3's v1 half are withdrawn with
SD17. Their ids, dependencies and the acceptance criteria they carry are unchanged: H1 (AC28 run,
AC29), H2 (AC30 and the real-world halves of AC19-AC22), H3 (AC31, rollback only), H4 (AC32,
human half).

---

## Acceptance criteria → tasks

| AC | Tasks | AC | Tasks | AC | Tasks |
|---|---|---|---|---|---|
| AC1 | T11 | AC12 | T6 | AC23 | T15, T16 |
| AC2 | T11, T18 | AC13 | T7 | AC24 | T15, T16 |
| AC3 | T11, T18, T20 | AC14 | T5 | AC25 | T1 |
| AC4 | T12, T18 | AC15 | T5 | AC26 | T1 |
| AC5 | T15, T17, T18 | AC16 | T4 | AC27 | T2 |
| AC6 | T1, T10, T13 | AC17 | T14, T18 | AC28 | T10, T17, H1 |
| AC7 | T13, T18 | AC18 | T14 | AC29 | T6, T7, H1 |
| AC8 | T3, T6 | AC19 | T15, T16, H2 | AC30 | T19, H2 |
| AC9 | T3, T13, T18 | AC20 | T16, H2 | AC31 | T19, H3, T22 |
| AC10 | T3, T13 | AC21 | T8, T15, T16, H2 | AC32 | T9, H4 |
| AC11 | T3 | AC22 | T15, T16, H2 | | |

Every task names at least one AC or SD. T20 and T21 implement the spec's "In scope: Documents"
(T20 also records AC3's figure).

---

## Task graph

```
Server spine:   T1 ─ T2 ─ T4 ─ T5 ─ T6 ─ T7 ─ T14 ─ T16 ─ T18 ─ T19 ─ T20
                          T3 ──┘    (T3 also feeds T13, T21)
Beside it:      T1 ─ T8 ─────────────────────────────┘ (into T16)
                T1 ─ T10 ─ T13 (also T3, T11) ─ T14
                T1 ─ T11 ─ T12 ─────────────────────────── (into T18)
                T1 ─ T15 ─ T16;  T10, T15 ─ T17 ─ T19, T21
                T9 (alone) ─ H4
Documents:      T3, T5, T6, T17 ─ T21
Documents:      T19, T20 ─ T22   (amendment A1)
Human:          T17, T18, T19 ─ H1;  T16, T18, T19 ─ H2;  H1, H2 ─ H3;  T9, T19 ─ H4   (phase-8-human-steps.md)
```

Edges, exactly:
`T2←T1` · `T4←T2` · `T5←T3,T4` · `T6←T1,T2,T5` · `T7←T6` · `T8←T1` · `T10←T1` · `T11←T1` ·
`T12←T11` · `T13←T3,T10,T11` · `T14←T7,T13` · `T15←T1` · `T16←T8,T13,T14,T15` ·
`T17←T10,T15` · `T18←T11,T12,T13,T14,T16` · `T19←T15,T16,T17,T18` · `T20←T11,T16,T17,T18,T19` ·
`T21←T3,T5,T6,T17` · `H1←T17,T18,T19` · `H2←T16,T18,T19` · `H3←H1,H2` · `H4←T9,T19` · `T22←T19,T20`.
`T1`, `T3` and `T9` depend on nothing.

**The server chain T1 → T2 → T4 → T5 → T6 → T7 is forced, not cautious.** `main.py` is written
by T1, T2, T4 and T6; `boot.py` by T3, T5 and T6; `health.py` by T1 and T6;
`test_boot.py`/`test_real_process.py` by T3 and T6. Standby comes after the clock work so that
its refactor of `boot.py` lands once, on top of the SD3 and offset edits. Builders run one at a
time anyway (ADR 0010 §1), so the groups give the merge order.

Shared files, ordered by dependency:
- `app/main.py`: T1 → T2 → T4 → T6.
- `app/runtime/boot.py`: T3 → T5 → T6.
- `app/api/health.py`, `tests/integration/test_health.py`, `tests/unit/test_app_shell.py`: T1 → T6.
- `tests/integration/test_boot.py`, `tests/integration/test_real_process.py`: T3 → T6 (→ T7 for
  `test_real_process.py`'s stream helper).
- `tests/integration/realapp/harness.py`: T7 → T14.
- `tests/image/conftest.py`: T13 → T14 → T16.
- `tests/meta/test_no_latest.py`: T15 creates it, and T17 only runs it.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T3, T9 | T1: `core/config.py`, `.env.example`, `main.py`, `api/health.py`, `test_config.py`, `test_app_shell.py`, `test_auth.py`, `test_health.py`, `test_proxy_keying.py` · T3: `0011`, `migrations/compat.py`, `script.py.mako`, `db/models.py`, `db/schema_compat.py`, `runtime/boot.py`, `integration/conftest.py`, `test_migrations.py`, `test_schema.py`, `test_boot.py`, `test_real_process.py`, `test_schema_compat*.py` · T9: `test_v1_keys.py`, `test_no_v1_key_import.py` |
| 2 | T2, T8, T10, T11, T15 | T2: `main.py`, `test_static.py` · T8: `app/hostdir.py`, `jobs/{naming,export_xlsx}.py`, `api/exports.py`, export tests · T10: `scripts/smoke.py`, `test_smoke_script.py` · T11: `docker/Dockerfile`, `pyproject.toml`, `uv.lock`, `scripts/ci/check_image.py`, `test_check_image.py`, `test_dockerfile.py` · T15: `deploy/venue/**`, `test_venue_stack.py`, `test_no_latest.py` |
| 3 | T4, T12, T13, T17 | T4: `runtime/clock.py`, `main.py`, `runtime/{orders,manipulation,drinks,config,close}.py`, `test_app_clock.py`, `test_stamp_monotonic.py` · T12: `scripts/ci/scan_image.sh`, `.trivyignore`, `test_trivyignore.py` · T13: `tests/image/{__init__,conftest,test_boot_image}.py` · T17: `render.yaml`, `.github/workflows/deploy.yml`, `test_render_blueprint.py` |
| 4 | T5 | `runtime/{ticker,gap}.py`, `runtime/boot.py`, `test_ticker.py`, `test_rehydrate.py`, `test_gap.py`, `test_boot.py` |
| 5 | T6 | `runtime/boot.py`, `main.py`, `api/{health,standby}.py`, `realtime/ws.py`, `db/advisory_lock.py`, `test_standby.py`, `test_boot.py`, `test_real_process.py`, `test_health.py`, `test_app_shell.py` |
| 6 | T7, T21 | T7: `test_handover.py`, `realapp/harness.py`, `test_real_process.py` · T21: ADR 0001, 0003, 0011, `architecture.md` |
| 7 | T14 | `tests/image/{conftest,test_kill_drill}.py`, `test_db_restart.py`, `realapp/harness.py` (if needed), `tests/support/proxy.py` (if needed) |
| 8 | T16 | `scripts/make_bundle.sh`, `tests/image/{conftest,test_venue}.py`, `.gitignore` |
| 9 | T18 | `.github/workflows/ci.yml` |
| 10 | T19 | `docs/runbooks/**` |
| 11 | T20 | `README.md`, `CLAUDE.md`, `docker-compose.yml` (header), `defect-register.md`, `manual-checklist.md` |
| 12 | T22 | `docs/runbooks/**`, `deploy/venue/LEESMIJ.md`, `README.md`, ADR 0011 |
| Human | H1 (after T19); H2 after T16, T18, T19; H3 after H1, H2; H4 after T9 and T19 | `docs/runbooks/rehearsals/*.md` |

No two tasks in one group write the same file. In group 1, only T1 writes `main.py`, and only T3
writes `boot.py` and the boot and process tests. In group 2, only T2 writes `main.py`; T15
creates `test_no_latest.py` and nobody else in the group touches it. In group 3, only T4 writes
`main.py`. In group 6, T21 touches only documents.

**Phase exit (Gate D):**
- `./scripts/check.sh` green on `main`, with the output pasted.
- The CI run on `main` that pushed the image: the `image`, `image-drill`, `venue` and `push` jobs
  green. Paste the size line, the Trivy summary and the drill output.
- T11's measured size, recorded in the register (T20).
- H1–H4's rehearsal records, which together meet the spec's exit condition: the same digest on
  Render and the venue laptop, rollback within 5 min, and a mock borrel offline.

---

## Data changes

One migration, `0011_schema_compat.py` (T3). It is forward-only and expand-only. Nothing in
0001–0010 is edited.

| Change | Columns / constraint | Backfill | Expand/contract |
|---|---|---|---|
| `schema_compat` | `id smallint PRIMARY KEY CHECK (id = 1)`, `min_code_revision text NOT NULL` | One row, `(1, '0011')` | New table; an older image never reads it |

`downgrade()` drops it. The round-trip test runs on an empty database. From `0012` on, every
migration declares `min_code_revision` (PD2, AC11).

**No new Python or npm dependency (SD20).** T11 replaces `uvicorn[standard]` with three of its
own extras' packages. All three are already in `uv.lock`, so the change *removes* `watchfiles`,
`python-dotenv` and `pyyaml` from the runtime.

**Container tools used in CI only, not added to the repo:**

| | Trivy (T12, T18) | actionlint (T18, optional, R11) |
|---|---|---|
| What | Image vulnerability scan and CycloneDX SBOM | Lints GitHub workflow files |
| How | `aquasec/trivy@sha256:…` via `docker run`, digest-pinned in the script | `rhysd/actionlint@sha256:…` via `docker run`, a local check only |
| Why not stdlib | A CVE database and matcher | A workflow schema checker |
| Licence | Apache-2.0 | MIT |
| Maintenance | Aqua Security; active, frequent releases | One primary maintainer; active |
| Approval | Named in the approved spec (SD20) and in Phase 0 D12. The PR restates licence and maintenance | **Not in the spec. Ask before using it.** Without it, the PR's CI run is the YAML check |

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **The spec is uncommitted**: `docs/specs/phase-8-deploy-cutover.md` is modified on `docs/phase-8-plan` | Commit it with this plan, so the audit and the builders read the approved text |
| R2 | **PD5 bends the spec's wording**: the host write is not "from `app/jobs/`", which the spec said kept `test_no_file_io.py` green; that is impossible as written | Marked Confirm. The intent, the worker in `app/jobs` and the meta test green, is kept |
| R3 | **AC9's "previous image" has no real subject** until a second SD3 image exists in GHCR | PD3's stamped-ahead database proves the boot rule. `--previous-image` is wired but unused in CI until then. H3's Render rollback is the real-world proof |
| R4 | **The standby refactor of `boot.py`** is the riskiest server change: lifecycle, cancellation and two exit paths | T6 keeps the fast path byte-for-byte in behaviour, so all existing boot tests apply unchanged. It stops at about 400 source lines. The R4-of-Phase-7 WebSocket flake (memory) may show in `/ws` tests: report it, do not retry to green |
| R5 | **Render's real overlap behaviour is unknown.** If Render stops the old instance before starting the new one, standby is exercised only by T7 | H1 records it, as the spec's Verification says |
| R6 | **A stale ticker makes `/healthz` 503**, and Render may then restart the instance | Restart then rehydrates, which is the right response to a ticker that cannot commit. `incident.md` explains it. The spec chose `/healthz` (SD5) |
| R7 | **Windows bind mounts and uid 1001**: Docker Desktop usually maps Windows paths writable for any uid, but this is unverified for `/exports` | T15 stops and asks if a `user:` override is needed. H2 checks that auto exports appear |
| R8 | **`restart: on-failure` after a hard power-off**: whether Docker Desktop restarts an `on-failure` container on daemon start is not verified | `LEESMIJ.md` and `venue.md` say "run `start.cmd` after any power loss". H2 includes the hard power-off |
| R9 | **The image may exceed 300 MB, or Trivy may find a fixable HIGH** in the base digest | T11 and T12 stop and ask. A base-digest bump is the first remedy; a waiver is the human's |
| R10 | **The image drills on Windows builders** need Docker Desktop with Linux containers, beside the user's running dev stack and other projects (memory: the port-5432 conflict) | No Postgres host port, random app ports, unique names, and no `rmi` outside CI (T13, T16). If Docker is unavailable, the builder stops |
| R11 | **The workflow YAML cannot be verified locally** without a new tool | actionlint as a container is optional, needs the human's yes, and is listed under Data changes. Otherwise the PR's CI run is the check, and pushing is the human's step |
| R12 | **`uv run uvicorn app.main:app --reload`** (CLAUDE.md, development) bypasses `main()`, so uvicorn's CLI defaults read `FORWARDED_ALLOW_IPS` there | Development only. The image runs `python -m app.main`. T20 notes it beside the command. Changing the dev command is out of scope |
| R13 | **The smoke test's theme re-save** goes through PD13's `ETag` parsing | T10's test pins the shape. A new `GET /api/theme` is the fallback if the human prefers it |
| R14 | **A long-running AC16 property test** in `check.sh` | T4 bounds it to about 20 s and prints the seed on failure |
| R15 | **The auto export may share a slug across runs** with the same name (PD7) | Accepted: it affects only which 8 auto files are kept. Final and manual copies are never pruned |
| R16 | **Size**: T6, T15 and T16 may approach 400 source lines | The standard stop-and-ask at about 400 source lines, tests excluded (memory note) |
| R17 | **Windows hazards**: CRLF from text-mode Python edits, the `localhost` DSN crawling, and `check.sh` piped through `tail` | Use the Edit tool; `.env.local` uses `127.0.0.1`; never pipe `check.sh` (memory notes). The `.cmd` files must be CRLF; `.gitattributes` handling is checked in T15 |
| R18 | **The `/healthz` exact-payload test** (`test_health.py:168`) and the hard-coded revisions (`test_boot.py:315,338`, `test_real_process.py:191`) | Each is fixed in the task that changes it (T1, T3) |

---

## Out of scope for this plan

Everything in the spec's "Out of scope", and also:
- pinning GitHub Actions by commit SHA (they stay pinned by tag);
- a `GET /api/theme` route (PD13);
- in-process database reconnection: recovery is "exit and be restarted" (T14);
- a persisted clock offset (PD4 recomputes it at boot);
- a `user:` override for the venue app, unless T15 proves it necessary (R7);
- changing the development `uvicorn --reload` command (R12);
- any change to `exchange/`, the golden fixtures, or what an order charges.

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
- [x] PD1, PD3, PD5, PD6, PD7, PD9, PD12, PD13, PD14 confirmed or overruled — all **confirmed**
- [x] actionlint (R11) approved or declined — **approved** (local container check only, T18)

**Findings raised at the audit.** Resolved by the amendment below:
- ~~The v1 fallback tar has no producing task.~~ **H5** added; `v1-fallback.md` (T19) names the
  steps.
- ~~`restore.cmd`'s failure path is unspecified.~~ T15 defines it (the app stays stopped); T16
  tests it; `restore.md` (T19) covers it.
- ~~PD4 misses `app/api/news.py:68`.~~ Added to PD4, T4 and the Files table.
- ~~The rollback floor is unstated.~~ `rollback.md` (T19) states it.

Accepted as-is (the human chose "accept all lines"):
- **Over the size limit on files:** T3 (~13), T6 (~11–12), T15 (~16); T1 and T4 borderline. Not
  split; the ~400 source-line stop-and-ask still applies.
- **Weakly checkable outputs:** T19, T20, T21 (`check.sh` and review only); T18 (the PR's CI run);
  T17's deploy-hook `imgURL` form (text-checked only); the `.cmd` scripts (exercised only in H2).
- **T11 makes `websockets`, `httptools`, `uvloop` direct dependencies**: already locked, named in
  the spec's scope; the PR still states their licence and maintenance.
- **AC9's older-image half** is proven by a stamped-ahead database, not an older binary (PD3),
  until a second SD3 image exists in GHCR (R3).
- R1 is stale: the spec was committed (`40c2c89`) before the audit.

Audited by: MartijnBoot (human, Gate B)  Date: 2026-10-10

Amended after audit (2026-10-10): H5 added; T4, T15, T16, T19, H2, H3 and the graph edited to
close the findings above. Re-audit of those sections: MartijnBoot (human), 2026-10-10 — approved

**Amendment A1 (2026-10-11): no v1 fallback.** H5 and H3's v1 half withdrawn; the human tasks
moved to `phase-8-human-steps.md`; T22 added to remove the fallback from the built runbooks
(T19, T20 stay merged). Spec: Amendment A1.

Re-audit of A1 (2026-10-11): all ten checklist lines accepted by the human ("accept all
lines"). Findings folded into T22 and this file: `docs/design/architecture.md:267-268` still
described the v1 fallback and was in neither A1's table nor T22 (added, hard stop); T22's grep
widened to catch it; stale status lines at the top of this plan corrected. The spec's A1 change
table is left as written; T22 is the authority for the architecture.md edit. Accepted as-is:
T22 has no AC of its own (its criterion is A1's change table), and T19's text keeps describing
`v1-fallback.md` as history.

Audited by: MartijnBoot (human, Gate B, A1 re-audit)  Date: 2026-10-11

---

## Amendment A2 (2026-10-11): the smoke test accepts a weak ETag — T23

**Found by H1 step 6** (defect D-H1-1, [phase-8-human-steps.md](phase-8-human-steps.md)).
On Render, Cloudflare sits in front of the app and rewrites `ETag: "theme-0-blauw"` to
`etag: W/"theme-0-blauw"`: weak, and with a lowercase name. PD13 and T10 assumed the strong form
reaches the client; T10's test runs against the app directly, so it could not see this. The
deploy itself worked (`/healthz` named the SHA), but `smoke.py` failed at step 6 and the
workflow ended red, so AC28's "smoke passes" is not yet met on Render. **The app is right; the
smoke check is too strict.** Nothing in the spec changes.

### T23 — The smoke test reads the ETag as a proxy delivers it

- **Implements:** SD12, AC28 (as T10 did); PD13 refined, not replaced.
- **Expected output:** in `scripts/smoke.py`:
  - a function that takes the response headers and returns `(revision, preset)`: it finds
    `ETag` without regard to the case of the name, strips a leading `W/`, then applies the
    existing `"theme-<rev>-<preset>"` match; it raises `SmokeFailed` otherwise;
  - the failure message names the ETag value it actually received (`theme.css: 200, ETag
    'W/"..."'`), not only the `ETag`-cased lookup, which printed `None` here.
- **Verification (failing test first):**
  - `tests/unit/test_smoke_etag.py`: strong `"theme-3-blauw"` → `(3, "blauw")`; weak
    `W/"theme-3-blauw"` → the same; header name `etag` and `ETag` and `ETAG` all work; a missing
    header, `"theme-x-blauw"`, and `"other"` raise `SmokeFailed`, and the message contains the
    received value;
  - `uv run pytest tests/integration/test_smoke_script.py -v` still passes (strong form);
  - `./scripts/check.sh`.
- **Not in T23 (follow-up, recorded):** `app/api/theme.py:115` compares `if-none-match` exactly,
  so behind Cloudflare the app never answers 304. Harmless (the CSS is resent); leave as it is.
- **Depends on:** T10 (merged).
- **Autonomy note:**
  - **May decide alone:** the function's name and whether it sits above `main`.
  - **Must stop and ask if:** the fix seems to need a change under `app/` (it must not), or a
    new dependency.
- **After it merges (human, H1 step 6 again):** CI pushes n+2, which contains the fixed
  `smoke.py`. The deploy workflow checks out the SHA it deploys, so only **n+2** can pass; run
  **deploy** with n+2 and expect seven passing steps. **n+2 is then the image for H1's mid-run
  deploy (step 8), and n+1 the previous image for H3.** The first deployed image stays n.
- **Graph:** `T23←T10` · `H1←T23` (step 6 onward).

Re-audit A2: _pending, the human's call._
