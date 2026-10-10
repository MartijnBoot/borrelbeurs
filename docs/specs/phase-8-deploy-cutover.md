# Spec: Phase 8 — Deploy and cutover

Status: Approved (rewritten at the spec interview, 2026-10-10; replaces the earlier approved
draft, which predates Phases 3–7) · Depends on: Phase 7 · Fixes: D-42, D-43

## Problem

v2 must run in two places that fail in different ways. On Render, the platform restarts
instances and overlaps them on deploy. On a laptop at a venue with no internet, there is no
platform, and recovery has to be something a tired treasurer can do. Today v2 is a development
stack: an image CI builds and throws away, and a compose file that says it is not a deployment
artefact.

**What v2 has today.**

- **The image is close but unproven.** It is multi-stage, digest-pinned and runs as non-root
  (`docker/Dockerfile:16,31,57-58`). CI builds it as `borrelbeurs:<sha>` and never runs, scans,
  measures or pushes it (`.github/workflows/ci.yml:126-133`).
  - `pip` stays in the runtime image; only `uv` is removed (`docker/Dockerfile:44-46`).
  - `uvicorn[standard]` pulls `watchfiles`, `python-dotenv` and `pyyaml` into it
    (`uv.lock:811-819`).
  - Nothing checks the built image for tarballs, `.git` or secrets (D-43). No v2 size has been
    recorded; v1's was 406 MB after the hotfix (ADR 0007:39). The old spec's note about
    `fastapi-cli`, `rich` and `typer` no longer applies: v2 is on fastapi 0.141 without them
    (`uv.lock:274-283`).
- **Rolling back to the previous image fails at boot.** Every boot runs `alembic upgrade head`
  (`app/runtime/boot.py:83-87,143-148`). An image whose scripts lack the database's current
  revision raises "Can't locate revision" and boot fails. That contradicts the expand-only
  promise Phase 7 made for exactly this case (SD13; `db/migrations/versions/0010_phase_7_lifecycle.py:19-20`).
- **A Render deploy cannot complete while the app runs.** A second instance that cannot take
  the advisory lock raises `BootFailure` (`app/runtime/boot.py:138-141`). uvicorn then exits
  with code 3 before opening a socket. On a zero-downtime deploy, Render starts the new
  instance while the old one still holds the lock (ADR 0003:31-33), so the new instance can
  never become healthy. ADR 0011:71-73 assumes the opposite: that the new instance migrates
  while the old one drains.
- **Phones cannot log in on the offline laptop.** The session cookie is `Secure` by default
  (`app/core/config.py:98`). The compose `app` does not override it
  (`docker-compose.yml:77-88`), and phones reach the laptop over plain `http://`. Phase 3 SD8
  handed this to Phase 8.
- **Every login on Render shares one rate-limit bucket.** The limiter keys on
  `request.client.host` (`app/api/auth.py:58`). uvicorn is started without proxy settings
  (`app/main.py:253-263`), so it trusts forwarded headers only from localhost, and every client
  arrives as Render's proxy. That gives 10 logins a minute for the whole borrel (Phase 3 SD7).
  - uvicorn also reads `FORWARDED_ALLOW_IPS` from the environment itself, a second reader of the
    environment that CLAUDE.md forbids.
- **Render's database URL is refused.** Render supplies `postgresql://…`; the validator demands
  `postgresql+asyncpg://` (`app/core/config.py:143-148`). There is no `render.yaml`.
- **The compose stack is not a venue stack.**
  - The app service builds from source (`docker-compose.yml:70-72`), and building needs the
    network.
  - There is no `name:`, so the volume and image names follow the checkout directory. On a
    differently named checkout the database is empty.
  - `JWT_SECRET` defaults to empty (`:85`), and `setup.sh` writes `.env.local`, which compose
    does not read.
  - `restart: unless-stopped` (`:91`) restarts the app after "Sluit app" exits 0
    (`app/api/admin.py:35-39`).
  - Postgres is published on host port 5432 (`:46`), which collides with any other local
    Postgres.
- **No backups and no host-side copy of an export.** No `pg_dump` exists anywhere. The xlsx
  export is a `bytea` row in the same Postgres (`app/jobs/export_xlsx.py:267-307`), so it is not
  independent of the database until someone downloads it (ADR 0004:30-33).
- **A clock stepped back beyond the budget freezes prices.** The ticker re-anchors, but
  `gap_shift_ms` returns `None` for a negative gap (`app/runtime/gap.py:31-34`), so no gap is
  written (`app/runtime/ticker.py:259`). Ticks are then held at the last commit's stamp
  (`:216`). One hour back means about one hour of frozen prices. ADR 0003 says a step back
  beyond the budget "is a gap and re-anchors".
