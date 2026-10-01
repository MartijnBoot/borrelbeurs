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
# pnpm itself isn't in the base image; pin the major the committed lockfile
# was written with (lockfileVersion 9.0).
RUN npm install --global --no-fund --no-audit pnpm@9 \
    && pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# --- Stage 2: runtime ----------------------------------------------------------

FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

# Manifests only. `uv` is this project's resolver (D6) everywhere else, so the
# image installs through it too rather than introducing pip-compile or a
# hand-exported requirements.txt as a second source of truth; pinned to the
# version this repo develops against, then removed in this same layer so it
# never reaches the final image.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.14 \
    && uv sync --frozen --no-dev --no-install-project \
    && pip uninstall --yes uv

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

# `/healthz` does no work and touches nothing (app/api/health.py) — exactly
# what a liveness probe should ask. Plain `python`, not curl: the slim base
# doesn't carry curl, and the interpreter that already has to be here is one
# fewer thing to install.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c 'import os, urllib.request as u; u.urlopen("http://127.0.0.1:" + os.environ.get("PORT", "8000") + "/healthz", timeout=2)' || exit 1

EXPOSE 8000

# `python -m app.main`, not `uvicorn app.main:app`: app/main.py's own `main()`
# reads `settings.port` (plan D11, PORT defaults to 8000), so the port Render
# injects is honoured without a shell-form CMD re-parsing $PORT.
CMD ["python", "-m", "app.main"]
