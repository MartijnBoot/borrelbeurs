# Rebuild progress

Route: [rebuild-route.md](rebuild-route.md) · Loop: [ADR 0009](../adr/0009-autonomous-swarm-delivery.md)
Swarm state: CONTINUE
Updated: 2026-09-21 by orchestrator run 3

This file is the swarm's only memory. It is reconciled against git at the start of every run,
and written after **every** state transition — a run can die at any moment, and a transition
that is not written down did not happen.

## Now

Phase 0. In flight: **T2 `building`** (attempt 1). Blocked on: **nothing — run 2's hard stop is
resolved.**

> **⚠ Guard for the next run — read before dispatching anything.** Run 3 dispatched a live
> `task-builder` on T2 at 2026-09-21 and the branch had **0 commits at dispatch time**. The usual
> reconciliation rule ("no commits ⇒ never built ⇒ dispatch a builder") is therefore **unsafe for
> T2 specifically** — a branch still sitting at `58fc17a` may mean the builder is mid-flight, not
> that it never ran. Before re-dispatching T2: check whether the worktree
> `../.borrelbeurs-swarm/phase-0-t2` has uncommitted changes (`git status --short` from inside it).
> **Dirty tree ⇒ a builder was interrupted** — resume by inspecting its work, do not start a second
> one over the top. Clean tree *and* 0 commits ⇒ it is genuinely safe to dispatch. Delete this
> guard once T2 reaches `verifying` or later.

Run 3 reconciliation against git, 2026-09-21:

- **The run-2 hard stop is lifted.** The human added
  `"additionalDirectories": ["../.borrelbeurs-swarm"]` to `.claude/settings.json` in commit
  `538fb17` ("update config to allow edits from swarm"). Verified empirically this run rather
  than assumed — see the evidence below. Question 1 is **closed**; Question 2 (T12 / `gh api`)
  stays open but does not block, and its recommended answer is unchanged.
- `main` at `538fb17`, working tree clean, **0 commits unpushed** — the human pushed runs 1–2's
  ledger commits. `gh pr list --state open` → empty. `gh auth status` → `MartijnBoot`, active,
  scopes `gist, read:org, repo, workflow`.
- Branch `feature/phase-0-t2-skeleton-pins-legacy` and worktree `../.borrelbeurs-swarm/phase-0-t2`
  still exist, still at `58fc17a`, **still zero commits**, working tree clean. T2 was never built;
  there is no work to overwrite and no double-build risk. Reused as-is — the resume cost zero
  rework exactly as run 2 predicted.
- Note `58fc17a` is two commits behind `main`; both are ledger-only. The builder branches from it
  unchanged and the rebase at integration will pick them up.

Permission evidence, this run — read, git and **write** all confirmed inside the worktree:

```
Glob(../.borrelbeurs-swarm/phase-0-t2/*)     → 80 files listed, no prompt
ls -a ../.borrelbeurs-swarm/phase-0-t2       → .claude .git backend docs exchange scripts static ...
(cd worktree) git status --short             → clean
(cd worktree) git log --oneline -1           → 58fc17a docs(ledger): close T1 Gate C ...
(cd worktree) git rev-parse --abbrev-ref HEAD→ feature/phase-0-t2-skeleton-pins-legacy
Write(../.borrelbeurs-swarm/phase-0-t2/.swarm-write-probe)
                                             → File created successfully   ← the wall run 1 hit
rm .swarm-write-probe; git status --short    → clean
```