- **Orders stamp the raw wall clock.** `place_order` uses `clock.wall_ms()`
  (`app/runtime/orders.py:208`) and records it as the last commit (`:292`). After a backward
  step an order can stamp earlier than the tick before it, so `price_tick.wall_ts_ms` can go
  backwards. That contradicts ADR 0003's "stamps never go back".
- **Durability is proven only against a process kill.** A SIGKILL of the app at five points
  loses no acknowledged order (`tests/integration/test_real_process.py:88-175`). Nothing kills
  Postgres or both containers.
- **The +1 h clock step is untested.** The re-anchor is tested at +10 min, asserting stamps but
  not prices (`tests/integration/test_ticker.py:258-272`).
- **Caching is undefined.** `index.html` and the hashed assets are served without
  `Cache-Control` (deferred here by the Phase 4 plan:791). After a deploy or rollback, a cached
  `index.html` can point at assets that no longer exist.
- **v1's keys are still valid wherever v1 runs** (D-42). They remain in the `borrelbeurs-v1`
  history (ADR 0007:42-43; `docs/plans/rebuild-progress.md:1113`). v2 never imported them
  (Phase 2 SD3) and its key format `bb_<id>_<secret>` cannot parse one
  (`app/api/security.py:77-86`).
- **Nothing exists yet for:** `render.yaml`, an image registry, a scan, an SBOM, a smoke test,
  the offline bundle, runbooks (`docs/runbooks/` does not exist) or a rehearsal record.

## Decisions

**Settled at the spec interview (2026-10-10).** The human chose SD1–SD3. For everything after,
the human delegated: "apply all recommendations". Those are marked *(delegated)*; overrule any
of them at approval.

**The venue**

- **SD1 — An offline profile over plain HTTP: `APP_ENV=venue`.**
  - `venue` is a new `APP_ENV` value. It allows `SESSION_COOKIE_SECURE=false`, and hides
    `/docs`, `/redoc` and `/openapi.json` as `production` does. `production` still refuses
    `SESSION_COOKIE_SECURE=false` (Phase 3 SD8 unchanged).
  - Accepted risk: anyone on the venue router's wifi can read a session cookie off the air. The
    audience is closed, the wifi has a password (SD2), and sessions last 24 h.
  - No TLS at the venue (out of scope).
- **SD2 — A dedicated travel router with no uplink.**
  - The laptop has a fixed IP by DHCP reservation, so the URL is the same at every event and
    can be printed as a QR code. The venue's own wifi is never used.
  - "No network" in the acceptance criteria means **no uplink**. The router's LAN is required.
  - The venue app listens on host port 80, so the URL has no port (`http://<fixed-ip>/`). The
    port can be changed in the bundle's `.env`.
- **SD3 — An older image boots against a newer schema when that is declared safe.**
  - A migration adds a singleton `schema_compat(min_code_revision)` row. From then on, every
    migration sets it to the oldest revision whose *code* still runs correctly against the
    schema that migration leaves.
    - An expand-only migration leaves it unchanged.
    - A contract migration sets it to itself.
  - At boot, under the lock:
    - **Database revision known to the image's scripts:** `upgrade head` as today.
    - **Database revision unknown, and `min_code_revision` known to the image's scripts:** the
      image's head is at or after it, since history is linear. Skip migrating, log
      `schema_ahead` with both revisions at WARNING, and serve.
    - **Database revision unknown, and `min_code_revision` unknown or missing:** refuse to boot
      with `BootFailure("schema ahead of image")`.
  - Rollback is therefore "run the previous SHA", on Render and at the venue, with no data
    loss.
  - Rolling back to an image older than the one that introduces SD3 is unsupported. The first
    SD3 image is the rollback floor.
  - A meta test fails if a migration after SD3's own does not set `min_code_revision`, or
    states it explicitly unchanged.
  - Conflicts with nothing. It is the mechanism ADR 0011's expand/contract consequence
    (ADR 0011:71-74) assumed without having.

**Render**

