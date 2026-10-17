# BorrelBeurs

A drink stock exchange for student borrels. Prices move live with demand, idle decay and
Brownian noise; bar staff place orders, a big screen shows the market, admins pull the levers.

> **Status: live.** The v2 rebuild is finished (all nine phases). It runs on Render and on an
> offline venue laptop; see [Deploy and venue](#deploy-and-venue). The repository as the rebuild
> left it — v1's source, every phase plan, the build ledger — is at tag `v2-rebuild-complete`.

## Requirements

- **Git Bash** — `setup.sh` and `check.sh` are bash. On Windows, use the Git Bash that ships
  with Git for Windows. There is no PowerShell equivalent of either; `dev.ps1` only starts and
  stops a local dev stack (below).
- **Docker** (Desktop on Windows/macOS) — Postgres runs in a container.
- **Python 3.11** (`.python-version`) and [`uv`](https://docs.astral.sh/uv/).
- **Node 22** (`.nvmrc`) and [`pnpm`](https://pnpm.io/).

## Setup

```sh
git clone https://github.com/MartijnBoot/borrelbeurs.git
cd borrelbeurs
./scripts/setup.sh
./scripts/check.sh
```

`setup.sh` copies `.env.example` to `.env.local` with a generated secret, installs both
toolchains from their lockfiles, starts Postgres and applies migrations. It is idempotent —
run it again after pulling. `check.sh` is the gate: format, lint, types, the web build, unit,
integration and end-to-end tests, in that order, and it is the same script CI runs. The golden
engine tests run only on Linux; on Windows, `bash scripts/golden_linux.sh` runs them in the
pinned image.

To run it locally: `uv run uvicorn app.main:app --reload --port 8000`, or, in PowerShell,
`./dev.ps1 up` (Postgres, migrations, the API on :8000 and Vite on :5173; `./dev.ps1 down`
stops them).

## Working on it

New work follows one loop, one fresh session per step: `/backlog` → `/spec` → `/plan` →
`/audit` → `/build` → `/verify` → `/review`. See [.claude/README.md](.claude/README.md) and,
for agents, [CLAUDE.md](CLAUDE.md).

## Layout

| Path | What lives there |
|---|---|
| `app/` | FastAPI backend — API routes, realtime, config, persistence |
| `exchange/` | The pricing engine. Pure: no clock, no I/O, no framework |
| `web/` | Vite + React + TypeScript frontend, served from the same origin |
| `db/` | Alembic migrations |
| `docker/` | Dockerfile and build context |
| `scripts/` | `setup.sh`, `check.sh`, `smoke.py`, `make_bundle.sh`, `ci/` (image checks, Trivy) |
| `deploy/venue/` | The offline venue stack: compose file, `.cmd` wrappers, `LEESMIJ.md` |
| `tests/` | `unit/`, `integration/`, `engine/` (golden fixtures), `meta/` (boundary checks), `fixtures/v1/` (the v1 files the tests read, hash-pinned) |
| `docs/` | Specs, ADRs, design notes, runbooks, the backlog and the rebuild review |
| `dev.ps1` | PowerShell: start/stop the local dev stack |

Start with [docs/README.md](docs/README.md). Architectural decisions are in
[docs/adr/](docs/adr/); the invariants every change keeps are in
[docs/plans/rebuild-route.md](docs/plans/rebuild-route.md).

## Deploy and venue

CI builds one image and pushes it to GHCR by commit SHA on `main`; merging deploys nothing.
Real events run on a laptop with no internet (`deploy/venue/`); Render is the hosted option.
The runbooks in [docs/runbooks/](docs/runbooks/) cover each case:
[deploy](docs/runbooks/deploy.md), [rollback](docs/runbooks/rollback.md),
[restore](docs/runbooks/restore.md), [the venue](docs/runbooks/venue.md) and
[incidents](docs/runbooks/incident.md).

## Licence

Proprietary — see [LICENSE](LICENSE).
