# The phased rebuild route

Nine phases. Each is a set of vertical slices; each slice is one PR sized to the
way-of-working Section Definition of Done (§4.6) — reviewable in under 30 minutes, roughly
≤400 changed lines across ≤10 files.

Per-phase specs live in [../specs/](../specs/). Per-phase implementation plans
(`phase-N.md` in this folder) are written one phase at a time, in a fresh session, and
audited by a human before any code — see [Working the loop](#working-the-loop).

## Order, and why

| Phase | Name | Exit criterion |
|---|---|---|
| **−1** | v1 authorization hotfix | ✅ Done — commit `b617a56` |
| **0** | Foundations | `scripts/setup.sh` then one command gives a running shell app; CI green |
| **1** | **Engine extraction + golden tests** | Pure engine reproduces v1's outputs exactly |
| **2** | Data model + persistence | Live config round-trips through Postgres; restart preserves prices |
| **3** | API + auth + realtime | Every route authorized; integration tests green against real Postgres |
| **4** | React shell + theme + auth + koers | Big screen works end to end; theme propagates across machines |
| **5** | Bar + order path | Price shown equals price charged, enforced by a property test |
| **6** | Manipulation + settings | An admin can configure a borrel from scratch |
| **7** | Analytics + run lifecycle | Two past borrels comparable; xlsx export matches the database |
| **8** | Deploy + cutover | Runs on Render *and* offline; rollback rehearsed; mock borrel passed |

**Highest risk first.** Phase 1 is the engine. If the maths changes silently, nothing
downstream can be trusted and nobody notices until a borrel prices wrongly. Doing it first
means discovering that while there is still time to change course.

**Phases 4–6 are ordered by blast radius.** The display page is read-only, so it validates
the whole stack — auth, protocol, theming, charts — with no risk of charging anyone
incorrectly. The order path comes next. The destructive admin surface comes last.

## Phase 1 is the one that must not be rushed

Before touching the engine, generate golden fixtures from the **current** code by
monkeypatching `exchange.engine.now_ms` and seeding `engine.rng`, replay scripted scenarios,
and commit the resulting price series. These fixtures are the contract for "the pricing
maths does not change".

Scenario set, **live config first**:

1. **Live config** (`a=d=s0=c=0`, `demand_enabled: false`, `eta: 0.8`, `K: 5.0`,
   `step_quant: 0.1`, `phi_persist: 0.1`) — a 30-minute scripted order stream.
2. Same, with a price jump overlapping orders, so jump-overrides-order is locked in.
3. Same, pinned at `p_min` and `p_max` to exercise the floor/ceiling unstick hack.
4. Default config with `demand_enabled: true`, to cover the demand branch at all.
5. Market crash — all six drinks smoothstepping to `p_min`.

Scenario 1 is first **deliberately**: a large part of the engine is dead code in production.
`expected_flow_from_price`, `calibrate_s0_to_p0` and the `alpha_price` cross-term are all
identically zero under the live config. Keep them, maths frozen, but test what actually runs.

## Working the loop

Per way-of-working §4.2, and supported by the commands in [`.claude/commands/`](../../.claude/commands/):

```
  /spec N     interview → docs/specs/phase-N.md         (AI, then human approves)
  /plan N     read-only exploration → docs/plans/phase-N.md   (AI)
  /audit N    the audit checklist                       ← the step teams skip
  /build N T  implement ONE task from the plan          (AI)
  /verify     run the check, produce evidence           (AI)
  /review     fresh-context review of the diff          (AI, separate context)
```

**In practice the route is driven as one long-running swarm**, per
[ADR 0009](../adr/0009-autonomous-swarm-delivery.md): `./scripts/swarm.ps1` re-invokes the
`/rebuild` orchestrator, which dispatches `phase-planner` → `plan-auditor` per phase and then a
`task-builder` → `task-verifier` → `fresh-eyes-reviewer` triad per ready task, up to three
concurrently, each in its own worktree. The audit and review gates still have to pass; they are
signed by fresh-context agents rather than by the human, and the human reads a phase digest
afterwards. The commands above remain the manual path for driving one step by hand.

Rules that hold throughout:

- **No code before a spec. No implementation before an audited plan.**
- **A fresh context between spec, plan, implementation and review.** The interview context is
  noise for planning; the planning context biases review. Under the swarm that separation is
  one agent per step; by hand it is one session per step.
- **Never let the context that wrote the code be its only reviewer.**
- **Everything with a consequence a `git revert` cannot undo stays with the human** — the
  hard-stop list in [`.claude/commands/rebuild.md`](../../.claude/commands/rebuild.md).
- Per §4.1, use the most capable model for the engine work, specs, planning and review; bulk
  implementation of an approved plan does not need it.

## Cross-phase invariants

These hold from the phase that introduces them onward, and every later phase's Definition of
Done re-checks them:

| From | Invariant |
|---|---|
| 1 | The `exchange` package imports no clock, no I/O, no framework. Enforced by a test |
| 1 | Golden fixtures pass. This is the gate on the entire rebuild |
| 2 | No float ever holds a euro amount in the database |
| 2 | Per-drink persisted values are keyed by `drink_id`, never by array position |
| 3 | Every route has an explicit authorization dependency; the WS handshake checks role |
| 3 | Inside the state lock: pure numpy plus one short DB transaction, nothing else |
| 4 | No runtime request leaves the origin. Enforced by a CI check on built output |
| 5 | The price displayed is the price charged, or the order is rejected |

## What is out of scope for the whole rebuild

- Porting the pricing maths to TypeScript ([ADR 0002](../adr/0002-keep-the-python-pricing-engine.md)).
- Multi-tenant / multiple associations.
- Entra ID or any hosted identity provider.
- Kubernetes, Redis, message queues, search indexes.
- A dedicated admin audit log — `run_config_revision` gives most of the value.
- **Any change to pricing behaviour.** Prices must move exactly as they do in v1, and the
  golden fixtures are what prove it.
