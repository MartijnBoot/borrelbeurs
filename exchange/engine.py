# exchange/engine.py
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Deque, Dict, List, Optional, Tuple, Any

import numpy as np

# ----------------------------- constants -----------------------------
# Small epsilon used to keep fractions strictly inside (0, 1) for log/sigmoid stability.
_FRAC_EPS = 1e-9
_FRAC_EPS_LOOSE = 1e-6  # looser bound used in barrier computation

# ----------------------------- utils -----------------------------
def now_ms() -> int:
    return int(time.time() * 1000)

def _sigmoid(x): return 1.0 / (1.0 + np.exp(-x))

def _inv_sigmoid(p):
    p = np.clip(p, _FRAC_EPS, 1 - _FRAC_EPS)
    return np.log(p / (1 - p))

def _quantize_step(x, step=0.5): return np.round(x / step) * step

def prices_from_y(y, p_min, p_max, step):
    p_cont = p_min + (p_max - p_min) * _sigmoid(y)
    p_q = _quantize_step(p_cont, step=step)
    return p_cont, p_q

def expected_flow_from_price(p_q: np.ndarray, p_mean: float,
                             a: np.ndarray, d: np.ndarray, s0: np.ndarray, c: np.ndarray) -> np.ndarray:
    lam = a - d * p_q + s0 + c * (p_mean - p_q)
    return np.maximum(0.0, lam)

def calibrate_s0_to_p0(engine: "ExchangeState"):
    _, p_q = prices_from_y(engine.y, engine.p_min, engine.p_max, engine.params.step_quant)
    p_mean0 = float(np.mean(p_q))
    engine.s0 = engine.d * p_q - engine.a - engine.c * (p_mean0 - p_q)

# ----------------------------- params -----------------------------
@dataclass
class Params:
    alpha_price: float = 0.0
    lambda_orders: float = 0.8
    eta: float = 0.6
    K: float = 12.0
    step_quant: float = 0.5
    phi_persist: float = 0.03
    decay_rho: float = 0.98
    history_window_minutes: float = 15.0
    refresh_minutes: float = 1.0
    idle_decay_minutes: float = 1.0
    idle_strength: float = 0.5
    idle_targets: List[str] = field(default_factory=list)
    idle_rise_minutes: float = 1.0
    idle_rise_strength: float = 0.5
    idle_rise_targets: List[str] = field(default_factory=list)
    bm_enabled: bool = True
    bm_sigma: float = 0.15          # legacy
    bm_dt_minutes: float = 1.0
    bm_sigma_y: float = 0.18        # volatility in y per √minute
    flow_vol_amp: float = 0.7
    flow_beta: float = 0.25
    y_clip: float = 6.0
    auto_calibrate_s0: bool = False
    demand_enabled: bool = True

    @classmethod
    def from_dict(cls, d: Dict) -> "Params":
        p = cls()
        for k, v in (d or {}).items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p

    def to_dict(self) -> Dict:
        return asdict(self)

# ----------------------------- price jump -----------------------------
@dataclass
class PriceJump:
    i: int               # drink index
    y0: float            # start y
    y1: float            # target y
    t0_ms: int           # start time
    t1_ms: int           # end time
    done: bool = False

