# ADR 0007: Close the v1 authorization gap before the rebuild

Date: 2026-09-12 · Status: Implemented (commit `b617a56`)

## Context

The audit preceding the rebuild found that v1 had **no API-level authorization at all**.
Every mutating endpoint was open: `/order`, `/config`, `/price-jump`, `/market-crash`,
`/reset`, `/drinks`, `/news`, `/upload/theme-image`.

The page routes did have RBAC (`backend/auth.py:76-88`), but it was decorative — they
redirect to `/static/<page>.html`, and `app.mount("/static", StaticFiles(...))` served those
unauthenticated. Anyone who could reach the port could open the admin page and reset a live
event.

The rebuild is months of work. Leaving this open for that long was not acceptable.

## Decision

A self-contained hotfix against v1, on branch `fix/api-authorization`, separate from the
rebuild:

1. Gate the `/static` mount with the same role rules as the page routes, keeping
   `login.html` and `theme.js` public so login still works.
2. Add a `require_role()` dependency and apply it to all 16 API routes.
3. Require a session on the `/ws` handshake.
4. Let `/shutdown` accept an admin session as well as `X-Admin-Token` — the settings page
   never sent the header, so that button always returned 401.
5. Generate and persist `config/.jwt_secret` in `run.bat`. `JWT_SECRET` previously fell back
   to a per-process random value (`auth.py:20`), logging out every bar tablet on restart.
6. Add `.dockerignore`. The Dockerfile did `COPY . .` with no exclusions, so
   `bierbeurs-image.tar` was copied into the image it built.
7. Untrack `config/keys.json`.

## Consequences

- Verified with a 31-check suite against the real app and by building and running the
  container. Anonymous requests blocked, roles enforced, login flow intact, WebSocket gated.
- Image size measured at **1.65 GB → 406 MB**. Reaching the tens of MB needs the multi-stage
  build and trimmed dependencies scheduled for the rebuild's Phase 8; `python:3.11-slim`
  plus numpy plus the `fastapi` 0.111 dependency tree accounts for most of the remainder.
- **The v1 access keys remain in git history and must be rotated.** Untracking the file does
  not remove it from past commits. The fresh repository leaves that history behind.
- This work is thrown away when v2 lands. That is the correct trade for closing a live hole.
