# BorrelBeurs documentation

| Folder | Contents |
|---|---|
| [way-of-working.md](way-of-working.md) | The team operating manual. Everything here follows it. |
| [adr/](adr/) | Architecture Decision Records. One page each: context, decision, alternatives, consequences. |
| [design/](design/) | The v2 architecture, in detail. |
| [specs/](specs/) | One spec per rebuild phase, plus the defect register. Acceptance criteria live here. |
| [runbooks/](runbooks/) | Deploy, rollback, restore, the venue, incidents. |
| [plans/](plans/) | The finished rebuild route and its standing invariants, plans for new work. |
| [backlog.md](backlog.md) | Feature ideas, ordered, before they become specs. Fed by `/backlog`. |
| [rebuild-review.md](rebuild-review.md) | The rebuild measured against its own contract, and the triage. |

## Start here

1. [design/architecture.md](design/architecture.md) — the system.
2. [adr/0001-setup-decision-record.md](adr/0001-setup-decision-record.md) — the decisions and what they cost.
3. [plans/rebuild-route.md](plans/rebuild-route.md) — the invariants every change keeps.
4. [specs/defect-register.md](specs/defect-register.md) — everything wrong with v1 that v2 must not inherit.

## Working on this

The workflow is committed in [`.claude/`](../.claude/) — see [.claude/README.md](../.claude/README.md).
New work runs by hand, one fresh session per step:

    /backlog <idea>    brainstorm it into backlog.md; promote it when it is next
    /analyse <thing>   understand what is really there
    /spec <N>          interview -> docs/specs/phase-N-*.md
    /plan <N>          read-only -> docs/plans/phase-N-*.md
    /audit <N>         the audit checklist, walked by hand
    /build <N> [T]     implement one task (or the whole plan), test-first
    /verify            run the gate, produce evidence
    /review <N>        fresh context reviews the diff

## History

The rebuild is finished: all nine phases are on `main`. The per-phase plans, the build ledger and
v1's source (`legacy/v1/`) were removed after the review and live on at tag `v2-rebuild-complete`.
The specs, the defect register and the ADRs stay, because code comments cite their IDs.
