# Rebuild progress

Route: [rebuild-route.md](rebuild-route.md) · Loop: [ADR 0009](../adr/0009-autonomous-swarm-delivery.md)
Swarm state: CONTINUE
Updated: 2026-09-21 by orchestrator run 1

This file is the swarm's only memory. It is reconciled against git at the start of every run,
and written after **every** state transition — a run can die at any moment, and a transition
that is not written down did not happen.

## Now

Phase 0. In flight: **T2 building**. Blocked on: nothing.

T1's outstanding Gate C is now closed — `fresh-eyes-reviewer` returned **PASS** with zero
Correctness findings, so no remediation task is needed and T2 was released.

Run 1 reconciliation against git, 2026-09-21:

- Working tree clean, `main` at `e0704bf`. No swarm worktrees, no open PRs. Only branches are
  `chore/allowlist-toolchain` and `chore/autonomous-swarm-workflow`, both already merged. No task
  was mid-flight from a killed run; the ledger matched reality and needed no correction.
- `gh auth status` → logged in as `MartijnBoot`. PRs are available; no `no-PR` fallback needed.
- Gate A: `docs/specs/phase-0-foundations.md` exists (human-approved, not agent-authored).
- Gate B: `docs/plans/phase-0-foundations.md` signed `Audited by: MartijnBoot Date: 2026-09-21`.
- **Parallel groups recomputed** from the plan's own `Depends on` fields (T2←T1, T3←T2, T4←T3,
  T5←T3, T6←T5, T7←T3, T8←T6+T7, T9←T4+T6+T7, T10←T9, T11←T10, T12←T11, T13←T7). They agree with
  the table below; no correction was needed.
- T1's Gate C is the one genuine gap: it merged pre-swarm with no review. Dispatched. If the
  review reports Correctness findings, they become a task in the plan rather than a silent fix —
  and anything needing a history rewrite is a hard stop, not something the swarm resolves.

## Phases

| Phase | Spec | Plan audited | Tasks | Exit criterion | State |
|---|---|---|---|---|---|
| −1 v1 authorization hotfix | — | — | — | done, commit `b617a56` | ✅ closed |
| 0 Foundations | ✅ approved | ✅ human, 2026-09-21 | 1/13 merged | `setup.sh` then one command gives a running shell app; CI green | in progress |
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
| T2 skeleton + pins + legacy move | building | 1 | `feature/phase-0-t2-skeleton-pins-legacy` | — | — | — |
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

None.
