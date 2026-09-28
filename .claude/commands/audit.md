---
description: Walk me through the human audit of a phase plan — the step teams skip
argument-hint: [phase number]
allowed-tools: Read, Grep, Glob, Bash(git*)
model: sonnet
---

Audit the plan for phase **$1** with me.

Read `docs/specs/phase-$1-*.md` and `docs/plans/phase-$1-*.md`.

**This step is mine, not yours.** You are here to make it fast and honest, not to approve the
plan. The way-of-working calls this the step teams skip, because a plan looks finished and
reading it carefully is boring. An agent will happily plan, build and verify the wrong thing
to a very high standard.

## Do this

1. **Build the traceability table.** Every acceptance criterion against the tasks that
   implement it, and every task against the criteria it serves. Show me:
   - criteria with **no** task — the plan is incomplete
   - tasks with **no** criterion — this is where scope creep enters
2. **Flag each task whose expected output is not concrete enough to check.** "Implement the
   repository layer" is not checkable; "`OrderRepository.create()` writes order + lines +
   engine_state + price_tick in one transaction, proven by `test_order_atomic`" is.
3. **Flag every task over the size limit** — roughly 400 lines or 10 files.
4. **List every new dependency** and whether it carries an approval note.
5. **Check data changes are additive and reversible**, and that the expand → migrate →
   contract sequence is stated where anything breaking is involved.
6. **Name anything that touches secrets, production, or `infra/`.**
7. **Check reuse:** for each task, is there already a module in this repo that does this? Name
   it.

## Then walk me through the checklist

Ask me each line separately and wait for my answer. Do not tick anything on my behalf.

- Every AC maps to at least one task
- Every task maps to at least one AC
- Each task's expected output is what we actually need
- Existing patterns reused; nothing reinvented
- No new dependency without an approval note
- Data changes additive and reversible
- Errors, empty states and permissions are tasks, not afterthoughts
- Each task reviewable in one sitting
- Verification named per task
- Nothing touches prod, secrets or infra it should not

## Then

Edit the plan file directly with whatever I decide — that is faster than negotiating in chat
and the file is the record. Fill in `Audited by` and the date, and commit the plan.

Only after that may `/build` run.
