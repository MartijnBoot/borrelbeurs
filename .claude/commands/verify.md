---
description: Run the full local gate and report the actual output as evidence
model: haiku
---

Run the checks and report evidence.

$ARGUMENTS

## Run

1. `scripts/check.sh` — the full local gate: format, lint, types, unit, integration. This is
   the same script CI runs; there is one definition of green.
2. If the diff touches `exchange/`: `pytest tests/engine` explicitly, and call out the golden
   fixture result on its own line. This is the gate on the whole rebuild.
3. If the diff touches migrations: apply **and** roll back against a scratch database.
4. If the diff touches the frontend: type check, unit tests, and the built-output check that
   no asset reference leaves the origin.
5. If the diff touches the order path: run the price-invariant property test and report the
   case count.

## Report

For each check: the **command** and its **actual output**. Not a summary, not a claim.

Then a single verdict line: **green** or **red**. If red, quote the failure and stop — do not
attempt a fix in this command, and do not describe the work as complete.

## What not to do

- Do not fix the root cause by suppressing the error.
- Do not skip a check because it is slow or because you are confident.
- Do not say "should pass" about anything you did not run. If you could not run it, say which
  one and why.
