# Pending `.claude/` edits — apply these by hand

The harness refuses edits to `.claude/` and `~/.claude.json` from an agent session running in
auto mode (classifier: *Self-Modification*). Everything below was written on 2026-09-22 while
applying [ADR 0010](../adr/0010-the-swarm-owns-its-own-delivery-mechanics.md); the parts that
could be applied already were. These are the leftovers.

**None of them blocks a build.** `rebuild.md` — the file the orchestrator actually reads — is
already correct, and the ledger plus ADR 0010 are authoritative where a file below disagrees.
They are stale wording that will send a future run back down the worktree dead end. Delete this
file once they are applied.

---

## 1. `.claude/agents/task-builder.md`

**Frontmatter, line 3** — replace `in its own worktree` with `on its own branch`:

```
description: Implements exactly ONE task from an audited phase plan, test-first, on its own branch, and reports evidence. Use for every task the swarm builds. It never reviews its own work and never merges.
```

**Lines 8–12** — replace:

```
You implement one task from an audited plan. One task, in the worktree you were given, on the
branch you were given. Then you stop and report.

You will be told: the phase, the task id, the worktree path and the branch name. Everything
else you read from the files.
```

with:

```
You implement one task from an audited plan. One task, on the branch you were given, in the
repository's primary checkout. Then you stop and report.

You will be told: the phase, the task id and the branch name. Everything else you read from
the files.
```

**Line 20–21** — replace the precondition bullet:

```
- You are in the worktree you were given, on the named branch, and the tree is clean. Never
  build on `main`.
```

with:

```
- `git rev-parse --abbrev-ref HEAD` returns the branch you were given, and `git status
  --porcelain` is empty. Never build on `main`.
```

**Lines 23–27** — replace the whole "session's working directory" paragraph:

```
**The session's working directory is the main checkout, not your worktree.** Every shell
command must be rooted in the worktree — `cd <worktree> && <command>`, or `git -C <worktree>`
— and every file you edit must be an absolute path under it. Confirm with `git -C <worktree>
rev-parse --abbrev-ref HEAD` before your first edit. Editing the main checkout by accident is
the one mistake here that corrupts another builder's work as well as your own.
```

with:

```
**You work in the repository's primary checkout, on your branch — not in a worktree.** A
subagent cannot run `git` against any non-primary worktree (ADR 0010 §1); if you are handed a
worktree path, ignore it and say so in your report. Your first command is `git rev-parse
--abbrev-ref HEAD`, and if it does not name your branch, stop rather than build on `main`.

Your cwd resets between Bash calls, so `cd` in one call buys nothing in the next: keep every
command self-contained and every path absolute.

`git mv` and `git rm` are not allowlisted. Use `mv`/`rm` plus `git add -A`, which produces a
byte-identical commit — git detects renames at read time rather than recording them.
```

## 2. `.claude/agents/task-verifier.md`

**Line 12** — replace:

```
You will be told the worktree path, the branch, the phase and the task id.
```

with:

```
You will be told the branch, the phase and the task id. The work is on that branch in the
primary checkout; there is no worktree.
```

## 3. `.claude/agents/phase-planner.md`

**Lines 99–102** — replace:

```
- **Tasks in the same parallel group must not write the same file.** Three builders run
  concurrently in separate worktrees and merge into one `main`; two tasks editing
  `pyproject.toml` in the same group is a conflict you designed in. If two tasks must share a
  file, make one depend on the other and say why.
```

with:

```
- **Tasks in the same group must not write the same file.** Builders run one at a time in the
  primary checkout (ADR 0010 §1), but a group's branches still all merge into one `main`, so
  two tasks editing `pyproject.toml` in the same group is a conflict you designed in. If two
  tasks must share a file, make one depend on the other and say why.
```

## 4. `.claude/agents/plan-auditor.md`

**Lines 93–95** — replace:

```
   cycle; two tasks in the same parallel group do not write the same file. The swarm runs
   parallel groups concurrently in separate worktrees, so a wrong graph becomes a merge
   conflict at best and a lost edit at worst. Recompute the groups yourself from the
```

with:

```
   cycle; two tasks in the same group do not write the same file. Every branch in a group
   merges into one `main`, so a wrong graph becomes a merge conflict at best and a lost edit
   at worst. Recompute the groups yourself from the
```

## 5. `.claude/README.md`

**Lines 21–23** — the diagram caption:

```
                                            │   per ready task, up to 3 concurrently:
                                            └─► task-builder ──► task-verifier ──► fresh-eyes-reviewer
                                                  (own worktree)    (fresh ctx)      (+ engine-guardian
```

becomes:

```
                                            │   one ready task at a time:
                                            └─► task-builder ──► task-verifier ──► fresh-eyes-reviewer
                                                  (own branch)     (fresh ctx)      (+ engine-guardian
```

**Line 69** — `| `task-builder` | Implementing exactly one task, in its own worktree |` becomes
`| `task-builder` | Implementing exactly one task, on its own branch |`.

## 6. `.claude/commands/rebuild.md`

Mostly applied already. Two edits were refused:

**The state-machine diagram** — `attempt += 1 (max 3, then blocked)` becomes
`attempt += 1 (max 3, then parked — the run goes on)`.

**"Things you must not do", second bullet** — replace:

```
- Write or modify code, tests or config. The ledger and the digests are your files.
```

with:

```
- Write or modify product code, tests or config. Your files are the ledger, the digests, and —
  only to fix a mechanics blocker under ADR 0010 — `.claude/`, `scripts/swarm.ps1` and ADR 0010
  itself. Everything in `backend/`, `exchange/`, `frontend/`, `static/` and `config/` reaches
  `main` through a builder, an audited plan and both gates. No exceptions, not even one line.
```

## 7. `.claude/settings.json`

- **Delete** `"additionalDirectories": ["../.borrelbeurs-swarm"],` — that directory is dead
  under ADR 0010, and it is permission surface granted for nothing.
- **Add** to `permissions.allow`: `"Bash(git mv:*)"`, `"Bash(git rm:*)"`,
  `"Bash(git restore:*)"`. A refused `git mv` mid-task costs a builder a detour every time.
- **Leave** `"Bash(gh api:*)"` denied. Phase 0 T12 stays a human task; see the ledger.
- Optional, and only if you want the swarm to be able to repair its own prompts: the
  self-modification guard on `.claude/` is enforced by the harness, not by this file, so there
  is nothing to add here that would lift it. Applying ADR 0010 §2 fully means a human applies
  edits like these, which is the loop this file exists to close.
