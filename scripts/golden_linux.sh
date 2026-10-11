#!/usr/bin/env bash
# The golden tests (and the fixtures' capture) in a Linux container.
#
# The golden numbers are captured on Linux under the numeric pin in
# tests/engine/golden/__init__.py; the C maths library differs on Windows, so the tests skip
# there and this is how a laptop runs them. The image is the one the app ships on, by digest.
#
#   scripts/golden_linux.sh            # replay and reproduce the committed fixtures
#   scripts/golden_linux.sh --write    # recapture them (a deliberate behaviour change only)
#
# Git Bash only; needs docker.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_IMAGE="python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce"

if ! command -v docker >/dev/null 2>&1; then
  echo "scripts/golden_linux.sh: 'docker' is required but not installed." >&2
  exit 1
fi

# Works on a copy, so the host's .venv (Windows) and node_modules stay out of it; --write
# copies the fixtures back.
MODE="${1:-check}"
case "$MODE" in
  check | --write) ;;
  *)
    echo "usage: scripts/golden_linux.sh [--write]" >&2
    exit 2
    ;;
esac

MSYS_NO_PATHCONV=1 docker run --rm -e MODE="$MODE" \
  -v "$REPO_ROOT":/src -w /work "$PYTHON_IMAGE" bash -c '
set -euo pipefail
mkdir /work/repo && cd /work/repo
tar -C /src --exclude=.venv --exclude=node_modules --exclude=web --exclude=bundle \
  --exclude=.git -cf - . | tar -xf -
pip install --quiet uv
uv sync --frozen --quiet
if [ "$MODE" = "--write" ]; then
  uv run python -m tests.engine.golden.capture --write
  cp tests/engine/golden/fixtures/*.json /src/tests/engine/golden/fixtures/
else
  uv run python -m tests.engine.golden.capture --check
  uv run pytest tests/engine -q
fi
'
