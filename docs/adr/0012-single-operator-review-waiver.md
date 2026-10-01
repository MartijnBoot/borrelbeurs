# ADR 0012: Waive the required approving review while there is a single operator

Date: 2026-10-01 · Status: Accepted (at the Phase 0 plan audit, 2026-09-21, as R5) ·
Departs from: [way-of-working](../way-of-working.md) §7.1:1123 ·
Rests on: [ADR 0001](0001-setup-decision-record.md), [ADR 0009](0009-autonomous-swarm-delivery.md)

> **Numbering.** The Phase 0 plan (R5, T12) calls for this to be filed as
> `0010-single-operator-review-waiver.md`. By the time it was written, 0010 and 0011 were
> taken, so it is 0012. Clerical only — the decision is the one accepted at the audit.

## Context

way-of-working §7.1:1123 requires branch protection on `main` with a PR, **at least one
approving review**, required status checks, dismissal of stale approvals, no force-push, no
deletion and linear history.

[ADR 0001](0001-setup-decision-record.md) records a single operator. GitHub does not let a
PR's author approve their own PR, so with one person a required review is not a stricter
gate. It is a gate nobody can pass. Every merge would need an admin bypass, and a rule that
is bypassed on every merge does nothing except teach the operator to bypass it.

## Decision

Branch protection on `main` is configured as §7.1 says **except** for the approving-review
requirement, which is set to zero:

- PR required; required status checks `check`, `secret-scan` and `docker` (the three jobs in
  `.github/workflows/ci.yml`); dismiss stale approvals; no force-push; no deletion; linear
  history.

The review that §7.1 asks a second human for is supplied by two compensating controls:

1. **Required status checks.** `check` runs the identical `./scripts/check.sh` a developer
   runs locally (format, lint, types, unit, integration), `secret-scan` runs gitleaks, and
   `docker` builds the shipped image. None of them can be skipped by the author.
2. **The `fresh-eyes-reviewer` agent.** Every task is reviewed against its spec and plan in a
   context that did not write the code (way-of-working §4.2 step 7, ADR 0009). The session
   that wrote a change is never its only reviewer.

`.github/CODEOWNERS` is committed anyway, for `db/migrations/` and `docker/`. With no review
required it enforces nothing today. It records ownership so that turning the requirement
back on needs no other change.

## Revisit

**When a second contributor joins**, set the required approving reviews back to one and turn
on "Require review from Code Owners". The waiver exists because of the single operator and
lapses with it.

## Consequences

- A change can reach `main` without a second human ever reading it. That cost is accepted,
  and it is the reason the fresh-context review is mandatory rather than advisory.
- "PR required" also forbids pushing straight to `main`. Any workflow that merges locally
  and then runs `git push origin main` has to go through a PR instead, or rely on an admin
  bypass of the rule. Relying on the bypass would defeat this ADR.
