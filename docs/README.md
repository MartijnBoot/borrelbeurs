# BorrelBeurs documentation

| Folder | Contents |
|---|---|
| [way-of-working.md](way-of-working.md) | The team operating manual. Everything here follows it. |
| [adr/](adr/) | Architecture Decision Records. One page each: context, decision, alternatives, consequences. |
| [design/](design/) | The v2 target architecture, in detail. |
| [specs/](specs/) | One spec per rebuild phase, plus the defect register. Acceptance criteria live here. |
| [plans/](plans/) | The phased rebuild route and per-phase implementation plans. |

## Start here

1. [plans/rebuild-route.md](plans/rebuild-route.md) — what is being built, in what order, and why that order.
2. [adr/0001-setup-decision-record.md](adr/0001-setup-decision-record.md) — the decisions and what they cost.
3. [design/architecture.md](design/architecture.md) — the target system.
4. [specs/defect-register.md](specs/defect-register.md) — everything wrong with v1 that v2 must not inherit.

## Working on this

The workflow is committed in [`.claude/`](../.claude/) — see [.claude/README.md](../.claude/README.md).

The rebuild runs as one long-running swarm, per
[adr/0009-autonomous-swarm-delivery.md](adr/0009-autonomous-swarm-delivery.md):

    ./scripts/swarm.ps1   drive the route until it finishes or blocks
    /rebuild [N]          one orchestrator run, resumed from plans/rebuild-progress.md

The per-step commands remain the manual path, one fresh session each:

    /analyse <thing>   understand what is really there
    /spec <N>          interview -> docs/specs/phase-N.md
    /plan <N>          read-only -> docs/plans/phase-N.md
    /audit <N>         the audit checklist, walked by hand
    /build <N> <T>     implement ONE task, test-first
    /verify            run the gate, produce evidence
    /review <N>        fresh context reviews the diff

## Status

The architecture and the phase boundaries are settled. Phase 0's plan
([plans/phase-0-foundations.md](plans/phase-0-foundations.md)) is written and audited, and its
T1 has landed — this repository *is* T1's output. Plans for phases 1–8 are written one phase at
a time, each audited before any code. `specs/phase-N.md` states a phase's scope, acceptance
criteria and exit condition; `plans/phase-N.md` states the file-by-file task breakdown.

Live state is [plans/rebuild-progress.md](plans/rebuild-progress.md); what each finished phase
produced is in [plans/digests/](plans/digests/).

One change has already landed against v1: see [adr/0007-v1-authorization-hotfix.md](adr/0007-v1-authorization-hotfix.md).
