# Spec: Phase 0 — Foundations

Status: Approved · Depends on: nothing · Fixes: —

## Problem

The rebuild needs a repository, a toolchain and a definition of "green" before any feature
code exists. v1's repo cannot be the base: ~600 MB of image tarballs in history (342 MB
pack) and real access keys committed. Retrofitting structure later is one of the more
expensive things you can do.

## In scope

- A **fresh repository**, with v1 imported as the starting commit for reference.
- Repo structure per way-of-working §5.2: `app/`, `exchange/`, `web/`, `db/`, `docker/`,
  `docs/`, `scripts/`, `tests/`.
- `.env.example` committed, plus a config module that parses the environment through a
  schema and **fails fast at boot**.
- `docker-compose.yml` (app + Postgres, pinned versions) — a development tool only, never a
  deployment artifact.
- `scripts/setup.sh` and `scripts/check.sh`. `check.sh` runs format, lint, types, unit and
  integration, and is **the same script CI runs**.
- CI workflow green against an empty app shell.
- Branch protection, PR template, secret scanning, Dependabot.
- `CLAUDE.md` for the new repo, under a page (Appendix E).
- These `docs/` carried across.

## Out of scope

- Any pricing, persistence, API or UI behaviour.
- Bicep / Azure anything — the target is Render ([SDR](../adr/0001-setup-decision-record.md)).
- A shared dev environment; there are only local and prod.

## Acceptance criteria

- **AC1.** When a developer runs `./scripts/setup.sh` on a clean checkout, the system shall
  copy `.env.example` to `.env.local`, install dependencies, start Postgres, and apply
  migrations, without further manual steps.
- **AC2.** When the app starts with a required environment variable missing or malformed,
  the system shall fail at boot with a message naming the variable, and shall not serve
  traffic.
- **AC3.** While the app is running, the system shall read `process.env` / `os.environ`
  only inside the config module. A lint or test shall fail on reads elsewhere.
- **AC4.** When `./scripts/check.sh` is run locally and when CI runs, both shall execute the
  same checks and agree on pass/fail.
- **AC5.** When a commit is pushed, CI shall run format, lint, type check, unit tests,
  secret scan and a Docker build, and shall block the merge on any failure.
- **AC6.** When the Docker image is built, the build context shall exclude tarballs, `.git`,
  uploads and earnings, and the resulting image shall not contain them.
- **AC7.** When a secret-shaped string is committed, push protection shall reject it.

## Verification

- `./scripts/setup.sh && ./scripts/check.sh` from a clean clone, on a machine that has never
  run the project. Evidence: terminal output.
- `docker build` then `docker history` / `docker run --rm <img> ls -la /app`, asserting no
  tarball and no `keys.json`.
- Deliberately break one env var and show the boot failure message.
- A CI run on a throwaway PR, green.

## Exit condition

`./scripts/setup.sh` followed by one command yields a running shell app at `localhost`, and
CI is green. No feature behaviour exists yet, and that is correct.

## Notes for the planner

The first session of this phase writes **no feature code**. It produces the SDR, the phase
specs, the per-phase plans and `CLAUDE.md` — the written intent the way-of-working requires
before implementation. Then a human audits.
