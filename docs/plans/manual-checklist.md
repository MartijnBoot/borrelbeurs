# Manual rebuild checklist

Hand-driven replacement for `scripts/swarm.ps1`. Tick boxes as you go.

- Lines starting with `/` are typed into Claude Code. **Always `/clear` first** — each step
  reads its inputs from files, not from the conversation.
- All other lines are typed into a terminal in the repo root.
- Models are pinned in the command files: `/build` sonnet, `/verify` haiku, `/review` opus.

## Reference: the per-task loop

Every task below follows these steps. `<N>` = phase, `<T>` = task id, `<branch>` = the branch named in the task.

| Step | Command |
|---|---|
| 1. Start clean from `main` | `git switch main` then `git pull` |
| 2. Create the task branch | `git switch -c <branch>` |
| 3. Build | `/clear` then `/build <N> <T>` (for `exchange/`, concurrency or migration tasks: `/model opus` first) |
| 4. Verify | `/clear` then `/verify` |
| 5. Review | `/clear` then `/review <N>` (runs engine-guardian by itself if `exchange/` changed) |
| 5b. Review has a Correctness finding | `/clear` then `/build <N> <T>` + paste only the finding, then back to step 4 |
| 6. Merge | `git switch main` then `git merge --squash <branch>` then `git commit -m "Phase <N> <T> — <task title>"` |
| 7. Clean up + publish | `git branch -D <branch>` then `git push origin main` |
| 8. Tick the box here | `git commit -am "docs: tick <T>"` then `git push origin main` |

Until T9 lands, `scripts/check.sh` does not exist. If `/verify` reports that, run the gate by hand:
`uv run ruff format --check . ; uv run ruff check . ; uv run mypy app tests ; uv run pytest -q`

## Reference: the per-phase loop

| Step | Command |
|---|---|
| 1. Approve the spec | Read `docs/specs/phase-<N>-*.md`. OK → change line 3 to `Status: Approved`. Not OK → `/clear` then `/spec <N>` |
| 2. Branch for the plan | `git switch main` then `git pull` then `git switch -c docs/phase-<N>-plan` |
| 3. Plan | `/clear` then `/plan <N>` → writes `docs/plans/phase-<N>-*.md` |
| 4. Audit | `/clear` then `/audit <N>` → fill in `Audited by` / `Date` at the bottom of the plan |
| 5. Merge the plan | `git add docs` then `git commit -m "docs(plan): phase <N>"` then `git switch main` then `git merge --squash docs/phase-<N>-plan` then `git commit -m "docs(plan): phase <N> audited"` then `git branch -D docs/phase-<N>-plan` then `git push origin main` |
| 6. List the tasks here | Copy the plan's `### T…` headings into this file under that phase |
| 7. Build every task | Per-task loop, in the plan's dependency order |
| 8. Close the phase | Check the exit criterion by hand, tick it, `git commit -am "docs: phase <N> done"` then `git push origin main` |

---

## Step 0 — housekeeping (once, right now)

- [x] Commit the uncommitted work on the T7 branch (model changes, checklist, last swarm ledger notes)
- [x] Stop the swarm for good — 2026-09-28, after run 10 ended `BLOCKED` on `pnpm`. This
  checklist is now the only workflow; `rebuild-progress.md` is frozen history from here on.
- [ ] Commit the last swarm ledger notes and this checklist, then publish the 3 unpushed commits
  on `main` (run 9/10 ledger + T13):
  `git add docs/plans/rebuild-progress.md docs/plans/manual-checklist.md` then
  `git commit -m "docs: stop the swarm; checklist caught up"` then `git push origin main`
- [ ] Delete the merged T7 branch on the remote:
  `git push origin --delete feature/phase-0-t7-postgres-compose-alembic`

## Phase −1 — v1 authorization hotfix
- [x] Done (`b617a56`)

## Phase 0 — Foundations
Exit: `scripts/setup.sh` then one command gives a running shell app; CI green.

- [x] Spec approved
- [x] Plan written + audited (2026-09-21)
- [x] T1 fresh repo
- [x] T2 skeleton, toolchain pins, v1 moved aside
- [x] T3 config module, fail-fast boot
- [x] T4 config boundary enforcement
- [x] T5 FastAPI shell + health endpoints

