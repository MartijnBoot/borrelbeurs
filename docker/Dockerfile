# BorrelBeurs — the one deployment artifact (plan T10, AC6).
#
# Two toolchains, two stages: `web-build` compiles the SPA with the exact Node
# this repo pins (.nvmrc); `runtime` installs only the Python dependencies the
# app needs to run — never ruff, mypy, pytest or testcontainers — and serves
# both the API and the built frontend from one process (docs/design/
# architecture.md:23). Both base images are digest-pinned: ADR 0004 makes the
# offline venue laptop a real target, and `docker save` there must bundle the
# exact image that was tested, not whatever the tag points at today.
#
# Layer order in both stages is manifests -> install -> source, so editing
# `app/` or `web/src/` never invalidates the dependency-install layer.

# --- Stage 1: compile the SPA -------------------------------------------------

FROM node:22-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS web-build
WORKDIR /web

# Manifests only, so `pnpm install` is cached until a dependency changes.
COPY web/package.json web/pnpm-lock.yaml ./
# pnpm itself isn't in the base image; pinned to the exact version CI uses
# (.github/workflows/ci.yml), so the image builds what the gate tested.
RUN npm install --global --no-fund --no-audit pnpm@9.15.9 \
    && pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# --- Stage 2: runtime ----------------------------------------------------------

FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

# Manifests only. `uv` is this project's resolver (D6) everywhere else, so the
# image installs through it too rather than introducing pip-compile or a
# hand-exported requirements.txt as a second source of truth; pinned to the
# version this repo develops against, then removed in this same layer so it
# never reaches the final image. So is every other packaging tool the base
# image carries -- pip, setuptools, wheel, ensurepip's bundled wheels -- and
# every vendored `tests` directory (greenlet's, numpy's): nothing at runtime
# installs a package or runs a library's own tests (Phase 8 T11, D-43, PD9).
# `--no-cache` keeps uv's wheel cache out of /root; and websockets' deprecated
# `legacy` package goes too -- uvicorn's `auto` WebSocket protocol is the
# sans-I/O one, which never imports it (scripts/ci/check_image.py bans any
# directory named `legacy`, so this would otherwise fail the image).
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.14 \
    && uv sync --frozen --no-dev --no-install-project --no-cache \
    && pip uninstall --yes uv \
    && /usr/local/bin/python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /usr/local/bin/pip* /usr/local/lib/python3.11/ensurepip/_bundled \
    && find /usr/local/lib/python3.11 /app/.venv -depth -type d -name tests -exec rm -rf {} + \
    && rm -rf /app/.venv/lib/python3.11/site-packages/websockets/legacy

# Source, after dependencies are resolved — `exchange/` and `db/` are plain
# packages this app imports, not separately installed.
COPY app/ ./app/
COPY exchange/ ./exchange/
COPY db/ ./db/
COPY --from=web-build /web/dist ./web/dist

# Unprivileged: a compromised request handler gets a UID with no home
# directory and no shell, not root.
RUN useradd --uid 1001 --no-create-home --shell /usr/sbin/nologin appuser
USER 1001

# The commit this image is built from (Phase 8 SD7): CI passes `github.sha`;
# `/healthz` and the start log report it, so a deploy can tell which image runs.
# Declared after the dependency install: an ARG is an environment variable of every
# later RUN, so earlier it would rebuild that ~200 MB layer for every commit.
ARG BUILD_SHA=unknown
ENV BUILD_SHA=$BUILD_SHA
LABEL org.opencontainers.image.revision=$BUILD_SHA

# `/healthz` is 200 while the ticker loop turns (and in standby), and 503 once
# it has not turned for three intervals (app/api/health.py) -- the liveness a
# probe should ask about; a database outage alone fails `/readyz`, not this.
# Plain `python`, not curl: the slim base
# doesn't carry curl, and the interpreter that already has to be here is one
# fewer thing to install.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c 'import os, urllib.request as u; u.urlopen("http://127.0.0.1:" + os.environ.get("PORT", "8000") + "/healthz", timeout=2)' || exit 1

EXPOSE 8000

# `python -m app.main`, not `uvicorn app.main:app`: app/main.py's own `main()`
# reads `settings.port` (plan D11, PORT defaults to 8000), so the port Render
# injects is honoured without a shell-form CMD re-parsing $PORT.
CMD ["python", "-m", "app.main"]
