# Agent configuration

Committed on purpose (way-of-working §5.1) so the workflow is part of the repo rather than
folklore.

## The loop

Each step is a separate session. Clear between them — carrying context forward biases the
next step toward whatever you happened to discuss.

```
  /analyse <thing>     understand what is really there        (read-only)
  /spec <N>            interview → docs/specs/phase-N.md      → I approve
  /plan <N>            read-only → docs/plans/phase-N.md
  /audit <N>           the human audit                        ← the step teams skip
  /build <N> <T>       implement ONE task, test-first
  /verify              run the gate, produce evidence
  /review <N>          fresh context reviews the diff         ← never the author
```

Steps 1, 4, 7 and 9 of the way-of-working loop are human-owned and cannot be delegated.
`/audit` and `/review` exist to make those fast, not to do them for you.

`/rebuild [N]` drives that loop across all nine phases: it sequences the steps, dispatches a
fresh agent per step, runs the checks itself, and halts at every human gate. It writes no
code — only `docs/plans/rebuild-progress.md`, which is how it resumes in a new session.

## Commands

| Command | Purpose | Model |
|---|---|---|
| `/analyse` | Fan out `codebase-analyst` agents over a slice of the code | opus |
| `/spec` | Interview, then write the phase spec | opus |
| `/plan` | Read-only exploration → an auditable task plan | opus |
| `/audit` | Traceability table + the human checklist | opus |
| `/build` | Implement one task from an audited plan | opus |
| `/verify` | Run the gate, report actual output | sonnet |
| `/review` | Fresh-context review against spec and plan | opus |
| `/rebuild` | Orchestrate the nine-phase route; stops at each gate | opus |

Model tiers follow way-of-working §4.1: architecture, specs, planning and review get the most
capable model, because errors there propagate into everything downstream. Running a check and
reporting its output does not.

## Agents

| Agent | Use when |
|---|---|
| `codebase-analyst` | You need an exhaustive, quotable inventory before designing |
| `spec-interviewer` | Starting a unit of work; finds the holes in your thinking |
| `phase-planner` | Turning an approved spec into tasks |
| `fresh-eyes-reviewer` | Before every merge |
| `engine-guardian` | **Any diff touching `exchange/`** — verifies the pricing maths is unchanged |

## The rules these encode

- No code before a spec. No implementation before an audited plan.
- One vertical slice at a time; a section is only in when it passes the Definition of Done.
- The agent must have a check it can run. Evidence, not assertions.
- The session that wrote the code is never its only reviewer.
- Agents never hold production credentials.

See [../docs/way-of-working.md](../docs/way-of-working.md) for the full version, and
[../docs/plans/rebuild-route.md](../docs/plans/rebuild-route.md) for the phase order.
