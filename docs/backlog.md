# Feature backlog

Feature ideas for after the rebuild, gathered and ordered before any of them becomes a spec.
An item here is a thought worth keeping, not a commitment: nothing in this file is scheduled
until it goes through `/spec`.

    /backlog <idea>      brainstorm an idea, then add it here
    /backlog             show the order and pick what to do
    /backlog order       re-order the list
    /backlog spec B-nn   mark an item ready and hand it to /spec

## Order

Top is next. Every item that is not `specced` or `dropped` appears here exactly once.

| # | ID | Feature | Size | Status |
|---|---|---|---|---|

## Items

<!--
Template — copy it below the last item, take the next free B-nn, never reuse a number.

### B-nn — <short title>

- **Status:** idea | ready | specced → `docs/specs/<file>.md` | dropped (<why>)
- **Added:** YYYY-MM-DD
- **Size:** S (a day or less) | M (a few tasks) | L (a phase of its own)

**Problem.** Who runs into what, and when — a real moment at a borrel, not a wish.

**Idea.** What would change, in their terms. Not how it is built.

**Why it matters.** What gets better, for whom, and what it costs us not to have it.

**Not this.** What it explicitly is not, or what would make it a failure even if it works.

**Open questions.** What `/spec` will have to settle. Fine to have many.

**Touches.** Areas likely involved (koers screen, bar, admin, engine, …) and any `D-nn` or ADR
it brushes against. A guess is fine; mark it as one.
-->

## Deferred work

Not features: work the rebuild left unfinished on purpose. It stays out of the `Order`
table above. Each item says where it came from.

### Offline venue path: rehearse it (from Phase 8 H2 and H3 step 1)

Deferred 2026-10-17 because the hardware (travel router with no uplink, venue laptop) is not
available. The software is built and merged (Phase 8 T-tasks, `docs/runbooks/venue.md`); what is
missing is the evidence that it works in the real world:

- A mock borrel offline, at least 1 hour, two bar phones and one display: drink added mid-run,
  "Sluit app" then `start.cmd`, hard power-off and restart, laptop clock +1 h and back, manual
  export on a phone, dumps and auto exports accruing, run closed, restore of the newest dump
  (steps and evidence: `docs/plans/phase-8-human-steps.md`, H2). Record:
  `docs/runbooks/rehearsals/<date>-mock-borrel.md`.
- Venue rollback rehearsal (H3 step 1), from bundle n+4 to n+3, timed against 5 minutes.
- Until this is done, the Phase 8 exit ("runs on Render *and* offline; mock borrel passed") is
  not met, and the offline path is unproven in practice (only the image drills in `tests/image`).
