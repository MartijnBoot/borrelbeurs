# ADR 0012: `flow_ema` keeps v1's semantics — updated by orders only, never decayed

Date: 2026-10-01 · Status: Accepted (at the Phase 1 plan audit, 2026-10-01, decision D6) ·
Resolves: [D-23](../specs/defect-register.md) ·
Rests on: [ADR 0002](0002-keep-the-python-pricing-engine.md)

## Context

`flow_ema` is an exponential moving average of order volume per drink. It feeds exactly one
thing: the scale of the Brownian noise, `1 + flow_vol_amp · log1p(flow_ema)`
([exchange/steps.py](../../exchange/steps.py), `apply_brownian`). Busy drinks jitter more.

In v1 it lived in the API, not the engine: `post_order` updates it with `flow_beta`
(legacy/v1/backend/api.py:355). Nothing else touches it. A drink that sold heavily at nine
o'clock and not at all since keeps its nine o'clock volatility all night (D-23).

That looks like a bug, and decay would be the obvious fix. But Phase 1's one non-negotiable
is that the numbers do not change: the spec puts "any change to the pricing behaviour" out of
scope, and the golden fixtures are v1's own price series. A decaying `flow_ema` changes the
scale of every Brownian draw after any quiet spell — every golden scenario with a pause in it,
which is all of them.

## Decision

1. `flow_ema` keeps v1's semantics exactly: `apply_orders` updates it,
   `(1 - flow_beta) · flow_ema + flow_beta · orders`; `apply_idle`, `apply_brownian` and
   `apply_jumps` never change it. A test pins this
   (`tests/engine/test_steps_idle_brownian.py::test_d23_flow_ema_is_unchanged_by_idle_and_brownian`).
2. The update moves from the API into the engine (`exchange.steps.apply_orders`), because it
   is pricing state. Where it is computed changes; what it computes does not.

## Consequences

- D-23 is resolved by decision, not by a code change: the behaviour is now deliberate and
  documented at the point of use (`apply_orders` and `apply_brownian` docstrings point here).
- Changing it later is a **deliberate behaviour change**: its own spec, a new decision
  recorded against this ADR, and a regeneration of the golden fixtures
  (`python -m tests.engine.golden.capture --write` against a v1 reference changed to match, or
  new fixtures captured from the new engine with the old ones retired). It must not ride
  along with an unrelated change; the replay test will refuse it if it tries.
- A decay would need a clock input `flow_ema` does not have today — a `last_flow_ms` anchor in
  `EngineState` and in Phase 2's `engine_state` table. That cost is noted, not paid.