- **SD4 — Standby instead of exit when the lock is held.** *(delegated)*
  - A booting instance that cannot take the advisory lock does not exit. It enters
    **standby**:
    - It retries `pg_try_advisory_lock` every 1 s and runs no migration, no rehydrate and no
      ticker.
    - `/healthz` returns 200 `{"status": "standby"}`; `/readyz` returns 503.
    - Every `/api` route returns 503 `standby`, and `/ws` closes with 1013.
    - It logs `lock_wait` at WARNING on entry and every 30 s.
  - When it takes the lock, it continues with ADR 0011's order: migrate (or SD3), rehydrate,
    ticker, ready.
  - This lets a Render deploy work. The new instance passes the health check on `/healthz` and
    Render sends SIGTERM to the old one. The old one drains and releases the lock (Phase 3
    SD10), and the new one takes over. The cost is a few seconds in which the API answers 503;
    the bar retries with the same `Idempotency-Key` (Phase 3 SD20).
  - **ADR conflict:** this changes ADR 0003 decision 4 ("fails fast and loudly if it cannot
    acquire it"). Single-writer still holds, because a standby never writes, but the decision
    text changes. **An ADR 0003 addendum is required and the human must accept it at
    approval.**
  - ADR 0011's overlap paragraph is also superseded: the old instance never runs against a
    schema the new one migrated. Expand-only is still required, for SD3.
  - `app.cli.runs go-live` keeps refusing while the lock is held. Standby is the app's
    behaviour only.
- **SD5 — Render health check path is `/healthz`.** *(delegated)*
  - Not `/readyz`: a standby fails `/readyz` by design, so a `/readyz` health check would
    deadlock every deploy against the old instance.
  - Known risk: Render can route traffic to an instance whose migration then fails. Mitigation:
    CI boots the image against the previous release's schema before pushing (AC9), and SD3
    makes rolling back from that cheap.
- **SD6 — One image, built once, pushed to GHCR by full git SHA; deploy is a manual step.**
  *(delegated)*
  - CI's `docker` job builds, checks (AC1–AC9) and, on `main` only, pushes
    `ghcr.io/<owner>/borrelbeurs:<full-sha>`. `latest` is never pushed or referenced.
  - Render runs that image as an image-backed service. It does not build from the repo.
  - A `workflow_dispatch` "deploy" workflow takes a SHA and refuses one that is not in GHCR. It
    triggers Render's deploy hook with that image, waits for `/healthz` to report the SHA
    (SD7), then runs the smoke test (SD12).
  - Merging is not deploying. This matches ADR 0009 ("`main` is not deployed automatically"),
    and a merge mid-borrel must not redeploy a live event. **SDR §3 ("Deploys: on merge to
    main") is amended.**
  - The offline bundle `docker pull`s that same SHA, so the exit condition's "same image" is
    literally the same digest.
- **SD7 — The image carries its SHA.** *(delegated)*
  - A build argument sets `BUILD_SHA`, which `app/core/config.py` reads (default `unknown`).
  - `/healthz` reports it as `build_sha`, and boot logs it.
- **SD8 — Render's `DATABASE_URL` is a manual secret, in the validator's existing shape.**
  *(delegated)*
  - In `render.yaml`, `DATABASE_URL` is `sync: false`. The deploy runbook says to paste Render's
    *internal* URL with the scheme changed to `postgresql+asyncpg://`.
  - The validator is unchanged. CLAUDE.md's "one DSN shape" holds, and no rewrite logic is
    added.
  - `JWT_SECRET` is `generateValue: true`. `APP_ENV=production`.
  - Database: `borrelbeurs-db`, Postgres 16, Frankfurt. Web: `borrelbeurs-web`, one instance
    (SDR §2, §5).
- **SD9 — Proxy trust is a setting, passed to uvicorn explicitly.** *(delegated)*
  - New setting `TRUSTED_PROXY_IPS`, default empty, read in `app/core/config.py` only. When
    set, `app/main.py` passes `proxy_headers=True, forwarded_allow_ips=<it>`. When empty, it
    passes `proxy_headers=False`, so uvicorn never consults its own environment variable.
  - Render sets `*`. The venue leaves it empty, since phones connect directly.
  - Accepted risk: with `*`, a client can put its own `X-Forwarded-For` in front and choose its
    rate-limit bucket. The limiter guards a 256-bit random secret, so brute force is not the
    threat it slows down.
- **SD10 — Hosting tiers are the human's cost decision.** *(delegated: recommendation
  recorded)*
  - Free Render Postgres expires after 90 days (SDR §8), and a free web service sleeps when
    idle, which stops the ticker.
  - Recommendation: paid Postgres and a paid Starter instance before any **live borrel on
    Render**. Creating the services is a human step.
  - **Each deployment is its own database.** Real events run on the venue laptop (SD2). Render
    and the laptop are not synchronised. Moving data between them is a dump and restore, which
    the restore runbook describes.

**The bundle and the venue stack**

- **SD11 — A separate venue compose file; the dev compose stays a dev tool.** *(delegated)*
  This resolves Phase 0 R4.
  - **`deploy/venue/compose.yml`:**
    - Fixed `name: borrelbeurs-venue`.
    - `app` uses `image: ghcr.io/<owner>/borrelbeurs:${BB_IMAGE_SHA}` and has no `build:`.
    - `APP_ENV=venue`, `SESSION_COOKIE_SECURE=false`, `EXPORT_DIR=/exports`.
    - `JWT_SECRET` comes from the bundle's `.env`.
    - Ports: `"${BB_HTTP_PORT:-80}:8000"`.
    - `restart: on-failure`, so "Sluit app" (exit 0) stays stopped, while a lost lock (exit 70)
      and a failed boot are retried.
    - `db` publishes **no** host port, and `backup` is added (SD13).
    - Container names, the volume and the network are all prefixed `borrelbeurs-venue`, so the
      venue stack never collides with the dev stack or another local Postgres.
  - **The bundle**, made by `scripts/make_bundle.sh <sha>` on a networked machine, is a folder
    to copy to the laptop or a USB stick:
    - `images.tar`: `docker save` of the app at `<sha>` and Postgres, both for `linux/amd64`.
    - `compose.yml` and `.env.example`.
    - Double-clickable `.cmd` scripts: `start`, `stop`, `status`, `backup-now`, `restore`,
      `logs`.
    - `LEESMIJ.md`, the treasurer's card (SD16).
    - `SHA256SUMS`.
  - `start` loads `images.tar` only when the image is absent. On first run it generates
    `JWT_SECRET` into `.env`. It then runs `compose up -d`, waits for `/readyz` and prints the
    URL.
  - Data lives in the named volume and in `C:\BorrelBeurs\data\{backups,exports}`, outside the
    bundle folder, so installing a newer bundle keeps the data.
  - **Target laptop (assumption):** Windows 11, x86_64, Docker Desktop on WSL2, installed and
    tested at home with internet before the event. Scripts for macOS and Linux are out of
    scope.
- **SD12 — Smoke test: `scripts/smoke.py`, stdlib only (urllib), against a base URL.**
  *(delegated)*
  - It checks `/healthz` (200 with the expected `build_sha` when one is given) and `/readyz`.
  - It logs in with an admin key read from stdin or `BB_SMOKE_KEY`, outside `app/`.
  - It reads `/api/auth/me` and `GET /api/runs/current`.
  - Its write re-saves the current theme unchanged with `PUT /api/theme` and the same-origin
    `Origin` header. That is idempotent, safe mid-borrel, and goes through CSRF, a transaction
    and a broadcast. It then logs out.
  - Exit 0 or 1, one line per step.
  - CI runs it against the image (AC9). The deploy workflow runs it against Render with a
    dedicated admin key labelled `smoke`, created once by the human and stored as a GitHub
    secret. The venue runbook runs it against the laptop.

**Backups and exports at the venue**

- **SD13 — `pg_dump` every 5 minutes, into a bind mount, by a sidecar on the same Postgres
  image.** *(delegated)*
  - The `backup` service reuses the pinned Postgres image, so the bundle still holds exactly two
    images (AC11).
  - Every 5 minutes it runs `pg_dump -Fc` to `/backups/borrelbeurs-<UTC yyyymmddThhmmssZ>.dump`.
    It writes a temporary name and renames it, so a partial dump never carries a final name.
  - It keeps the newest 288 dumps (24 h). A failed dump is logged and the loop continues.
  - It does not depend on the app: it runs with the app stopped.
  - `backup-now.cmd` triggers one dump immediately.
  - On Render, backups are the managed database's own. No sidecar runs there.
- **SD14 — Every export also lands on the host, plus an automatic one every 15 minutes.**
  *(delegated)*
  - When `EXPORT_DIR` is set:
    - The export worker (`app/jobs/`, not `app/db` or `app/runtime`, keeping
      `tests/meta/test_no_file_io.py` green) writes each completed export to it as
      `borrel-<slug>-<yyyymmdd-hhmm>-<kind>.xlsx`, by temporary name then rename.
    - While a run is live, it also builds an `auto` export every 15 minutes, written **only to
      the host directory**: no `export` row, no schema change, invisible in the UI.
  - An auto export uses the one export slot (Phase 7 SD6). It is skipped, not queued, when the
    slot is busy, and never delays a manual or final export.
  - Host retention: final exports are kept forever; the newest 8 auto exports per run are kept;
    manual exports are kept.
  - Render leaves `EXPORT_DIR` unset, because its filesystem is ephemeral.
  - **Neither path depends on the other.** The dump does not read the export directory, and the
    export does not read a dump.

**Clock**

- **SD15 — Stamps never go back; a backward step beyond the budget becomes an offset and a
  gap.** *(delegated)*
  - The runtime stamps every commit from one **app clock**, `app_now = wall + offset`. Ticks,
    orders, jumps, events and close all use it. `offset ≥ 0` starts at 0 and only ever grows.
  - When the ticker sees the wall clock more than the budget (30 s) behind the last commit:
    - It raises `offset` so `app_now` continues from the last commit.
    - It re-anchors.
    - It writes one `gap` tick with no time evolved and no anchor shift.
    - It logs `clock_stepped_back` with the step and the new offset.
  - Prices then keep evolving on the 1 Hz grid instead of freezing for the size of the step.
  - At boot, rehydrate computes the same offset from the last commit when the wall clock is
    behind it.
  - A backward step within the budget keeps ADR 0003's documented hold. An order stamps
    `max(app_now, last_commit)`, as a tick does, so `price_tick.wall_ts_ms` never decreases.
  - Forward steps are unchanged (the gap rule). AC14 tests +1 h with prices.
  - The ADR 0003 addendum (SD4) records this too. It makes ADR 0003's existing sentence true,
    rather than changing the decision.

**Runbooks, cutover and keys**

- **SD16 — Runbooks.** *(delegated)*
  - `docs/runbooks/`, in English: `deploy.md`, `rollback.md`, `restore.md`, `venue.md` (the
    offline event end to end, including laptop preparation, router, power plan and lid
    settings), `incident.md`, and `v1-fallback.md`.
  - The bundle's `LEESMIJ.md` is a one-page card **in Dutch**, for the treasurer: start,
    status, "it hangs", "the power went off", "make a backup now", "where are the files", and
    when to call whom.
- **SD17 — v1 stays as a fallback, run from its own saved image, never rebuilt from
  `legacy/v1/`.** *(delegated)*
  - The fallback image is the one built in `borrelbeurs-v1` at the hotfix (`b617a56`), saved as
    a tar next to the bundle. `legacy/v1/` has no `.dockerignore`, and building from it would
    re-create D-43.
  - It runs on the same laptop and router on host port 8000, with fresh keys generated on the
    laptop (SD18).
  - **Falling back loses v2's live prices**: v1 starts from its own config. Revenue so far stays
    in v2's last dump and host exports. `v1-fallback.md` says so.
  - Target: from the decision to the bar taking orders on v1 in **≤ 5 minutes**. Previous-image
    rollback of v2, at the venue or on Render: **≤ 5 minutes**. Both are rehearsed and timed
    (AC23, AC24).
  - v1's hard-coded `ADMIN_TOKEN=TestTest` in its `run.bat` is accepted for a fallback on a
    closed router. Fixing v1 is out of scope.
- **SD18 — v1 key rotation (D-42) is a human task with a recorded outcome.** *(delegated)*
  - Every place v1 runs gets a new `config/keys.json`, generated where it runs and never
    committed. The leaked keys then grant nothing anywhere.
  - Recommended alongside: make `borrelbeurs-v1` private or archive it (Phase 0 R8).
  - The outcome (where v1 runs, date rotated, repo status) is recorded in the rehearsal record,
    with no key material.
- **SD19 — Rehearsals are recorded in `docs/runbooks/rehearsals/<yyyy-mm-dd>-<what>.md`.**
  *(delegated)* One file per rehearsal: date, image SHA, what was done, timings, what broke, and
  the follow-ups. Human-performed; an agent may draft the file from the human's notes.
- **SD20 — Dependencies.** No new Python or npm dependency.
  - Trivy runs as a digest-pinned container (`aquasec/trivy`, Apache-2.0, Aqua Security), not
    as a GitHub Action. It also produces a CycloneDX SBOM, which CI keeps as an artifact.
  - GHCR is used through the `docker` CLI with `GITHUB_TOKEN` (`packages: write` on the push
    job only).
  - The PR still states the licence and maintenance for Trivy, as CLAUDE.md requires. Phase 0
    D12 and the earlier spec already named it.
- **SD21 — Trivy fails on CRITICAL or HIGH findings that have a fix.** *(delegated)*
  - `--severity CRITICAL,HIGH --ignore-unfixed`.
  - An unfixed finding can only be waived in `.trivyignore` with a reason and an expiry date. A
    meta test rejects an entry that lacks either.

**Human-only steps (hard stops; nothing an agent may do)**

- Creating the Render services and GHCR visibility or registry credentials, pasting
  `DATABASE_URL`, and storing the deploy-hook and smoke-key secrets.
- The first deploy, and any deploy during a live borrel.
- Rotating v1's keys and changing `borrelbeurs-v1`'s visibility.
- Preparing the laptop and router.
- The mock borrel and the rehearsals.

## In scope

- **Image:**
  - trimmed runtime dependencies: `uvicorn` with `websockets`, `httptools` and `uvloop`
    explicitly, instead of `[standard]`;
  - `pip`, `setuptools` and `wheel` removed from the runtime image;
  - `BUILD_SHA`;
  - checks on image contents and size;
  - the Trivy scan and SBOM;
  - the built assets checked *inside the image*.
- **CI:**
  - the `docker` job runs the image against Postgres;
  - it boots the image on the previous release's schema;
  - smoke, durability drill, push to GHCR on `main`;
  - the manual deploy workflow.
- **Server:**
  - standby (SD4) and `schema_compat` with the SD3 boot rule, plus its migration;
  - `APP_ENV=venue`, and the `BUILD_SHA`, `TRUSTED_PROXY_IPS` and `EXPORT_DIR` settings;
  - proxy settings passed to uvicorn;
  - the app clock and backward-step handling (SD15);
  - the host-directory export and the 15-minute auto export (SD14);
  - `Cache-Control` (AC27).
- **Deploy artefacts:**
  - `render.yaml`;
  - `deploy/venue/` (compose file, `.cmd` scripts, `.env.example`, `LEESMIJ.md`);
  - `scripts/make_bundle.sh`;
  - `scripts/smoke.py`;
  - `.trivyignore` and its meta test.
- **Documents:**
  - `docs/runbooks/` (SD16) and the rehearsal records (SD19);
  - addenda to ADR 0003 (standby, app clock), ADR 0011 (SD3, overlap superseded) and the SDR
    (deploy trigger, venue profile, router);
  - `architecture.md` (deploy topology);
  - README and CLAUDE.md commands (bundle, smoke, deploy);
  - the dev compose header (R4 resolved);
  - the defect register (a Phase 8 evidence table, and the Phase column for D-42 and D-43);
  - `docs/plans/manual-checklist.md`.
- **Human tasks:** the list above, the mock borrel, the rehearsals, key rotation.

## Out of scope

- Multi-region, WAF, CDN, autoscaling, a second replica, Kubernetes ([SDR](../adr/0001-setup-decision-record.md)).
- Any synchronisation between the Render database and the venue laptop's. Moving data is a
  manual dump and restore.
- TLS at the venue, a local CA, mDNS names, or a captive portal.
- Point-in-time recovery, off-site or cloud backup automation, and encrypted backups. Copying
  the backup folder to a USB stick is a runbook step.
- Automatic deploy on merge, preview environments, and a staging environment (SDR §3: local and
  prod only).
- Image signing (cosign), multi-architecture images (amd64 only), and automated digest bumps
  (Renovate, Dependabot).
- Venue scripts for macOS or Linux.
- Monitoring, alerting or uptime services beyond Render's logs and `/healthz`.
- Per-request `correlation_id` (deferred by the Phase 3 plan:822 to here; no criterion needs
  it, so it is deferred again).
- Deleting `legacy/v1/`. Specs and the register cite its line numbers.
- Any edit to v1 (its `run.bat`, `ADMIN_TOKEN`, Dockerfile), or a v1 → v2 live state transfer
  during fallback.
- Changes to the dev `docker-compose.yml` beyond its header comment.
- Any change to pricing behaviour. The golden fixtures stay green.
- An admin UI for backups, restore or the auto exports.

## Acceptance criteria

**Image — D-43**

- **AC1.** When the production image is built, it shall use a multi-stage build, run as a
  non-root user, and pin every base image by digest.
- **AC2.** When CI builds the image, it shall list the image filesystem and fail if any
  `*.tar`, `*.tar.gz`, `.git`, `.env*`, `keys.json`, `.jwt_secret`, `tests/`, `legacy/`,
  `node_modules`, `pip`, `uv` or `setuptools` is present. *(D-43)*
- **AC3.** When CI builds the image, it shall record its uncompressed size in the job log and
  fail if it exceeds **300 MB**, a ceiling well under v1's 406 MB. The measured figure shall be
  recorded in the defect register's Phase 8 evidence. *(D-43)*
- **AC4.** When the image is scanned with Trivy, CI shall fail on any CRITICAL or HIGH finding
  that has a fix. A `.trivyignore` entry without a reason and an expiry date shall fail a meta
  test. The CycloneDX SBOM shall be kept as a CI artifact.
- **AC5.** When CI pushes an image, it shall be tagged with the full git SHA, only from `main`.
  No workflow, `render.yaml` or venue file shall reference `:latest` (meta test).
- **AC6.** When the image runs, `/healthz` shall report `build_sha` equal to the commit it was
  built from, and the boot log shall include it.
- **AC7.** When the image's `/app/web/dist` is copied out, `scripts/check_built_assets.py` shall
  pass on it. Built output inside the image makes no request that leaves the origin (Phase 4
  invariant).

**Boot, schema and rollback**

- **AC8.** When an image boots against a database at a revision its scripts contain, it shall
  migrate to head under the lock before serving, as today. A failed migration shall exit
  non-zero with `/readyz` never green. *(regression)*
- **AC9.** When CI boots the new image against a database migrated to the **previous**
  release's head, the image shall migrate and pass the smoke test. When it boots the
  **previous** image (or a fixture image one contract-free revision behind) against the new
  head, that image shall log `schema_ahead` and pass the smoke test.
- **AC10.** When an image boots against a database whose revision it does not know and whose
  `min_code_revision` it does not know either, it shall refuse to boot, exit non-zero, and log
  `boot_failed` with reason `schema ahead of image`, having written nothing.
- **AC11.** When a migration after the one that introduces `schema_compat` neither sets
  `min_code_revision` nor states it explicitly unchanged, a meta test shall fail.

**Single writer on Render**

- **AC12.** When a second instance boots while another holds the advisory lock, it shall enter
  standby:
  - no migration, no tick and no write;
  - `/healthz` 200 with `status: standby`, `/readyz` 503;
  - every `/api` route 503 `standby`, `/ws` closed with 1013;
  - `lock_wait` logged on entry and every 30 s.

  Exactly one instance shall tick at any time.
- **AC13.** When the holder of the lock shuts down gracefully or dies, a standby shall take the
  lock within 2 s, then migrate, rehydrate and become ready. An integration test with two real
  processes shall show contiguous versions, no duplicate tick stamps and no lost acknowledged
  order across the handover.

**Clock**

- **AC14.** When the wall clock steps **forward by one hour** mid-run, the system shall write
  one `gap` tick, re-anchor, and resume ticking at 1 Hz. Every drink's `p_cont` immediately
  after the gap shall equal its value before it: prices shall not jump.
- **AC15.** When the wall clock steps **back by one hour** mid-run, the system shall write one
  `gap` tick, keep every tick and order stamp non-decreasing, and keep advancing the grid at
  1 Hz within 2 s. Prices shall not freeze for the size of the step. *(SD15)*
- **AC16.** When an order commits after a backward step, its `wall_ts_ms` shall be ≥ the
  previous commit's, and `price_tick.wall_ts_ms` shall never decrease within a run (property
  test over random clock steps and order timings).

