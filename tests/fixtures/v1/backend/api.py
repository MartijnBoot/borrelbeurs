# backend/api.py
# py -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload

import os
import uuid
import secrets
import signal
import time
import asyncio
from typing import Dict, List, Optional, Literal, Set
import pathlib
import hashlib
import json
import threading

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, conint, confloat

from .auth import (validate_key, make_token, get_session, require_page, require_role,
                   role_allows, COOKIE_NAME, ROLE_LANDING, PUBLIC_STATIC, STATIC_PAGE_ROUTES)

# --- local module imports ---
from .config import CONFIG_PATH, STATIC_DIR, BAR_PRICE_PATH, UPLOADS_DIR
from exchange.engine import ExchangeState, prices_from_y, expected_flow_from_price, calibrate_s0_to_p0, now_ms
from .persistence import (
    load_engine_from_config, save_engine,
    start_new_earnings_workbook, append_sale_to_workbook,
    earnings_summary_from_workbook, finalize_current_earnings, 
    current_earnings_filename, HAVE_XLSX,
    get_news_list, append_news_item, delete_news_item
)

# ----------------------------- API models -----------------------------
class OrderItem(BaseModel):
    drink: str
    qty: conint(ge=0)

class BatchOrder(BaseModel):
    orders: List[OrderItem]
    snapshot_version: Optional[int] = None

class NewsPost(BaseModel):
    text: str
    level: Optional[Literal["Info","Success","Warning","Danger"]] = "Info"

class PriceJumpReq(BaseModel):
    drink: str
    target_price: float = Field(ge=0)
    duration_ms: int = Field(ge=10)

class MarketCrashReq(BaseModel):
    duration_ms: int = Field(default=30000, ge=100)
    target: Literal["min", "max", "mid"] = "min"

class ConfigUpdate(BaseModel):
    p_min: Optional[Dict[str, confloat(ge=0)]] = None
    p_max: Optional[Dict[str, confloat(gt=0)]] = None
    p0:    Optional[Dict[str, confloat(ge=0)]] = None
    bar_price: Optional[Dict[str, confloat(ge=0)]] = None
    a: Optional[Dict[str, float]] = None
    d: Optional[Dict[str, float]] = None
    s0: Optional[Dict[str, float]] = None
    c: Optional[Dict[str, float]] = None
    alpha_price: Optional[float] = None
    lambda_orders: Optional[float] = None
    eta: Optional[float] = None
    K: Optional[float] = None
    step_quant: Optional[float] = None
    phi_persist: Optional[float] = None
    decay_rho: Optional[float] = None
    history_window_minutes: Optional[float] = None
    refresh_minutes: Optional[float] = None
    idle_decay_minutes: Optional[float] = None
    idle_strength: Optional[float] = None
    idle_targets: Optional[List[str]] = None
    idle_rise_minutes: Optional[float] = None
    idle_rise_strength: Optional[float] = None
    idle_rise_targets: Optional[List[str]] = None
    bm_enabled: Optional[bool] = None
    bm_sigma: Optional[float] = None
    bm_dt_minutes: Optional[float] = None
    bm_sigma_y: Optional[float] = None
    flow_vol_amp: Optional[float] = None
    flow_beta: Optional[float] = None
    y_clip: Optional[float] = None
    auto_calibrate_s0: Optional[bool] = None
    demand_enabled: Optional[bool] = None
    anchor_s0: Optional[bool] = None

class DrinkSpec(BaseModel):
    name: str
    p_min: confloat(ge=0)
    p_max: confloat(ge=0)
    p0: confloat(ge=0)
    bar_price: Optional[float] = None
    a: Optional[float] = 10.0
    d: Optional[float] = 0.6
    s0: Optional[float] = 8.0
    c: Optional[float] = 0.4

class DrinksOp(BaseModel):
    op: Literal["add", "remove"]
    drink: Optional[DrinkSpec] = None
    name: Optional[str] = None

class LoginRequest(BaseModel):
    key: str


