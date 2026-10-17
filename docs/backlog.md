# Backlog

Work that is wanted but not scheduled. Each item says where it came from.

## Offline venue path: rehearse it (from Phase 8 H2 and H3 step 1)

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
