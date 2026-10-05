#!/usr/bin/env bash
# BorrelBeurs -- clone-to-running-stack, in one command (AC1, plan T8).
#
# On a clean checkout this generates .env.local, installs both toolchains
# from their lockfiles, starts Postgres and applies migrations -- "without
# further manual steps" (AC1) means nothing beyond this and one run command
# (README's Setup section).
#
# Idempotent: running it again -- after a pull, or after `docker compose
# down -v` throws the database away -- exits 0 and leaves the same stack
# running. Nothing here is safe to run twice by accident; each step below is
# safe to run twice on purpose.
#
# Git Bash only (plan R2). No PowerShell equivalent, and there will not be one.

set -euo pipefail

# Resolve the repository root from this file's own location rather than the
# caller's working directory, so `./scripts/setup.sh` and
# `some/other/dir$ ../../scripts/setup.sh` do the same thing.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- toolchain, checked before anything is touched ---------------------------
# A missing tool fails here, named, rather than midway through a half-applied
# install with a confusing error from whichever command needed it.
require() {
  local tool="$1" hint="$2"
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "scripts/setup.sh: '${tool}' is required but not installed. ${hint}" >&2
    exit 1
  fi
}

require docker "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
require uv "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
require pnpm "Install pnpm: https://pnpm.io/installation (or 'corepack enable pnpm')"

# --- .env.local, generated once -----------------------------------------------
# `.env.example` ships a JWT_SECRET placeholder too short to pass validation
# (app/core/config.py) on purpose -- a committed secret would be a leaked one.
# Generated only when .env.local is absent: regenerating it on every run would
# invalidate every session on each restart, and would make a second run
# something other than the no-op this script promises.
if [ ! -f .env.local ]; then
  secret="$(openssl rand -hex 32)"
  sed "s|^JWT_SECRET=.*|JWT_SECRET=${secret}|" .env.example > .env.local
  echo "scripts/setup.sh: wrote .env.local with a generated JWT_SECRET"
else
  echo "scripts/setup.sh: .env.local already exists, leaving it as is"
fi

# --- dependencies, frozen ------------------------------------------------------
uv sync --frozen
pnpm --dir web install --frozen-lockfile
# The gate's e2e step drives Chromium (Phase 4 T23); a no-op once installed.
pnpm --dir web exec playwright install chromium

# --- Postgres, waited for rather than assumed ---------------------------------
# `--wait` blocks until docker-compose.yml's healthcheck reports healthy, or
# this fails after --wait-timeout -- either way, the migration step below never
# runs against a database that cannot yet take a connection.
docker compose up -d --wait --wait-timeout 60 db

# --- migrations ----------------------------------------------------------------
# app/core/config.py reads only the process environment and loads no .env file
# itself (spec AC3), so .env.local must be exported before anything that
# imports it runs -- db/migrations/env.py among them. This is the "exporting
# it is the caller's job" the config module's own docstring names this script
# as responsible for.
set -a
# shellcheck disable=SC1091  # .env.local does not exist until the block above
. ./.env.local
set +a

uv run alembic -c db/alembic.ini upgrade head