# ----------------------------- engine state -----------------------------
@dataclass
class ExchangeState:
    names: List[str]
    p_min: np.ndarray
    p_max: np.ndarray
    p0:   np.ndarray
    a:    np.ndarray
    d:    np.ndarray
    s0:   np.ndarray
    c:    np.ndarray
    params: Params
    y: np.ndarray
    cum_orders: np.ndarray
    totals_ordered: np.ndarray
    revenue_per_drink: np.ndarray
    history: Deque[Tuple[int, List[float]]]
    last_snapshot_ts_ms: int
    last_order_ts: np.ndarray
    last_idle_apply_ms: int
    last_bm_ts_ms: int
    t_round: int = 0
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng())
    flow_ema: np.ndarray = field(default=None, repr=False)
    # new: active price jumps (one per drink index)
    price_jumps: Dict[int, PriceJump] = field(default_factory=dict)

    @classmethod
    def init(cls, names, p_min, p_max, p0, a, d, s0, c, params: Params) -> "ExchangeState":
        y = _inv_sigmoid((p0 - p_min) / (p_max - p_min))
        ts = now_ms()
        p_cont0, p_q0 = prices_from_y(y, p_min, p_max, params.step_quant)
        p_disp0 = _quantize_step(p_cont0, 0.01)
        st = cls(
            names=list(names), p_min=p_min, p_max=p_max, p0=p0, a=a, d=d, s0=s0, c=c, params=params,
            y=y, cum_orders=np.zeros(len(names)), totals_ordered=np.zeros(len(names)),
            revenue_per_drink=np.zeros(len(names)),
            history=deque(maxlen=100000), last_snapshot_ts_ms=ts,
            last_order_ts=np.full(len(names), ts, dtype=np.int64),
            last_idle_apply_ms=0, last_bm_ts_ms=0
        )
        st.flow_ema = np.zeros(len(names), dtype=float)
        st._append_hist(ts, p_q0, p_disp0)
        if st.params.auto_calibrate_s0:
            calibrate_s0_to_p0(st)
        return st

    def to_persist(self) -> Dict:
        return {
            "names": self.names,
            "p_min": self.p_min.tolist(),
            "p_max": self.p_max.tolist(),
            "p0":    self.p0.tolist(),
            "a":     self.a.tolist(),
            "d":     self.d.tolist(),
            "s0":    self.s0.tolist(),
            "c":     self.c.tolist(),
            "params": self.params.to_dict(),
        }

    @staticmethod
    def from_persist(d: Dict) -> "ExchangeState":
        names = d.get("names") or ["Bier","Wijn","Cola","Koffie","Gin-tonic","Mocktail"]
        p_min = np.array(d.get("p_min", [0.5,1.5,0.5,0.5,2.0,1.0]), float)
        p_max = np.array(d.get("p_max", [3.0,5.0,3.0,3.0,6.0,5.0]), float)
        p0    = np.array(d.get("p0",    [1.0,3.0,1.5,1.0,4.0,2.0]), float)
        n = len(names)
        a  = np.array(d.get("a",  [10.0]*n), float)
        d_ = np.array(d.get("d",  [0.6]*n), float)
        s0 = np.array(d.get("s0", [8.0]*n), float)
        c  = np.array(d.get("c",  [0.4]*n), float)
        params = Params.from_dict(d.get("params", {}))
        return ExchangeState.init(names, p_min, p_max, p0, a, d_, s0, c, params)

    def current_prices(self) -> Tuple[np.ndarray, np.ndarray, float]:
        p_cont, p_q = prices_from_y(self.y, self.p_min, self.p_max, self.params.step_quant)
        return p_cont, p_q, float(np.mean(p_q))

    def _snapshot(self, ts: Optional[int] = None):
        ts = now_ms() if ts is None else ts
        p_cont, p_q, _ = self.current_prices()
        p_disp = _quantize_step(p_cont, 0.01)
        self._append_hist(ts, p_q, p_disp)

    def retarget_y_to_hold_quantized_prices(self):
        _, p_q, _ = self.current_prices()
        frac = (np.array(p_q) - self.p_min) / (self.p_max - self.p_min)
        frac = np.clip(frac, _FRAC_EPS, 1 - _FRAC_EPS)
        self.y = np.log(frac / (1 - frac))

    def snapshot_if_due(self):
        interval_ms = max(1, int(self.params.refresh_minutes * 60_000))
        ts = now_ms()
        if ts - self.last_snapshot_ts_ms >= interval_ms:
            self._snapshot(ts)
            self.last_snapshot_ts_ms = ts
            self._trim_history()

    def single_step(self, orders_vec: np.ndarray) -> Dict:
        p_cont, p_q, p_mean = self.current_prices()
        exp_flow = expected_flow_from_price(p_q, p_mean, self.a, self.d, self.s0, self.c) if self.params.demand_enabled else np.zeros_like(p_q)

        dev = orders_vec - exp_flow
        N = len(self.names)
        if np.allclose(orders_vec, 0.0):
            order_pressure = np.zeros_like(dev)
        else:
            others_avg_dev = (np.sum(dev) - dev) / max(N - 1, 1)
            order_pressure = dev - self.params.lambda_orders * others_avg_dev

        self.cum_orders = self.params.decay_rho * self.cum_orders + dev
        cross = self.params.alpha_price * (p_mean - p_q) if self.params.alpha_price else np.zeros_like(p_q)
        E = order_pressure + self.params.phi_persist * self.cum_orders + cross

        frac = np.clip((p_cont - self.p_min) / (self.p_max - self.p_min), _FRAC_EPS_LOOSE, 1 - _FRAC_EPS_LOOSE)
        barrier = np.clip(frac * (1.0 - frac) * 4.0, 0.2, 1.0)
        E *= barrier

        y_next = self.y + self.params.eta * np.tanh(E / max(self.params.K, 1e-6))
        p_cont_next, p_q_next = prices_from_y(y_next, self.p_min, self.p_max, self.params.step_quant)

        step = self.params.step_quant
        tol = 1e-9
        for i in range(len(self.names)):
            if ((E[i] > 0) or (orders_vec[i] > 0)) and abs(p_q[i] - self.p_min[i]) <= tol and abs(p_q_next[i] - p_q[i]) <= tol:
                target = min(self.p_max[i], self.p_min[i] + step)
                p_q_next[i] = target
                f = np.clip((target - self.p_min[i]) / (self.p_max[i] - self.p_min[i]), _FRAC_EPS, 1 - _FRAC_EPS)
                y_next[i] = _inv_sigmoid(f)
            if ((E[i] < 0) or (orders_vec[i] < 0)) and abs(p_q[i] - self.p_max[i]) <= tol and abs(p_q_next[i] - p_q[i]) <= tol:
                target = max(self.p_min[i], self.p_max[i] - step)
                p_q_next[i] = target
                f = np.clip((target - self.p_min[i]) / (self.p_max[i] - self.p_min[i]), _FRAC_EPS, 1 - _FRAC_EPS)
                y_next[i] = _inv_sigmoid(f)

        self.y = y_next
        return {
            "p_now_q": p_q.tolist(),
            "p_now_cont": p_cont.tolist(),
            "p_next_q": p_q_next.tolist(),
            "p_next_cont": p_cont_next.tolist(),
            "order_pressure": order_pressure.tolist(),
            "cross_price_pressure": cross.tolist(),
            "cum_orders": self.cum_orders.tolist(),
        }

    # ----------------- idle decay / BM -----------------
    def apply_idle_adjust_if_needed(self):
        ts = now_ms()
        interval_ms = max(1, int(self.params.refresh_minutes * 60_000))
        if ts - self.last_idle_apply_ms < interval_ms:
            return

        # Nothing to do?
        if not (self.params.idle_targets or self.params.idle_rise_targets):
            self.last_idle_apply_ms = ts
            return

        _, p_q, p_mean = self.current_prices()
        exp_flow = expected_flow_from_price(
            p_q, p_mean, self.a, self.d, self.s0, self.c
        ) if self.params.demand_enabled else np.zeros_like(p_q)

        name_to_idx = {nm: i for i, nm in enumerate(self.names)}
        f = np.zeros(len(self.names), float)
        any_adj = False

        # decay (push down)
        if self.params.idle_targets:
            idle_ms = int(self.params.idle_decay_minutes * 60_000)
            for nm in self.params.idle_targets:
                j = name_to_idx.get(nm)
                if j is None: continue
                if ts - int(self.last_order_ts[j]) >= idle_ms:
                    base = exp_flow[j] if self.params.demand_enabled else 0.0
                    pop_weight = 1.0 + np.log1p(base)
                    f[j] -= abs(float(self.params.idle_strength)) * pop_weight
                    any_adj = True

        # rise (push up)
        if self.params.idle_rise_targets:
            rise_ms = int(self.params.idle_rise_minutes * 60_000)
            for nm in self.params.idle_rise_targets:
                j = name_to_idx.get(nm)
                if j is None: continue
                if ts - int(self.last_order_ts[j]) >= rise_ms:
                    base = exp_flow[j] if self.params.demand_enabled else 0.0
                    pop_weight = 1.0 + np.log1p(base)
                    f[j] += abs(float(self.params.idle_rise_strength)) * pop_weight
                    any_adj = True

        if not any_adj:
            self.last_idle_apply_ms = ts
            return

        self.single_step(f)
        self.t_round += 1
        self._snapshot(ts)
        self._trim_history()
        self.last_idle_apply_ms = ts

    def apply_bm_if_needed(self):
        if not self.params.bm_enabled:
            return
        ts = now_ms()
        dt_ms = max(1, int(self.params.bm_dt_minutes * 60_000))
        if ts - self.last_bm_ts_ms < dt_ms:
            return

        dt_min = dt_ms / 60_000.0
        sigma_y = float(self.params.bm_sigma_y)
        self.last_bm_ts_ms = ts
        if sigma_y <= 0:
            return

        ranges = self.p_max - self.p_min
        mean_range = float(np.mean(ranges)) if float(np.mean(ranges)) > 0 else 1.0
        range_scale = ranges / mean_range
        scale = range_scale * (1.0 + self.params.flow_vol_amp * np.log1p(self.flow_ema))
        dy = self.rng.normal(0.0, sigma_y * np.sqrt(dt_min), size=len(self.names)) * scale
        self.y = np.clip(self.y + dy, -self.params.y_clip, self.params.y_clip)

        self._snapshot(ts)
        self._trim_history()

    # ----------------- price jump (smoothstep) -----------------
    def _y_for_price_target(self, i: int, p_target: float) -> float:
        step = float(self.params.step_quant)
        p_target_q = float(_quantize_step(p_target, step))
        f = np.clip((p_target_q - self.p_min[i]) / (self.p_max[i] - self.p_min[i]), _FRAC_EPS, 1 - _FRAC_EPS)
        return float(_inv_sigmoid(f))

    def schedule_price_jump(self, name: str, p_target: float, duration_ms: int) -> Dict[str, Any]:
        idx = {nm: i for i, nm in enumerate(self.names)}.get(name)
        if idx is None:
            return {"ok": False, "error": f"unknown drink '{name}'"}
        y1 = self._y_for_price_target(idx, p_target)
        ts = now_ms()
        pj = PriceJump(i=idx, y0=float(self.y[idx]), y1=y1, t0_ms=ts, t1_ms=ts + max(1, int(duration_ms)))
        self.price_jumps[idx] = pj
        return {"ok": True, "i": idx, "t_end": pj.t1_ms}

    def apply_price_jumps_if_needed(self):
        if not self.price_jumps:
            return
        ts = now_ms()
        changed = False
        for i, pj in list(self.price_jumps.items()):
            if pj.done:
                continue
            if ts >= pj.t1_ms:
                self.y[i] = pj.y1
                pj.done = True
                changed = True
            else:
                # smoothstep easing
                f = (ts - pj.t0_ms) / max(1, pj.t1_ms - pj.t0_ms)
                f = np.clip(f, 0.0, 1.0)
                f = f * f * (3 - 2 * f)  # smoothstep
                self.y[i] = pj.y0 + f * (pj.y1 - pj.y0)
                changed = True
        # remove finished
        for k in [k for k, pj in self.price_jumps.items() if pj.done]:
            del self.price_jumps[k]
        if changed:
            self._snapshot(ts)
            self._trim_history()

    # ----------------- orders & history utils -----------------
    def ordered_vector(self, items: List[Dict[str, float]]) -> np.ndarray:
        idx = {nm: i for i, nm in enumerate(self.names)}
        vec = np.zeros(len(self.names), float)
        for it in items:
            nm, qty = it.get("drink"), float(it.get("qty", 0))
            if nm in idx and qty > 0:
                vec[idx[nm]] += qty
        return vec

    def _append_hist(self, ts: int, p_q, p_disp):
        entry_q = [float(x) for x in p_q]
        entry_disp = [float(x) for x in p_disp]
        # Dedup on the higher-resolution display track so sub-tick movement is captured.
        if not self.history or self.history[-1][2] != entry_disp:
            self.history.append((ts, entry_q, entry_disp))

    def _trim_history(self):
        window_ms = int(self.params.history_window_minutes * 60_000)
        if window_ms <= 0:
            return
        cutoff = now_ms() - window_ms
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()
