# Plan: Phase 0 — Foundations (generated in plan mode, audited by MartijnBoot on 2026-09-21)

Spec: [docs/specs/phase-0-foundations.md](../specs/phase-0-foundations.md) · Status: Approved (verbally, 2026-09-21)
Design: [architecture.md](../design/architecture.md), [frontend-architecture.md](../design/frontend-architecture.md)
ADRs honoured: 0001 (Render, single operator), 0002 (Python engine kept), 0003 (single writer), 0004 (Postgres everywhere), 0006 (bundle all assets)

---

## Approach

Phase 0 builds a **fresh repository containing a running but featureless system**, not a folder
of config files. The organising principle is that every gate in this phase must be proved by
something real passing through it: `check.sh` must have a test to run, CI must have an image to
build, the Dockerfile must have an app to serve, and the config module must have a boot to fail.
So the phase stands up a vertical slice — Vite/React shell → FastAPI → Alembic → Postgres —
that does nothing except answer `/healthz` and render a placeholder page. That slice is what
makes AC2 through AC6 verifiable rather than aspirational, and it front-loads the integration
risk (two languages, one image, one origin) that would otherwise surface in Phase 4.

The alternative considered and rejected was a "config-only" Phase 0: scaffolding, scripts and CI
with a stub `main.py` and no frontend. It is smaller, but it defers the two things most likely to
go wrong — the pnpm/uv toolchains coexisting in one Docker build, and FastAPI serving an SPA
catch-all without shadowing `/api/*` — to a phase whose spec is about pricing maths. It also
cannot honestly satisfy AC6's "the resulting image shall not contain them", because an image with
no frontend build stage is not the image we will ship. Second rejection: importing v1's git
history with a history rewrite instead of a squashed import. `git filter-repo` over a 342 MiB
pack to strip three tarball blobs and four `keys.json` blobs is achievable, but it preserves a
history nobody will read, keeps the rotation question ambiguous, and costs more than it returns.
The spec asks for "v1 imported as the starting commit", and one squashed commit is exactly that.

**Sequencing note.** T1 creates a new repository and is the only task here that is hard to
reverse. It needs an explicit go-ahead at the audit, including the repo name. Every task from T2
onward happens inside the new repo.

---

## Decisions this plan makes (the spec and the docs leave these open)

These are choices, not findings. Each one that carries a risk is repeated in Risks.

