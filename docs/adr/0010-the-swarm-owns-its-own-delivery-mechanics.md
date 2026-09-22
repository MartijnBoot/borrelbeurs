# ADR 0010: The swarm owns its own delivery mechanics; worktree isolation becomes serial branch isolation

Date: 2026-09-22 · Status: Accepted · Amends: [ADR 0009](0009-autonomous-swarm-delivery.md) §5

## Context

Three consecutive swarm runs produced zero product commits. Nothing in the spec, the plan or
the code was wrong. The swarm stopped twice on the same wall and once on the diagnosis of it.

The wall: **a subagent cannot run `git` against any non-primary worktree.** Confirmed on
2026-09-21 in four shapes — a worktree outside the repo root (`../.borrelbeurs-swarm/`), one
inside it (`/.worktrees/`), `git -C <worktree>` from the primary checkout, and `EnterWorktree`,
which is not in a subagent's tool set at all (`Bash, Edit, Glob, Grep, Read, Write`). The guard
keys on which git repository the command resolves against, not on cwd and not on the path, and
it is enforced by the harness, so no `settings.json` rule lifts it. Running git in the
**primary checkout** is permitted, and that is the only control that passes.

ADR 0009 §5 requires each builder–verifier–reviewer triad to work "in its own git worktree and
branch". That requirement is unreachable. A builder dispatched into a worktree can write files
and never commit one, which is exactly what Phase 0 T2 did for a whole run.

So there were two problems, and only one of them was the worktrees:

1. The isolation mechanism does not work in this harness.
2. The swarm had no authority to fix it. "Reversing an ADR" is on 0009's hard-stop list, the
   mechanism lives in an ADR, so the swarm correctly stopped and waited for a human — on a
   question with no product content whatsoever.

The second is the more expensive one. A swarm that halts on its own plumbing is not autonomous
in any useful sense; every environment paper-cut costs a human round trip measured in days.

## Decision

### 1. Serial branch isolation replaces per-task worktrees

ADR 0009 §5 is amended. Work is isolated **per branch in the primary checkout**, one builder at
a time:

- `git switch -c feature/phase-N-t<id>-<slug>` in the repo root; build, test and commit there.
- The concurrency cap drops from three triads to **one**. A task is built, verified, reviewed
  and merged before the next builder is dispatched.
- Verifier and reviewer run against that same checkout — `git diff main...<branch>` resolves in
  the primary repository, which subagents are permitted to do.

Everything the gates rest on is unaffected, because none of it depended on where the files sat:
spec before code, audited plan before implementation, a fresh context to verify, fresh eyes to
review, `engine-guardian` on anything touching `exchange/`, one PR per task with evidence in the
body. What is lost is wall-clock parallelism at the single point in Phase 0 where three tasks
could have run at once. Serial delivery that moves beats parallel delivery that is blocked.

The orchestrator's own git access is unrestricted; if a future harness lifts the guard, the
option worth revisiting is running builders as top-level `claude -p` processes with cwd in a
worktree, which preserves 0009 §5 as originally written.

### 2. Delivery mechanics are the swarm's to change

**Mechanics** means: how work is isolated, dispatched and committed; the agent prompts in
`.claude/`; the tool allowlist and workarounds for a refused tool; the ledger's shape; the
driver script; anything whose only consequence is how the swarm moves.

The swarm may change mechanics on its own authority — including amending ADR 0009 §5, §7 and
this section — provided it records the change in the ledger's decision log and, when the change
outlives the run, writes it into this ADR. It then **continues in the same run**. A mechanics
question is never a hard stop, never a BLOCKED sentinel, and never something to ask a human.

**Product** decisions are untouched and remain hard stops: ADRs 0001–0008, anything in
`docs/design/`, the specs, the pricing maths, the wire protocol, the data model, a new
third-party dependency, a credential or external account, and Gates B and C themselves. The
line is consequence: a mechanics mistake costs a run, a product mistake reaches a borrel.

### 3. A blocked task parks; it does not end the run

Three failed attempts on one task marks that task `blocked` and **parks** it. The swarm carries
on with every task that does not depend on it, and with later phases whose dependencies are
met. The run ends only when no task anywhere in the route can progress, and the ledger then
carries every parked task with its evidence at once — one human read for all of them instead of
one per task.

A phase whose exit criterion cannot be met because of a parked task is reported in the digest
and does not silently pass.

### 4. An environment blocker is diagnosed where it bites, then worked around

A refused tool, a missing binary, a path the harness will not touch: diagnose it in the context
that hit it, apply the narrowest workaround that keeps the gate intact, record it, continue.
`git mv` refused means `mv` plus `git add -A`, not a stop. Never validate a builder's
environment from the orchestrator's thread — the orchestrator is a top-level context with
permissions no subagent has, so every probe it runs passes while every builder still fails.
That mistake is what made the worktree guard take three runs to find.

## Consequences

- Throughput is now one task at a time. Against a swarm that shipped nothing in three runs, the
  comparison is not with the parallel ideal.
- The swarm can rewrite its own prompts and its own driver. The bound is the product/mechanics
  line above, and the fact that every code change still passes an audited plan, a fresh-context
  verify and a fresh-eyes review before it reaches `main`.
- Fewer human stops, and the ones that remain are product questions with a recommended answer,
  which is what a human is actually useful for here.
- `/.worktrees/` and `permissions.additionalDirectories` for `../.borrelbeurs-swarm` are dead
  weight and removed.
- Branch protection on GitHub (Phase 0 T12) stays a human task: `gh api` is denied deliberately,
  and an external-account change is a product-consequence stop, not mechanics.

## When this reverts

When ADR 0009 reverts, or when the harness permits subagent git in a worktree and parallelism is
worth reinstating. Section 2 reverts if the swarm uses mechanics authority to weaken a gate —
the one use of it that is out of bounds.
