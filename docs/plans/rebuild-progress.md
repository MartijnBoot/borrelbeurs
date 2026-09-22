# Rebuild progress

Route: [rebuild-route.md](rebuild-route.md) · Loop: [ADR 0009](../adr/0009-autonomous-swarm-delivery.md)
+ [ADR 0010](../adr/0010-the-swarm-owns-its-own-delivery-mechanics.md)
Swarm state: CONTINUE
Updated: 2026-09-22 by the human, unblocking the swarm's isolation model

This file is the swarm's only memory. It is reconciled against git at the start of every run,
and written after **every** state transition — a run can die at any moment, and a transition
that is not written down did not happen.

## Now

Phase 0. In flight: **nothing**. Blocked on: **nothing.** Next action: dispatch `task-builder`
for **T2** on branch `feature/phase-0-t2-skeleton-pins-legacy`, cut fresh from `main` in the
primary checkout.

**The isolation blocker is closed.** [ADR 0010](../adr/0010-the-swarm-owns-its-own-delivery-mechanics.md)
amends ADR 0009 §5: per-task worktrees are unreachable for subagent builders, so isolation is
**branch-level in the primary checkout, one builder at a time**. The evidence that closed it —
worktrees outside the root, inside the root, `git -C`, and `EnterWorktree` all refused for
subagents, git in the primary checkout permitted — is in ADR 0010's Context; it is not repeated
here, because this file is the swarm's memory and not its lab notebook.

Two further rulings from ADR 0010 change how a run ends:

- **Delivery mechanics are the swarm's own to fix** — isolation, dispatch, the agent prompts,
  the allowlist, the driver. Diagnose, work around, record in the decision log, keep going. A
  mechanics problem is never a `BLOCKED` sentinel.
- **Three failed attempts parks a task; the run continues** with everything that does not depend
  on it. The run ends only when nothing anywhere can progress.

Cleanup already done for you: the `.worktrees/phase-0-t2` worktree was removed (clean, zero
commits) and its branch deleted. `git worktree list` shows the primary checkout only.

## Phases

| Phase | Spec | Plan audited | Tasks | Exit criterion | State |
|---|---|---|---|---|---|
| −1 v1 authorization hotfix | — | — | — | done, commit `b617a56` | ✅ closed |
| 0 Foundations | ✅ approved | ✅ human, 2026-09-21 | 1/13 merged | `setup.sh` then one command gives a running shell app; CI green | ▶ in progress — T2 next |
| 1 Engine extraction + golden tests | ✅ exists | — | 0/– | pure engine reproduces v1's outputs exactly | not started |
| 2 Data model + persistence | ✅ exists | — | 0/– | live config round-trips through Postgres; restart preserves prices | not started |
| 3 API + auth + realtime | ✅ exists | — | 0/– | every route authorized; integration tests green against real Postgres | not started |
| 4 React shell + theme + auth + koers | ✅ exists | — | 0/– | big screen works end to end; theme propagates across machines | not started |
| 5 Bar + order path | ✅ exists | — | 0/– | price shown equals price charged, property-tested | not started |
| 6 Manipulation + settings | ✅ exists | — | 0/– | an admin configures a borrel from scratch | not started |
| 7 Analytics + run lifecycle | ✅ exists | — | 0/– | two borrels comparable; xlsx matches the database | not started |
| 8 Deploy + cutover | ✅ exists | — | 0/– | runs on Render *and* offline; rollback rehearsed; mock borrel passed | not started |

## Phase 0 tasks

Plan: [phase-0-foundations.md](phase-0-foundations.md) · audited by the human, 2026-09-21.

Dependency graph as stated by the plan — **not serial**, despite what the old ledger said.
Verified against the plan's `Depends on` fields by run 1:

```
T1 ─► T2 ─► T3 ─┬─► T4 ─┐
                ├─► T5 ─► T6 ─┼─► T9 ─► T10 ─► T11 ─► T12
                └─► T7 ─┬─────┘
                        ├─► T8
                        └─► T13
```

