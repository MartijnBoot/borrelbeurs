# Rebuild progress

Route: docs/plans/rebuild-route.md · Loop: docs/way-of-working.md §4.2
Updated: 2026-09-21 by audit session (branch `v2`)

## Now

Phase 0, step 5 BUILD. **Gate B passed** — the plan was audited and signed by MartijnBoot on
2026-09-21 ([phase-0-foundations.md](phase-0-foundations.md)). All ten checklist lines ticked,
with two recorded waivers: T1, T2 and T6 exceed the task size limit, and T5's logging/errors
skeletons and T13's `.claude/settings.json` carry no verification step. Six open questions
answered — repo `borrelbeurs` private, D10 boot-migration accepted (→ ADR 0009), R5 review
requirement waived (→ ADR 0010), Git Bash only, the four dependencies approved, T5 and T6 kept.

**Next:** `/build 0 1` — T1 creates the new repository, the one hard-to-reverse step.

## Phases

| Phase | Spec | Plan audited | Tasks done | Exit criterion | State |
|---|---|---|---|---|---|
| −1 v1 auth hotfix | — | — | — | commit `b617a56` | ✅ done |
| 0 Foundations | ✅ approved | ✅ signed 2026-09-21 | 0/13 | `setup.sh` + one command → running shell app; CI green | **ready to build** |
| 1 Engine + golden tests | ✅ exists | — | 0/– | pure engine reproduces v1 exactly | not started |
| 2 Data model + persistence | ✅ exists | — | 0/– | config round-trips Postgres; restart preserves prices | not started |
| 3 API + auth + realtime | ✅ exists | — | 0/– | every route authorized; integration tests green | not started |
| 4 React shell + koers | ✅ exists | — | 0/– | big screen end to end; theme propagates | not started |
| 5 Bar + order path | ✅ exists | — | 0/– | price shown == price charged, property-tested | not started |
| 6 Manipulation + settings | ✅ exists | — | 0/– | admin configures a borrel from scratch | not started |
| 7 Analytics + run lifecycle | ✅ exists | — | 0/– | two borrels comparable; xlsx matches DB | not started |
| 8 Deploy + cutover | ✅ exists | — | 0/– | Render *and* offline; rollback rehearsed; mock borrel | not started |

## Phase 0 tasks

Plan: [phase-0-foundations.md](phase-0-foundations.md). Strictly serial —
T1→T2→T3→{T4,T5,T7}→T6→T9→T10→T11→T12, T13 after T7.

| Task | Branch | Verified (command + result) | Reviewed | Merged |
|---|---|---|---|---|
| T1 fresh repo | — | — | — | — |
| T2 skeleton + pins + legacy move | — | — | — | — |
| T3 config module, fail-fast | — | — | — | — |
| T4 config boundary test | — | — | — | — |
| T5 FastAPI shell + health | — | — | — | — |
| T6 web shell, same origin | — | — | — | — |
| T7 Postgres + Compose + Alembic baseline | — | — | — | — |
| T8 `scripts/setup.sh` | — | — | — | — |
| T9 `scripts/check.sh` | — | — | — | — |
| T10 Dockerfile + build context | — | — | — | — |
| T11 CI workflow | — | — | — | — |
| T12 repo governance | — | — | — | — |
| T13 `CLAUDE.md` + agent config + migration hook | — | — | — | — |

Defects assigned to Phase 0: **none** (spec line 3, `Fixes: —`; the register's Phase column
has no `0` rows).

## Decisions taken mid-flight

None yet. The plan proposes D1–D14; they are not decisions until the audit accepts them.
D10 (migrate at boot) contradicts way-of-working §5.6:897 and the plan itself recommends an
ADR — see R3.

## Open questions for the human

Gate B is blocked on all of these (plan lines 403-409), plus two the orchestrator adds:

1. Repo name and visibility — D14 assumes `borrelbeurs`, private.
2. Accept D10 (migrate at boot)? If yes, it needs ADR 0009 before T7 is built.
3. R5 — branch protection wants ≥1 approving review; a single-operator repo cannot give one.
4. R2 — is Git Bash acceptable for `setup.sh`/`check.sh`, or do you want PowerShell parity?
5. Approve `uv`, `ruff`, `mypy`, `pydantic-settings`.
6. Does the Exit condition justify T5 and T6, or does Phase 0 ship without a frontend?
7. **No task asserts `.env.local` is gitignored**, yet T8 generates a real `JWT_SECRET` into it.
8. **T1 moves the project to a new repository.** Where does this progress file, the docs and
   the `/rebuild` loop continue — and what happens to the old repo (R8: it keeps v1's keys
   in history)?

## Standing items, carried until closed

- v1 access keys remain in the old repo's git history and need rotating (Phase 8 AC17).
- v1 `CLAUDE.md` still says "Don't introduce a database" — reversed by this rebuild, corrected
  in T13 for the new repo and at Phase 8 cutover for the old.
