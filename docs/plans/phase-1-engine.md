# Plan: Phase 1 — Engine extraction and golden tests

Spec: [docs/specs/phase-1-engine.md](../specs/phase-1-engine.md) · Status: Approved
Design: [architecture.md §The engine](../design/architecture.md#the-engine-pure-with-a-reproducible-noise-stream), [§Module layout](../design/architecture.md#module-layout)
ADRs honoured: 0002 (engine stays Python, maths untouched), 0003 (one owner of time; v1 Brownian is not elapsed-time-scaled), 0009/0010 (hard stops: pricing-maths ambiguity, golden-fixture divergence)
Defects fixed: D-21, D-22, D-23 ([defect-register.md:45-47](../specs/defect-register.md#L45-L47))

---

## Approach

Capture first, refactor second, and keep the v1 engine runnable for the rest of the project.
T1 moves `exchange/engine.py` **verbatim** (`git mv`, hash-pinned) to
`tests/engine/v1_reference/engine.py`, then drives it with a fake clock through six scripted
scenarios that reproduce *exactly* the call sequences v1's API makes — the order path
([legacy/v1/backend/api.py:350-392](../../legacy/v1/backend/api.py#L350-L392)) followed, as
v1 does, by the broadcast-payload sequence `idle → jumps → brownian`
([api.py:775-777](../../legacy/v1/backend/api.py#L775-L777)). The resulting fixtures are
committed before a line of `exchange/` is rewritten. The new package is then built bottom-up —
`pricing` + `spec`, `state`, `steps` (three slices), `advance` — with every step tested
**bitwise against the v1 reference** on the same inputs, so a divergence is caught in the
task that introduces it rather than at the end in a 1800-row golden diff. Two things that
lived in `api.py`, not the engine, move into `apply_orders` because they are pricing state:
the `flow_ema` update and `last_order_ts` (api.py:355-361).

The counter-based RNG is the one place where "identical numbers" and "replace the RNG" pull
against each other: v1's seeded `Generator` stream and `default_rng(SeedSequence([run_seed,
rng_counter]))` produce different draws, so no refactor can reproduce fixtures captured with
the former. The plan resolves it at capture time: the harness injects into v1's `engine.rng`
a shim whose `.normal()` derives each draw from `(run_seed, counter)` exactly as the new engine
will (D1). Rejected alternatives: capturing with a plain seeded `default_rng(seed)` (makes AC1
unsatisfiable by construction); capturing with Brownian disabled (scenario 1 would no longer
be the live config, which is the spec's reason for its existence); and leaving `engine.py` in
`exchange/` as the reference (it imports `time`, so AC2 could only pass by not walking it).

---

## Decisions this plan makes

These are choices the spec and design leave open. **D1, D5 and D6 need explicit confirmation
at the audit** — each touches pricing maths, which is on the hard-stop list.

| # | Question | Decision | Reason |
|---|---|---|---|
| D1 | How golden fixtures can be "identical" with a new RNG | Capture injects a shim into v1's `engine.rng`: each `.normal(loc, scale, size)` call returns `default_rng(SeedSequence([run_seed, k])).normal(loc, scale, size)` for `k = 0, 1, 2, …` (one `k` per Brownian firing that draws). The new engine computes the same with `k = state.rng_counter` | The only reading under which spec In-scope 5 and AC1 both hold. Formula is the one in [architecture.md:82](../design/architecture.md#L82) |
| D2 | Where the v1 code lives after extraction | `git mv exchange/engine.py tests/engine/v1_reference/engine.py`, byte-identical, sha256 pinned by a test; excluded from ruff/mypy | Keeps recapture and differential testing possible forever; `exchange/` then imports no clock. `legacy/v1/` may not be edited, so it cannot go there |
| D3 | What one golden event means | Four event kinds, each the exact v1 API sequence: `tick` = idle→jumps→bm (api.py:775-777); `order(vec)` = flow_ema, last_order_ts, single_step, t_round+1, jumps (api.py:352-387) **then** the tick sequence (via `_save_snapshot`, api.py:392→585-592); `jump(drink, target, dur)` = schedule then the tick sequence (api.py:469-472); `crash(target, dur)` = schedule for every drink then the tick sequence (api.py:482-509). `snapshot_if_due` and history are not recorded — they never touch `y` | History leaves the package (spec In-scope 3). Recording `y`, `p_cont`, `p_q` after every event is the price series AC1 compares |
| D4 | Scheduling state in `EngineState` | Keeps v1's anchors `last_idle_ms` and `last_bm_ms` (renamed from `last_idle_apply_ms`, `last_bm_ts_ms`) alongside the design's field list. `last_snapshot_ts_ms` leaves (history) | v1's gates are elapsed-time gates (engine.py:240-243, 296-299); without the anchors AC1 is impossible. Grid alignment is the Phase 3 ticker's job (ADR 0003) and does not need the engine to change. See R3 |
| D5 | AC7 "jump overrides … Brownian" vs AC1 | **Keep v1.** In v1's tick sequence Brownian runs *after* jumps (api.py:776-777), so on a tick where BM fires a jumping drink is published with one draw of noise on top, overwritten at the next jump application. The AC7 test asserts the override at the point of jump application, and asserts — as a pinned v1 behaviour — the one-step residual | Changing the order changes scenario 2's and 5's numbers, which the spec puts out of scope. **Must confirm; see R1** |
| D6 | D-23: should `flow_ema` decay? | **No, not in this phase.** It keeps v1's semantics (EMA updated only on orders); recorded in ADR 0012 with the reason and the cost of changing it later (a deliberate fixture regeneration) | "The numbers must be identical." Decay would move every BM draw's scale after a quiet spell. **Must confirm** |
| D7 | D-21: the new name for `calibrate_s0_to_p0` | `anchor_s0_to_current_y(spec, y) -> MarketSpec` in `spec.py` | Says what it does (engine.py:38-41 anchors to current `y`); takes `y`, not a state, so `spec.py` stays import-free of `state.py` |
| D8 | What AC2's "transitive imports" walks | AST walk over `exchange/**/*.py`, following `exchange.*` imports (absolute and relative); every other import's top-level package is checked against the ban list and **not descended into** | numpy itself imports `os`; descending into third-party packages makes AC2 unsatisfiable. Same AST style as [tests/meta/test_config_boundary.py](../../tests/meta/test_config_boundary.py) |
| D9 | Counter semantics | `version` +1 on every `advance` and every `schedule_jump`; `tick_index` +1 on `advance(orders=None)` only; `rng_counter` +1 per Brownian draw (none when `bm_enabled` false or `bm_sigma_y <= 0`, matching engine.py:294-305); `t_round` exactly as v1 (+1 per order and per idle step that adjusts, engine.py:288) | [architecture.md:91-104](../design/architecture.md#L91-L104): orders bump `version` but not `tick_index` |
| D10 | Idle decay/rise has no golden scenario | **Add scenario 6**: live config with `idle_targets` and `idle_rise_targets` set | All five specified scenarios have empty idle targets, so `apply_idle_adjust_if_needed` (engine.py:239-291) would only ever be tested by unit tests. Additive — confirm at audit |
| D11 | Event cadence in scenarios | Ticks at 1 Hz from `start_ms`; orders at scripted ms between ticks | ADR 0003's grid. v1's gates fire on elapsed time, so they land on the same instants |
| D12 | `advance`'s order input | `orders: NDArray[float64] \| None`, length N, finite, ≥ 0, else `ValueError`. Name→vector mapping stays outside the engine (Phase 5's order path) | Types at the boundary. Internally `apply_orders` still accepts negative vectors because the idle step feeds it one (engine.py:256-287) |
| D13 | Float identity | Fixtures are JSON (Python float `repr` round-trips exactly); comparisons use `np.array_equal`, never `allclose`, for every AC1 assertion | AC1 says full float precision |
| D14 | Immutability mechanism | `MarketSpec`, `Params`, `EngineState`, `PriceJump` are frozen dataclasses; every ndarray they hold is made read-only (`setflags(write=False)`) at construction; `idle_targets` and `jumps` are tuples | A mutation raises instead of passing silently; AC4's test still compares deep copies |

---

## Files

| Path | Create/Modify | Purpose |
|---|---|---|
| `exchange/engine.py` → `tests/engine/v1_reference/engine.py` | Move (T1) | D2 — v1 verbatim, hash-pinned |
| `tests/engine/v1_reference/__init__.py` | Create (T1) | Package marker |
| `tests/engine/golden/__init__.py`, `scenarios.py`, `capture.py` | Create (T1) | Scenario event scripts; v1 driver with fake clock and D1 shim; `--write` / `--check` CLI |
| `tests/engine/golden/fixtures/s1_live.json` … `s6_idle.json` | Create (T1) | The six golden fixtures (data) |
| `tests/engine/test_golden_capture.py` | Create (T1) | Hash pin; fixtures reproduce; each scenario exercises its target branch |
| `pyproject.toml` | Modify (T1) | Drop the `exchange` exclusion from ruff and mypy; exclude `tests/engine/v1_reference/` instead (+ mypy override for its importers) |
| `scripts/check.sh` | Modify (T1) | `mypy app db exchange tests`; remove `tests/engine` from `ALLOW_EMPTY` |
| `CLAUDE.md` | Modify (T1) | The `exchange/` convention line and the `tests/engine stays empty` note are now false |
| `exchange/pricing.py` | Create (T2) | `sigmoid`, `inv_sigmoid`, `quantize_step`, `prices_from_y`, `expected_flow_from_price` (dead under live config, marked) |
| `exchange/spec.py` | Create (T2) | `Params`, `DrinkSpec`, `MarketSpec` (AC5 validation), `anchor_s0_to_current_y` (D-21) |
| `tests/engine/test_pricing.py`, `tests/engine/test_spec.py` | Create (T2) | Bitwise vs v1 reference; AC5 |
| `exchange/state.py` | Create (T3) | `PriceJump`, `EngineState`, `initial_state`, `retarget_y_to_hold_quantized_prices` |
| `tests/engine/test_state.py` | Create (T3) | Bitwise `y` vs v1 `init`; immutability |
| `exchange/steps.py` | Create (T4), Modify (T5, T6) | `apply_orders`; `schedule_jump`, `apply_jumps`; `apply_idle`, `apply_brownian`, `_normal` |
| `tests/engine/test_steps_orders.py` | Create (T4) | AC6, AC9, AC10, bitwise vs `single_step` |
| `tests/engine/test_steps_jumps.py` | Create (T5) | AC7, AC8 |
| `tests/engine/test_steps_idle_brownian.py` | Create (T6) | D-22 pinned, D-23 pinned, RNG derivation |
| `exchange/advance.py`, `exchange/__init__.py` | Create / Modify (T7) | `advance`, `AdvanceResult`, `next_due_ms`; public API |
| `tests/engine/golden/replay.py` | Create (T7) | Drives the new engine through a fixture's events (shared with T9) |
| `tests/engine/test_golden_replay.py`, `tests/engine/test_advance.py` | Create (T7) | AC1; AC4; counters; `next_due_ms` contract |
| `tests/engine/test_purity.py` | Create (T8) | AC2 |
| `tests/engine/test_properties.py` | Create (T9) | AC3 property test; differential fuzz vs v1 |
| `docs/adr/0012-flow-ema-keeps-v1-semantics.md` | Create (T10) | D6 recorded |
| `docs/specs/defect-register.md` | Modify (T10) | D-21/22/23 resolution notes |

No new dependency. The property tests use the standard library's `random.Random` (allowed in
`tests/`, banned only in `exchange/`) and numpy, both already present. `hypothesis` was
considered and is not needed.

---

## Tasks

Every task leaves `./scripts/check.sh` green. Branch names follow `feature/phase-1-tN-<slug>`.

### T1 — Move v1 aside, capture the golden fixtures

- **Implements:** AC1 (the fixtures it compares against); spec In-scope 1 ("capture before
  refactoring anything"); Golden scenarios table 1–5, plus scenario 6 (D10)
- **Expected output:**
  - `tests/engine/v1_reference/engine.py` byte-identical to `exchange/engine.py` at `main`
    (`git mv`, 100 % rename); `exchange/` now holds only an empty `__init__.py`.
  - `tests/engine/golden/scenarios.py`: six scenarios as plain data — config (live =
    [legacy/v1/config/exchange_config.json](../../legacy/v1/config/exchange_config.json)
    loaded as a dict; default = v1's `from_persist` defaults, engine.py:154-163), `run_seed`,
    `start_ms`, and an event list (D3, D11). Order scripts are generated once from a fixed
    `random.Random(seed)` and stored in the fixture, so replay never regenerates them.
    1. Live, 30 min, scripted orders.
    2. Live, a 60 s price jump on one drink, with orders on that drink during it, spanning at
       least one Brownian firing (locks D5).
    3. Live, one drink driven to `p_max` and another to `p_min`, then pressure reversed
       (unstick branches, engine.py:215-225).
    4. Default config, `demand_enabled: true`.
    5. Live, orders, `crash("min", 30 s)`, then ≥ 5 min of ticks and orders after it ends.
    6. Live with `idle_targets` and `idle_rise_targets` set to two different drinks.
  - `tests/engine/golden/capture.py`: monkeypatches the reference module's `now_ms`, replaces
    `engine.rng` with the D1 shim after `init`, runs each event as the exact v1 sequence (D3),
    and records `y`, `p_cont`, `p_q`, `cum_orders`, `flow_ema` after every event.
    `uv run python -m tests.engine.golden.capture --write` writes the fixtures;
    `--check` recaptures in memory and exits non-zero on any difference.
  - Each scenario **asserts at capture time** that it hit its target branch (scenario 2: a BM
    firing during an active jump; 3: both unstick branches taken; 4: non-zero expected flow;
    5: all drinks at `p_min` at crash end; 6: both idle branches adjusted). A scenario that
    silently stops exercising its branch is a guard that cannot fail.
  - `pyproject.toml`, `scripts/check.sh`, `CLAUDE.md` updated per the Files table.
- **Verification:**
  - `git diff -M --stat main` shows `exchange/engine.py => tests/engine/v1_reference/engine.py` with 0 changed lines.
  - `uv run pytest tests/engine/test_golden_capture.py -v` (sha256 pin; `--check` equivalent in-process; branch-hit assertions).
  - `./scripts/check.sh` green, and the same in CI on Linux (see R4) **before merge**.
- **Depends on:** —
- **Autonomy note:** May choose scenario lengths, order volumes, seeds, which drinks are
  targeted, JSON layout and file names, and how the shim is written. Must **not** change one
  byte of the reference engine, and must replicate v1's call order exactly as D3 lists it —
  including the double `apply_price_jumps_if_needed` on the order path. If a scenario cannot
  reach its target branch on the live config without changing a parameter, stop and ask
  rather than changing the config. If `--check` passes on Windows but fails in CI, that is a
  golden-fixture divergence: hard stop (R4).

### T2 — `pricing.py` and `spec.py`

- **Implements:** AC5; spec In-scope 2–3 (the `MarketSpec` half); D-21 (D7)
- **Expected output:** `exchange/pricing.py` with v1's pure helpers (engine.py:13-36) under
  public names, expressions unchanged; `expected_flow_from_price` carrying a docstring that it
  is identically zero under the live config and kept with frozen maths (spec Out of scope).
  `exchange/spec.py` with frozen `Params` (every v1 field, engine.py:45-69, same defaults;
  `idle_targets` as tuples), `DrinkSpec`, and `MarketSpec` exposing read-only arrays `p_min`,
  `p_max`, `p0`, `a`, `d`, `s0`, `c` and `names`. Construction raises `ValueError` on any
  drink with `p_min >= p0` or `p0 >= p_max`, `step_quant <= 0`, or `step_quant` not a
  multiple of 0.01. `anchor_s0_to_current_y(spec, y)` returns a new spec with v1's `s0`
  formula (engine.py:38-41); its docstring states D-21.
- **Verification:** `uv run pytest tests/engine/test_pricing.py tests/engine/test_spec.py -v`
  — `prices_from_y`, `inv_sigmoid`, `quantize_step`, `expected_flow_from_price` and
  `anchor_s0_to_current_y` are `np.array_equal` to the v1 reference over ≥ 1000 random inputs;
  one AC5 case per condition plus the live and default configs constructing cleanly
  (`step_quant` 0.1 and 0.5 must pass despite `0.1 / 0.01 == 10.000000000000002`).
- **Depends on:** T1
- **Autonomy note:** Names of helpers, the multiple-of-0.01 tolerance method, whether
  `MarketSpec` is built from `DrinkSpec`s or arrays. Must not reorder any arithmetic in a
  ported expression — `a - d*p + s0 + c*(m - p)` stays in that order. Stop and ask if a v1
  config in this repo fails AC5 validation.

### T3 — `state.py`

- **Implements:** AC4 (immutability of state); spec In-scope 3 and 6 (`EngineState`, the
  three counters)
- **Expected output:** frozen `PriceJump` (engine.py:84-90, minus the mutable `done`) and
  frozen `EngineState` with `y`, `cum_orders`, `flow_ema`, `last_order_ts` (int64),
  `jumps: tuple[PriceJump, ...]`, `last_idle_ms`, `last_bm_ms` (D4), `rng_counter`,
  `version`, `tick_index`, `t_round` — arrays read-only (D14). `initial_state(spec, now_ms)`
  reproduces v1 `init`'s `y`, zeroed arrays and `last_order_ts = now_ms`, anchors at 0
  (engine.py:120-137); it does **not** apply `auto_calibrate_s0` — the caller does, via
  `anchor_s0_to_current_y`, documented. `retarget_y_to_hold_quantized_prices(spec, state)`
  ported from engine.py:176-180 (Phase 6's config path needs it).
- **Verification:** `uv run pytest tests/engine/test_state.py -v` — `initial_state(...).y`
  `np.array_equal` to the v1 reference `init` for the live and default configs; retarget
  bitwise vs v1; writing to any array of a constructed state raises `ValueError`.
- **Depends on:** T2
- **Autonomy note:** Field order, helper constructors (`replace`-style updaters), whether the
  counters start at 0. Must ask before adding any field not in D4/design, or dropping one.

### T4 — `steps.apply_orders`

- **Implements:** AC6, AC9, AC10; part of AC4
- **Expected output:** `apply_orders(spec, state, orders, *, now_ms) -> (EngineState,
  OrderDiagnostics)` — the order half of D3: `flow_ema` EMA and `last_order_ts` (api.py:355-361,
  only when the call is a real order), then v1 `single_step` (engine.py:190-236) including the
  `alpha_price` cross-term (dead, marked) and both unstick branches, `t_round + 1`.
  Diagnostics carry `order_pressure`, `cross_price_pressure`, `cum_orders` as v1's `logs`.
  A private `_single_step` is what the idle step will reuse in T6.
- **Verification:** `uv run pytest tests/engine/test_steps_orders.py -v`:
  bitwise vs v1 `single_step` (+ the api.py flow_ema/last_order_ts lines) over ≥ 500 random
  states and vectors; **AC6** — at `p_min` with a positive order the quantised price rises by
  ≥ one `step_quant`, and the mirror case at `p_max`; **AC9** — with `demand_enabled` false
  and non-zero `a,d,s0,c`, pressure equals the raw-order computation with zero expected flow;
  **AC10** — live config, BM off, equal orders on every drink: the pre-barrier pressure
  `order_pressure + phi_persist * cum_orders` is uniform across drinks every round, and over
  30 rounds the spread of per-drink fractional moves is < 25 % of the favoured drink's move
  when the same volume goes to one drink.
- **Depends on:** T3
- **Autonomy note:** Signature details, diagnostics type. The AC10 threshold may be tightened,
  not loosened: if 25 % does not hold on v1's own maths, stop and ask — do not tune a number
  until it passes. Expressions are ported, not rewritten.

### T5 — `steps.schedule_jump` and `steps.apply_jumps`

- **Implements:** AC7, AC8
- **Expected output:** `schedule_jump(spec, state, *, drink: int, p_target, duration_ms,
  now_ms) -> EngineState` (engine.py:318-332: target quantised to `step_quant`, fraction
  clipped — the saturation AC8 asks for; `t1 = now + max(1, int(duration_ms))`; replaces any
  jump on that drink; unknown index raises). `apply_jumps(spec, state, *, now_ms)`
  (engine.py:334-358): smoothstep while active, exact `y1` at/after `t1`, finished jumps
  removed.
- **Verification:** `uv run pytest tests/engine/test_steps_jumps.py -v`: bitwise vs v1 over
  random jump timelines; **AC7** — `apply_orders` then `apply_jumps` mid-jump yields `y[i]`
  equal to `y0 + s(f)(y1 - y0)` regardless of the orders, and so does `apply_brownian`
  (once T6 exists — in T5, a hand-perturbed `y`) followed by `apply_jumps`; the D5 residual is
  pinned by a test named for it; **AC8** — targets below `p_min` and above `p_max` saturate to
  the bound's `y` without raising and quantise to the bound.
- **Depends on:** T4 (same file, `exchange/steps.py`)
- **Autonomy note:** Internal structure. Must ask if AC7 cannot be expressed without changing
  the D3 call order.

### T6 — `steps.apply_idle` and `steps.apply_brownian`

- **Implements:** AC3 (the RNG half); spec In-scope 5; D-22, D-23
- **Expected output:** `apply_idle(spec, state, *, now_ms)` (engine.py:239-291), reusing
  `_single_step`; its docstring states D-22 — the gate is `refresh_minutes`,
  `idle_decay_minutes` / `idle_rise_minutes` are only the per-drink "since last order"
  thresholds. `apply_brownian(spec, state, *, now_ms, run_seed)` (engine.py:293-315) drawing
  via `_normal(run_seed, rng_counter, scale, size)` =
  `default_rng(SeedSequence([run_seed, rng_counter])).normal(0.0, scale, size)`, with
  `scale` computed by v1's exact expression, then `rng_counter + 1`; `flow_ema`'s docstring
  points at ADR 0012 (D6).
- **Verification:** `uv run pytest tests/engine/test_steps_idle_brownian.py -v`: bitwise vs
  v1 (reference driven with the D1 shim) for both steps across random states; idle fires on
  the `refresh_minutes` boundary and not before, even when `idle_decay_minutes` has elapsed
  (D-22 pinned); `flow_ema` unchanged by `apply_idle`/`apply_brownian` (D-23 pinned); same
  `(run_seed, rng_counter)` → same draw, different counter → different draw; no draw and no
  counter bump when `bm_sigma_y <= 0` or BM is disabled.
- **Depends on:** T5 (same file)
- **Autonomy note:** Helper names. The `_normal` call must pass `loc`/`scale`/`size`
  positionally identical to v1 (engine.py:311) — multiplying a unit normal afterwards is not
  the same floats. Stop on any non-bitwise result.

### T7 — `advance`, `next_due_ms`, golden replay

- **Implements:** AC1, AC4; spec In-scope 4, 6, 7
- **Expected output:** `advance(spec, state, *, now_ms, orders=None, run_seed) ->
  AdvanceResult(state, diagnostics)`: with orders — `apply_orders → apply_jumps → apply_idle
  → apply_jumps → apply_brownian`, `version + 1`; without — `apply_idle → apply_jumps →
  apply_brownian`, `version + 1`, `tick_index + 1` (D3, D9); input validated per D12.
  `next_due_ms(spec, state) -> int`: the earliest `now_ms` at which `advance(orders=None)`
  could change any price — the idle and BM anchors plus their intervals, and the earliest
  active jump's `t0`. `exchange/__init__.py` exports the public API.
  `tests/engine/golden/replay.py` maps each fixture event onto it (a `jump`/`crash` event =
  `schedule_jump` per drink, then `advance(orders=None)`).
- **Verification:**
  - `uv run pytest tests/engine/test_golden_replay.py -v` — **AC1**: all six fixtures,
    `np.array_equal` on `y`, `p_cont`, `p_q` after every event; the failure message names the
    scenario, event index and first differing drink.
  - `uv run pytest tests/engine/test_advance.py -v` — **AC4**: deep copies of `spec` and
    `state` equal the originals after `advance` (orders, tick, jump-active and BM-firing
    cases); counters per D9; `next_due_ms` contract: for 1000 random states, `advance` at any
    `now_ms < next_due_ms(...)` with no orders changes no price, and at `next_due_ms` the
    scheduled effect fires; invalid orders (wrong length, negative, NaN) raise `ValueError`.
- **Depends on:** T6
- **Autonomy note:** `AdvanceResult` shape, replay internals. A golden mismatch is a hard
  stop — report the first differing event, do not adjust the engine or the fixture to fit.

### T8 — Import-purity test

- **Implements:** AC2
- **Expected output:** `tests/engine/test_purity.py`: the D8 walk from `exchange/__init__.py`,
  failing with `file:line` on any import of `time`, `datetime`, `random`, `os`, `asyncio`,
  `sqlalchemy`, `fastapi`, `openpyxl` (including `from x import`, relative imports into the
  package, and `importlib.import_module`/`__import__` string literals). Anti-vacuity:
  the walk reaches every `.py` file under `exchange/` (unreached files fail the test — dead
  modules are not exempt), and parametrised snippets of each banned form are flagged.
- **Verification:** `uv run pytest tests/engine/test_purity.py -v`. Once T7 is on `main`, the
  test reaches `pricing`, `spec`, `state`, `steps`, `advance`.
- **Depends on:** T1 (needs `engine.py` out of `exchange/`)
- **Autonomy note:** Structure follows `tests/meta/test_config_boundary.py`'s
  detector-plus-snippets shape; the builder may reuse its helpers by copy (tests are not a
  shared library) or import. Ask before adding modules to the ban list beyond AC2's.

### T9 — Property tests: determinism and differential fuzz

- **Implements:** AC3; AC1 (beyond the six scenarios); spec Verification "property test"
- **Expected output:** `tests/engine/test_properties.py`: (a) **AC3** — ≥ 2000 random
  sequences (random config within AC5's bounds, random orders/ticks/jumps/crashes, random
  `run_seed`): replaying each twice from the same inputs yields `np.array_equal` states at
  every step; (b) **differential** — ≥ 500 random sequences, including `alpha_price ≠ 0`,
  `demand_enabled` both ways, idle targets and `auto_calibrate_s0`, replayed through both the
  v1 reference (via `capture.py`'s driver) and the new engine via `replay.py`: identical
  prices at every step. Seeds fixed; a failure prints the seed and event index.
- **Verification:** `uv run pytest tests/engine/test_properties.py -v --durations=5`; the
  file completes in under 60 s on the dev laptop.
- **Depends on:** T7
- **Autonomy note:** Generators, counts above the minimums, runtime trimming. A differential
  failure is a hard stop (golden-fixture divergence), even if it is in a dead-code branch.

### T10 — Record D-21, D-22, D-23

- **Implements:** spec In-scope 7 (rename, document, decide)
- **Expected output:** `docs/adr/0012-flow-ema-keeps-v1-semantics.md` (context: D-23;
  decision: D6; consequence: changing it later is a deliberate behaviour change that
  regenerates fixtures and gets its own spec). `docs/specs/defect-register.md` rows D-21,
  D-22, D-23 annotated with their resolution and the task that lands it.
- **Verification:** `./scripts/check.sh` green (docs only); the three rows link to existing
  files (`uv run pytest tests/meta -q` unaffected).
- **Depends on:** — (but only after D6 is confirmed at the audit)
- **Autonomy note:** Wording. Must not edit `docs/design/` (hard stop); if the D6 decision
  is reversed at the audit, this task's ADR says so and T6's D-23 test changes with it.

---

## Task graph

```
T1 ─┬─ T2 ── T3 ── T4 ── T5 ── T6 ── T7 ── T9
    └─ T8
T10 (independent)
```

T4 → T5 → T6 is a chain because all three write `exchange/steps.py`, not because of a logical
dependency between orders, jumps and noise.

| Group | Tasks | Files they touch |
|---|---|---|
| 1 | T1, T10 | T1: `tests/engine/v1_reference/**`, `tests/engine/golden/**`, `tests/engine/test_golden_capture.py`, `pyproject.toml`, `scripts/check.sh`, `CLAUDE.md`, `exchange/engine.py` (moved) · T10: `docs/adr/0012-*.md`, `docs/specs/defect-register.md` |
| 2 | T2, T8 | T2: `exchange/pricing.py`, `exchange/spec.py`, `tests/engine/test_pricing.py`, `tests/engine/test_spec.py` · T8: `tests/engine/test_purity.py` |
| 3 | T3 | `exchange/state.py`, `tests/engine/test_state.py` |
| 4 | T4 | `exchange/steps.py`, `tests/engine/test_steps_orders.py` |
| 5 | T5 | `exchange/steps.py`, `tests/engine/test_steps_jumps.py` |
| 6 | T6 | `exchange/steps.py`, `tests/engine/test_steps_idle_brownian.py` |
| 7 | T7 | `exchange/advance.py`, `exchange/__init__.py`, `tests/engine/golden/replay.py`, `tests/engine/test_golden_replay.py`, `tests/engine/test_advance.py` |
| 8 | T9 | `tests/engine/test_properties.py` |

Build on opus (manual-checklist Phase 1 note); `/review 1` runs `engine-guardian` on T1–T7.

**Phase exit (Gate D):** `uv run pytest tests/engine -v` shows all six fixtures replaying
identically, the purity test, AC3 and the differential test green; `./scripts/check.sh` green
on `main` and in CI.

---

## Data changes

None. No migration, no table. Persistence of `EngineState` is Phase 2; the `engine_state`
columns in [data-model.md:27](../design/data-model.md#L27) will need `last_idle_ms` and
`last_bm_ms` added if D4 is accepted (R3).

---

## Risks and unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **AC7 and AC1 conflict.** v1 applies Brownian after jumps in the same tick (api.py:776-777), so a jumping drink carries one draw of noise until the next jump application. Literal AC7 ("override … Brownian") would require reordering, which changes scenario 2 and 5 numbers | D5 keeps v1 and pins the residual. **Needs a human decision before T5.** If AC7 wins, it becomes a deliberate, separately specced behaviour change after Phase 1 exits |
| R2 | D1 reads "seeding `engine.rng`" as "injecting a counter-derived shim into `engine.rng`" | The shim changes nothing in v1's maths, only where its noise comes from. Confirm at audit |
| R3 | D4 adds two fields to `EngineState` beyond architecture.md:72 | Additive, not a redesign; Phase 2 must carry them into `engine_state`. Changing `docs/design/` is a hard stop, so this plan does not — flag for the human to update the design doc |
| R4 | **Cross-platform float identity.** numpy's `exp`/`log`/`tanh` may differ by an ULP between Windows (capture) and Linux CI (SIMD/libm), which would fail AC1 on one platform only | T1 does not merge until `--check` passes in CI on Linux. The differential test (T9) is immune — both sides run on the same machine. If CI diverges: hard stop; the options (capture on Linux in the Docker image and treat that as canonical, or per-platform fixtures) are a human call |
| R5 | Fixture size: ~1800 events × 6 drinks × 5 arrays × 6 scenarios ≈ 2–4 MB of JSON | Acceptable for a repo with no size gate; T1 may drop `p_cont` if it is derivable bit-exactly from `y` (it is — `prices_from_y`) and say so |
| R6 | Property tests too slow for the gate | T9 budgets < 60 s; counts may drop to the stated minimums, not below |
| R7 | mypy `strict` on numpy-heavy code, and mypy following imports into the excluded v1 reference | `NDArray[np.float64]` annotations; a `[[tool.mypy.overrides]]` with `ignore_errors`/`follow_imports = "skip"` for `tests.engine.v1_reference.*` in T1 |
| R8 | A crash target saturates `y1` at `logit(1e-9) ≈ -20.7`, well past `y_clip = 6`, so after a crash a drink recovers only once the next BM draw clips it back to -6 | v1 behaviour, preserved and captured by scenario 5. Noted for Phase 6 (manipulation), not fixed here |
| R9 | AC10's "approximately" needs a number | T4 defines it (uniform pre-barrier pressure exactly; < 25 % spread) and may not loosen it. With `lambda_orders = 1.5 > 1`, equal orders move every price *down* together at first — a uniform move, consistent with AC10, but worth knowing |
| R10 | v1 calls `apply_price_jumps_if_needed` twice per order (api.py:387 and :776) | Preserved in D3; the second call is a no-op on `y` only when no jump is active, so it matters for golden identity |

---

## Out of scope for this plan

- `to_cents` (listed in architecture.md:46 for `pricing.py`) — money is Phase 5's.
- Name→index order mapping (`ordered_vector`, engine.py:361-368) and duplicate-name checks
  (D-24) — Phases 5 and 2.
- Active/removed drink masks (architecture.md:175-180) — Phase 6; in Phase 1 every slot is
  active.
- The ticker, its grid alignment and gap handling (ADR 0003) — Phase 3. `next_due_ms` is the
  seam it will use.
- Deleting `expected_flow_from_price` and the `alpha_price` cross-term — spec Out of scope;
  marked only.
- Any `flow_ema` decay, or reordering jumps/Brownian — behaviour changes (D5, D6).

---

## Audit (plan-auditor — PASS required before implementation starts)

Human audit (Gate B), walked via `/audit 1`. **Result: PASS.**

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC (no orphans) — T10 has no AC; accepted, it implements spec In-scope 7 (D-21/22/23)
- [x] Each task's expected output is what we actually need — D1, D4, D5, D6, D10 confirmed as written (pricing-maths decisions; R1, R2 resolved)
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note — none added
- [x] Data changes additive and reversible — none in this phase
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting — T1 touches ~15 paths (6 are fixture data); accepted as one unit
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not
- [x] Every task has a Depends on and an Autonomy note
- [x] No two tasks in one parallel group write the same file

Audited by: MartijnBoot  Date: 2026-10-01