# ----------------------------- app & state -----------------------------
app = FastAPI(title="Drink Exchange Backend", version="5.3")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Block cross-origin state-modifying requests.
    Same-origin requests (from frontend pages served by this server) do not
    include an Origin header, so they pass through. Cross-origin fetch
    attempts from a malicious site include Origin, which won't match Host.
    """
    origin = request.headers.get("origin")
    if origin is not None and request.method in ("POST", "PUT", "DELETE", "PATCH"):
        host = request.headers.get("host", "")
        origin_host = origin.split("://", 1)[-1].rstrip("/")
        if origin_host != host:
            return JSONResponse({"error": "CSRF check failed"}, status_code=403)
    return await call_next(request)

@app.middleware("http")
async def static_authz(request: Request, call_next):
    """Gate the /static mount with the same rules as the page routes.

    The mount serves every page HTML directly, so without this the RBAC on
    /, /koers, /bar, /settings and /manipulation can be bypassed by asking
    for /static/<page>.html instead.
    """
    path = request.url.path
    if not path.startswith("/static/"):
        return await call_next(request)

    name = path[len("/static/"):].rsplit("/", 1)[-1]
    if name in PUBLIC_STATIC:
        return await call_next(request)

    is_page = path.endswith(".html")
    session = get_session(request)
    if not session:
        if is_page:
            return RedirectResponse("/login", status_code=302)
        return JSONResponse({"ok": False, "error": "Niet ingelogd"}, status_code=401)

    route = STATIC_PAGE_ROUTES.get(name)
    if route and not role_allows(session.get("role", ""), route):
        return RedirectResponse("/login", status_code=302)

    return await call_next(request)

engine: ExchangeState = load_engine_from_config(CONFIG_PATH)
state_lock = asyncio.Lock()

# --- bar price sidecar (kept independent from engine) ---
def _load_bar_prices(names: List[str], default: List[float]) -> np.ndarray:
    # bar_price in exchange_config seeds the initial values (overrides p0 default)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg_bar = (json.load(f) or {}).get("bar_price", {})
    except Exception:
        cfg_bar = {}
    # bar_prices.json (written by the UI) takes final precedence
    try:
        with open(BAR_PRICE_PATH, "r", encoding="utf-8") as f:
            mp = json.load(f) or {}
    except Exception:
        mp = {}
    idx = {nm: i for i, nm in enumerate(names)}
    out = np.array(default, float)
    for k, v in cfg_bar.items():
        j = idx.get(k)
        if j is not None:
            out[j] = float(v)
    for k, v in mp.items():
        j = idx.get(k)
        if j is not None:
            out[j] = float(v)
    return out

def _save_bar_prices(names: List[str], arr: np.ndarray) -> None:
    mp = {names[i]: float(arr[i]) for i in range(len(names))}
    try:
        with open(BAR_PRICE_PATH, "w", encoding="utf-8") as f:
            json.dump(mp, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[bar_price] save failed: {e}")

# bar price vector (defaults to p0 if sidecar empty)
BAR_PRICE = _load_bar_prices(engine.names, engine.p0)

# create a workbook for the current game on boot
start_new_earnings_workbook()

def _name_to_idx(names: List[str]): return {nm: i for i, nm in enumerate(names)}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----------------------------- Auth -----------------------------
@app.get("/login")
async def serve_login():
    return _redir("login.html")

@app.post("/auth/login")
async def auth_login(req: LoginRequest):
    role = validate_key(req.key)
    if not role:
        return JSONResponse({"ok": False, "error": "Ongeldige toegangscode."}, status_code=401)
    token = make_token(role)
    redirect = ROLE_LANDING.get(role, "/")
    response = JSONResponse({"ok": True, "role": role, "redirect": redirect})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response

@app.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response

@app.get("/auth/me")
async def auth_me(request: Request):
    session = get_session(request)
    if not session:
        return JSONResponse({"ok": False}, status_code=401)
    return {"ok": True, "role": session.get("role")}

# ----------------------------- Theme image upload -----------------------------
_ALLOWED_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

@app.post("/upload/theme-image", dependencies=[Depends(require_role("admin"))])
async def upload_theme_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        raise HTTPException(400, f"Bestandstype niet toegestaan. Gebruik: {', '.join(_ALLOWED_IMAGE_EXTS)}")
    contents = await file.read()
    if len(contents) > _MAX_IMAGE_BYTES:
        raise HTTPException(400, "Bestand te groot (max 5 MB)")
    filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOADS_DIR, filename), 'wb') as f:
        f.write(contents)
    return {"url": f"/static/uploads/{filename}"}

@app.delete("/upload/theme-image/{filename}", dependencies=[Depends(require_role("admin"))])
async def delete_theme_image(filename: str):
    if '/' in filename or '\\' in filename or '..' in filename:
        raise HTTPException(400, "Ongeldige bestandsnaam")
    dest = os.path.join(UPLOADS_DIR, filename)
    if not os.path.isfile(dest):
        raise HTTPException(404, "Bestand niet gevonden")
    os.remove(dest)
    return {"ok": True}

# ----------------------------- WebSocket manager -----------------------------
class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, message: dict):
        dead = []
        try:
            data = json.dumps(message)
        except Exception as e:
            print(f"[broadcast] JSON serialization failed: {e}")
            return
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()
refresh_wakeup = asyncio.Event()

def _poke_broadcast_loop():
    # set+clear allows quick consecutive pokes
    if not refresh_wakeup.is_set():
        refresh_wakeup.set()

# ----------------------------- endpoints -----------------------------
@app.get("/state", dependencies=[Depends(require_role())])
async def get_state():
    async with state_lock:
        return _snapshot_payload_unlocked()
    

@app.get("/earnings", dependencies=[Depends(require_role("bar", "admin"))])
async def get_earnings():
    async with state_lock:
        return earnings_summary_from_workbook(engine.names, BAR_PRICE)

@app.get("/financials", dependencies=[Depends(require_role("bar", "admin"))])
async def get_financials():
    """Returns live financial data without updating LAST_SNAPSHOT or advancing engine state."""
    async with state_lock:
        return {
            "earnings": earnings_summary_from_workbook(engine.names, BAR_PRICE),
            "totals_ordered": engine.totals_ordered.tolist(),
            "revenue_per_drink": engine.revenue_per_drink.tolist(),
        }

@app.get("/earnings-file", dependencies=[Depends(require_role("bar", "admin"))])
async def get_earnings_file():
    summary = earnings_summary_from_workbook(engine.names, BAR_PRICE)
    file_url = summary.get("file_url")
    if not file_url:
        return {"ok": False, "error": "No earnings file yet"}
    fname = file_url.split("/")[-1]
    path = os.path.join(STATIC_DIR, "earnings", fname)
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if HAVE_XLSX else "text/csv"
    return FileResponse(path, filename=fname, media_type=media_type)

@app.post("/order", dependencies=[Depends(require_role("bar", "admin"))])
async def post_order(batch: BatchOrder):
    if batch.snapshot_version is not None and batch.snapshot_version != LAST_SNAPSHOT["version"]:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "stale_snapshot",
                    "current_version": LAST_SNAPSHOT["version"],
                    "prices": LAST_SNAPSHOT["p_q"].tolist()}
        )

    async with state_lock:
        items = [o.model_dump() for o in batch.orders]
        vec = engine.ordered_vector(items)

        # EMA for BM volatility
        engine.flow_ema = (1.0 - engine.params.flow_beta) * engine.flow_ema + engine.params.flow_beta * vec

        # last order ts
        nowts = now_ms()
        for i, q in enumerate(vec):
            if q > 0:
                engine.last_order_ts[i] = nowts

        # prices BEFORE tick for charging
        snap_p_q = LAST_SNAPSHOT["p_q"]
        snap_p_cont = LAST_SNAPSHOT["p_cont"]

        # advance engine
        logs = engine.single_step(vec)
        engine.t_round += 1
        engine.totals_ordered += vec

        # revenue & excel logging per sold line
        name_map = {nm: i for i, nm in enumerate(engine.names)}
        for it in items:
            nm, qty = it.get("drink"), float(it.get("qty", 0))
            if nm in name_map and qty > 0:
                j = name_map[nm]
                unit_price = float(snap_p_q[j])   # <-- snapshot quantized
                engine.revenue_per_drink[j] += unit_price * qty
                append_sale_to_workbook(
                    drink=nm, qty=qty, unit_price=unit_price,
                    p_cont=float(snap_p_cont[j]),  # <-- snapshot continuous, for analytics
                    p_min=float(engine.p_min[j]), p_max=float(engine.p_max[j]),
                    t_round=engine.t_round, ts_ms=nowts
                )

        engine.apply_price_jumps_if_needed()

        # engine._snapshot(nowts)
        # engine.last_snapshot_ts_ms = nowts
        engine._trim_history()
        broadcast_payload = _save_snapshot()
    await manager.broadcast(broadcast_payload)
    return {
        "ok": True,
        "t": engine.t_round,
        "charged_prices": snap_p_q.tolist(),
        "snapshot_version": LAST_SNAPSHOT["version"],
        "logs": logs,
    }



@app.post("/config", dependencies=[Depends(require_role("bar", "admin"))])
async def update_config(cfg: ConfigUpdate):
    async with state_lock:
        idx = _name_to_idx(engine.names)

        def apply_map(field: str, arr: np.ndarray):
            mp = getattr(cfg, field)
            if mp:
                for k, v in mp.items():
                    j = idx.get(k)
                    if j is not None:
                        arr[j] = float(v)
        
        for field, arr in (("p_min", engine.p_min), ("p_max", engine.p_max), ("p0", engine.p0),
                           ("a", engine.a), ("d", engine.d), ("s0", engine.s0), ("c", engine.c)):
            apply_map(field, arr)

        if cfg.bar_price:
            for k, v in cfg.bar_price.items():
                j = idx.get(k)
                if j is not None:
                    BAR_PRICE[j] = float(v)
            _save_bar_prices(engine.names, BAR_PRICE)

        scalars = cfg.model_dump(exclude_none=True)
        if "bm_sigma" in scalars and "bm_sigma_y" not in scalars:
            scalars["bm_sigma_y"] = scalars.pop("bm_sigma")

        for k in ["alpha_price","lambda_orders","eta","K","step_quant","phi_persist","decay_rho",
                  "history_window_minutes","refresh_minutes",
                  "idle_decay_minutes","idle_strength",
                  "idle_rise_minutes","idle_rise_strength",
                  "bm_dt_minutes","bm_sigma_y","flow_vol_amp","flow_beta","y_clip"]:
            if k in scalars and hasattr(engine.params, k):
                setattr(engine.params, k, float(scalars[k]))
        
        if "bm_enabled" in scalars:
            engine.params.bm_enabled = bool(scalars["bm_enabled"])
        if "auto_calibrate_s0" in scalars:
            engine.params.auto_calibrate_s0 = bool(scalars["auto_calibrate_s0"])
        if "demand_enabled" in scalars:
            engine.params.demand_enabled = bool(scalars["demand_enabled"])
        if "idle_targets" in scalars:
            known = set(engine.names)
            engine.params.idle_targets = [nm for nm in scalars["idle_targets"] if nm in known]
        if "idle_rise_targets" in scalars:
            known = set(engine.names)
            engine.params.idle_rise_targets = [nm for nm in scalars["idle_rise_targets"] if nm in known]
 
        engine.retarget_y_to_hold_quantized_prices()
        if cfg.model_dump(exclude_none=True).get("anchor_s0", False):
            calibrate_s0_to_p0(engine)

        if "refresh_minutes" in cfg.model_dump(exclude_none=True):
            refresh_wakeup.set()

        payload = _save_snapshot()
    await manager.broadcast(payload)
    _poke_broadcast_loop()  # wake the loop so new interval applies immediately
    return {"ok": True, "params": engine.params.to_dict(), "bar_price": BAR_PRICE.tolist()}


@app.post("/price-jump", dependencies=[Depends(require_role("bar", "admin"))])
async def price_jump(req: PriceJumpReq):
    async with state_lock:
        res = engine.schedule_price_jump(req.drink, float(req.target_price), int(req.duration_ms))
        if res.get("ok"):
            save_engine(CONFIG_PATH, engine)
            payload = _snapshot_payload_unlocked()   # build inside lock
        else:
            payload = None
    if payload is not None:
        await manager.broadcast(payload)             # broadcast outside
    return res

@app.post("/market-crash", dependencies=[Depends(require_role("bar", "admin"))])
async def market_crash(req: MarketCrashReq):
    async with state_lock:
        for i, name in enumerate(engine.names):
            if req.target == "min":
                p_target = float(engine.p_min[i])
            elif req.target == "max":
                p_target = float(engine.p_max[i])
            else:  # mid
                p_target = float(engine.p0[i])
            engine.schedule_price_jump(name, p_target, int(req.duration_ms))

        # Auto-generate news item for the market event
        if req.target == "min":
            news_text = "MARKTCRASH! Alle prijzen kelderen naar hun minimum!"
            news_level = "Danger"
        elif req.target == "max":
            news_text = "PRIJSBUBBEL! Alle prijzen schieten omhoog naar hun maximum!"
            news_level = "Warning"
        else:
            news_text = "Marktcorrectie: Prijzen keren terug naar startpositie."
            news_level = "Info"
        ts = now_ms()
        rid = f"{ts}-{int(np.random.default_rng().integers(10_000, 99_999))}"
        append_news_item({"id": rid, "ts_ms": ts, "level": news_level, "text": news_text})

        # Track active event for frontend animations
        _active_market_event["type"] = req.target
        _active_market_event["end_ms"] = ts + int(req.duration_ms)

        payload = _save_snapshot()
    await manager.broadcast(payload)
    return {"ok": True, "n": len(engine.names), "target": req.target, "duration_ms": req.duration_ms}

@app.post("/finalize-earnings", dependencies=[Depends(require_role("admin"))])
async def finalize_earnings_endpoint():
    """Finalize current earnings (write Summary sheet) and return the file URL."""
    async with state_lock:
        try:
            finalize_current_earnings(engine.names, BAR_PRICE)
        except Exception as e:
            print(f"[finalize-earnings] failed: {e}")
        summary = earnings_summary_from_workbook(engine.names, BAR_PRICE)
        file_url = summary.get("file_url")
        filename = file_url.split("/")[-1] if file_url else None
        return {"ok": bool(file_url), "file_url": file_url, "filename": filename}

@app.post("/reset", dependencies=[Depends(require_role("admin"))])
async def reset_endpoint():
    async with state_lock:
        try:
            finalize_current_earnings(engine.names, BAR_PRICE)
        except Exception as e:
            print(f"Warning: could not finalize earnings file: {e}")

        start_new_earnings_workbook()
        
        frac = ((engine.p0 - engine.p_min) / (engine.p_max - engine.p_min)).clip(1e-9, 1 - 1e-9)
        engine.y[:] = np.log(frac / (1 - frac))
        if engine.params.auto_calibrate_s0:
            calibrate_s0_to_p0(engine)
        engine.cum_orders[:] = 0
        engine.totals_ordered[:] = 0
        engine.revenue_per_drink[:] = 0.0
        engine.history.clear()
        engine.t_round = 0
        ts = now_ms()
        engine._snapshot(ts)
        engine.last_snapshot_ts_ms = ts
        engine.last_order_ts[:] = ts
        engine.last_idle_apply_ms = 0
        engine.last_bm_ts_ms = 0
        engine.price_jumps.clear()
        payload = _save_snapshot()
    await manager.broadcast(payload)
    return {"ok": True, "msg": "Game reset."}

def _drinks_to_dicts(eng: ExchangeState) -> List[dict]:
    """Serialize current engine drinks to a list of dicts."""
    return [{
        "name": eng.names[i],
        "p_min": float(eng.p_min[i]),
        "p_max": float(eng.p_max[i]),
        "p0":    float(eng.p0[i]),
        "a":     float(eng.a[i]),
        "d":     float(eng.d[i]),
        "s0":    float(eng.s0[i]),
        "c":     float(eng.c[i]),
    } for i in range(len(eng.names))]


def _rebuild_engine_from_drinks(drinks: List[dict], params) -> ExchangeState:
    """Create a fresh ExchangeState from a list of drink dicts, preserving params."""
    return ExchangeState.init(
        [d["name"] for d in drinks],
        np.array([d["p_min"] for d in drinks], float),
        np.array([d["p_max"] for d in drinks], float),
        np.array([d["p0"]    for d in drinks], float),
        np.array([d.get("a",  10.0) for d in drinks], float),
        np.array([d.get("d",   0.6) for d in drinks], float),
        np.array([d.get("s0",  8.0) for d in drinks], float),
        np.array([d.get("c",   0.4) for d in drinks], float),
        params,
    )


def _save_snapshot() -> dict:
    """Persist engine state and return a broadcast payload.

    Must be called while state_lock is held. Caller is responsible for
    broadcasting the returned payload after releasing the lock.
    """
    save_engine(CONFIG_PATH, engine)
    return _snapshot_payload_unlocked()


def _require_admin(request: Request):
    """Allow either an admin session cookie or the X-Admin-Token header.

    The settings page calls /shutdown without the header, so the token-only
    check meant the button always 401'd. The session path fixes that; the
    header path is kept so scripts and healthchecks keep working.
    """
    session = get_session(request)
    if session and session.get("role") == "admin":
        return

    admin_token = os.getenv("ADMIN_TOKEN", "")
    provided = request.headers.get("X-Admin-Token", "")
    # Reject if no token configured, or if comparison fails (timing-safe)
    if not admin_token or not secrets.compare_digest(provided.encode(), admin_token.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- robust shutdown route ---
@app.post("/shutdown")
async def shutdown(request: Request):
    _require_admin(request)
    # finalize earnings, but never fail shutdown because of it
    try:
        async with state_lock:
            try:
                finalize_current_earnings(engine.names, BAR_PRICE)
            except Exception as e:
                print(f"[shutdown] finalize failed: {e}")
    except Exception as e:
        # even if state_lock/finalize trips, still continue shutting down
        print(f"[shutdown] pre-exit error: {e}")

    # Send SIGTERM after response flushes; uvicorn handles graceful drain
    def _kill():
        time.sleep(0.25)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_kill, daemon=True).start()
    return JSONResponse({"ok": True, "msg": "shutting down"})

@app.post("/drinks", dependencies=[Depends(require_role("admin"))])
async def drinks_endpoint(op: DrinksOp):
    global engine
    global BAR_PRICE
    if op.op == "add":
        async with state_lock:
            if not op.drink:
                return {"ok": False, "error": "Missing drink spec"}

            try:
                finalize_current_earnings(engine.names, BAR_PRICE)
            except Exception:
                pass

            drinks = _drinks_to_dicts(engine)
            drinks.append(op.drink.model_dump())
            engine = _rebuild_engine_from_drinks(drinks, engine.params)

            BAR_PRICE = np.append(BAR_PRICE, float(op.drink.bar_price if op.drink.bar_price is not None else op.drink.p0))
            _save_bar_prices(engine.names, BAR_PRICE)

            start_new_earnings_workbook()
            payload = _save_snapshot()
            result = {"ok": True, "msg": f"Added {op.drink.name}", "names": engine.names}
        await manager.broadcast(payload)
        return result

    elif op.op == "remove":
        async with state_lock:
            if not op.name or op.name not in engine.names:
                return {"ok": False, "error": "Drink name not found"}

            try:
                finalize_current_earnings(engine.names, BAR_PRICE)
            except Exception:
                pass

            keep_idx = [i for i in range(len(engine.names)) if engine.names[i] != op.name]
            drinks = [d for d in _drinks_to_dicts(engine) if d["name"] != op.name]
            engine = _rebuild_engine_from_drinks(drinks, engine.params)

            BAR_PRICE = BAR_PRICE[keep_idx]
            _save_bar_prices(engine.names, BAR_PRICE)

            start_new_earnings_workbook()
            payload = _save_snapshot()
            result = {"ok": True, "msg": f"Removed {op.name}", "names": engine.names}
        await manager.broadcast(payload)
        return result

    else:
        return {"ok": False, "error": "Unknown op"}


@app.get("/news", dependencies=[Depends(require_role())])
async def news_list():
    return JSONResponse({"ok": True, "news": get_news_list()},
                        headers={"Cache-Control": "no-store, max-age=0"})

@app.post("/news", dependencies=[Depends(require_role("bar", "admin"))])
async def news_add(item: NewsPost):
    async with state_lock:
        ts = now_ms()
        rid = f"{ts}-{int(np.random.default_rng().integers(10_000, 99_999))}"
        append_news_item({"id": rid, "ts_ms": ts, "level": item.level, "text": item.text.strip()[:500]})
        payload = _snapshot_payload_unlocked()  # no save needed — news persisted by append_news_item
    await manager.broadcast(payload)
    return {"ok": True, "id": rid}

@app.delete("/news/{news_id}", dependencies=[Depends(require_role("bar", "admin"))])
async def news_delete(news_id: str):
    async with state_lock:
        ok = delete_news_item(news_id)
        payload = _snapshot_payload_unlocked()  # no save needed — news persisted by delete_news_item
    await manager.broadcast(payload)
    return {"ok": ok}


# ----------------------------- static & health -----------------------------
def _ver(file_path: str) -> str:
    p = pathlib.Path(file_path)
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:12]
    except Exception:
        return str(int(time.time() * 1000))

# --- frontend routes ---
def _redir(fname: str):
    ver = _ver(os.path.join(STATIC_DIR, fname))
    resp = RedirectResponse(f"/static/{fname}?v={ver}", status_code=307)
    resp.headers.update({
        "Cache-Control": "no-store, max-age=0, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    })
    return resp

@app.get("/")
async def serve_home(request: Request):
    if (denied := require_page(request, "/")): return denied
    return _redir("home.html")

@app.get("/koers")
async def serve_koers(request: Request):
    if (denied := require_page(request, "/koers")): return denied
    return _redir("koers.html")

@app.get("/bar")
async def serve_bar(request: Request):
    if (denied := require_page(request, "/bar")): return denied
    return _redir("bar.html")

@app.get("/settings")
async def serve_settings(request: Request):
    if (denied := require_page(request, "/settings")): return denied
    return _redir("settings.html")

@app.get("/manipulation")
async def serve_manipulation(request: Request):
    if (denied := require_page(request, "/manipulation")): return denied
    return _redir("manipulation.html")

@app.get("/config-ui")
async def serve_config_ui(request: Request):
    if (denied := require_page(request, "/config-ui")): return denied
    return _redir("settings.html")

# --- payload builders ---

LAST_SNAPSHOT = {
    "version": 0,          # int: engine.last_snapshot_ts_ms
    "p_q": None,           # np.ndarray (quantized)
    "p_cont": None,        # np.ndarray (continuous)
}

# Active market event tracking: type is "min" (crash), "max" (bubble), "mid" (correction), or None
_active_market_event: dict = {"type": None, "end_ms": 0}

def _snapshot_payload_unlocked() -> dict:
    # assumes state_lock is already held by caller
    engine.apply_idle_adjust_if_needed()
    engine.apply_price_jumps_if_needed()
    engine.apply_bm_if_needed()
    engine.snapshot_if_due()

    p_cont, p_q = prices_from_y(engine.y, engine.p_min, engine.p_max, engine.params.step_quant)
    LAST_SNAPSHOT["version"] = int(engine.last_snapshot_ts_ms or now_ms())
    LAST_SNAPSHOT["p_q"] = p_q.copy()
    LAST_SNAPSHOT["p_cont"] = p_cont.copy()
    exp_flow = expected_flow_from_price(
        p_q, float(np.mean(p_q)), engine.a, engine.d, engine.s0, engine.c
    ) if engine.params.demand_enabled else np.zeros_like(p_q)

    hist = [{"ts": ts, "prices": p_q, "prices_disp": p_disp} for (ts, p_q, p_disp) in list(engine.history)]

    return {
        "type": "state",
        "snapshot_version": LAST_SNAPSHOT["version"],
        "t": engine.t_round,
        "names": engine.names,
        "prices_quant": p_q.tolist(),
        "prices_cont": p_cont.tolist(),
        "p_min": engine.p_min.tolist(),
        "p_max": engine.p_max.tolist(),
        "p0":    engine.p0.tolist(),
        "params": engine.params.to_dict(),
        "a": engine.a.tolist(),
        "d": engine.d.tolist(),
        "s0": engine.s0.tolist(),
        "c": engine.c.tolist(),
        "totals_ordered": engine.totals_ordered.tolist(),
        "revenue_per_drink": engine.revenue_per_drink.tolist(),
        "expected_demand": exp_flow.tolist(),   # <- optional but useful
        "history": hist,                        # <- needed by index.html
        "server_time_wall": time.time(),
        "earnings": earnings_summary_from_workbook(engine.names, BAR_PRICE),
        "bar_price": BAR_PRICE.tolist(),
        "news": get_news_list(),
        "market_event": _active_market_event["type"] if now_ms() < _active_market_event["end_ms"] else None,
    }

async def _snapshot_payload() -> dict:
    async with state_lock:
        return _snapshot_payload_unlocked()

# --- periodic WebSocket broadcast loop ---
async def _ws_broadcast_loop():
    while True:
        # build state under lock
        async with state_lock:
            payload = _snapshot_payload_unlocked()
            minutes = float(getattr(engine.params, "refresh_minutes", 1.0) or 1.0)
        await manager.broadcast(payload)

        # clamp to 2s–10min
        sleep_s = max(2.0, min(600.0, minutes * 60.0))

        # Sleep, but wake early if someone pokes the event
        try:
            refresh_wakeup.clear()
            await asyncio.wait_for(refresh_wakeup.wait(), timeout=sleep_s)
        except asyncio.TimeoutError:
            pass  # normal tick

@app.get("/logo/{filename}")
async def serve_logo(filename: str):
    """Serve logo files with case-insensitive and jpg/jpeg interchangeable lookup."""
    logo_dir = os.path.join(STATIC_DIR, "logo")
    MEDIA = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
    req_stem, req_ext = os.path.splitext(filename.lower())
    # jpg and jpeg are interchangeable
    jpeg_exts = {".jpg", ".jpeg"} if req_ext in {".jpg", ".jpeg"} else {req_ext}
    try:
        files = os.listdir(logo_dir)
        # Exact match (case-insensitive) first
        for f in files:
            if f.lower() == filename.lower():
                path = os.path.join(logo_dir, f)
                ext = os.path.splitext(f)[1].lower()
                return FileResponse(path, media_type=MEDIA.get(ext.lstrip("."), "application/octet-stream"), headers={"Cache-Control": "public, max-age=3600"})
        # Fallback: same stem, interchangeable jpeg extension
        for f in files:
            stem, ext = os.path.splitext(f.lower())
            if stem == req_stem and ext in jpeg_exts:
                path = os.path.join(logo_dir, f)
                return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="Logo not found")

@app.get("/healthz")
async def healthz():
    ok = len(engine.names) == len(engine.p_min) == len(engine.p_max) == len(engine.p0) == len(engine.y)
    return {"ok": ok, "n": len(engine.names)}

@app.middleware("http")
async def nocache_selected(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if (
        p in ("/", "/koers", "/bar", "/settings", "/manipulation", "/config-ui")
        or p.startswith("/static/home.html")
        or p.startswith("/static/koers.html")
        or p.startswith("/static/bar.html")
        or p.startswith("/static/settings.html")
        or p.startswith("/static/manipulation.html")
    ):
        resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.on_event("startup")
async def _start_background_tasks():
    from .auth import KEYS_PATH
    if not os.path.isfile(KEYS_PATH):
        print(f"[ERROR] keys.json not found at {KEYS_PATH} — every login will be "
              f"rejected. It is excluded from the image on purpose; mount ./config.")
    if not os.getenv("JWT_SECRET"):
        print("[WARNING] JWT_SECRET not set — every restart logs out all clients")
    asyncio.create_task(_ws_broadcast_loop())

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # The socket carries the full state payload, so it needs the same gate
    # as /state. 1008 = policy violation.
    if not get_session(ws):
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    try:
        # initial snapshot for this client only
        await ws.send_text(json.dumps(await _snapshot_payload()))
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
            elif msg == "state":
                await ws.send_text(json.dumps(await _snapshot_payload()))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)

# ----------------------------- run -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
