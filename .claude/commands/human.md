---
description: Walk me through the human-only steps of a phase, one at a time
argument-hint: "[phase number] [step id, e.g. H1 — omit to continue where we left off]"
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(git status*), Bash(git log*), Bash(git diff*), Bash(gh run*), Bash(gh pr view*), Bash(docker manifest inspect*), Bash(sha256sum*), Bash(uv run pytest*), Bash(bash scripts/make_bundle.sh*)
model: sonnet
---

Guide me through the human steps of phase **$1**, from `docs/plans/phase-$1-human-steps.md`.
If a step id is given (`$2`), start there; otherwise read the Progress list and continue with
the first step not ticked.

**These steps are mine, not yours.** They are the ones only a person can do: dashboards,
secrets, a laptop at a router, a hard power-off. You make them fast and honest.

Read the plan, its "Rules for the agent" section first, and obey it exactly. In short:

- One step at a time. Say what to do, what to paste back, then **wait**.
- Do not do the step: no deploy workflow (CLAUDE.md), no secrets or variables, no dashboards,
  nothing in `borrelbeurs-v1` (hard stop, ADR 0009).
- Never connect to production, and never `curl` a deployed URL: ask me to run it and paste.
- Never ask for, repeat or write key material, `DATABASE_URL` or a hook URL.
- Run the plan's "Preconditions (agent checks)" yourself first and show the real output.
- A step is done when I have pasted its named evidence. Then tick its checkbox, fill its "Notes"
  line, and say what is next.
- Draft the rehearsal record from my notes into `docs/runbooks/rehearsals/`, following the
  template in its README. Show it to me before writing it. Do not commit unless I ask.
- If something breaks, write it down as a follow-up or a defect entry; never fix it silently.

Start by telling me where we are: which steps are ticked, which SHA is **n**, and the first
action for me.