**Durability**

- **AC17.** When the app and Postgres containers are both killed with SIGKILL during a stream of
  orders and then started again, the run shall resume with prices equal to the last committed
  state (gap rule applied), versions contiguous, and **zero acknowledged orders lost**. This is
  a CI drill against the image.
- **AC18.** When Postgres alone is killed and restarted, the app shall become ready again within
  60 s without human action, and no acknowledged order shall be lost.

**Venue**

- **AC19.** When the laptop is on the travel router with **no uplink** and the images are only
  in the local store, `start.cmd` shall bring up app, Postgres and backup without pulling or
  building, and print the URL. Phones on the router shall log in over `http://<fixed-ip>/`
  (SD1) and a full borrel shall be runnable.
- **AC20.** When the bundle is produced for a SHA, it shall contain the app image at that SHA
  and the pinned Postgres image, both `linux/amd64`, plus the compose file, scripts,
  `LEESMIJ.md` and `SHA256SUMS`. `docker load` of `images.tar` on a machine with no network
  shall make `start.cmd` succeed.
- **AC21.** While a run is live at the venue:
  - a `pg_dump` shall appear in the backups directory at least every 5 minutes;
  - an xlsx of the live run shall appear in the exports directory at least every 15 minutes;
  - every completed manual and final export shall appear there too.

  With the app stopped, dumps shall continue. With the backup service stopped, exports shall
  continue. Neither shall read the other's output. A partial file shall never carry a final
  name.