**T7 Postgres, Compose and the Alembic baseline** — already on `feature/phase-0-t7-postgres-compose-alembic`, attempt 2 fix committed (`e0a524d`)
- [x] build
- [x] verify — `/clear` then `/verify`
- [x] review — `/clear` then `/review 0`
- [x] merge — `git switch main` then `git merge --squash feature/phase-0-t7-postgres-compose-alembic` then `git commit -m "Phase 0 T7 — Postgres, Compose and the Alembic baseline"`
- [x] clean up — `git branch -D feature/phase-0-t7-postgres-compose-alembic` then `git push origin main`

**T4b no filesystem side effects** (needs T5, T7 — not in the audited plan; its brief is in `rebuild-progress.md` → "Decisions the swarm took alone")
- [x] branch — `git switch main` then `git pull` then `git switch -c feature/phase-0-t4b-no-fs-side-effects`
- [x] build — `/clear` then `/build 0 T4b` (tell it to read the T4b entry in `docs/plans/rebuild-progress.md`)
- [x] verify — `/clear` then `/verify`
- [x] review — `/clear` then `/review 0`
- [x] merge — `git switch main` then `git merge --squash feature/phase-0-t4b-no-fs-side-effects` then `git commit -m "Phase 0 T4b — no filesystem side effects"`
- [x] clean up — `git branch -D feature/phase-0-t4b-no-fs-side-effects` then `git push origin main`

**Prerequisite — Node toolchain** (blocks T6, and so T8–T12)
- [x] Switch to Node 22 (per `.nvmrc`), e.g. `nvm install 22` then `nvm use 22`
- [x] `corepack enable pnpm` then `pnpm --version` prints a version

**T6 web shell, same origin** (needs T5 + the Node prerequisite)
- [x] branch — `git switch main` then `git pull` then `git switch -c feature/phase-0-t6-web-shell`
- [x] build — `/clear` then `/build 0 T6`
- [x] verify — `/clear` then `/verify`
- [x] review — `/clear` then `/review 0`
- [x] merge — `git switch main` then `git merge --squash feature/phase-0-t6-web-shell` then `git commit -m "Phase 0 T6 — web shell served from the same origin"`
- [x] clean up — `git branch -D feature/phase-0-t6-web-shell` then `git push origin main`

**T8 `scripts/setup.sh`** (needs T6 and T7 — it installs the web deps, so it waits for T6)
- [x] branch — `git switch main` then `git pull` then `git switch -c feature/phase-0-t8-setup-script`
- [x] build — `/clear` then `/build 0 T8`
- [x] verify — `/clear` then `/verify`
- [x] review — `/clear` then `/review 0`
- [x] merge — `git switch main` then `git merge --squash feature/phase-0-t8-setup-script` then `git commit -m "Phase 0 T8 — scripts/setup.sh"`
- [x] clean up — `git branch -D feature/phase-0-t8-setup-script` then `git push origin main`

**T13 `CLAUDE.md`, agent configuration and the migration hook** (needs T7) — built by the swarm, run 10
- [x] build
- [x] verify
- [x] review — Gate C PASS on attempt 2, zero Correctness findings
- [x] merge — `9194bef` "Phase 0 T13 — CLAUDE.md, the migration guard hook, and its pending registration"
- [x] clean up (local branch deleted) — the push happens in Step 0 above
- [x] apply the stale `.claude/` edits by hand from `docs/plans/pending-claude-config-edits.md` — **including §8, registering the migration-guard hook in `.claude/settings.json`**; until then nothing enforces it. Then `git rm docs/plans/pending-claude-config-edits.md` then `git commit -am "chore: apply pending .claude edits"` then `git push origin main`

**T9 `scripts/check.sh`** (needs T4, T6, T7)
- [ ] branch — `git switch main` then `git pull` then `git switch -c feature/phase-0-t9-check-script`
- [ ] build — `/clear` then `/build 0 T9`
- [ ] verify — `/clear` then `/verify` (from here on it runs the real `scripts/check.sh`)
- [ ] review — `/clear` then `/review 0`
- [ ] merge — `git switch main` then `git merge --squash feature/phase-0-t9-check-script` then `git commit -m "Phase 0 T9 — scripts/check.sh"`
- [ ] clean up — `git branch -D feature/phase-0-t9-check-script` then `git push origin main`

