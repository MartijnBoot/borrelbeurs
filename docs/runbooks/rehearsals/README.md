# Rehearsal records (SD19)

One file per rehearsal, `docs/runbooks/rehearsals/<yyyy-mm-dd>-<what>.md`, for example
`2026-11-02-mock-borrel.md`. Human-performed; an agent may draft the file from your notes.
Never put key material in one.

```markdown
# <what> -- <yyyy-mm-dd>

- **Image SHA:** <40 hex>
- **Who / where:** <names, venue or laptop>
- **What was done:** <the steps actually performed, in order>
- **Timings:** <each timed step, against its target (rollback: 5 minutes)>
- **What broke:** <anything that did not go as the runbook says; "nothing" if so>
- **Follow-ups:** <one line each: a task, a defect-register entry, or "none">
```

Anything that broke becomes a follow-up task or a defect entry, never a silent fix.