- **AC22.** When the newest dump is restored into an empty volume with `restore.cmd` and the
  stack started, the app shall boot, rehydrate the run with the gap rule, and hold every order
  committed before that dump.
- **AC23.** When "Sluit app" is used at the venue, the app container shall stay stopped until
  `start.cmd`. When the app exits with a lost lock or a failed boot, it shall be restarted.
- **AC24.** When the venue stack runs, Postgres shall publish no host port, and no container,
  volume or network name shall collide with the dev stack's.
- **AC25.** When `APP_ENV=venue`, `SESSION_COOKIE_SECURE=false` shall be accepted and `/docs`
  shall be 404. When `APP_ENV=production`, `SESSION_COOKIE_SECURE=false` shall still refuse to
  boot.

**Render**

- **AC26.** When `TRUSTED_PROXY_IPS` is set, the login limiter shall key on the forwarded client
  address. When it is empty, forwarded headers shall be ignored. uvicorn shall be passed its
  proxy settings explicitly, so `FORWARDED_ALLOW_IPS` in the environment changes nothing.
- **AC27.** When `index.html` or an SPA route is served, the response shall carry
  `Cache-Control: no-store`. Hashed assets under `/assets/` shall carry `public,
  max-age=31536000, immutable`.
- **AC28.** When the deploy workflow runs for a SHA, it shall refuse a SHA not present in GHCR,
  deploy it to Render, wait for `/healthz` to report that `build_sha`, and run the smoke test
  (health, readiness, login, one read, one write), failing the workflow on any step.
