# Spec: Phase 1 — Engine extraction and golden tests

Status: Approved · Depends on: Phase 0 · Fixes: D-21, D-22, D-23
**This phase is the gate on the entire rebuild.**

## Problem

`exchange/engine.py` is the product: 383 lines of numpy evolving prices in a latent logit
space. It has **no tests**. It is also entangled with everything it should not be — it holds
money, a chart buffer, scheduling state and a live unseeded RNG, and it calls `time.time()`
in six places, so it is its own clock.

Nothing downstream can be trusted until there is proof the maths did not change.

## In scope

- **Capture golden fixtures from the current v1 code, before refactoring anything.**
- Extract `exchange/` as a pure package: `spec.py`, `state.py`, `pricing.py`, `steps.py`,
  `advance.py`.
- Split `ExchangeState` into frozen `MarketSpec` and frozen `EngineState`; money and history
  leave the package.
- Make every step non-mutating.
- Replace the live RNG with counter-based derivation from `(run_seed, rng_counter)`.
- Introduce `version`, `tick_index`, `rng_counter` as three distinct counters.
- `next_due_ms()` as a pure predicate — the scheduler asks when the next effect is due,
  rather than the engine asking whether it is late.
- Rename what lies: `calibrate_s0_to_p0` → a name reflecting that it anchors to current `y`
  (D-21). Document that the idle gate uses `refresh_minutes`, not `idle_decay_minutes`
  (D-22), and decide deliberately whether `flow_ema` should decay (D-23).

## Out of scope

- Any change to the pricing behaviour. **The numbers must be identical.**
- Postgres, the API, the ticker, the frontend.
- Removing the dead code paths (`expected_flow_from_price`, the `alpha_price` cross-term).
  They stay, maths frozen, merely marked.

## Acceptance criteria

- **AC1.** When the refactored engine replays each golden scenario, the system shall produce
  price series **identical** to those captured from v1, to full float precision.
- **AC2.** While the `exchange` package is imported, the system shall import none of `time`,
  `datetime`, `random`, `os`, `asyncio`, `sqlalchemy`, `fastapi`, `openpyxl`. A test shall
  walk transitive imports and fail otherwise.
- **AC3.** When `advance()` is called twice with the same `(spec, state, now_ms, orders,
  run_seed, rng_counter)`, the system shall return identical results.
- **AC4.** When `advance()` is called, the system shall not mutate its `spec` or `state`
  arguments. A test shall assert the inputs are unchanged afterwards.
- **AC5.** When a `MarketSpec` is constructed with `p_min >= p0`, `p0 >= p_max`, a
  non-positive `step_quant`, or a `step_quant` that is not a multiple of 0.01, the system
  shall raise at construction.
- **AC6.** When an order vector is applied at `p_min` with positive pressure, the system
  shall move the quantised price by at least one `step_quant` (the unstick hack).
- **AC7.** When a price jump is active, the system shall override order-driven and Brownian
  movement for its duration, easing by smoothstep.
- **AC8.** When a price jump target lies outside `[p_min, p_max]`, the system shall saturate
  at the bound rather than raise.
- **AC9.** When `demand_enabled` is false, the system shall treat expected flow as zero and
  drive pressure from raw order counts.
- **AC10.** When all drinks are ordered equally, the system shall produce approximately no
  net relative price movement — the relative-demand property that is the heart of the game.

## Golden scenarios

Captured by monkeypatching `exchange.engine.now_ms` and seeding `engine.rng` on the **v1**
code, committed as fixtures.

| # | Scenario | Why |
|---|---|---|
| 1 | **Live config** (`a=d=s0=c=0`, `demand_enabled: false`), 30 min scripted orders | This is what actually runs in production |
| 2 | Live config, price jump overlapping orders | Locks in jump-overrides-order |
| 3 | Live config, pinned at `p_min` and `p_max` | Exercises the unstick hack |
| 4 | Default config, `demand_enabled: true` | Covers the demand branch at all |
| 5 | Market crash — all drinks smoothstepping to `p_min` | The most visible live behaviour |

Scenario 1 is first deliberately. A large part of the engine is dead code in production:
`expected_flow_from_price`, `calibrate_s0_to_p0` and the `alpha_price` cross-term are all
identically zero under the live config. Testing the defaults would test the wrong thing.

## Verification

- `pytest tests/engine` — golden fixtures plus the import-purity test. Evidence: full output.
- A property test: `advance` is deterministic given a fixed seed, across thousands of random
  order sequences.
- Mutation check: assert input `spec` and `state` are unchanged after `advance`.

## Exit condition

The pure engine reproduces v1's outputs exactly on all five scenarios, imports nothing it
should not, and every branch of the pricing logic has a test. **No later phase starts until
this passes.**