**T10 Dockerfile and build-context hygiene** (needs T9)
- [ ] branch — `git switch main` then `git pull` then `git switch -c feature/phase-0-t10-dockerfile`
- [ ] build — `/clear` then `/build 0 T10`
- [ ] verify — `/clear` then `/verify`
- [ ] review — `/clear` then `/review 0`
- [ ] merge — `git switch main` then `git merge --squash feature/phase-0-t10-dockerfile` then `git commit -m "Phase 0 T10 — Dockerfile and build-context hygiene"`
- [ ] clean up — `git branch -D feature/phase-0-t10-dockerfile` then `git push origin main`

**T11 CI workflow** (needs T10)
- [ ] branch — `git switch main` then `git pull` then `git switch -c feature/phase-0-t11-ci-workflow`
- [ ] build — `/clear` then `/build 0 T11`
- [ ] verify — `/clear` then `/verify`
- [ ] review — `/clear` then `/review 0`
- [ ] merge — `git switch main` then `git merge --squash feature/phase-0-t11-ci-workflow` then `git commit -m "Phase 0 T11 — CI workflow"`
- [ ] clean up — `git branch -D feature/phase-0-t11-ci-workflow` then `git push origin main`
- [ ] CI green — `gh run list --branch main --limit 1` shows `completed success`

**T12 repository governance** (needs T11 green — human, GitHub UI — see plan `docs/plans/phase-0-foundations.md` T12)

Don't start before T11's CI has run once: requiring `check` / `secret-scan` / `docker` before
they exist blocks every PR. The repo is **private on a personal account** — check first
whether your plan allows branch protection and push protection there:
- [ ] plan — `gh api user --jq .plan.name` (private-repo branch protection needs Pro)
- [ ] available security features — `gh api repos/MartijnBoot/borrelbeurs --jq .security_and_analysis`
- [ ] if push protection is unavailable: decide — make the repo public, or record an AC7 waiver ADR like R5's
- [ ] branch protection on `main` — github.com/MartijnBoot/borrelbeurs → Settings → Branches: PR required, required checks `check` / `secret-scan` / `docker`, dismiss stale approvals, no force-push, no deletion, linear history (no required review — R5 waiver)
- [ ] secret scanning + push protection — Settings → Code security
- [ ] repo files (can be a normal `/build 0 T12` task): `.github/dependabot.yml`, `CODEOWNERS`, `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/{bug,feedback}.yml`, review-waiver ADR
- [ ] check — `gh api repos/MartijnBoot/borrelbeurs/branches/main/protection` shows the three checks and `allow_force_pushes: false`
- [ ] check — `gh api repos/MartijnBoot/borrelbeurs/secret-scanning/alerts` returns 200
- [ ] check AC7 — on a throwaway branch, commit a known provider-pattern secret and `git push`; the push is rejected (keep the message)

Run these in PowerShell or Git Bash exactly as written. The `Bash(...:*)` form in
`rebuild-progress.md` is a Claude Code permission rule, not a command.

**Phase 0 exit**
- [ ] `bash scripts/setup.sh` then the one run command from the README → app answers on `/healthz`
- [ ] tick + `git commit -am "docs: phase 0 done"` then `git push origin main`

## Phase 1 — Engine extraction + golden tests
Exit: pure engine reproduces v1's outputs exactly. **Build on opus (`/model opus` before `/build`); `/review` runs engine-guardian on every task.**

- [x] Spec approved (`docs/specs/phase-1-engine.md` already says `Status: Approved`)
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-1-plan`
- [ ] plan — `/clear` then `/plan 1`
- [ ] audit — `/clear` then `/audit 1`, fill in `Audited by` / `Date`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 1
- [ ] tasks (copy from the plan, then per-task loop with `/build 1 <T>` and `/review 1`):
  - [ ] …
- [ ] exit criterion — `/clear` then `/verify` shows the golden fixtures passing on `main`

## Phase 2 — Data model + persistence
Exit: live config round-trips through Postgres; restart preserves prices.

- [ ] spec — read `docs/specs/phase-2-persistence.md` (currently `Draft`) → set `Status: Approved`, or `/clear` then `/spec 2`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-2-plan`
- [ ] plan — `/clear` then `/plan 2`
- [ ] audit — `/clear` then `/audit 2`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 2
- [ ] tasks (`/build 2 <T>`, `/review 2`):
  - [ ] …
