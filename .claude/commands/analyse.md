---
description: Deep read-only analysis of part of the codebase, fanned out to parallel analyst agents
argument-hint: [what to analyse, e.g. "the order path" or "static/koers.html"]
model: sonnet
---

Analyse: **$ARGUMENTS**

Produce an exhaustive, quotable inventory of how this actually works today. This is input to
a design decision, so accuracy matters more than brevity and vagueness is useless.

## How to run this

1. **Read `docs/` first** — `design/`, `adr/` and `specs/defect-register.md`. Much may
   already be documented, and re-deriving it wastes the session. Say what you are relying on
   rather than re-analysing it.

2. **Split the work across `codebase-analyst` agents, launched in parallel in one message.**
   Two or three, each with a distinct, non-overlapping slice — never the same files. Give
   each one a specific brief, not a general instruction to "look at the backend".

3. Give each agent the same standing requirements:
   - Read the actual files; never infer behaviour from names or comments.
   - Quote exact identifiers verbatim — field names, config keys, route paths.
   - `file:line` for every claim.
   - Check the **live** configuration values, not the defaults. Report what is dead code in
     production.
   - Report defects found that were not asked about.

4. **Do not take an agent's findings at face value if something looks off.** Spot-check the
   surprising claims yourself before repeating them.

## Output

Consolidate into one report. Separate clearly:

- **What it does** — the inventory.
- **Defects found** — with the consequence of each, not just the fact.
- **Open questions** — what you could not determine and what would settle it.

If the analysis changes something recorded in `docs/`, say so explicitly. Do not silently
contradict an ADR.

Do not propose an architecture in this command. Analysis and design are separate steps, and
mixing them is how you end up defending a design instead of reading the code.
