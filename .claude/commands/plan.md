---
description: Turn an approved phase spec into an auditable task plan (read-only)
argument-hint: [phase number]
allowed-tools: Read, Grep, Glob, Bash(git*), Bash(ls*), Bash(find*), Bash(rg*), Write, Edit
model: opus
---

Plan phase **$1**.

Spec: `docs/specs/phase-$1-*.md`. If it does not exist or is still Draft without my approval,
stop and say so — **no implementation before an approved plan, and no plan before a spec.**

## Rules

**Explore read-only.** The only file you may create or edit is `docs/plans/phase-$1-*.md`.
No implementation code, no scaffolding, no "while I was here" fixes.

Read first: the spec, `docs/design/`, `docs/adr/`, `docs/specs/defect-register.md`, and the
actual code you intend to change. Do not reopen decisions already in an ADR — if you
disagree, put it in Risks.

Delegate wide exploration to `phase-planner` or `codebase-analyst` agents so the reading does
not consume this session's context.

## Output

`docs/plans/phase-$1-<name>.md`, following `docs/way-of-working.md` Appendix D: Approach,
Files table, Tasks (each with *Implements*, *Expected output*, *Verification*, *Depends on*,
*Autonomy note*), the task graph and its parallel groups, Data changes, Risks and unknowns,
Out of scope, and the audit checklist. The exact template is in
[`.claude/agents/phase-planner.md`](../agents/phase-planner.md).

The plan is also a **work queue**: the swarm schedules from `Depends on`, so every task needs
one, and no two tasks in the same parallel group may write the same file.

## What makes this plan good or useless

- **Every acceptance criterion maps to at least one task. Every task maps back to at least
  one criterion.** Orphan tasks are where scope creep enters.
- **Each task is one vertical slice that leaves the system working** — not "the whole
  backend".
- **Reviewable in one sitting**: roughly ≤400 changed lines across ≤10 files. Split anything
  larger.
- **Verification named per task.** "Tests pass" is not a verification; `pytest
  tests/db/test_rehydrate.py` is.
- **Name the existing module to reuse.** Duplicated logic is this project's most likely
  failure mode.
- **No new dependency without an approval note**: what it does, why not the standard library,
  licence, maintenance status.

## Finish by

Stating plainly what you are uncertain about. Then the plan goes to `plan-auditor`, whose PASS
is what unblocks implementation — a plan is a proposal, not an instruction, and an agent will
happily plan, build and verify the wrong thing to a very high standard. Run `/audit $1` instead
if you want to walk the checklist yourself; the swarm dispatches the agent either way.