| Group | Tasks | Note |
|---|---|---|
| 1 | T2 | |
| 2 | T3 | |
| 3 | T4, T5, T7 | eligible together, built one after another — ADR 0010 §1 caps builders at one |
| 4 | T6, T13 | |
| 5 | T8, T9 | T9 also needs T4 |
| 6 | T10 → T11 → T12 | serial tail |

| Task | State | Attempt | Branch | PR | Verified (command + actual output) | Review |
|---|---|---|---|---|---|---|
| T1 fresh repo | merged | 1 | `main` (founding commits `aaf1e3b`, `d6c10a9`) | none — pre-swarm | `git count-objects -vH` → `size-pack: 457.37 KiB`, `in-pack: 122`, `packs: 1` < 5 MiB · `git rev-list --max-parents=0 HEAD` → `aaf1e3b` (sole root) · `git log --all --oneline --` for `config/keys.json`, `config/.jwt_secret`, `*.tar`, `static/earnings`, `static/uploads`, `*__pycache__*`, `*.pyc`, `*.pdf` → all empty · largest blob in repo is `docs/way-of-working.md` at 112,691 B < 200 kB · `git diff --name-status d6c10a9 HEAD` → no imported v1 file modified after import | **Gate C PASS** — `fresh-eyes-reviewer`, run 1, 2026-09-21. Zero Correctness findings. 5 Risk + 3 Optional recorded below |
| T2 skeleton + pins + legacy move | **ready** — dispatch now | 1 | `feature/phase-0-t2-skeleton-pins-legacy` — deleted, cut it fresh from `main` in the primary checkout | — | attempt 1 returned `blocked` with nothing written: git unusable in a worktree for subagents. An environment failure, not a code failure; it does not consume the attempt budget, and the cause is now fixed (ADR 0010) | — |
| T3 config module, fail-fast | pending | 0 | — | — | — | — |
| T4 config boundary test | pending | 0 | — | — | — | — |
| T5 FastAPI shell + health | pending | 0 | — | — | — | — |
| T6 web shell, same origin | pending | 0 | — | — | — | — |
| T7 Postgres + Compose + Alembic baseline | pending | 0 | — | — | — | — |
| T8 `scripts/setup.sh` | pending | 0 | — | — | — | — |
| T9 `scripts/check.sh` | pending | 0 | — | — | — | — |
| T10 Dockerfile + build context | pending | 0 | — | — | — | — |
| T11 CI workflow | pending | 0 | — | — | — | — |
| T12 repository governance | pending | 0 | — | — | — | — |
| T13 `CLAUDE.md` + agent config + migration hook | pending | 0 | — | — | — | — |

## ⚠ Live inconsistency — `.claude/` edits need the human

`.claude/commands/rebuild.md` has been corrected to branch-level isolation. Some sibling files
still describe worktrees, because editing files under `.claude/` is refused by the harness's
self-modification guard and has to be applied by the human:

| File | What is stale |
|---|---|
| `.claude/agents/task-builder.md` | the whole "you are in the worktree you were given" preamble; should be "on the branch you were given, in the primary checkout" |
| `.claude/agents/task-verifier.md` | "you will be told the worktree path" |
| `.claude/agents/phase-planner.md`, `.claude/agents/plan-auditor.md` | describe concurrent groups running "in separate worktrees" |
| `.claude/README.md` | the diagram's "(own worktree)" caption |
| `.claude/settings.json` | `additionalDirectories: ["../.borrelbeurs-swarm"]` is dead; `git mv`/`git rm`/`git switch` are not allowlisted |

The exact old-and-new text for every one of them is in
[pending-claude-config-edits.md](pending-claude-config-edits.md); delete that file once applied.