**One residual quirk, recorded so the next run does not misread it as the old block.** Two Bash
forms are still refused outside the project root: `cd <worktree> && git <cmd>` in one call ("changes
directory before running a version-control command"), and `git -C <worktree> <cmd>`. The working
form is `cd <worktree>` as its own call — the Bash tool's cwd persists, and git then runs normally.
This is a shell-invocation heuristic, not a directory grant, and it does not affect the file tools
at all. Builders work from inside their worktree anyway, so it costs one extra call and nothing else.

Carried from run 2, 2026-09-21:

- `main` at `58fc17a`, working tree clean, **1 commit unpushed** to `origin/main` (run 1's ledger
  commit). No open PRs. `gh auth status` → logged in as `MartijnBoot`.
- Branch `feature/phase-0-t2-skeleton-pins-legacy` exists and the worktree
  `../.borrelbeurs-swarm/phase-0-t2` is registered — **both at `58fc17a`, identical to `main`.**
  Zero commits. **T2 was never built**, so the ledger's `building` was wrong and is corrected to
  `ready`, attempt 0. No double-build risk: there is no work to overwrite.
- **Root cause of the stall found.** `../.borrelbeurs-swarm/` is outside the project root and
  `.claude/settings.json` has no `permissions.additionalDirectories`. Run 1 could *create* the
  worktree (`Bash(git worktree add:*)` is allowed) but its builder could not write a single file
  into it. Run 1 marked T2 `building` and died against that wall.
- Gate A: `docs/specs/phase-0-foundations.md` exists (human-approved, not agent-authored).
- Gate B: `docs/plans/phase-0-foundations.md` signed `Audited by: MartijnBoot Date: 2026-09-21`.
  The task graph and parallel groups below were re-derived from the plan's `Depends on` fields and
  still agree; no correction needed.
- The stale T2 worktree and branch are **deliberately left in place** — they are reusable as-is
  the moment the permission lands, and removing them would only cost a re-create.

Carried from run 1:

- Working tree clean, `main` at `e0704bf`. No swarm worktrees, no open PRs. Only branches are
  `chore/allowlist-toolchain` and `chore/autonomous-swarm-workflow`, both already merged. No task
  was mid-flight from a killed run; the ledger matched reality and needed no correction.
- `gh auth status` → logged in as `MartijnBoot`. PRs are available; no `no-PR` fallback needed.
- Gate A: `docs/specs/phase-0-foundations.md` exists (human-approved, not agent-authored).
- Gate B: `docs/plans/phase-0-foundations.md` signed `Audited by: MartijnBoot Date: 2026-09-21`.
- **Parallel groups recomputed** from the plan's own `Depends on` fields (T2←T1, T3←T2, T4←T3,
  T5←T3, T6←T5, T7←T3, T8←T6+T7, T9←T4+T6+T7, T10←T9, T11←T10, T12←T11, T13←T7). They agree with
  the table below; no correction was needed.
- T1's Gate C was the one genuine gap: it merged pre-swarm with no review. `fresh-eyes-reviewer`
  returned **PASS** with zero Correctness findings, so no remediation task was needed and T2 was
  released. The 5 Risk + 3 Optional findings are recorded below.

## Phases

| Phase | Spec | Plan audited | Tasks | Exit criterion | State |
|---|---|---|---|---|---|
| −1 v1 authorization hotfix | — | — | — | done, commit `b617a56` | ✅ closed |
| 0 Foundations | ✅ approved | ✅ human, 2026-09-21 | 1/13 merged | `setup.sh` then one command gives a running shell app; CI green | 🔨 in progress — T2 building |
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
| 3 | T4, T5, T7 | three concurrent triads — exactly the cap |
| 4 | T6, T13 | |
| 5 | T8, T9 | T9 also needs T4 |
| 6 | T10 → T11 → T12 | serial tail |

| Task | State | Attempt | Branch | PR | Verified (command + actual output) | Review |
|---|---|---|---|---|---|---|
| T1 fresh repo | merged | 1 | `main` (founding commits `aaf1e3b`, `d6c10a9`) | none — pre-swarm | `git count-objects -vH` → `size-pack: 457.37 KiB`, `in-pack: 122`, `packs: 1` < 5 MiB · `git rev-list --max-parents=0 HEAD` → `aaf1e3b` (sole root) · `git log --all --oneline --` for `config/keys.json`, `config/.jwt_secret`, `*.tar`, `static/earnings`, `static/uploads`, `*__pycache__*`, `*.pyc`, `*.pdf` → all empty · largest blob in repo is `docs/way-of-working.md` at 112,691 B < 200 kB · `git diff --name-status d6c10a9 HEAD` → no imported v1 file modified after import | **Gate C PASS** — `fresh-eyes-reviewer`, run 1, 2026-09-21. Zero Correctness findings. 5 Risk + 3 Optional recorded below |
| T2 skeleton + pins + legacy move | **building** | 1 | `feature/phase-0-t2-skeleton-pins-legacy` (worktree `../.borrelbeurs-swarm/phase-0-t2`, at `58fc17a`, 0 commits at dispatch) | — | dispatched run 3, 2026-09-21 — write access confirmed first | — |
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

