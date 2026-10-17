# Agent configuration

Committed on purpose (way-of-working §5.1) so the workflow is part of the repo rather than
folklore.

## Commands — the loop, one step at a time

New work runs by hand, one fresh session per step; clear whatever you happened to discuss.

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
| `/analyse` | Fan out `codebase-analyst` agents over a slice of the code | opus |
| `/backlog` | Brainstorm a feature idea into `docs/backlog.md`; order it; promote it to `/spec` | opus |
| `/spec` | Interview, then write a phase spec | opus |
| `/plan` | Read-only exploration → an auditable, schedulable task plan | opus |
| `/audit` | Traceability table + the checklist, walked with you | opus |
| `/build` | Implement one task from an audited plan | opus |
| `/verify` | Run the gate, report actual output | sonnet |
| `/review` | Fresh-context review against spec and plan | opus |

Model tiers follow way-of-working §4.1: architecture, specs, planning and review get the most
capable model, because errors there propagate into everything
downstream. Running a check and reporting its output does not.

## Agents

| Agent | Use when |
|---|---|
| `phase-planner` | Turning an approved spec into a schedulable task graph |
| `plan-auditor` | **Gate B** — adversarial plan audit; its PASS unblocks implementation |
| `fresh-eyes-reviewer` | **Gate C** — before every merge |
| `engine-guardian` | **Any diff touching `exchange/`** — verifies the pricing maths is unchanged |
| `codebase-analyst` | You need an exhaustive, quotable inventory before designing |
| `spec-interviewer` | Starting a unit of work by hand; finds holes in your thinking |

No agent is ever the only judge of its own output, which is the one property the whole
arrangement rests on.

## Permissions

[settings.json](settings.json) is committed: an allowlist broad enough that an agent is not
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
  the hard-stop list in [../CLAUDE.md](../CLAUDE.md).

See [../docs/way-of-working.md](../docs/way-of-working.md) for the full version, and
[../docs/plans/rebuild-route.md](../docs/plans/rebuild-route.md) for the cross-phase invariants.