| # | Question | Decision | Reason |
|---|---|---|---|
| D1 | Python version | **3.11** (`.python-version`, `python:3.11-slim` base) | v1 runs 3.11 ([Dockerfile:7](../../Dockerfile#L7)). Phase 1 captures golden fixtures from v1 and replays them on v2; the same interpreter removes one variable from the one gate that blocks the whole rebuild. |
| D2 | numpy version | **pinned `==1.26.4`**, identical to v1 | Golden-fixture reproducibility. numpy's `Generator` stream is stable by policy, but the fixtures are the product's safety net — do not lean on policy. |
| D3 | Postgres version | **16** (`postgres:16-alpine`, digest-pinned) | ADR 0001:42 requires local major == Render major. Render's current default is 16. |
| D4 | Node version | **22 LTS** (`.nvmrc`) | way-of-working §9.2's reference image is `node:22-bookworm-slim`. |
| D5 | JS package manager | **pnpm** | Used throughout the way-of-working (§5.5, Appendix E). The only binding rule is a committed lockfile with frozen installs (§5.1:661). |
| D6 | Python package manager | **`uv`** with `pyproject.toml` + `uv.lock` | NOT SPECIFIED anywhere in the docs. See the dependency note — this is the toolchain choice with the least precedent. |
| D7 | Python format + lint | **ruff** (one tool, both jobs) | NOT SPECIFIED. One dependency replaces black + flake8 + isort. |
| D8 | Python type checker | **mypy**, strict on `app/` and `db/` | NOT SPECIFIED. §4.6:601 requires a clean type check, so the slot must be filled by something. |
| D9 | `check.sh` contents | format, lint, types, unit, integration — **per §5.5:887**. Secret scan and Docker build are **CI-only**, per AC5. | §5.5:887 and AC5 list different sets. The reading that satisfies both: CI invokes `check.sh` verbatim (AC4 — same checks, same verdict) and then runs two extra stages that need CI infrastructure. AC5 requires CI to run them; it does not require `check.sh` to. |
| D10 | Migrations at boot | **Yes**, guarded by the `pg_try_advisory_lock` ADR 0003 already mandates | §5.6:897 forbids boot-migration to prevent replica races; ADR 0003 forbids replicas and the advisory lock enforces it. The offline venue laptop has no CI to run a migration job. **Accepted at the audit; becomes ADR 0009 — see R3.** |
| D11 | Port | **8000**, read from `PORT`, defaulting to 8000 | v1 uses 8000; Render injects `$PORT` and the app must honour it. Reading it through the config module is the point. |
| D12 | Phase 0 Dockerfile scope | Multi-stage, digest-pinned, non-root, healthcheck, `.dockerignore`, cache-ordered layers. **Deferred to Phase 8:** SBOM, the Trivy gate, the size target. | §9.1 calls all 15 rules mandatory; [phase-8 spec:13](../specs/phase-8-deploy-cutover.md) claims the production Dockerfile. The cheap rules cost a line each now and are expensive to retrofit; the three deferred ones are genuinely Phase 8 work. |
| D13 | Where v1 code lands | Commit 1 = v1 verbatim at its original paths. T2 then moves `backend/`, `static/`, `config/`, the `.bat` files and v1's `Dockerfile` into `legacy/v1/`, excluded from every gate. **`exchange/engine.py` stays at the repo root.** | Phase 1 refactors `exchange/` in place, so leaving it at root preserves `git blame` through the extraction. `engine.py` imports only stdlib + numpy ([exchange/engine.py:4-9](../../exchange/engine.py#L4-L9)), so it is importable standalone for fixture capture without any of v1's backend. |
| D14 | Repo name | **`borrelbeurs`**, private | **Confirmed at the audit (2026-09-21).** T1 has its go-ahead. |

---

## Files

Paths are relative to the **new** repository root unless marked `[v1]`.

| Path | Create/Modify | Purpose |
|---|---|---|
| `.python-version`, `.nvmrc` | Create | D1, D4 — same runtime locally, in CI and in the image (§5.1:661) |
| `.editorconfig`, `.vscode/settings.json`, `.vscode/extensions.json` | Create | §5.1:655-659 — LF, trim trailing whitespace, format on save |
| `.gitignore` | Create | §7.1:1119 — `.env*`, build output, `node_modules`, `__pycache__`, `*.tar`, uploads, earnings |
| `LICENSE`, `README.md` | Create | §7.1:1117, §5.2:755 — setup in ≤5 commands |
| `pyproject.toml`, `uv.lock` | Create | D6-D8 — dependencies plus ruff, mypy and pytest config in one file |
| `app/__init__.py`, `app/main.py` | Create | FastAPI shell: lifespan, `/api` router, SPA mount |
| `app/core/config.py` | Create | **The only module that reads `os.environ`.** Schema + fail-fast (AC2) |
| `app/core/logging.py` | Create | Structured JSON logs with a correlation id (§5.3:839) — skeleton, extended in Phase 3 |
| `app/core/errors.py` | Create | Typed error base + one global handler (§5.3:837) — skeleton |
| `app/api/health.py` | Create | `/healthz`, `/readyz` (ADR 0001:24) |
| `exchange/__init__.py`, `exchange/engine.py` | From the v1 import | Left at root untouched — Phase 1's target. Not linted or typed in Phase 0. |
| `db/alembic.ini`, `db/migrations/env.py`, `db/migrations/script.py.mako` | Create | Alembic, async, taking `DATABASE_URL` from `app.core.config` |
| `db/migrations/versions/0001_baseline.py` | Create | Empty baseline so `upgrade head` / `downgrade base` both succeed (AC1) |
| `web/package.json`, `web/pnpm-lock.yaml`, `web/tsconfig.json`, `web/vite.config.ts` | Create | Vite + React + TypeScript shell |
| `web/eslint.config.js`, `web/.prettierrc` | Create | ESLint with `eslint-plugin-boundaries` and the `import.meta.env` ban (AC3) |
| `web/index.html`, `web/src/main.tsx`, `web/src/app/App.tsx` | Create | Placeholder page proving the SPA is served from the same origin |
| `web/src/lib/config.ts` | Create | The only module that reads `import.meta.env` (AC3, web half) |
| `tests/meta/test_config_boundary.py` | Create | AC3 for Python — AST walk, fails on env reads outside the config module |
| `tests/meta/test_repo_hygiene.py` | Create | AC6 — asserts `.dockerignore` still covers the exclusion list |
| `tests/unit/test_config.py` | Create | AC2 — missing and malformed variables each fail at boot, naming the variable |
| `tests/integration/test_health.py` | Create | Proves the integration layer is wired: app + real Postgres answer `/healthz` |
| `tests/engine/.gitkeep` | Create | Phase 1's fixtures land here; `pytest tests/engine` must already be a valid path |
| `tests/conftest.py` | Create | Shared fixtures, testcontainers Postgres |
| `.env.example` | Create | Appendix B shape, this project's variables only (AC1, §3.3:243) |
| `docker-compose.yml` | Create | app + Postgres, both digest-pinned (AC1) |
| `docker/Dockerfile` | Create | D12 — multi-stage web→python, non-root, healthcheck |
| `.dockerignore` | **Extend** (v1 already ships one) | AC6 — v1's covers `.git`, `*.tar`, `*.pdf`, `config/keys.json`, `config/.jwt_secret`, uploads, earnings, `__pycache__`. Add `.env*`, `node_modules`, `legacy/`, `docs/`, `tests/`, `.github/`, `web/dist` |
| `scripts/setup.sh` | Create | AC1 |
| `scripts/check.sh` | Create | AC4, D9 |
| `.github/workflows/ci.yml` | Create | AC4, AC5 |
| `.github/PULL_REQUEST_TEMPLATE.md` | Create | Appendix F |
| `.github/ISSUE_TEMPLATE/bug.yml`, `feedback.yml` | Create | §5.2:693 |
| `.github/dependabot.yml` | Create | §7.1:1131 — grouped weekly, three ecosystems |
| `.github/CODEOWNERS` | Create | §7.1:1125 — `db/migrations/` and `docker/` |
| `CLAUDE.md` | Create | Appendix E, ≤1 page. **Must reverse v1's "don't introduce a database"** (ADR 0004:36) |
| `.claude/**` | Carry across | Agents and commands from v1's `.claude/`, minus `settings.local.json` (absolute Windows paths) |
| `.claude/settings.json` | Create | Committed allow/deny list plus the applied-migration write hook (§5.6:893) |
| `docs/**` | Carry across | Already v2 content; moves verbatim |
| `[v1] legacy/v1/**` | Move | v1 `backend/`, `static/`, `config/`, `run.bat`, `rebuild.bat`, `Dockerfile`, `requirements.txt` — reference only, excluded from all gates |

---

## Tasks

Each task leaves the repository in a working state: from T9 onward `scripts/check.sh` passes, and
from T5 onward the app still boots.

### T1 — Fresh repository with v1 as the starting commit

- **Implements:** spec In-scope 1; precondition for AC6 (the repo itself must carry no tarballs)
- **Expected output:** A new private GitHub repo with exactly two commits: (1) `chore: import v1
  as reference baseline` — v1's working tree minus `bierbeurs-image.tar`, `config/keys.json`,
  `config/.jwt_secret`, `__pycache__/**`, `static/earnings/**`, `static/uploads/**` and both
  PDFs; (2) `docs: carry v2 documentation across` — `docs/**` and `.claude/**`. `main` exists.
  Pack under 5 MiB.
- **Verification:** `git count-objects -vH` shows `size-pack` < 5 MiB ·
  `git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' | sort -k2 -rn | head -5`
  shows no blob over 200 kB except `docs/way-of-working.md` ·
  `git log --all --oneline -- config/keys.json` returns nothing ·
  `git log --all --oneline -- '*.tar'` returns nothing
- **Depends on:** — (human go-ahead on the repo name and visibility)

### T2 — Repo skeleton, toolchain pins, v1 moved aside

- **Implements:** AC4 (a pinned toolchain is what lets local and CI agree); spec In-scope 2
- **Expected output:** `app/ exchange/ web/ db/ docker/ docs/ scripts/ tests/ legacy/v1/` exist.
  `.python-version` (3.11), `.nvmrc` (22), `.editorconfig`, `.vscode/*`, `.gitignore`, `LICENSE`,
  and a `README.md` whose setup is ≤5 commands. v1's `backend/`, `static/`, `config/`, `run.bat`,
  `rebuild.bat`, `Dockerfile`, `requirements.txt`, `readme.txt` and `ARCHITECTURE.md` moved under
  `legacy/v1/` with `git mv`. `exchange/` untouched at root. The five tracked `.pyc` files removed.
- **Verification:** `test -d app -a -d web -a -d db -a -d scripts -a -d tests` ·
  `git ls-files | grep -c '\.pyc$'` returns 0 · `git ls-files legacy/v1 | wc -l` > 20 ·
  `git log --follow --oneline exchange/engine.py` reaches the import commit
- **Depends on:** T1

### T3 — Config module with fail-fast boot

- **Implements:** AC2, AC3
- **Expected output:** `pyproject.toml` with the D6-D8 tooling and Phase 0's runtime dependencies.
  `app/core/config.py` exposes one `Settings` (pydantic-settings) covering `DATABASE_URL`,
  `JWT_SECRET` (required, ≥32 chars), `PORT` (default 8000), `LOG_LEVEL` and `APP_ENV`, plus a
  `get_settings()` that raises on the first invalid value with a message naming the variable.
  **No filesystem side effects at import** — v1's
  [backend/config.py:11-13](../../backend/config.py#L11-L13) `mkdir`s three directories on import;
  this must not. `.env.example` lists every variable with a comment and a safe placeholder.
- **Verification:** `pytest tests/unit/test_config.py -v` — four cases: missing `DATABASE_URL`
  raises naming it; a 10-character `JWT_SECRET` raises naming it; `PORT=banana` raises naming it;
  a complete environment constructs cleanly. Manual: `JWT_SECRET= uv run uvicorn app.main:app`
  exits non-zero before binding a port.
- **Depends on:** T2

### T4 — Config boundary enforcement

- **Implements:** AC3
- **Expected output:** `tests/meta/test_config_boundary.py` walks the AST of `app/**` and `db/**`
  and fails on any `os.environ`, `os.getenv` or `dotenv` reference outside `app/core/config.py`,
  reporting the offending `file:line`. This reuses the transitive-import purity-test pattern that
  [architecture.md:87-89](../design/architecture.md#L87-L89) already prescribes for `exchange/` —
  same mechanism, different predicate. `web/eslint.config.js` gains a `no-restricted-syntax` rule
  banning `import.meta.env` outside `web/src/lib/config.ts`.
- **Verification:** `pytest tests/meta/test_config_boundary.py` passes · temporarily add
  `os.getenv("X")` to `app/main.py`, rerun, see it fail naming `app/main.py:<line>`, revert ·
  `pnpm --dir web lint` fails on a temporary `import.meta.env.FOO` in `web/src/app/App.tsx`
- **Depends on:** T3

### T5 — FastAPI shell with health endpoints

- **Implements:** AC2 (there is now a real boot to fail); spec Exit condition
- **Expected output:** `app/main.py` with a lifespan that loads settings, configures JSON logging
  and yields. `/healthz` returns `{"status":"ok"}`; `/readyz` returns 200 only once the lifespan
  has completed. Application routes live under `/api/*`
  ([architecture.md:36-38](../design/architecture.md#L36-L38)). `app/core/logging.py` and
  `app/core/errors.py` exist as skeletons — one JSON formatter with a correlation id, one typed
  base error, one global handler. The server binds `settings.port`.
- **Verification:** start `uv run uvicorn app.main:app --port 8000`, then
  `curl -fsS localhost:8000/healthz` returns `{"status":"ok"}` and `curl -fsS localhost:8000/readyz`
  returns 200 · `curl -s localhost:8000/api/nope` returns a JSON 404, not HTML
- **Depends on:** T3

### T6 — Web shell served from the same origin

- **Implements:** spec Exit condition; precondition for AC6 (the image must contain the real
  frontend build for the exclusion assertion to mean anything)
- **Expected output:** `web/` is a Vite + React + TypeScript project laid out per
  [frontend-architecture.md:28-41](../design/frontend-architecture.md#L28-L41) — `src/app/`,
  `src/features/`, `src/components/ui/`, `src/lib/`, `src/styles/` created (mostly empty) and
  `src/api/generated/` with a `.gitkeep`. `App.tsx` renders a placeholder that fetches `/healthz`
  and displays the result. `eslint-plugin-boundaries` is configured with the feature-isolation
  rule, scoped to `src/features/*` so Phase 4's features inherit it. `pnpm build`
  emits `web/dist/`. `app/main.py` mounts `web/dist` as an SPA catch-all **after** the `/api`
  router. No CDN references anywhere (ADR 0006).
- **Verification:** `pnpm --dir web build && pnpm --dir web lint && pnpm --dir web exec tsc -b` ·
  with the app running, `curl -fsS localhost:8000/` returns the SPA HTML while
  `curl -fsS localhost:8000/healthz` still returns JSON ·
  `grep -rnE "(src|href)=[\"']?https?://|url\([\"']?https?://|@import +[\"']?https?://" web/dist`
  returns nothing
- **Amended 2026-09-29 (T6 review):** two verification commands could not do their job.
  `tsc --noEmit` against the root `tsconfig.json` (`"files": []`, references only) type-checks
  no file and exits 0 on a type error; `tsc -b` follows the references and fails. A bare
  `https?://` grep can never come back empty, because React's bundle carries non-request URL
  strings (`react.dev/errors/…`, the `w3.org` SVG/MathML namespaces). The replacement grep looks
  only where a CDN reference can load something: `src`/`href` attributes, CSS `url()` and
  `@import`. It was shown to catch an injected `<script src="https://…">`, `<link href=https://…>`,
  `@import "https://…"` and `url(https://…)`.
- **Depends on:** T5

### T7 — Postgres, Compose and the Alembic baseline

- **Implements:** AC1 (the "start Postgres, apply migrations" half)
- **Expected output:** `docker-compose.yml` with `borrelbeurs-db` (`postgres:16-alpine`,
  digest-pinned, named volume, healthcheck) and the app service. Alembic initialised under `db/`
  with an async `env.py` that takes `DATABASE_URL` from `app.core.config` — **not** from
  `alembic.ini` and **not** from `os.environ` (AC3). One empty baseline revision, so
  `alembic_version` exists and Phase 2's first real migration has a parent.
- **Verification:** `docker compose up -d db && uv run alembic -c db/alembic.ini upgrade head`,
  then `psql "$DATABASE_URL" -c '\dt'` shows `alembic_version` ·
  `uv run alembic -c db/alembic.ini downgrade base && uv run alembic -c db/alembic.ini upgrade head`
  both exit 0 · `pytest tests/meta/test_config_boundary.py` still passes with `db/` in scope
- **Depends on:** T3

### T8 — `scripts/setup.sh`

- **Implements:** AC1
- **Expected output:** One script that, on a clean checkout, copies `.env.example` to `.env.local`
  if absent — generating a real random `JWT_SECRET` rather than shipping a placeholder that T3's
  validation would reject — installs Python dependencies with `uv sync --frozen` and web
  dependencies with `pnpm --dir web install --frozen-lockfile`, runs `docker compose up -d db`,
  waits for the healthcheck, and applies migrations. `set -euo pipefail`. Idempotent: a second run
  is a no-op that exits 0. Fails with a named message if `docker`, `uv` or `pnpm` is missing.
- **Verification:** from a fresh `git clone` into a temp directory, `./scripts/setup.sh` exits 0
  and leaves `borrelbeurs-db` running with `alembic_version` present · a second run exits 0 ·
  `docker compose down -v && ./scripts/setup.sh` exits 0
- **Depends on:** T6, T7

### T9 — `scripts/check.sh`

- **Implements:** AC4
- **Expected output:** One script running, fast checks first (§7.3:1179): `ruff format --check` →
  `ruff check` → `pnpm --dir web format:check` → `pnpm --dir web lint` → `mypy app db tests` →
  `pnpm --dir web exec tsc -b` → `pytest tests/unit tests/meta tests/engine` →
  `pnpm --dir web test --run` → `pytest tests/integration`. Exits non-zero on the first failure.
  `legacy/` and `exchange/` are excluded from ruff and mypy — v1 code, and `exchange/` enters the
  gate in Phase 1. pytest's exit code 5 ("no tests collected") is handled per directory rather
  than suppressed globally, so an empty `tests/engine/` is green today but a genuine collection
  error is still red.
- **Verification:** `./scripts/check.sh` exits 0 and its output shows all nine steps · introduce a
  formatting violation in `app/main.py`, rerun, it exits non-zero at step 1 and the later steps do
  not run · remove a required variable from `.env.local`, rerun, the integration step fails naming
  that variable
- **Depends on:** T4, T6, T7

### T10 — Dockerfile and build-context hygiene

- **Implements:** AC6
- **Expected output:** `docker/Dockerfile`, multi-stage: `web-build` (node:22-slim, digest-pinned,
  `pnpm install --frozen-lockfile`, `pnpm build`) → `runtime` (python:3.11-slim, digest-pinned)
  which installs runtime Python dependencies only, copies `app/`, `exchange/`, `db/` and
  `web/dist` from the first stage, creates and switches to `USER 1001`, declares a `HEALTHCHECK`
  against `/healthz`, and runs uvicorn on `$PORT`. Layer order: manifests → install → source.
  `.dockerignore` is **extended, not created** — v1 already ships one covering `.git`, `*.tar`,
  `*.pdf`, `config/keys.json`, `config/.jwt_secret`, `static/uploads`, `static/earnings`,
  `__pycache__` and `*.pyc`; carry those across and add `.env*`, `node_modules`, `legacy/`,
  `docs/`, `tests/`, `.github/` and `web/dist`. `tests/meta/test_repo_hygiene.py` asserts the
  full list is present so it cannot silently regress.
- **Verification:** `docker build -f docker/Dockerfile -t borrelbeurs:test .` succeeds ·
  `docker run --rm borrelbeurs:test ls -la /app` shows no `.tar`, no `keys.json`, no `legacy`, no
  `tests` · `docker run --rm --entrypoint sh borrelbeurs:test -c 'id -u'` prints `1001` ·
  `docker history --no-trunc borrelbeurs:test | grep -ci '\.tar'` returns 0 ·
  `docker run --rm -e DATABASE_URL=... -e JWT_SECRET=... -p 8000:8000 borrelbeurs:test` then
  `curl -fsS localhost:8000/healthz` returns ok · `pytest tests/meta/test_repo_hygiene.py`
- **Depends on:** T9

### T11 — CI workflow

- **Implements:** AC4, AC5
- **Expected output:** `.github/workflows/ci.yml` — one workflow on every PR and every push to
  `main` (§7.3:1179). Three jobs: `check` (checkout → set up Python and Node at the pinned
  versions → restore cache → frozen installs → **`./scripts/check.sh`**, with a Postgres 16
  service container for the integration step), `secret-scan` (gitleaks over full history) and
  `docker` (build `docker/Dockerfile`, tag `<git-sha>`, no push). Concurrency group per ref so a
  new push cancels the previous run. **`check` calls the identical script a developer runs — the
  step list is not restated in YAML.** That is what makes AC4 structurally true rather than a
  promise someone has to keep.
- **Verification:** open a throwaway PR; all three jobs green; the `check` job log shows the same
  nine steps in the same order as local `./scripts/check.sh` output · push a commit with a lint
  error — `check` fails and the PR shows the merge blocked · push a commit containing
  `AKIAIOSFODNN7EXAMPLE` — `secret-scan` fails
- **Depends on:** T10

### T12 — Repository governance

- **Implements:** AC5 (the "shall block the merge" half), AC7
- **Expected output:** Branch protection on `main`: PR required, required status checks =
  `check` / `secret-scan` / `docker`, dismiss stale approvals, no force-push, no deletion, linear
  history. Secret scanning **and push protection** enabled. `.github/dependabot.yml` for pip, npm
  and github-actions, grouped weekly. `.github/CODEOWNERS` covering `db/migrations/` and
  `docker/`. `.github/PULL_REQUEST_TEMPLATE.md` per Appendix F, including the new-dependency
  block. `.github/ISSUE_TEMPLATE/{bug,feedback}.yml`. **§7.1:1123 also requires ≥1 approving
  review, which a single-operator repo cannot satisfy — see R5.** The waiver is recorded in
  `docs/adr/0010-single-operator-review-waiver.md`, naming the compensating controls (required
  status checks plus the `fresh-eyes-reviewer` agent) and the trigger that revisits it (a second
  contributor).
- **Verification:** `gh api repos/<owner>/borrelbeurs/branches/main/protection` shows the three
  required checks and `allow_force_pushes: false` ·
  `gh api repos/<owner>/borrelbeurs/secret-scanning/alerts` returns 200 ·
  **AC7 directly:** on a throwaway branch, commit a line matching a known provider pattern and
  `git push` — the push is rejected by push protection. Keep the rejection message as evidence.
- **Depends on:** T11

### T13 — `CLAUDE.md`, agent configuration and the migration hook

- **Implements:** spec In-scope 8 (`CLAUDE.md`, under a page); ADR 0004:36
- **Expected output:** `CLAUDE.md` of ≤1 page following Appendix E: commands
  (`./scripts/setup.sh`, `./scripts/check.sh`, `uv run alembic ...`), the workflow loop,
  conventions and a Never list. It **must** state that Postgres is the persistence layer — v1's
  `CLAUDE.md` says the opposite and ADR 0004:36 flags that as actively misleading. It must define
  what `lib/` and `core/` mean in this repo, or the repo must stop using those names (§5.2:825).
  `.claude/settings.json` committed with an allow-list of safe commands, a deny covering
  `legacy/`, secrets and production, and a `PreToolUse` hook blocking writes to any file under
  `db/migrations/versions/` that is not the newest revision (§5.6:893, §4.7:644).
- **Verification:** `wc -w CLAUDE.md` under ~500 · `grep -i postgres CLAUDE.md` matches and
  `grep -i "don't introduce a database" CLAUDE.md` does not · ask the agent to edit
  `db/migrations/versions/0001_baseline.py` and confirm the hook blocks it, keeping the block
  message as evidence
- **Depends on:** T7

---

## Traceability

| AC | Tasks |
|---|---|
| AC1 — `setup.sh` on a clean checkout | T7, T8 |
| AC2 — fail fast at boot, naming the variable | T3, T5 |
| AC3 — env read only in the config module | T3, T4 |
| AC4 — `check.sh` and CI agree | T2, T9, T11 |
| AC5 — CI runs the gate and blocks merges | T11, T12 |
| AC6 — build context and image exclude junk | T1, T6, T10 |
| AC7 — push protection rejects secrets | T12 |

| Task | Maps back to |
|---|---|
| T1 | AC6 (the repo carries no tarballs) + spec In-scope 1 |
| T2 | AC4 (pinned toolchain) + spec In-scope 2 |
| T3 | AC2, AC3 |
| T4 | AC3 |
| T5 | AC2 + Exit condition ("a running shell app") |
| T6 | AC6 (real image contents) + Exit condition |
| T7 | AC1 |
| T8 | AC1 |
| T9 | AC4 |
| T10 | AC6 |
| T11 | AC4, AC5 |
| T12 | AC5, AC7 |
| T13 | spec In-scope 8 + ADR 0004:36 |

T5, T6 and T13 serve the Exit condition or an ADR consequence rather than a numbered AC. **If the
audit rejects that justification, T5 and T6 are the cut — but AC6's verification then weakens to
asserting things about an image we will not ship.**

---

## Data changes

No application tables. One Alembic baseline revision that creates nothing, so `alembic_version`
exists and Phase 2's first real migration has a parent. Reversible by definition — `downgrade
base` drops nothing. Expand/contract does not apply yet. Migration files are named
`NNNN_slug.py` so ordering is readable in a directory listing.

---

## New dependencies

Per §5.3:843 and Appendix F, each needs a note. Most are already fixed by the design documents —
marked *pre-approved* with the citation. **Four are my choice and need your explicit approval.**

| Package | Status | Note |
|---|---|---|
| fastapi, uvicorn, pydantic | Pre-approved | ADR 0001:27, ADR 0002:18 |
| numpy `==1.26.4` | Pre-approved | ADR 0002:9; pinned exactly per D2 |
| sqlalchemy 2.0, asyncpg | Pre-approved | [architecture.md:211](../design/architecture.md#L211) |
| alembic | Pre-approved | [data-model.md:3](../design/data-model.md#L3) |
| pytest, testcontainers | Pre-approved | phase-1 spec:82, phase-2 spec:56 |
| react, react-dom, react-router | Pre-approved | [frontend-architecture.md:13](../design/frontend-architecture.md#L13) — inside the five-dependency budget |
| vite, typescript, eslint, prettier, vitest, eslint-plugin-boundaries | Pre-approved | frontend-architecture.md:43, 187; §5.1:657 |
| gitleaks (CI action) | Pre-approved | §7.3:1194 |
| **uv** | **NEW — needs approval** | Python package manager and resolver, written in Rust. Not the standard library: pip has no lockfile, and §5.1:661 requires a committed lockfile with frozen installs. Alternatives: pip-tools (lockfile but no environment management — two tools), Poetry (slower, heavier, worse Docker caching). Licence MIT/Apache-2.0. Maintained by Astral; very active. ~35 MB, build stage only. |
| **ruff** | **NEW — needs approval** | Linter and formatter in one; replaces black, flake8 and isort. Not stdlib. Licence MIT. Astral; very active. |
| **mypy** | **NEW — needs approval** | Static type checker. Not stdlib. §4.6:601 requires a clean type check, so something must fill this slot; mypy is the reference implementation. Licence MIT. Alternative: pyright, which would drag Node into the Python gate. |
| **pydantic-settings** | **NEW — needs approval** | Parses environment variables into a validated pydantic model. Not stdlib — `os.environ` hands back unvalidated strings, which is exactly what AC2 and AC3 exist to prevent. First-party pydantic package, licence MIT, small. |

Phase 0 deliberately does **not** install argon2, openpyxl, zustand, lightweight-charts, zod or
Playwright. Those belong to the phases that use them.

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Golden-fixture reproducibility.** Phase 1 captures fixtures from v1 and replays them on v2. If Phase 0 picks a different Python or numpy, a mismatch in Phase 1 will look like a porting bug and cost days. | D1 and D2 pin both to v1's exact versions. T2's verification confirms `exchange.engine` is importable from the new repo before Phase 1 starts. |
| R2 | **`check.sh` on Windows.** You work on Windows 11; `setup.sh` and `check.sh` are bash. AC1 says "without further manual steps" and the verification specifies a machine that has never run the project. | The scripts target Git Bash, which ships with Git for Windows and is already in use in this session. The README states the requirement. **Resolved at the audit: Git Bash only, no PowerShell parity.** |
| R3 | **Migrations at boot contradict §5.6:897.** D10 chooses boot-migration on the strength of ADR 0003's advisory lock and the offline laptop's lack of CI. No document sanctions it. | **Resolved at the audit:** D10 accepted. `docs/adr/0009-migrate-at-boot.md` records it before T7 is built. |
| R4 | **Compose is "a development tool only, never a deployment artifact" per §5.5:885 and the Phase 0 spec, but the offline production runtime per ADR 0004:28-30 and Phase 8 AC10.** | Phase 0 builds one `docker-compose.yml` that satisfies the development case and, by digest-pinning both images, does not block the offline case. Resolving the contradiction is Phase 8's; flagging it so it is not discovered there. |
| R5 | **Branch protection requires ≥1 approving review (§7.1:1123), and the SDR records a single operator (ADR 0001:3).** GitHub will not let you approve your own PR. | **Resolved at the audit:** waive the review requirement, compensating with required status checks plus the `fresh-eyes-reviewer` agent. T12 configures everything else and records the waiver in `docs/adr/0010-single-operator-review-waiver.md`. |
| R6 | **Two toolchains in one image.** A node:22 build stage feeding a python:3.11 runtime is new for this project; cache behaviour and image size are unknown. | T10 is its own task with its own verification precisely so this surfaces in isolation rather than inside T11's CI debugging. |
| R7 | **T1 is outward-facing and hard to reverse.** Creating a repo and abandoning the old one decides where the project lives. | T1 does not run until the audit ticks it with the repo name confirmed. This plan does not delete or archive the old repo. |
| R8 | **v1's access keys stay in the old repo's history.** A fresh repo leaves them behind but does not invalidate them (ADR 0007:42-43). Rotation is Phase 8 AC17. | Out of scope here, but the old repo should be made private or archived when the new one takes over. Raised so it is not forgotten for eight phases. |
| R9 | **Several ADRs have corrupted prose** — dropped words and mangled table rows in 0001:24-25, 0001:56-59, 0003:36-43, 0006:34-41, 0007:35-42. The decisions are legible; the reasoning is damaged. | This plan cites them because the decisions are clear. They deserve a cleanup pass before they become an audit trail nobody can read. Not Phase 0 work. |
| R10 | **Empty test directories.** `tests/engine/` holds nothing until Phase 1, and pytest exits 5 on "no tests collected" — which would make `check.sh` red on day one. | T9 handles exit code 5 per directory rather than applying a blanket suppression that would later hide genuine collection errors. |

### Open questions — answered at the audit (2026-09-21)

| # | Question | Answer |
|---|---|---|
| 1 | Repo name and visibility | **`borrelbeurs`, private** — D14 confirmed. T1 has its go-ahead. |
| 2 | Accept D10 (migrate at boot)? ADR 0009? | **Accepted.** Record it as `docs/adr/0009-migrate-at-boot.md` before T7 is built, citing ADR 0003's advisory lock and the offline laptop's lack of CI as the grounds for departing from §5.6:897. |
| 3 | R5 — approving-review requirement | **Waived**, compensated by required status checks + `fresh-eyes-reviewer`. Recorded in `docs/adr/0010-single-operator-review-waiver.md`. |
| 4 | R2 — Git Bash or PowerShell parity? | **Git Bash only.** No PowerShell parity; the README states the requirement. Not a scope addition. |
| 5 | Approval for `uv`, `ruff`, `mypy`, `pydantic-settings` | **All four approved.** |
| 6 | Do T5 and T6 survive without a numbered AC? | **Both kept.** The Exit condition justifies them, and T6 keeps AC6's assertion about the image actually shipped. The three no-AC extras (T5's logging/errors skeletons, T6's `eslint-plugin-boundaries` + `src/api/generated/`, T12's issue templates) are kept as planned. |

---

## Out of scope for this plan

- Any pricing, persistence, API or UI **behaviour** — the shell app computes nothing and stores nothing.
- `render.yaml`, Render service creation, deployment, the production Dockerfile's size target,
  SBOM generation and the Trivy gate — all Phase 8
  ([phase-8 spec:13-14](../specs/phase-8-deploy-cutover.md)).
- Extracting or touching `exchange/engine.py` — Phase 1. It is carried in and left alone.
- The advisory-lock implementation — Phase 3 AC18. T5's lifespan leaves a named seam, not a lock.
- The OpenAPI→TypeScript drift check and the no-external-request check on built output — Phases 3
  and 4 own them; T11's workflow is shaped so they drop in as jobs without restructuring.
- Rotating v1's leaked keys — Phase 8 AC17 (see R8).
- `docs/runbooks/`, `docs/gated-sites.md`, `nightly-scan.yml`, the weekly rebuild-and-scan job.
  All are §5.2/§9.1 items, none are in the Phase 0 spec, and none gate Phase 1.
- Deleting `legacy/v1/` — Phase 8, once nothing references it.
- A feature-flag mechanism — not specified anywhere for this project, and nothing user-visible ships here.

---

## Audit (human — tick before implementation starts)

- [x] Every AC maps to ≥1 task — all seven traced; AC7 rests on T12 alone
- [x] Every task maps to ≥1 AC — T1, T2, T13 map to In-scope items 1, 2, 8; T5 and T6 to the Exit condition, accepted at the audit
- [x] Each task's expected output is what we actually need — accepted, with the four corrections below applied
- [x] Existing patterns reused; no reinvention (T4 reuses the purity-test pattern from architecture.md:87-89; T11 reuses `check.sh` instead of restating it in YAML; T13 carries v1's `.claude/` across; T10 extends v1's `.dockerignore`)
- [x] No new dependency without approval — `uv`, `ruff`, `mypy`, `pydantic-settings` approved at the audit
- [x] Data changes additive/reversible (one empty baseline migration; D10's boot-migration departure accepted and moved to ADR 0009)
- [x] Errors, empty states and permissions covered as tasks
- [x] Each task reviewable in one sitting — **with a waiver:** T1 and T2 exceed the limit as purely mechanical import and `git mv`, and T6 exceeds it on file count largely through a generated `pnpm-lock.yaml`. Accepted.
- [x] Verification named per task — **known gap:** T5's `logging.py`/`errors.py` skeletons and T13's `.claude/settings.json` allow/deny list carry no verification step. Accepted as-is.
- [x] Nothing touches prod, secrets or infra it should not — T1 (repo creation) and T12 (GitHub settings) both have their explicit go-ahead as of this audit; R8's unrotated v1 keys remain deferred to Phase 8

**Corrections applied at the audit:** `src/features/` added to T6 · `.dockerignore` relabelled
extend-not-create in the Files table and T10 · R5's waiver given a named file (ADR 0010) ·
`.claude/commands/rebuild.md` committed so T1's carry-across does not silently drop it.

Audited by: **MartijnBoot** Date: **2026-09-21**
