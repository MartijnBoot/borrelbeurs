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
- `uv run python -m tests.engine.golden.capture --check` — recapture the golden fixtures from
  the v1 reference and diff them (`--write` regenerates them: a deliberate behaviour change only).
- `uv run uvicorn app.main:app --reload --port 8000` — run the app.
- `uv run python -m app.cli.import_v1 --config <path> [--news <path>] [--bar-prices <path>]` —
  import v1's files as a new draft run; prints its `run_id`.
- `uv run python -m app.cli.keys create --role <display|bar|admin> --label <l>` / `list` /
  `revoke <key_id>` — access keys; `create` prints `bb_<key_id>_<secret>` once.
- `uv run python -m app.cli.runs go-live <run_id>` — make a draft run live; refused while the
  app runs (it holds the advisory lock), so it takes effect at the next boot.
- `bash scripts/make_bundle.sh <sha> [--local <image>]` — the venue bundle in `bundle/` (gitignored).
- `uv run python scripts/smoke.py <url> --expect-sha <sha>` — smoke-test a running app; the key is
  in `BB_SMOKE_KEY`.
- `uv run pytest tests/image --image <ref>` — drills against a built image (boot, kill, venue);
  skipped without `--image`; `check.sh` never collects it.
- `deploy` workflow (Actions, manual) — deploys a pushed SHA to Render; never run by an agent.

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
- `exchange/` imports no clock, no I/O, no framework, and (from Phase 1 T7) replays the golden fixtures in
  `tests/engine/golden/fixtures/` exactly. v1's engine lives on, verbatim and sha256-pinned, as
  `tests/engine/v1_reference/engine.py` — the fixtures are captured from it; excluded from
  ruff/mypy (`pyproject.toml`). Never edit it.
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

## Hard stops — the owner's, never an agent's

Everything with a consequence a `git revert` cannot undo stays with the owner. Stop, state the
question, the evidence and your recommended answer, and wait:

- A spec ambiguity with two readings that produce different user-visible behaviour, or any
  ambiguity at all in the pricing maths.
- A golden fixture diverges, or `engine-guardian` reports a maths change.
- A new third-party dependency is needed.
- A decision that reverses or contradicts a product ADR (every ADR but 0009 and 0010), or changes
  anything in `docs/design/`.
- A credential, secret or external account is needed — `config/keys.json`, Render, GitHub
  settings, anything you would have to be given rather than compute.
- A cross-phase invariant is broken and cannot be restored inside the task that broke it.
- Pushing, merging, opening a PR, deleting a remote branch, any history rewrite or force-push —
  and anything at all touching the `borrelbeurs-v1` repository.
