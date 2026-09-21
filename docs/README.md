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
Each step is a separate session:

    /analyse <thing>   understand what is really there
    /spec <N>          interview -> docs/specs/phase-N.md
    /plan <N>          read-only -> docs/plans/phase-N.md
    /audit <N>         the human audit
    /build <N> <T>     implement ONE task, test-first
    /verify            run the gate, produce evidence
    /review <N>        fresh context reviews the diff

## Status

The architecture and the phase boundaries are settled. **Per-phase implementation plans
(`plans/phase-N.md`) are not written yet** — the way-of-working calls for those to be
produced in a fresh session per §4.2, then audited by a human before any code is written.
`specs/phase-N.md` states each phase's scope, acceptance criteria and exit condition;
`plans/phase-N.md` will state the file-by-file task breakdown.

One change has already landed against v1: see [adr/0007-v1-authorization-hotfix.md](adr/0007-v1-authorization-hotfix.md).