- **AC29.** When a deploy happens during a live run on Render, the run shall continue on the new
  instance with no double tick, contiguous versions and no lost acknowledged order. The logs
  shall show `lock_wait` on the new instance until the old one released the lock.

**Cutover — D-42**

- **AC30.** Before the first real event, a full mock borrel shall be run on the venue setup with
  no uplink and v1 available as fallback, and recorded per SD19.
- **AC31.** Before go-live, a v2 previous-image rollback (at the venue and on Render) and a v1
  fallback shall each be rehearsed, timed against the 5-minute targets, and recorded.
- **AC32.** Before go-live, the v1 keys in `borrelbeurs-v1`'s history shall grant access to
  nothing:
  - every running v1 shall have new keys;
  - a v1 key presented to v2's login shall return 401 (test);
  - v2 shall have no import path for v1 keys (test).

  The rotation shall be recorded without key material. *(D-42)*

## Verification

- **The image gate in CI (`docker` job):** build → contents check (AC2) → size (AC3) → Trivy and
  SBOM (AC4) → assets check on the extracted `dist` (AC7) → run with Postgres → smoke with
  `build_sha` (AC6, AC9) → previous-schema boot both ways (AC9) → the kill drill (AC17) → push
  on `main` only (AC5). Paste the job output as evidence.
