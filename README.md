# BorrelBeurs

A drink stock exchange for student borrels. Prices move live with demand, idle decay and
Brownian noise; bar staff place orders, a big screen shows the market, admins pull the levers.

> **Status: Phase 0, in progress.** The repository skeleton and toolchain pins are in place.
> `scripts/setup.sh`, `scripts/check.sh` and the application shell arrive later in this phase
> (plan tasks T5-T9). Until then the setup below is the target, not yet the reality.

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
| `scripts/` | `setup.sh`, `check.sh` |
| `tests/` | `unit/`, `integration/`, `engine/` (golden fixtures), `meta/` (boundary checks) |
| `docs/` | Specs, ADRs, design notes and the rebuild plan |
| `legacy/v1/` | v1, verbatim and frozen. Reference only — no gate reads it, nothing imports it |

Start with [docs/README.md](docs/README.md). Architectural decisions are in
[docs/adr/](docs/adr/); the rebuild route is [docs/plans/rebuild-route.md](docs/plans/rebuild-route.md).

## Licence

Proprietary — see [LICENSE](LICENSE).