Until those land, **this ledger and ADR 0010 are authoritative on isolation.** A builder handed
a worktree path should ignore it and work on its branch in the primary checkout. Nothing here
blocks a build: a builder that stays in the primary checkout can commit, which is the only thing
the old wording actually broke.

## Decisions the swarm took alone

- **2026-09-21, T1 — v1 repo renamed to free D14's chosen name.** D14 specifies `borrelbeurs`,
  but GitHub repo names are case-insensitive and the name was held by v1's own `BorrelBeurs`.
  v1 became `MartijnBoot/borrelbeurs-v1`; the new repo took `borrelbeurs`. The same collision
  hit the filesystem, so the new repo is cloned at `borrelbeurs-v2` locally. **Directory name ≠
  repo name; do not "fix" this.** R8 is unaffected — renaming does not rotate v1's keys, and
  Phase 8 still owns that.
- **2026-09-21, run 3 — swarm worktrees move inside the project root**, from
  `../.borrelbeurs-swarm/phase-N-t<id>` to `.worktrees/phase-N-t<id>`, with `/.worktrees/` added to
  `.gitignore` and the two paths in `.claude/commands/rebuild.md` updated. Nothing else changes;
  `scripts/swarm.ps1` contains no worktree path.

  Why this and not the alternatives: it is the **only** option that works under the permissions
  that exist today, proven by the control test `cd <inside-root> && git status` → allowed. Granting
  `Bash(git -C ../.borrelbeurs-swarm:*)` needs a human (the self-modification classifier refuses
  agents editing `.claude/settings.json`) and may not even work, since the refusal looks like a
  version-control heuristic rather than a missing allow rule. Building in the main tree with no
  worktree abandons the per-task isolation ADR 0009 §5 names.

  **Run 2 recorded this option as unavailable because `.gitignore` is a code edit "the orchestrator
  is not allowed to make". That reasoning was wrong** — the orchestrator may not *write* code, but
  it may *dispatch an agent* to. That distinction is the difference between a two-run stall and a
  ten-minute fix, and it is why this is not a hard stop.

  **No ADR needed.** ADR 0009 §5 says only "each in its own git worktree and branch" — it does not
  specify a location, so per-task isolation is preserved exactly. Reversible in one commit.

  Follow-on for T2's builder: T2 rewrites `.gitignore`, so it must **preserve** the swarm worktree
  ignore entry rather than drop it.

  **⚠ Superseded the same day — the premise above was wrong.** Relocating to `.worktrees/` inside
  the root did **not** make git usable for subagents. Verified after the move:

  ```
  $ cd .../borrelbeurs-v2/.worktrees/phase-0-t2 && ls
  ARCHITECTURE.md  backend  CLAUDE.md  config  Dockerfile  docs  exchange ...   ← allowed
  $ cd .../borrelbeurs-v2/.worktrees/phase-0-t2 && git status --short
  Permission to use Bash has been denied.
  $ cd .../borrelbeurs-v2 && git -C .worktrees/phase-0-t2 rev-parse --abbrev-ref HEAD
  Permission to use Bash has been denied.
  $ cd .../borrelbeurs-v2 && git status --short          ← primary checkout
   M .gitignore                                           ← allowed
  ```

  **The discriminator is the git repository the command resolves to, not the directory's location.**
  A path with its own `.git` file resolving to a non-primary worktree is refused, inside the root or
  outside it, by `cd` or by `git -C`. The control test that motivated the move — `cd <outside> && ls`
  is allowed — only ever proved directory *reachability*, which was never the problem. It tested a
  non-git command against a git-specific guard, so it could not have failed. **That is the reasoning
  error to avoid repeating: a control test must exercise the thing being guarded.**

  Still true and still useful: the Write tool *does* create files in the worktree. Only `git` is
  unreachable — so a builder can write but cannot commit, which is no better than useless.

Taken by the swarm:

