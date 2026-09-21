# ADR 0009: The rebuild runs as an autonomous agent swarm; the human gates become agent gates

Date: 2026-09-21 · Status: Accepted

## Context

The rebuild loop as designed (`docs/way-of-working.md` §4.2, and `/rebuild` as first written)
has nine steps, four of them human-owned: FRAME, AUDIT, REVIEW, LOG. The orchestrator was
explicitly forbidden from passing a gate on its own authority.

Applied to this route that is roughly a hundred stops. Nine phases, thirteen tasks in Phase 0
alone, and every task costs an audit stop, a review stop and a merge go-ahead. Phase 0 reached
T1 in a working week. The gates were not producing that much information per stop: Gate B's
audit was answered from the plan file, and Gate C's human diff read came after a fresh-context
review had already reported.

The way-of-working document is written for client delivery — real users, a production
environment, a team, and consequences that outlive the project. This is a hobby project for
student borrels with one developer, no users yet, no production environment, and a `main` that
costs one `git revert` to undo. The cost of a defect here is a wrong price on a screen at a
party, caught and fixed in the room. Carrying client-grade ceremony against that risk profile
buys very little and costs the whole throughput of the project.

## Decision

For the v2 rebuild, and only for it, the four human-owned steps are delegated to
**fresh-context agents**, and `/rebuild` runs as a long-running swarm that stops only on a
declared hard-stop list.

1. **Gate A (spec)** is satisfied by the specs for phases 0–8 already existing and approved. A
   missing spec is agent-authored from the route and `docs/design/`, and flagged.
2. **Gate B (plan audit)** is held by a new `plan-auditor` agent: read-only, adversarial, a
   context that did not write the plan. Its PASS unblocks implementation; a FAIL returns the
   plan to `phase-planner`, three rounds maximum.
3. **Gate C (diff review)** is held by `fresh-eyes-reviewer`, plus `engine-guardian` on any
   diff touching `exchange/`. Every Correctness finding must be fixed and re-verified before
   merge. Risk and Optional findings are recorded and deliberately not chased.
4. **Gate D (phase exit)** is run by the orchestrator itself, with real command output, and
   published as a phase digest for the human to read afterwards.
5. Work is **parallelised** across the audited plan's task dependency graph, capped at three
   concurrent builder–verifier–reviewer triads, each in its own git worktree and branch.
6. The swarm may commit, push, open PRs and squash-merge into `main` of
   `MartijnBoot/borrelbeurs`.
7. A **driver** (`scripts/swarm.ps1`) re-invokes the orchestrator headlessly until the ledger
   reads `COMPLETE` or `BLOCKED`, so the workflow survives context exhaustion.

## What is consciously relaxed, and what replaces it

Three of the 14 non-negotiables are affected. Naming them is the point of this record.

| Non-negotiable | Relaxed how | What carries the load instead |
|---|---|---|
| #2 No implementation before a plan **audited by a human** | The signature moves to `plan-auditor` | Same checklist, same traceability table, adversarial prompt, a context that did not write the plan, and a FAIL that actually blocks |
| #6 Fresh eyes review | Fresh eyes are no longer *human* eyes | `fresh-eyes-reviewer` + `engine-guardian`; every Correctness finding blocks the merge, which is stricter than a human skim |
| §4.6 DoD: "a human has read the whole diff" | Becomes post-hoc and selective | Every increment is a squash-merged PR with evidence in its body; the phase digest names the two or three diffs most worth a second opinion |

What is **not** relaxed: no code before a spec, no implementation before an audited plan, a
runnable check per task, evidence rather than assertions, the reviewer never being the author,
one vertical slice per PR, and the cross-phase invariants. Those are the parts that catch
defects rather than the parts that record approval.

## Why this is defensible here and would not be at a client

The gates exist against two different risks. One is **drift** — building the wrong thing
confidently — and agents can be held against that, because drift is detectable by comparing a
diff to a written criterion, which is exactly what a fresh context is good at. The other is
**consequence** — that a defect reaches users, money or data that cannot be restored. Only a
human can carry that, and here there is nothing to carry: no users, no production, no personal
data, no money, and a revert that costs nothing.

So the delegation is bounded by consequence, not by difficulty. Everything with a consequence
a revert cannot undo stays with the human, and that is precisely what the hard-stop list is.

## Hard stops — what the swarm may never decide

Spec ambiguity that changes user-visible behaviour · any ambiguity in the pricing maths · a
golden-fixture divergence · a new third-party dependency · reversing an ADR or changing
`docs/design/` · anything needing a credential, secret or external account · three failed
attempts on one task · a cross-phase invariant it cannot restore · any history rewrite,
force-push, or touching the `borrelbeurs-v1` repository.

On a hard stop the swarm writes the question, the evidence and its recommended answer into the
ledger and exits.

## Consequences

- Throughput stops being bounded by the human's review capacity. §4.4's "parallel sessions are
  capped by your review capacity" no longer applies, because review is no longer the human's.
- The **ledger becomes load-bearing.** `docs/plans/rebuild-progress.md` is the only memory
  across runs; an unwritten state transition did not happen. It is reconciled against git at
  the start of every run, because a killed run must not cause a double build.
- Defects will reach `main` that a human review would have caught. That is the accepted trade;
  `main` is not deployed automatically and Phase 8 gates the first real use.
- The audit trail changes shape: it is PR bodies, verifier output in the ledger, and phase
  digests, rather than a human's approval in a session.
- Model spend goes up. Three concurrent triads plus a reviewer per task is more tokens per
  merged line than a serial loop with a human gate.

## When this reverts

This ADR is a temporary local relaxation, not a change to the way of working. It reverts, and
the human gates come back, when any of these happens:

- A defect the swarm merged reaches a live borrel.
- The project gets a second developer, real users, or a production environment with data worth
  keeping.
- Two consecutive phases exit with a digest whose "what a human should look at" section turns
  out to have missed something material.

`docs/way-of-working.md` is unchanged and remains the standard for client work. This record is
the exception, its reasoning, and its expiry.
