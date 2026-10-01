---
description: Implement a task — or a whole phase, task by task — from an audited plan, test-first, with evidence
argument-hint: "[phase number] [task id, e.g. T3 — omit to build every task in the phase]"
model: opus
---

Phase **$1**, task **$2**, from `docs/plans/phase-$1-*.md`.

**If no task id is given, build the whole phase:** every task in the plan, one at a time, in
the order of its task graph (a task only after everything it `Depends on`). Each task is run
exactly as the single-task rules below describe — its own branch, its own failing test, its
own green gate, its own commit — before the next one starts. Batching does not loosen any
rule; it only saves me typing the next command.

## Preconditions — check these and stop if any fails

- The plan exists and its audit checklist is filled in with a name and date — either mine or
  `plan-auditor`'s PASS, per [ADR 0009](../../docs/adr/0009-autonomous-swarm-delivery.md). **No
  implementation before an audited plan.**
- Task $2 exists in that plan (single-task mode).
- The working tree is clean, and you are on a feature branch — not `main`.

## Scope

**Only the current task. Only the files that task names.** If you find something else that
wants fixing, write it down and tell me; do not fix it. A 40-file diff is not a favour.

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

## Whole-phase mode

- **Branches stack.** Task N's branch, `feature/phase-$1-tN-<slug>`, is cut from the previous
  task's branch, so later tasks build on earlier ones before I have merged anything. Commit
  each task on its own branch with a conventional message (`feat(phase-$1): TN — ...`).
- **Never push, merge or open a PR.** I do that by hand, in order.
- **Stop the whole run — do not skip to the next task — on:** a red gate you cannot make
  green within the task's scope; anything the task's autonomy note says to stop or ask on; a
  golden-fixture divergence; an ambiguity; a task that has grown beyond the plan. Report where
  you stopped and what is still unbuilt.
- **Steps that need me** (e.g. a "green in CI before merge" verification) are not yours to
  wait for: note them against the task and carry on, unless a later task's correctness depends
  on the result.
- **Subagents run on sonnet.** Whenever you dispatch one (`engine-guardian`, or any other),
  pass `model: "sonnet"` explicitly — that overrides the agent's own pin for this run only.
- Keep a running ledger in your final report: per task, branch, commit, the check command and
  its result.

## Invariants you must not break

From `docs/plans/rebuild-route.md`:

- The `exchange` package imports no clock, no I/O, no framework.
- Golden fixtures pass. **If you touched anything under `exchange/`, run the
  `engine-guardian` agent before claiming that task done.**
- No float holds a euro amount in the database.
- Per-drink persisted values keyed by `drink_id`, never array position.
- Every route has an explicit authorization dependency.
- Inside the state lock: pure numpy plus one short DB transaction, nothing else.
- No runtime request leaves the origin.
- The price displayed is the price charged, or the order is rejected.

## Finish with evidence, not assertions

Show the actual command and its actual output, for every task. "Tests pass" is not
acceptable; the test output is. If something is still failing, say so plainly and show it —
do not report partial work as complete.

Then tell me to run `/review` in a **fresh session** — per task, in order. You must not be
the only reviewer of your own code.