- **Integration tests (in `./scripts/check.sh`):**
  - SD3 boot rule: known, ahead-and-compatible, ahead-and-incompatible (AC8, AC10);
  - two real processes for standby and handover (AC12, AC13);
  - FakeClock steps of +1 h and −1 h with price and stamp assertions (AC14, AC15) and the
    stamp property test (AC16);
  - Postgres restart (AC18);
  - proxy keying (AC26), cache headers (AC27), venue config (AC25), host-directory exports with
    a temp `EXPORT_DIR` (AC21's export half).
- **Meta tests:** `schema_compat` coverage (AC11), no `:latest` (AC5), the `.trivyignore`
  shape (AC4), no v1-key import path (AC32).
- **Render:** the human creates the services. Deploy SHA *n*, start a borrel, take orders from
  a phone, deploy SHA *n+1* mid-run, and keep the logs showing `lock_wait`, the handover and
  contiguous versions (AC29). Then roll back to *n* through the deploy workflow and time it
  (AC31). Record Render's actual overlap behaviour. If Render does not overlap, say so: SD4 is
  then exercised only by the integration test.
- **The real check — the mock borrel (AC30):**
  - Venue setup: travel router with no uplink, laptop on its fixed IP, bundle loaded from USB.
  - At least one hour, at least two bar phones and one display, with v1's tar on the laptop.
  - Include:
    - a drink added mid-run;
    - "Sluit app" then `start.cmd`;
    - a **hard power-off** (power button held, mains out) and a restart (AC17's real-world
      half);
    - the laptop clock moved +1 h and back (AC14, AC15);
    - a manual export downloaded on a phone;
    - checking that dumps and auto exports are accruing (AC21);
    - closing the run.
  - Afterwards: restore the newest dump into a fresh volume and check the order count (AC22),
    and copy `data/` to a USB stick.
  - Record what broke (SD19).
- **Rehearsals (AC31):** previous-image rollback at the venue and on Render, and the v1
  fallback, each timed.
- **Key rotation (AC32):** the human rotates the keys and records it; a test shows a v1 key
  fails v2 login.

## Exit condition

The same image digest serves on Render and on the offline venue laptop; previous-image rollback
and the v1 fallback have been rehearsed within their time targets; and a full mock borrel has
been run offline without needing v1, recorded.
