# Agent configuration

Committed on purpose (way-of-working §5.1) so the workflow is part of the repo rather than
folklore.

## How the rebuild actually runs

One long-running swarm, per [ADR 0009](../docs/adr/0009-autonomous-swarm-delivery.md). The
four human-owned steps of way-of-working §4.2 are delegated to fresh-context agents for this
rebuild; the human reads a digest per phase instead of standing in the loop.

```
  ./scripts/swarm.ps1        drive the whole route until it finishes or blocks
  /rebuild [N]               one orchestrator run, resumed from the ledger
```

Per phase the orchestrator dispatches:

```
  phase-planner ──► plan-auditor ──► PASS ──┐
                                            │   per ready task, up to 3 concurrently:
                                            └─► task-builder ──► task-verifier ──► fresh-eyes-reviewer
                                                  (own worktree)    (fresh ctx)      (+ engine-guardian
                                                                                      if exchange/ moved)
                                                                          │
                                                             squash-merge ┘ ──► ledger ──► next task
```

State lives in [../docs/plans/rebuild-progress.md](../docs/plans/rebuild-progress.md) and is
reconciled against git at the start of every run, so no run needs to survive its own context.
Phase digests land in `../docs/plans/digests/`.

## Manual commands — the same loop, one step at a time

Still there, and still the right thing when you want to drive a single step yourself or
override the swarm. Each step is a separate session; clear whatever you happened to discuss.

```
  /analyse <thing>     understand what is really there        (read-only)
  /spec <N>            interview → docs/specs/phase-N.md      → you approve
  /plan <N>            read-only → docs/plans/phase-N.md
  /audit <N>           the human audit, if you want it yourself
  /build <N> <T>       implement ONE task, test-first
  /verify              run the gate, produce evidence
  /review <N>          fresh context reviews the diff         ← never the author
```

| Command | Purpose | Model |
|---|---|---|
| `/rebuild` | Drive the route autonomously; stop only on the hard-stop list | opus |
| `/analyse` | Fan out `codebase-analyst` agents over a slice of the code | opus |
| `/spec` | Interview, then write a phase spec | opus |
| `/plan` | Read-only exploration → an auditable, schedulable task plan | opus |
| `/audit` | Traceability table + the checklist, walked with you | opus |
| `/build` | Implement one task from an audited plan | opus |
| `/verify` | Run the gate, report actual output | sonnet |
| `/review` | Fresh-context review against spec and plan | opus |

Model tiers follow way-of-working §4.1: architecture, specs, planning, review and the
orchestrator get the most capable model, because errors there propagate into everything
downstream. Running a check and reporting its output does not.

## Agents

| Agent | Use when |
|---|---|
| `phase-planner` | Turning an approved spec into a schedulable task graph |
| `plan-auditor` | **Gate B** — adversarial plan audit; its PASS unblocks implementation |
| `task-builder` | Implementing exactly one task, in its own worktree |
| `task-verifier` | Running the gate on someone else's work; fixes nothing |
| `fresh-eyes-reviewer` | **Gate C** — before every merge |
| `engine-guardian` | **Any diff touching `exchange/`** — verifies the pricing maths is unchanged |
| `codebase-analyst` | You need an exhaustive, quotable inventory before designing |
| `spec-interviewer` | Starting a unit of work by hand; finds holes in your thinking |

No agent is ever the only judge of its own output, which is the one property the whole
arrangement rests on.

## Permissions

[settings.json](settings.json) is committed: an allowlist broad enough that the swarm is not
asking about `pytest` for the hundredth time, and a denylist covering `config/keys.json`,
force-push, history rewrite, `gh repo`/`gh secret`, and the `borrelbeurs-v1` repository.
Approving the tenth prompt in a row is not review, it is muscle memory — so the interesting
refusals are configured rather than clicked.

Autonomy comes from that allowlist, not from switching the permission system off.

## The rules these files encode

- No code before a spec. No implementation before an audited plan.
- One vertical slice at a time; a section is only in when it can be left in `main` unattended.
- A runnable check per task. Evidence, not assertions.
- The context that wrote the code never reviews it.
- Agents never hold production credentials.
- Everything with a consequence a `git revert` cannot undo stays with the human. That list is
  the hard-stop list in [commands/rebuild.md](commands/rebuild.md).

See [../docs/way-of-working.md](../docs/way-of-working.md) for the full version,
[../docs/adr/0009-autonomous-swarm-delivery.md](../docs/adr/0009-autonomous-swarm-delivery.md)
for what this rebuild relaxes and why, and
[../docs/plans/rebuild-route.md](../docs/plans/rebuild-route.md) for the phase order.
