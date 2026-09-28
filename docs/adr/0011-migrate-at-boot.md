# ADR 0011: Migrations run at boot, under the advisory lock ADR 0003 already mandates

Date: 2026-09-27 · Status: Accepted (at the Phase 0 plan audit, 2026-09-21) ·
Departs from: [way-of-working](../way-of-working.md) §5.6:897 ·
Rests on: [ADR 0003](0003-single-writer-owns-time.md), [ADR 0004](0004-postgres-everywhere-offline-first.md)

> **Numbering.** The Phase 0 plan (D10, R3, open question 2) calls for this to be filed as
> `0009-migrate-at-boot.md`. By the time it was written, 0009 and 0010 had been taken by the
> swarm's own delivery ADRs, so it is 0011. Clerical only — the decision is the one accepted
> at the audit on 2026-09-21, unchanged.

## Context

way-of-working §5.6:897 says migrations must not run at application boot. The reason is a
good one and it is about concurrency: with more than one replica, every instance races to
apply the same migration against the same database on every deploy. The prescribed shape is a
separate migration step in the deployment pipeline, gated before the new version starts.

This project has two properties that change the arithmetic.

**There is never more than one writer, and that is enforced, not hoped for.**
[ADR 0003](0003-single-writer-owns-time.md) makes single-writer a hard requirement — one
ticker owns time — and backs it with a Postgres `pg_try_advisory_lock` taken at boot, failing
fast and loudly if it cannot be acquired. The exact hazard §5.6 exists to prevent is already
excluded by a mechanism this system needs anyway.

**The environment that matters most has no pipeline to put a migration step in.**
[ADR 0004](0004-postgres-everywhere-offline-first.md) makes an offline laptop at the venue a
first-class deployment target: `docker compose up`, no internet, no CI, no operator with a
terminal open at 23:00. A "run the migration job first" instruction is a step a tired
treasurer has to remember, and the failure mode when they do not is an app that starts
against a schema it does not understand. Boot-migration turns that into something that cannot
be got wrong.

## Decision

The application applies `alembic upgrade head` during its startup lifespan, **after** taking
ADR 0003's advisory lock and **before** serving traffic. If the migration fails, boot fails:
the process exits non-zero and `/readyz` never goes green. Nothing serves against a schema
that was not successfully migrated.

The lock is the load-bearing part. Boot-migration without it is exactly the practice §5.6
forbids, and this ADR does not sanction that.

## Alternatives

**A separate migration job in the deploy pipeline (§5.6's prescription).** Rejected for the
offline target only. It remains correct for Render, and nothing here prevents running it
there as well — `alembic upgrade head` is idempotent, so a pipeline that migrates first
simply makes the boot-time call a no-op. This ADR sets the floor, not a ceiling.

**A human-run `scripts/migrate.sh` at the venue.** Rejected. It is the instruction most likely
to be skipped on the one night it matters, and skipping it is silent until the first query.

**Migrate lazily on first request.** Rejected outright. It moves schema changes onto the
request path and makes the first customer of the evening the person who discovers a broken
migration.

## Consequences

- Boot is slower by one round trip to Postgres and one `alembic upgrade head` even when there
  is nothing to apply. Measured in milliseconds; irrelevant against an event that runs for
  hours.
- **The advisory lock is a precondition of this decision, and it does not exist yet.** Phase 0
  leaves a named seam in the lifespan (plan "Out of scope"); Phase 3 AC18 implements the lock.
  Until it lands, the only sanctioned environment is a single local process. Phase 3 must wire
  the two together in the right order — lock, then migrate, then serve — or this ADR is not
  being honoured, only cited.
- A failed migration is now an outage rather than a degraded start. That is the intended
  trade: a refusal to start is diagnosable, a half-migrated running app is not.
- Migrations must stay backwards-compatible enough to survive Render's overlap window, where
  the new instance boots while the old one is still draining. The old instance will be running
  against the new schema for a few seconds. Expand/contract, per the way-of-working, is
  therefore still mandatory — boot-migration does not relax it.
- **Revisit this when** a second replica is ever wanted, or when a deployment pipeline exists
  that can run a gated migration step for *every* target including the offline one. Either
  removes the grounds for departing from §5.6.