- [ ] exit criterion — change a config value, restart the app, prices are unchanged

## Phase 3 — API + auth + realtime
Exit: every route authorized; integration tests green against real Postgres.

- [ ] spec — read `docs/specs/phase-3-api-realtime.md` (`Draft`) → approve, or `/clear` then `/spec 3`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-3-plan`
- [ ] plan — `/clear` then `/plan 3`
- [ ] audit — `/clear` then `/audit 3`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 3
- [ ] tasks (`/build 3 <T>`, `/review 3`):
  - [ ] …
- [ ] exit criterion — `/clear` then `/verify` shows the integration suite green against Postgres

## Phase 4 — React shell + theme + auth + koers
Exit: big screen works end to end; theme propagates across machines.

- [ ] spec — read `docs/specs/phase-4-web-koers.md` (`Draft`) → approve, or `/clear` then `/spec 4`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-4-plan`
- [ ] plan — `/clear` then `/plan 4`
- [ ] audit — `/clear` then `/audit 4`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 4
- [ ] tasks (`/build 4 <T>`, `/review 4`):
  - [ ] …
- [ ] exit criterion — open koers on two machines, change the theme on one, the other follows

## Phase 5 — Bar + order path
Exit: price shown equals price charged, enforced by a property test. **Build on opus.**

- [ ] spec — read `docs/specs/phase-5-bar-orders.md` (`Draft`) → approve, or `/clear` then `/spec 5`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-5-plan`
- [ ] plan — `/clear` then `/plan 5`
- [ ] audit — `/clear` then `/audit 5`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 5
- [ ] tasks (`/build 5 <T>`, `/review 5`):
  - [ ] …
- [ ] exit criterion — `/clear` then `/verify` reports the price-invariant property test and its case count

## Phase 6 — Manipulation + settings
Exit: an admin can configure a borrel from scratch.

- [ ] spec — read `docs/specs/phase-6-admin.md` (`Draft`) → approve, or `/clear` then `/spec 6`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-6-plan`
- [ ] plan — `/clear` then `/plan 6`
- [ ] audit — `/clear` then `/audit 6`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 6
- [ ] tasks (`/build 6 <T>`, `/review 6`):
  - [ ] …
- [ ] exit criterion — start from an empty database and configure a whole borrel through the UI

## Phase 7 — Analytics + run lifecycle
Exit: two past borrels comparable; xlsx export matches the database.

- [ ] spec — read `docs/specs/phase-7-analytics.md` (`Draft`) → approve, or `/clear` then `/spec 7`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-7-plan`
- [ ] plan — `/clear` then `/plan 7`
- [ ] audit — `/clear` then `/audit 7`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 7
- [ ] tasks (`/build 7 <T>`, `/review 7`):
  - [ ] …
- [ ] exit criterion — run two short borrels, compare them, export the xlsx and check its totals against the database

## Phase 8 — Deploy + cutover
Exit: runs on Render *and* offline; rollback rehearsed; mock borrel passed.

- [ ] spec — read `docs/specs/phase-8-deploy-cutover.md` (`Draft`) → approve, or `/clear` then `/spec 8`
- [ ] branch — `git switch main` then `git pull` then `git switch -c docs/phase-8-plan`
- [ ] plan — `/clear` then `/plan 8`
- [ ] audit — `/clear` then `/audit 8`
- [ ] merge the plan — per-phase loop step 5 with `<N>` = 8
- [ ] tasks (`/build 8 <T>`, `/review 8`):
  - [ ] …
- [ ] rotate the v1 access keys still in `borrelbeurs-v1` git history (human, AC17)
- [ ] exit criterion — deploy to Render, run offline on the venue laptop, rehearse a rollback, hold a mock borrel