- **2026-09-21, run 1 — a tracked `.gitattributes` is folded into T2 (risk R3).** The plan does
  not list one. It is not new scope in spirit: T2 already owns line-ending policy via
  `.editorconfig`, and without a tracked `.gitattributes` the repo's byte-identity with v1
  survives only in one developer's local `.git/config`. That identity is what Phase 1's golden
  fixtures rest on, so losing it silently is the expensive failure. **Constraint on the builder:
  the file must preserve the current per-file CRLF/LF split exactly — it may not renormalise.**
  This is consistent with the T1 decision below, which asked for normalisation to be deliberate
  and separate rather than incidental. No ADR needed; if `plan-auditor` disagrees at the next
  phase it can be reverted in one commit.

  **Run 3 — the EOL baseline is now measured, and it rules out the obvious `.gitattributes`.**
  T2's blocked builder captured it read-only before hitting the git wall:

  ```
  $ git ls-files --eol | awk '{print $1, $2}' | sort | uniq -c | sort -rn
       61 i/lf w/lf
       11 i/crlf w/crlf
        6 i/-text w/-text
        2 i/none w/none

  $ git ls-files --eol | grep -E 'i/crlf|i/none'
  i/crlf  .claude/agents/task-builder.md · .claude/settings.json · Dockerfile
  i/crlf  backend/api.py · backend/config.py · backend/persistence.py
  i/crlf  exchange/engine.py · readme.txt · rebuild.bat · requirements.txt · run.bat
  i/none  backend/__init__.py · exchange/__init__.py
  i/-text static/logo/*.png, *.jpeg (6 binaries)
  ```

  **`exchange/engine.py` is stored CRLF in the index.** So the conventional `* text=auto` — or any
  `*.py text` — would rewrite that blob to LF on the next checkout and **silently break the
  byte-identity that Phase 1's golden fixtures rest on.** This is precisely the expensive failure
  R3 was raised to prevent, and it would have shipped unnoticed under the obvious formulation.

  The only formulation that provably renormalises nothing is **`* -text`** — EOL conversion off for
  everything. Diffs are unaffected, because textual diffing is the `diff` attribute, not `text`.
  **Binding on T2's builder:** use `* -text`, and prove it with `git ls-files --eol` before and
  after showing all 80 rows unchanged.

Carried forward from the pre-swarm loop:

- **2026-09-21, T1 — the new repo sets `core.autocrlf=false`.** v1 committed a mix of CRLF and
  LF; importing through a filter would have silently renormalised files. The import copied blob
  objects directly, so all 32 hashes match v1 byte for byte. T2's `.editorconfig` should treat
  line-ending normalisation as a deliberate, separate change — not something done incidentally
  during `git mv`.

- **2026-09-22, the human — isolation model amended and the swarm given its own mechanics.**
  [ADR 0010](../adr/0010-the-swarm-owns-its-own-delivery-mechanics.md) replaces per-task
  worktrees with serial branch isolation in the primary checkout, makes delivery mechanics the
  swarm's own to fix rather than to report, and turns a three-times-failed task into a parked
  task that does not end the run. Three runs had ended on mechanics; none had ended on the
  product. Trade accepted: one builder at a time instead of three.

## Findings recorded and not chased

From `fresh-eyes-reviewer` on T1, 2026-09-21. None blocks a gate; each is carried to the task
that already owns the surface, so none becomes a plan amendment on its own.

