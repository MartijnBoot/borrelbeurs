## What and why

Spec: docs/specs/___.md · Plan: docs/plans/phase-___.md

## Section

Which slice of the plan is this? (T3 of phase-N-*.md)

## How it was verified

<paste the command and its output — not "tests pass">

- [ ] `./scripts/check.sh` green
- [ ] Integration tests green
- [ ] Exercised by hand locally
- [ ] Fresh-context AI review run (`fresh-eyes-reviewer`); findings addressed

## Screenshots / recordings

<UI changes only>

## Data changes

- [ ] None
- [ ] Migration: <name> — additive? reversible? backfill?

## Rollback

How do we undo this? (flag / revision / corrective migration)

## New dependencies

None / <name — what it does, why not stdlib, licence, maintenance, weekly downloads>

## Checklist

- [ ] Only files in scope changed
- [ ] No secrets, keys or PII in code, tests or logs
- [ ] Docs / .env.example / API contract updated
- [ ] Feature flag added if user-visible
- [ ] Logs and metrics adequate to debug in production
