---
description: Fresh-context review of the current diff against its spec and plan
argument-hint: [phase number, optional]
allowed-tools: Read, Grep, Glob, Bash(git*), Bash(pytest*), Bash(npm*), Bash(pnpm*)
model: opus
---

Review the current diff.

**Run this in a session that did not write the code.** If this session wrote it, stop and
tell me to clear and start again. A context that wrote the code defends the reasoning that
produced it rather than judging the result.

## Read, in this order

1. `docs/specs/phase-$1-*.md` — the acceptance criteria are the contract, not the PR
   description.
2. `docs/plans/phase-$1-*.md` — the task boundaries.
3. `git diff main...HEAD`.
4. **The surrounding code the diff touches.** A diff read in isolation hides most bugs.

Use the `fresh-eyes-reviewer` agent for the pass. If the diff touches `exchange/`, also run
`engine-guardian` — a silent change to the pricing maths would not surface until a borrel
priced wrongly in front of a room full of people.

## Report

Findings ranked **Correctness** (must fix) / **Risk** (discuss) / **Optional**, each with
file, line, and the acceptance criterion or invariant it violates.

Check specifically:

- Every acceptance criterion in scope is implemented.
- Tests would **fail if the implementation were wrong** — mentally break one and see.
- Error paths, empty states and permissions handled, not just the happy path.
- Nothing outside the task's named files changed.
- No logic duplicated from somewhere it already exists.
- No invented API, config key or dependency — does it exist, is it in the lockfile?
- Migrations additive and reversible.
- No secrets or personal data in code, tests, logs or fixtures.
- The project invariants in `docs/plans/rebuild-route.md`.

## Do not report style

Formatting, naming preferences, and structure you would have done differently. The formatter
decides those.

## Calibration

You were asked to find gaps, so you will find some — that is a bias, not a signal. Chasing
every finding produces over-engineering: extra abstraction, defensive code, tests for cases
that cannot happen.

**"No correctness gaps" is a valid and useful result.** Say it plainly if it is true.
