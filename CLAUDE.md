# CLAUDE.md

Guidance for Claude Code in this repo. Fuller context: [README.md](README.md),
[docs/way-of-working.md](docs/way-of-working.md), [docs/plans/rebuild-route.md](docs/plans/rebuild-route.md).

## Project

BorrelBeurs — a drink stock exchange for student borrels, rebuilt from v1 (frozen, reference
only, in `legacy/v1/`). FastAPI (`app/`) serving a Vite/React frontend (`web/`) from one origin,
backed by **Postgres** (`db/`, Alembic), with the pure pricing engine (`exchange/`) underneath.

## Commands

- `./scripts/setup.sh` — clone to running stack: env, deps, `docker compose up -d db`, migrate.
  Idempotent. Git Bash only; needs `docker`, `uv`, `pnpm`.
- `./scripts/check.sh` — the gate: format, lint, types, unit, integration (Python and web),
  stopping at the first failure. Needs the compose `db` running for the integration step. CI
  will run this same script (T11). Run it before calling any task done.
- `uv run alembic -c db/alembic.ini revision -m "<msg>"` — new migration.
- `uv run alembic -c db/alembic.ini upgrade head` / `downgrade -1` — apply / roll back.
- `uv run pytest tests/unit tests/meta tests/engine` — fast tests, no database needed.
  (`tests/engine` stays empty until Phase 1.)
- `uv run uvicorn app.main:app --reload --port 8000` — run the app.

## Workflow

- Work from an audited plan in `docs/plans/phase-N-*.md`. No task without a PASS audit — not
  yours to waive.
- One task per branch, conventional commits (`feat(phase-0): T7 — ...`). `/build N` with no
  task id builds the whole phase in one session, task by task, on stacked branches.
- Bug fixes start with a failing test; a feature's acceptance criteria become its test cases.
- Run `./scripts/check.sh` and paste the actual output before saying a task is done —
  "tests pass" is not evidence.
- If a requirement is genuinely ambiguous, stop and ask; do not guess.

## Conventions

- `app/core/` is this repo's only `core/`: config, errors, logging — cross-cutting,
  framework-adjacent infrastructure with no business logic in it. There is no `lib/`; do not add
  one without first saying, here, what it means.
- **Postgres is the persistence layer, local and hosted** (ADR 0004) — one engine, one DSN shape
  (`postgresql+asyncpg://...`), validated in `app/core/config.py`, the only module that reads the
  environment (`os.environ` anywhere else under `app/` or `db/` is a bug `tests/meta/` catches).
- Migrations live in `db/migrations/versions/`, forward-only, applied in order. Never edit one
  that already has a successor — add a new one.
- Types at the boundary: every external input is validated (pydantic) before use. No untyped
  boundary.
- `exchange/` must end up importing no clock, no I/O, no framework, golden fixtures passing —
  Phase 1's target, not today: `engine.py` is v1 verbatim (`import time` and all), excluded
  from ruff/mypy until then (`pyproject.toml`).
- A new dependency needs justification in the PR (why not stdlib, licence, maintenance) — ask
  first.

## Never

- Never edit a migration that already has a successor — add a new one instead.
  `scripts/hooks/guard_migrations.py` decides this, is unit-tested, and is registered as a
  `PreToolUse` hook in `.claude/settings.json` for `Write|Edit|MultiEdit`. It does not see
  `Bash` — a `sed -i` on a superseded revision is not stopped by anything, so don't.
- Never introduce a second database engine, or a second place that reads the process environment.
- Never commit `.env*`, `config/keys.json`, real secrets or credentials.
- Never edit `legacy/v1/` — read it for reference only.
- Never use production credentials, or connect to production, from a dev or agent session.
