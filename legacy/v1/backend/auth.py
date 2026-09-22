# backend/auth.py
import json
import os
import secrets
import jwt
from datetime import datetime, timedelta, timezone

from fastapi import Request, HTTPException
from starlette.requests import HTTPConnection
from fastapi.responses import RedirectResponse

from .config import BASE_DIR

KEYS_PATH = os.path.join(BASE_DIR, "config", "keys.json")
COOKIE_NAME = "bb_session"
JWT_ALG = "HS256"
SESSION_HOURS = 24

# Loaded once at module import; falls back to a random secret (invalidated on restart).
# Set JWT_SECRET env var for persistence across restarts.
JWT_SECRET: str = os.getenv("JWT_SECRET") or secrets.token_hex(32)
if not os.getenv("JWT_SECRET"):
    print("[WARNING] JWT_SECRET env var not set — sessions will be invalidated on restart")

# Role → which page routes are allowed
ROLE_PAGES: dict[str, set[str]] = {
    "display": {"/koers"},
    "bar":     {"/bar", "/manipulation"},
    "admin":   {"/", "/koers", "/bar", "/manipulation", "/settings", "/config-ui"},
}

# Role → landing page after login
ROLE_LANDING: dict[str, str] = {
    "display": "/koers",
    "bar":     "/bar",
    "admin":   "/",
}


def _load_keys() -> dict[str, str]:
    """Return {key: role} mapping from keys.json."""
    with open(KEYS_PATH, "r", encoding="utf-8") as f:
        return {entry["key"]: entry["role"] for entry in json.load(f)}


def validate_key(key: str) -> str | None:
    """Return role string if key is valid, else None."""
    try:
        return _load_keys().get(key.strip())
    except Exception:
        return None


def make_token(role: str) -> str:
    payload = {
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        return None


def get_session(request: HTTPConnection) -> dict | None:
    """Return decoded JWT payload from cookie, or None.

    Accepts a Request or a WebSocket -- both are HTTPConnections and both
    carry .cookies.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_token(token)


def require_page(request: Request, route: str) -> RedirectResponse | None:
    """Check that the session cookie grants access to `route`.

    Returns a RedirectResponse to /login if access is denied, else None.
    """
    session = get_session(request)
    if not session:
        return RedirectResponse("/login", status_code=302)
    role = session.get("role", "")
    allowed = ROLE_PAGES.get(role, set())
    if route not in allowed:
        return RedirectResponse("/login", status_code=302)
    return None


# --- Static file gating -------------------------------------------------
# Files under /static that must stay reachable without a session, because the
# login page itself needs them.
PUBLIC_STATIC: set[str] = {"login.html", "theme.js"}

# Static page -> the page route whose role rules apply to it. Serving these
# directly from the /static mount used to bypass require_page entirely.
STATIC_PAGE_ROUTES: dict[str, str] = {
    "home.html":         "/",
    "koers.html":        "/koers",
    "bar.html":          "/bar",
    "manipulation.html": "/manipulation",
    "settings.html":     "/settings",
}


def role_allows(role: str, route: str) -> bool:
    return route in ROLE_PAGES.get(role, set())


def require_role(*roles: str):
    """FastAPI dependency: 401 unless the session carries one of `roles`.

    Pass no roles to require only that a valid session exists.
    """
    allowed = set(roles)

    def _dep(request: Request) -> dict:
        session = get_session(request)
        if not session:
            raise HTTPException(status_code=401, detail="Niet ingelogd")
        if allowed and session.get("role") not in allowed:
            raise HTTPException(status_code=403, detail="Geen toegang")
        return session

    return _dep
