"""HTTP routers. Everything the application exposes lives under `/api/*`.

The one exception is `app/api/health.py`: `/healthz` and `/readyz` are probes
for the platform, not application endpoints (ADR 0001:24). Render's health
check and the image's `HEALTHCHECK` both address them at the root, and moving
them under `/api` would only mean writing the same path twice in two Dockerfiles.
"""
