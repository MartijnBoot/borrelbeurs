---
description: Interview me about a phase or feature, then write its spec
argument-hint: [phase number, or a feature name]
model: opus
---

Write the spec for: **$ARGUMENTS**

## Before asking me anything

Read `docs/plans/rebuild-route.md`, `docs/specs/defect-register.md`, the relevant
`docs/design/` documents, and any existing spec for this phase. Do not ask me things the
repository already answers.

## Then interview me

Use the `spec-interviewer` agent, or follow its rules directly:

- **One question per message.** A list of six gets three answered.
- Prefer concrete either/or choices over open questions.
- Dig into the hard parts: failure modes, concurrency, empty states, permissions, what
  happens **mid-borrel**, what happens on restart, what happens with no network.
- Push back if an answer contradicts an existing ADR. Name the conflict.

Keep going until you could hand the spec to someone else and they would not need me.

## Then write it

To `docs/specs/phase-$1-<name>.md`, matching the structure of the existing phase specs:

- **Problem** — with `file:line` references to today's behaviour
- **In scope** / **Out of scope** — be generous with out of scope
- **Acceptance criteria** in EARS form (*When … the system shall …*), each one testable
- **Verification** — the end-to-end scenario that proves it works
- **Exit condition** — one sentence

Header must list `Depends on:` and `Fixes: D-nn` for every defect from the register this
phase closes. Each `D-nn` gets its own acceptance criterion — that is the whole point of
fixing defects during the rebuild rather than porting them.

## Then stop

Do not plan and do not write code. Tell me to start a **fresh session** and run `/plan $1`.
The interview context is noise for the planner and would bias the plan toward whatever we
happened to discuss.
