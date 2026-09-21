# ADR 0004: One database engine, Postgres, local and hosted

Date: 2026-09-12 · Status: Accepted

## Context

The app must run with **no internet** on a laptop at the venue, and also be hosted on
Render. `CLAUDE.md` currently states "Don't introduce a database — file-based JSON/xlsx
persistence is intentional for offline event use." That constraint is deliberately reversed
here, because the file-based approach is what loses the event on restart.

## Decision

PostgreSQL in both environments, same major version. Locally via Docker Compose alongside
the app; on Render via managed Postgres. `DATABASE_URL` is the only difference.

## Alternatives

**SQLite offline, Postgres hosted.** Rejected. Two engines means two sets of semantics —
`jsonb`, advisory locks, upsert behaviour, array handling — and the path that must never
fail is the *offline* one. It must therefore be the path exercised every day in development.

**Keep files, add a database only for analytics.** Rejected. It leaves the live state
un-durable, which is the primary problem being solved.

## Consequences

- `docker compose up` at a venue with no internet fails if the Postgres image is not already
  in the local image store. The existing `docker save` workflow must bundle **both** images,
  and the offline boot must be rehearsed as part of the go-live gate.
- Two independent recovery paths must exist on the host filesystem: a `pg_dump` on a timer
  into a bind mount, and the xlsx export. Neither may depend on the other. At a borrel the
  recovery procedure has to be executable by a tired treasurer with a USB stick.
- Render's free Postgres expires after 90 days. Either move to the paid tier or treat the
  offline deployment as authoritative.
- `CLAUDE.md` must be updated when this lands, or it will actively mislead.
