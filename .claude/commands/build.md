---
description: Implement ONE task from an audited phase plan, test-first, with evidence
argument-hint: "[phase number] [task id, e.g. T3]"
model: sonnet
---

Implement task **$2** from `docs/plans/phase-$1-*.md`.

## Preconditions — check these and stop if any fails

- The plan exists and its audit checklist is filled in with a name and date — either mine or
  `plan-auditor`'s PASS, per [ADR 0009](../../docs/adr/0009-autonomous-swarm-delivery.md). **No
  implementation before an audited plan.**
- Task $2 exists in that plan.
- The working tree is clean, and you are on a feature branch — not `main`.

## Scope

**Only task $2. Only the files that task names.** If you find something else that wants
fixing, write it down and tell me; do not fix it. A 40-file diff is not a favour.

If a requirement turns out to be ambiguous, **stop and ask** rather than guessing. A
confident guess that solves the adjacent problem is this project's most likely failure mode.

If the task turns out to be bigger than the plan assumed, stop and say so. Do not silently
expand it.

## How

1. **Write the failing test first.** For a bug fix, the regression test comes before the fix,
   always. For a feature, the acceptance criteria become the test cases.
2. Implement the simplest thing that satisfies the criteria. **No new abstraction unless two
   callers exist today.**
3. Follow the existing pattern — the plan names the module to imitate. Use only libraries
   already in the project; a new dependency needs my approval first.
4. Run the check named in the task, plus `scripts/check.sh`. Iterate until green.

## Invariants you must not break

From `docs/plans/rebuild-route.md`:

- The `exchange` package imports no clock, no I/O, no framework.
- Golden fixtures pass. **If you touched anything under `exchange/`, run the
  `engine-guardian` agent before claiming done.**
- No float holds a euro amount in the database.
- Per-drink persisted values keyed by `drink_id`, never array position.
- Every route has an explicit authorization dependency.
- Inside the state lock: pure numpy plus one short DB transaction, nothing else.
- No runtime request leaves the origin.
- The price displayed is the price charged, or the order is rejected.

## Finish with evidence, not assertions

Show the actual command and its actual output. "Tests pass" is not acceptable; the test
output is. If something is still failing, say so plainly and show it — do not report partial
work as complete.

Then tell me to run `/review` in a **fresh session**. You must not be the only reviewer of
your own code.
