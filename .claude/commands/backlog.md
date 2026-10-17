---
description: Brainstorm a feature idea into the backlog, or show, order and promote backlog items
argument-hint: [an idea in your own words | order | spec B-nn]
model: opus
---

Backlog request: **$ARGUMENTS**

The backlog is `docs/backlog.md`. Read it first, every time. Its header holds the template and
the rules for the `Order` table; follow them.

## What to do, by argument

### No argument — show it

Print the `Order` table as it stands (plus a count of `specced` and `dropped` items), then ask
one question: add an idea, re-order, or promote one to a spec?

### `order` — re-order

Show the current order. Ask what should move, one question at a time, and if I want help
deciding, weigh items on value at the next borrel against size. Rewrite the `Order` table
only; do not touch the items.

### `spec B-nn` — promote

Read the item. If its **Problem** or **Idea** is still vague, say which, and offer to
brainstorm it further first. Otherwise set its status to `ready`, and tell me to start a
**fresh session** and run `/spec B-nn`. Do not write the spec here; the interview belongs in
its own context.

When a spec for a backlog item lands, its status becomes
`specced → docs/specs/<file>.md` and it leaves the `Order` table.

### Anything else — a new idea

Use the `superpowers:brainstorming` skill on the idea, with these limits. They override the
skill wherever the two disagree:

- **The output is a backlog item, not a design.** Brainstorm until you can fill the template's
  Problem, Idea, Why it matters and Not this in my words. That is usually a handful of
  questions, not a long interview. Leave anything harder as an **Open question** for `/spec`.
- **Ground it before asking.** Skim `docs/plans/rebuild-route.md`, `docs/specs/defect-register.md`
  and the relevant `docs/design/` page so you neither ask what the repo already answers nor miss
  that the idea already exists, is already out of scope somewhere, or collides with an ADR.
  Say so if it does.
- **One question per message**, same as the skill.
- **Play the filled-in item back to me** before writing it. My approval is the skill's
  approval gate.
- **No design document, no plan, no code, no spike.** Do not invoke `superpowers:writing-plans`
  or any implementation skill afterwards.
- If the idea turns out to be two or three features, say so and make them separate items.

Then add it to `docs/backlog.md`: the next free `B-nn`, today's date, `Status: idea`. Ask me
where it goes in the `Order` table; if I do not care, put it at the bottom. Before stopping,
ask whether I have another idea to add.

## Never

- Never renumber an item or reuse a dropped number; `/spec` and commits refer to them.
- Never delete an item. Mark it `dropped (<why>)` so the reason survives.
- Never commit. Tell me the backlog changed; I commit it when I am done gathering.
