# Phase digests

One file per phase, written by the swarm orchestrator at each phase exit: what now works, the
exit criterion with its real command output, the invariant sweep, the decisions the swarm took
alone, the review findings it recorded and deliberately did not chase, and the two or three
diffs most worth a human's second opinion.

This is the report that replaces standing in the loop. Under
[ADR 0009](../../adr/0009-autonomous-swarm-delivery.md) nobody approves these before the work
merges — they exist so the work is still *readable* afterwards.
