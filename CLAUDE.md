# CLAUDE.md

Guidance for Claude Code when working in this repo.

## Project

**BorrelBeurs** — a "drink stock exchange" web app for student borrels. Drink prices fluctuate live based on demand, idle decay, Brownian noise, and admin-triggered jumps/crashes. Bar staff place orders, a big screen shows live prices, admins configure parameters.

Detailed architecture (component diagram + request/WS flow) lives in [ARCHITECTURE.md](ARCHITECTURE.md). Read it before non-trivial changes.

## Stack

- **Backend:** FastAPI + Uvicorn (Python 3.11), single worker, in-memory `ExchangeState` synchronized via WebSocket broadcast.
- **Engine:** [exchange/engine.py](exchange/engine.py) — pricing model (prices, demand, BM noise, idle decay, scheduled jumps).
- **Frontend:** static HTML/JS pages in [static/](static/) (no build step). Pages: `login`, `home` (admin), `koers` (display), `bar`, `manipulation`, `settings`. Theming via [static/theme.js](static/theme.js).
- **Auth:** key-based login → JWT cookie session, RBAC per page ([backend/auth.py](backend/auth.py)). Keys in `config/keys.json`.
- **Persistence:** JSON config + per-event xlsx earnings workbooks + news.json ([backend/persistence.py](backend/persistence.py)).
- **Deploy:** Docker. [run.bat](run.bat) loads `bierbeurs-image.tar` (or builds), mounts `./config` and `./static` into the container, exposes port 8000.

## Layout

- [backend/api.py](backend/api.py) — routes, WS `/ws`, order pipeline, jump/crash endpoints.
- [backend/auth.py](backend/auth.py) — `validate_key`, `require_page`, role landing.
- [backend/config.py](backend/config.py) — paths (`CONFIG_PATH`, `STATIC_DIR`, etc.), driven by env vars.
- [backend/persistence.py](backend/persistence.py) — engine load/save, xlsx earnings, news CRUD.
- [exchange/engine.py](exchange/engine.py) — `ExchangeState`, `single_step`, `prices_from_y`, calibration.
- [config/exchange_config.json](config/exchange_config.json) — live engine config (mounted volume).
- [static/](static/) — all client pages + uploads/logo/earnings dirs.

## Running locally

- Docker: `run.bat` (Windows) — prefers loading `bierbeurs-image.tar`, else builds. Container name `bierbeurs`, port 8000, default admin token `TestTest`.
- Rebuild after backend changes: `rebuild.bat` — builds the image, re-exports `bierbeurs-image.tar`, then calls `run.bat`. (`run.bat` alone won't pick up Python changes if a stale tar/image exists.)
- Dev (no Docker): `py -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload` (see top of [backend/api.py](backend/api.py)). `--reload` only watches Python; `static/` is served live, so frontend edits need no restart (hard-refresh the browser).
- Deps: [requirements.txt](requirements.txt) (FastAPI 0.111, numpy 1.26, openpyxl, PyJWT).
- No automated test suite — verify changes by running the app (Docker or uvicorn) and exercising the relevant page.
- Config resolution ([backend/config.py](backend/config.py)): paths come from `CONFIG_PATH`, `STATIC_DIR`, `DEFAULT_CONFIG_PATH` env vars. An empty/`{}` `exchange_config.json` falls back to the baked-in default template.

## Conventions

- Order requests carry a `snapshot_version`; server returns 409 on stale snapshots — preserve this when touching the order path.
- After any state mutation, save engine + broadcast over `/ws`. Don't mutate state without broadcasting.
- Frontend pages are plain HTML — no bundler, no framework. Keep changes vanilla JS/CSS.
- Pricing math (`a`, `d`, `s0`, `alpha_price`, `eta`, `K`, decay/idle params) is meaningful — don't rename or restructure config keys without checking [exchange/engine.py](exchange/engine.py) and existing `exchange_config.json`.
- UI strings are Dutch; keep that consistent.

## Don't

- Don't commit `static/earnings/*.xlsx`, `static/uploads/*`, or real `config/keys.json` contents.
- Don't change WebSocket broadcast format without updating every page in [static/](static/) that consumes it.
- Don't introduce a database — file-based JSON/xlsx persistence is intentional for offline event use.
