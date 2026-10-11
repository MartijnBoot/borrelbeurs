# BorrelBeurs

A drink stock exchange for student borrels. Prices move live with demand, idle decay and
Brownian noise; bar staff place orders, a big screen shows the market, admins pull the levers.

> **Status: Phase 8 (deploy and cutover), in progress.** The engine, API, web app, admin and
> analytics are built (Phases 0-7). Phase 8 adds the image, CI, the Render deploy and the
> offline venue stack; see [Deploy and venue](#deploy-and-venue).

## Requirements

- **Git Bash** — `setup.sh` and `check.sh` are bash. On Windows, use the Git Bash that ships
  with Git for Windows. There is no PowerShell equivalent and there will not be one.
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
run it again after pulling. `check.sh` is the gate: format, lint, types, unit and integration
tests, in that order, and it is the same script CI runs.

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
| `tests/` | `unit/`, `integration/`, `engine/` (golden fixtures), `meta/` (boundary checks) |
| `docs/` | Specs, ADRs, design notes and the rebuild plan |
| `legacy/v1/` | v1, verbatim and frozen. Reference only — no gate reads it, nothing imports it |

Start with [docs/README.md](docs/README.md). Architectural decisions are in
[docs/adr/](docs/adr/); the rebuild route is [docs/plans/rebuild-route.md](docs/plans/rebuild-route.md).

## Deploy and venue

CI builds one image and pushes it to GHCR by commit SHA on `main`; merging deploys nothing.
Real events run on a laptop with no internet (`deploy/venue/`); Render is the hosted option.
The runbooks in [docs/runbooks/](docs/runbooks/) cover each case:
[deploy](docs/runbooks/deploy.md), [rollback](docs/runbooks/rollback.md),
[restore](docs/runbooks/restore.md), [the venue](docs/runbooks/venue.md) and
[incidents](docs/runbooks/incident.md).

## Licence

Proprietary — see [LICENSE](LICENSE).