| # | Finding | Carried to | Why not chased now |
|---|---|---|---|
| R1 | `run.bat:60` hard-codes `ADMIN_TOKEN=TestTest`, gating `/shutdown` at `backend/api.py:606-609`. Not on T1's exclusion list, so it is in history | T3 (`Settings`) | Placeholder in a private repo, on a file T2 moves to `legacy/v1/`. **Treat `TestTest` as burned** — nothing at an event may use it, and `ADMIN_TOKEN` joins `JWT_SECRET` in T3's `Settings` without the literal reappearing. A rewrite to remove it would be a hard stop and is not worth it |
| R2 | `.gitignore` omits `static/uploads/`, `__pycache__/`, `*.pyc`, `*.pdf`, `.venv/` — all of which `.dockerignore` covers. Nothing stops a re-add | T2 | T2 already owns `.gitignore`; this is content within an existing deliverable, not new scope |
| R3 | `core.autocrlf=false` lives only in local `.git/config`; no tracked `.gitattributes`. A fresh clone on default Windows settings checks out CRLF for every LF file and renormalises on first commit | T2 | Material to Phase 1's byte-identity claim. See the decision log — folded into T2, and it must **preserve** current per-file EOL, never renormalise |
| R4 | `exchange/engine.py` imports `time` and defines `now_ms()`. The purity test `docs/design/architecture.md:87-89` mandates would go red on imported baseline code if it lands before Phase 1 replaces the engine | Phase 1 planning | Invariant 1 is introduced *by* Phase 1, not before it. Phase 0 must not add that test; when `phase-planner` reaches Phase 1, the test and the engine rewrite land together |
| R5 | T2's "five tracked `.pyc` files removed" is already a no-op — T1's `__pycache__/**` exclusion took them. T2's check `grep -c '\.pyc$'` → 0 passes trivially | T2 verifier | Harmless, but a verifier could read the absent removal commit as an unimplemented step. Flagged so it is not mistaken for a gap |

Optional, for the record: `readme.txt` carries a RFC1918 LAN address (disappears when T2 moves
it); `docs/plans/phase-0-foundations.md:283` contains `AKIAIOSFODNN7EXAMPLE` as the secret-scan
fixture, which gitleaks will flag on its own fixture unless T5 allowlists it; repo visibility is
unverified because `gh repo` is on the swarm's never-do list — **worth a human eyeball.**

## Open items the plan does not cover

- **No task asserts `.env.local` is gitignored**, yet T8 generates a real `JWT_SECRET` into it.
  T8 is not built yet. The swarm should fold this into T8's own verification rather than adding
  a task; if that is not possible, it is a plan amendment and needs `plan-auditor` to re-pass.

## Standing items, carried until closed

- The v1 access keys are still in the `borrelbeurs-v1` git history and need rotating. Phase 8
  AC17 owns it. **Hard stop when reached** — it needs a human with account access.
- `CLAUDE.md` still says "Don't introduce a database"; this rebuild reverses that. T13 fixes it
  in this repo; Phase 8 cutover confirms it.


## Blocked — needs a human

**Nothing blocks the swarm.** Run 3's hard stop (Question 3 — how builders get an isolated
working tree) was answered on 2026-09-22 by [ADR 0010](../adr/0010-the-swarm-owns-its-own-delivery-mechanics.md):
branch-level isolation in the primary checkout, one builder at a time. Question 1 (worktree
directory permissions) and Question 4 (`git mv` not allowlisted — use `mv` plus `git add -A`)
are closed with it. The full history of all three is in the git history of this file and in
ADR 0010's Context; it is not carried here any more.

### One human task remains, and it does not block the route

**T12 repository governance needs `gh api`, which is denied on purpose.** Branch protection,
secret scanning and push protection are account-level and outward-facing, so they stay a human
job — five minutes in the GitHub UI. The swarm builds T1–T11 and T13, parks T12 with a
checklist, and Phase 0's digest records it as human-owned rather than passing it quietly.

```
docs/plans/phase-0-foundations.md:299  gh api repos/<owner>/borrelbeurs/branches/main/protection
docs/plans/phase-0-foundations.md:301  gh api repos/<owner>/borrelbeurs/secret-scanning/alerts
```

Granting blanket `gh api` to an autonomous swarm to save that is write access to every
repository setting — a bad trade. If you would rather it ran T12 itself, the narrow grant is
`Bash(gh api repos/MartijnBoot/borrelbeurs/branches/main/protection:*)` plus the secret-scanning
path.