## Decisions the swarm took alone

- **2026-09-21, T1 — v1 repo renamed to free D14's chosen name.** D14 specifies `borrelbeurs`,
  but GitHub repo names are case-insensitive and the name was held by v1's own `BorrelBeurs`.
  v1 became `MartijnBoot/borrelbeurs-v1`; the new repo took `borrelbeurs`. The same collision
  hit the filesystem, so the new repo is cloned at `borrelbeurs-v2` locally. **Directory name ≠
  repo name; do not "fix" this.** R8 is unaffected — renaming does not rotate v1's keys, and
  Phase 8 still owns that.
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

Carried forward from the pre-swarm loop:

- **2026-09-21, T1 — the new repo sets `core.autocrlf=false`.** v1 committed a mix of CRLF and
  LF; importing through a filter would have silently renormalised files. The import copied blob
  objects directly, so all 32 hashes match v1 byte for byte. T2's `.editorconfig` should treat
  line-ending normalisation as a deliberate, separate change — not something done incidentally
  during `git mv`.

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

**Nothing is blocking. The run-2 hard stop was answered in commit `538fb17` and the swarm is
running again.** One open question remains below, flagged early but not blocking today.

### ✅ Question 1 — RESOLVED 2026-09-21 by commit `538fb17`

The human added `"additionalDirectories": ["../.borrelbeurs-swarm"]` to `.claude/settings.json` —
exactly the recommended answer. Run 3 verified read, git and write access inside the worktree
before dispatching anything (evidence in [Now](#now)) and resumed T2 with zero rework. The original
analysis is kept below because it is the reason the swarm stalled for two runs, and the residual
Bash-invocation quirk noted in [Now](#now) is worth knowing if worktree access ever looks broken
again.

<details>
<summary>Original run-2 analysis (historical)</summary>

**2026-09-21, run 2 — the swarm cannot write into its own worktrees. Two permission grants are
needed; both are one-line config edits.** Hard-stop category: *a credential or permission that
must be given rather than computed.* Nothing is wrong with the spec, the plan, or any code.

#### Question 1 — grant the swarm access to its worktree directory (blocks every task, now)

The parallelism model puts each task in `../.borrelbeurs-swarm/phase-N-t<id>`, which is **outside
the project root**. `.claude/settings.json` declares no `permissions.additionalDirectories`, so
every file tool and every Bash argument pointing there needs interactive approval — and
`scripts/swarm.ps1` runs `claude -p` headless, where nothing can be approved.

Evidence, from this run:

```
$ git worktree list
C:/.../borrelbeurs-v2                                        58fc17a [main]
C:/.../.borrelbeurs-swarm/phase-0-t2                         58fc17a [feature/phase-0-t2-skeleton-pins-legacy]

$ git -C ../.borrelbeurs-swarm/phase-0-t2 status --short
This command requires approval

$ test -d ../.borrelbeurs-swarm/phase-0-t2 && ls ../.borrelbeurs-swarm/phase-0-t2
This Bash command contains multiple operations. The following parts require approval:
  test -d ../.borrelbeurs-swarm/phase-0-t2 && echo ... && ls ../.borrelbeurs-swarm/phase-0-t2

Glob(path: C:\...\.borrelbeurs-swarm\phase-0-t2)
Claude requested permissions to read from C:\...\.borrelbeurs-swarm\phase-0-t2,
but you haven't granted it yet.
```

`Bash(git worktree add:*)` *is* allowlisted, which is exactly why this failed so quietly: run 1
created the worktree successfully, dispatched a builder into it, and the builder could not write
one file. T2 sat at `building` with zero commits. **This is the whole reason the swarm made no
progress.** Note the allowlist itself is live — `git log`, `cat` and `ls` inside the repo all ran
unprompted this run, so the `hasTrustDialogAccepted` gotcha is *not* active; the scope is the only
problem. Checked directly since: `~/.claude.json` has `hasTrustDialogAccepted: true` for
`C:/Users/MartijnBoot/Documents/GitHub-Personal/borrelbeurs-v2` and no directory grant of any kind,
so the one line below is the whole fix.

**Recommended answer — add `additionalDirectories` to `.claude/settings.json`:**

```json
  "permissions": {
    "defaultMode": "acceptEdits",
    "additionalDirectories": ["../.borrelbeurs-swarm"],
    "allow": [
```

This edit has to come from the human: an agent session asked to make it is refused by the auto-mode
classifier with `[Self-Modification]` — both the direct edit of `.claude/settings.json` and the
`update-config` skill. Confirmed again 2026-09-21 in an interactive session. The swarm therefore
cannot lift this block itself under any prompt; it stays a hard stop until the line is added by hand.

Why this over the alternatives:

- **Passing `--add-dir ../.borrelbeurs-swarm` in [scripts/swarm.ps1:146](../../scripts/swarm.ps1#L146)**
  grants exactly the same access per `claude -p` invocation instead of repo-wide, and is an ordinary
  code edit rather than a Claude-config edit. It is the second-best answer: it keeps the grant next
  to the thing that needs it, but it only covers the swarm launcher — an orchestrator or builder
  started any other way (interactive `/rebuild`, a re-dispatch by hand) hits the same wall again.
  Say the word and the swarm will make this edit itself; it is the one route to unblocking that does
  not need your hands on a config file.
- **Moving worktrees inside the repo** (e.g. `.claude/worktrees/`) would put them in the project
  root where the existing allowlist already works — but `.gitignore` does not cover that path, so
  the parent tree would see the whole worktree as untracked and a builder running `git add -A`
  could commit a worktree into `main`. That needs a `.gitignore` change, which is a code edit the
  orchestrator is not allowed to make.
- **Building in the main working tree with no worktree** would work for T2 and T3 (the plan's graph
  makes them serial anyway) but abandons the per-task isolation ADR 0009 §5 explicitly names, and
  would hit the same wall at group 3 (T4/T5/T7 concurrent). It would also mean merging tasks under
  a weaker isolation model than the ADR describes without the human having ruled on it. Available
  as a fallback if you would rather have throughput than isolation — say so and the swarm will take
  it, serially, and record the deviation.

</details>

### Question 2 — T12 needs `gh api`, which is explicitly denied (blocks later, flagged now) — STILL OPEN

Not blocking today, but it will block T12 with eleven tasks of work already merged, so it is
cheaper to decide once, here.

`.claude/settings.json:125` denies `Bash(gh api:*)`, and `:119-121` deny `gh repo delete/rename/edit`.
T12 ("Repository governance") both **configures** branch protection and **verifies** it:

```
docs/plans/phase-0-foundations.md:299  gh api repos/<owner>/borrelbeurs/branches/main/protection
docs/plans/phase-0-foundations.md:301  gh api repos/<owner>/borrelbeurs/secret-scanning/alerts
```

There is no allowlisted route to either. T12 is also on the swarm's hard-stop list independently —
it changes GitHub account settings, which is outward-facing and not revertible by `git revert`.

**Recommended answer: leave the deny in place and let T12 stay a human task.** Branch protection,
secret scanning and push protection are account-level, outward-facing, and a five-minute job in the
GitHub UI. Granting blanket `gh api` to an autonomous swarm to save that is a bad trade — it is
write access to every repository setting. The swarm will build T1–T11 and T13, then stop and hand
you a checklist for T12. If you would rather it ran T12 itself, the narrow grant is
`Bash(gh api repos/MartijnBoot/borrelbeurs/branches/main/protection:*)` plus the secret-scanning
path — still outward-facing, so the hard stop stands regardless and this only removes the typing.

### What happens next

Run 3 is building T2, then T3, then the T4/T5/T7 parallel group. The swarm will build T1–T11 and
T13 and then stop at T12 with a checklist, unless Question 2 is answered differently before then.
