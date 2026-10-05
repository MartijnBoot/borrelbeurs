#!/usr/bin/env bash
# BorrelBeurs -- regenerate the web's API types from the app's OpenAPI schema
# (Phase 4 SD26, plan PD18).
#
# In-process, not over HTTP: create_app() is pure (no environment, no I/O), so
# its schema is dumped by `uv run python` straight to a temp file and
# openapi-typescript turns that into web/src/api/generated/schema.d.ts. The
# JSON schema itself is never committed -- only the generated types are.
#
# The gate (scripts/check.sh) runs this and then fails on any diff under
# web/src/api/generated, so a response model changed without regenerating is
# red. Developers run it after changing one.
#
# Git Bash only (plan R2).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Python makes the temp file and prints its native path: Git Bash's /tmp is
# not a path Node can open on Windows.
schema="$(uv run python -c '
import json, sys, tempfile
from app.main import create_app

with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="bb-openapi-", delete=False) as f:
    json.dump(create_app().openapi(), f)
sys.stdout.write(f.name)
')"
trap 'rm -f "$schema"' EXIT

pnpm --dir web exec openapi-typescript "$schema" -o src/api/generated/schema.d.ts
