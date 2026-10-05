# Spec: Phase 8 — Deploy and cutover

Status: Approved · Depends on: Phase 7 · Fixes: D-43 (properly)

## Problem

v2 must run in two places that fail in different ways: Render, where the platform restarts
and briefly overlaps instances, and a laptop at a venue with no internet, where there is no
platform at all and the recovery procedure has to be executable by a tired treasurer.

## In scope

- Multi-stage, non-root Dockerfile with a pinned base and a trimmed dependency set.
- `render.yaml`, managed Postgres, environment and secret wiring, health probes.
- The offline bundle: `docker save` of **both** images, plus a documented boot procedure.
- Backups: `pg_dump` on a timer into a bind mount.
- Runbooks: deploy, rollback, restore, offline event, incident.
- Cutover, with v1 retained as fallback.

## Out of scope

- Multi-region, WAF, CDN, autoscaling ([SDR](../adr/0001-setup-decision-record.md)).

## Acceptance criteria

**Image**

- **AC1.** When the production image is built, it shall use a multi-stage build, run as a
  non-root user, and pin its base image by digest.
- **AC2.** When the image is scanned, the build shall fail on CRITICAL or HIGH findings.
- **AC3.** When the image is built, it shall contain no tarball, no `.git`, and no secrets.
- **AC4.** When the image is tagged, it shall be tagged by git SHA. `latest` shall not be
  deployed.
- **AC5.** The runtime image shall be materially smaller than the 406 MB measured after the
  v1 hotfix. *(the hotfix only removed the self-inclusion; trimming the `fastapi` 0.111 tree,
  which drags in `fastapi-cli`, `rich`, `typer` and `watchfiles`, plus a multi-stage build,
  is the remaining work)*

**Render**

- **AC6.** When a deploy occurs while a run is live, exactly one instance shall hold the
  advisory lock and tick; the other shall exit loudly rather than double-tick.
- **AC7.** When the app starts, migrations shall run as a gated step before it serves traffic.
- **AC8.** When a deploy is rolled back, the previous image shall serve correctly against the
  current schema. *(expand-only migrations)*
- **AC9.** After deploy, a smoke test shall exercise health, login, one read and one write.

**Offline**

- **AC10.** When the event laptop has **no network at all**, `docker compose up` shall start
  the app and Postgres from the local image store, and a full borrel shall be runnable.
- **AC11.** When the offline bundle is produced, it shall contain both the app and Postgres
  images.
- **AC12.** While a run is live offline, a database dump shall be written to a host directory
  on a timer, and an xlsx export shall be independently obtainable. Neither shall depend on
  the other.
- **AC13.** When the laptop's clock is stepped forward by an hour mid-run, prices shall not
  jump; the grid shall re-anchor and a gap shall be recorded.
- **AC14.** When the machine is hard-powered-off mid-run and restarted, the run shall resume
  with prices intact and zero orders lost.

**Cutover**

- **AC15.** Before the first real event, a **full mock borrel** shall be run offline end to
  end, with v1 available as fallback, and the result recorded.
- **AC16.** Rollback to v1 shall be rehearsed and timed before go-live.
- **AC17.** Old v1 access keys shall be rotated and shall not grant access to v2.

## Verification

- Trivy scan output in CI.
- Deploy to Render, then deliberately redeploy during a live run and show the lock behaviour
  in the logs.
- **The real check:** disconnect the venue laptop from all networks, run a mock borrel with
  several phones for at least an hour, including a crash, a drink addition, a restart, and an
  export. Record what broke.
- A timed rollback rehearsal.

## Exit condition

The same image runs on Render and offline; rollback is rehearsed; a full mock borrel has been
run offline without v1.
