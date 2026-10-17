# Plan: Rebuild review and repository clean-up

Basis: [rebuild-route.md](rebuild-route.md) (exit criteria, cross-phase invariants, out of scope) ·
[Phase 8 spec](../specs/phase-8-deploy-cutover.md) "Follow-up, after cutover: remove `legacy/v1/`" ·
[defect-register.md](../specs/defect-register.md)
Status: **Audited — PASS** (owner, `/audit`, 2026-10-17; see [Audit](#audit)). The PASS covers
this plan as written. Any amendment R8's triage adds (`A1`) needs its own `/audit` before its
tasks are built. Decisions D1–D7 recorded 2026-10-17; D5 deferred to R7 and triage.

---

## Approach

**First review, then delete.** The review is read-only. It decides what the clean-up may remove.
For example, it shows which docs are still cited and which v1-era code is still called. Deleting
first would remove the evidence the review needs.

**The review measures the rebuild against its own contract**, not against taste. The route
defines four things, and each one gets a check:
- an exit criterion per phase;
- the cross-phase invariants;
- an out-of-scope list;
- the defect register.

The specs add acceptance criteria. Anything the review finds becomes one of four things, which
the owner decides:
- a fix task;
- a defect-register entry;
- a backlog line;
- an accepted risk.

**Clean-up removes, it does not rewrite.** Each C-task deletes one kind of thing on its own
branch. It leaves `./scripts/check.sh` green and leaves no `git grep` hit for what it deleted.
Git history keeps everything. A tag on `main` before the first deletion gives one permanent name
for "the repo as the rebuild left it". Prose that cites a deleted file can then say
"see tag `v2-rebuild-complete`" and need not be rewritten.

**What is not bloat and stays:**
- `exchange/`;
- the golden fixtures (3.5 MB, but they are the gate on the whole rebuild);
- `tests/engine/v1_reference/engine.py` (sha-pinned);
- the migrations;
- the ADRs (an ADR is never deleted; it is superseded);
- `docs/design/` and `docs/runbooks/`;
- `uv.lock` and `pnpm-lock.yaml`.

---

## Decisions for the owner

| # | Question | Recommendation | Owner's answer (2026-10-17) |
|---|---|---|---|
| D1 | Is Phase 8 closed with its waivers? H2 (offline) is deferred, H3 (rollback) skipped, H4 (key rotation) not done. | **Yes.** The review records them as *waived by the owner*, not as *met*. | **Yes.** Phase 8 is closed; R1 records H2–H4 as waived by the owner. |
| D2 | What happens to the build-process docs: the per-phase plans (`phase-0…8-*.md`, ~7.6k lines), `rebuild-progress.md` (frozen swarm ledger, 125 KB), `manual-checklist.md` and `phase-8-human-steps.md`? | **Delete them, with history kept by the tag.** No later work reads them. `.claude/` agents read `phase-N-*.md` by pattern for *new* phases only. | **Delete all but `phase-8-human-steps.md`, which stays.** C4 must exclude it from its `phase-{0..8}-*.md` glob. |
| D3 | What happens to the specs and the defect register? | **Keep them.** Code comments cite their IDs (`SD14`, `AC6`, `D-20`). They are the living "why". | **Keep them.** |
| D4 | Remove `legacy/v1/` now, as the Phase 8 spec's follow-up plans? This lifts CLAUDE.md's "never edit `legacy/v1/`" for this one task. | **Yes, in C5**, after its test fixtures are copied into `tests/`. | **Yes, in C5.** |
| D5 | Keep the v1-migration code: `app/cli/import_v1.py`, `app/cli/v1_files.py`, the v1 key import (Phase 8 T9) and their tests? | **Decide after R7.** R7 reports what each costs in lines and whether anything else calls it. If you might import v1's settings once more, keep `import_v1`. | **Deferred to R7.** Decided at R8 triage. |
| D6 | Remove the swarm machinery: `scripts/swarm.ps1`, `/rebuild`, `docs/plans/digests/`, `.swarm-logs/` and `/.worktrees/` in `.gitignore`. Also mark ADR 0009 and 0010 *Superseded*. | **Yes.** The swarm was stopped for good on 2026-09-28. The ADR status lines need your approval of the text. | **Yes, in C3.** The ADR status text is still a hard stop for approval. |
| D7 | This work has no spec. Is this plan, with your answers to D1–D6, its spec? | **Yes**, then run `/audit` on it. A separate `/spec` interview adds little to a removal job. | **Yes.** `/audit` runs on the plan plus any A1 from triage. |

---

## Part P — Pre-flight

### P1 — Land or drop the in-flight branches

- **Expected output:** `main` holds everything the owner wants kept before the tag. The branches
  in question:
  - `feature/v1-default-params` (`30fa48d`, built without an audit, waived 2026-10-17). It gets a
    `/review` first.
  - `docs/phase-8-h1-done-h2-deferred` (3 commits). It adds the H1 rehearsal record and
    `docs/backlog.md`.
  - `docs/phase-8-amendment-a2` and `docs/phase-8-h1-step6-notes`. Their content may already be
    on `main` via #12 and #14; the check below decides.
- **Verification:** for each branch `b`, `git merge-tree --write-tree main "$b"` prints the same
  tree as `git rev-parse 'main^{tree}'`. That means the branch has nothing `main` lacks.
- **Autonomy:** merging and pushing are the owner's. The agent hands over the commands.

### P2 — Baseline gate on `main`

- **Expected output:** the full `./scripts/check.sh` output on `main`'s tip, pasted into the
  review report (R8) as the "before" picture. Also
  `uv run python -m tests.engine.golden.capture --check`.
- **Note:** `tests/api/test_ws` has a known intermittent `CancelledError` (Phase 3 tip). If it
  fails, rerun once and record both outputs. Don't fix it here; R6 carries it.

### P3 — Tag the rebuild

- **Expected output:** an annotated tag, `git tag -a v2-rebuild-complete -m "v2 rebuild as
  delivered, before review clean-up" main`, on the commit P2 gated.
- **Autonomy:** the agent creates the tag locally. `git push origin v2-rebuild-complete` is the
  owner's.
- **Depends on:** P1, P2

---

## Part R — Review (read-only)

Each R-task runs in a context that did not write the code under review (`codebase-analyst`,
`engine-guardian`, `fresh-eyes-reviewer`, or `/analyse` fan-out). R1–R7 are independent and run
in parallel. Each one returns findings as `file:line` plus a status. **No R-task edits anything.**

### R1 — Phase exit criteria

For each phase −1…8 in the route's table, the report records:
- the exit criterion;
- the command or test that proves it today;
- its output;
- a status: **met / waived (by whom, where recorded) / not met**.

Phase 8's offline run, rollback and mock borrel go in as waived per D1. Their source is
`phase-8-human-steps.md` Notes and `docs/backlog.md`.

### R2 — Cross-phase invariants

For each row of the route's invariants table, the report names:
- the test or check that enforces it;
- that check run on its own, with its output;
- any gap. A gap is an invariant with no enforcing test, or a test that would pass if the
  invariant broke.

`engine-guardian` owns these rows:
- "exchange imports no clock/I/O/framework";
- "golden fixtures pass".

### R3 — Defect register closure

Every `D-nn` in `defect-register.md` gets a status:
- **fixed**: the test that pins it;
- **deferred**: where it is tracked;
- **open**.

An entry marked fixed with no pinning test is a finding.

### R4 — Acceptance-criteria traceability

Per spec (phases 0–8), every `ACn` gets the test(s) that exercise it. Fan out one analyst per
spec. An AC with no test, or with only a test that cannot fail, is a finding. This is the
largest R-task. If it runs long, it stops per spec and reports what it has covered.

### R5 — Docs against code

- Every command in `CLAUDE.md` and `README.md` still runs. Check with `--help` or a dry run,
  never against production.
- `docs/design/*.md` and the ADRs still describe the code. Spot-check one claim per section
  against `file:line`.
- Status text that is out of date is a finding. Known example: `docs/README.md` "Status" still
  describes Phase 0 T1 and the swarm.

### R6 — Carried-over open items

Each item below gets a status: **still true / fixed (where) / not reproducible**.
- the `test_ws` `CancelledError` flake;
- the Phase 8 T5 clock offset never shrinks (documented in the ADR 0003 addendum);
- T6 dropped-lock fencing has no test;
- the T11 smoke traceback on a dropped connection;
- the DB-clock columns `ended_at`, `deleted_at`, `removed_at`;
- `/theme.css` answering 304 behind Cloudflare (H1 notes);
- per-request `correlation_id` (deferred twice);
- the `fresh-eyes-reviewer` verdict on `feature/v1-default-params`, if P1 merged it without one.

### R7 — Dead weight inventory

This is the input to every C-task. List each item with its path, size, every reference to it
(`git grep`), and a proposed C-task.
- Tracked files nothing reads, imports or links to:
  - empty-dir `.gitkeep`s in directories that now have files (`app/`, `db/`, `tests/`,
    `tests/engine/`, `web/src/features/`);
  - `docs/plans/digests/` (only a README, no digest was ever written).
- Python modules, functions and routes that nothing calls, outside tests. Use `git grep`, not a
  new tool. Adding `vulture` or `knip` is a new dependency, so ask first.
- Web components, hooks and exports that nothing imports. Also `web/package.json` dependencies
  with no import.
- `.claude/` agents and commands that no remaining command uses once D6 is applied.
- What D5 would remove, with its line counts.
- Untracked local weight (not repo bloat, but disk). For each, give its size and how to
  regenerate it:
  - `bundle/` (~400 MB);
  - `.swarm-logs/`, `.dev/*.log`;
  - the caches;
  - the `../bb-gate` worktree;
  - docker images `borrelbeurs:local`, `docker:29-dind`, `rhysd/actionlint`;
  - 111 local and 47 remote branches.

### R8 — Report and triage

- **Expected output:** `docs/rebuild-review.md`. It holds:
  - P2's baseline;
  - one section per R1–R7;
  - a findings table: `id | finding | evidence | proposed: fix / register / backlog / accept`.
- **Owner step:** the owner sets the last column. Fix-now findings become tasks in an amendment
  to this plan (`A1`), audited like any other. Register findings and backlog findings (as
  `B-nn` entries in `docs/backlog.md`, via `/backlog`) are written in the same commit as the
  report.
- **Depends on:** R1–R7

---

## Part C — Clean-up

Every C-task is one branch, `chore/cleanup-cN-<slug>` off `main`, with one conventional commit
(`chore(cleanup): CN — …`). Each one is verified the same way:
1. `./scripts/check.sh` is green, with the output pasted;
2. `git grep` for every deleted path returns only the hits the task lists as allowed;
3. `uv run python -m tests.engine.golden.capture --check` is unchanged.

The owner pushes and opens the PRs. Each task's scope is only what R7 listed for it, minus what
R8 marked *keep*.

### C1 — Branches and worktree

- Delete local branches whose content is on `main`. Use P1's `merge-tree` test, not
  `git branch --merged`. Every phase branch was squash-merged, so `--merged` misses them.
  Branches that fail the test are listed for the owner, never deleted.
- Remove `../bb-gate` with `git worktree remove`.
- Hand the owner one `git push origin --delete …` command for the remote branches that pass the
  same test. Deleting remote branches is the owner's.
- **No commit.** The evidence is `git branch | wc -l` before and after.

### C2 — Local untracked weight

Show the owner `git clean -ndX` and R7's docker list. Remove only what the owner names. **No
commit.** Note that `bundle/` is rebuilt by `scripts/make_bundle.sh`.

### C3 — Swarm machinery (D6)

- **Delete:** `scripts/swarm.ps1`, `.claude/commands/rebuild.md`, `docs/plans/digests/`.
- **`.gitignore`:** delete the `.swarm-logs/` and `/.worktrees/` entries.
- **ADRs:** add a `Status: Superseded (2026-10-…) — the swarm was stopped; see
  manual workflow` line to ADR 0009 and 0010. This is a **hard stop for text approval**.
- **Text that describes the swarm as how work runs:**
  - `.claude/README.md` "How the rebuild actually runs";
  - `docs/plans/rebuild-route.md` "In practice the route is driven as one long-running swarm";
  - `docs/README.md` "Working on this".
- Docstrings in `tests/meta/test_config_boundary.py:45` and `test_import_side_effects.py:37` cite
  `rebuild-progress.md`. Rewrite them to cite the tag.
- **Allowed `git grep swarm` hits:** ADR 0009, ADR 0010, and `docs/specs/` (frozen history).

### C4 — Completed build-process docs (D2)

- **Delete:**
  - `docs/plans/phase-{0..8}-*.md`, except `phase-8-human-steps.md` (D2);
  - `docs/plans/rebuild-progress.md`;
  - `docs/plans/manual-checklist.md`.
- **Keep:** `phase-8-human-steps.md` (D2: the H1 rehearsal record and the waiver notes).
- **Keep:** `rebuild-route.md`. `.claude/agents` read its invariants table, so it is
  load-bearing. Retitle its intro as the record of a finished route plus the standing invariants.
- **`.github/workflows/ci.yml`:** it cites `manual-checklist`. Fix the comment.
- **The 21 code files citing `docs/plans/…`:**
  - a path or link becomes `(tag v2-rebuild-complete)`;
  - prose like "Phase 3 plan T5" stays.
- **Allowed `git grep 'docs/plans/phase-'` hits:**
  - `.claude/` (the pattern for *future* plans);
  - `docs/specs/` (frozen; it resolves via the tag).

### C5 — Remove `legacy/v1/` (D4; Phase 8 spec follow-up)

- **First, while every test still passes:** copy the four files v2 tests read into `tests/fixtures/v1/`,
  byte-identical:
  - `config/exchange_config.json`;
  - `static/news.json`;
  - `static/theme.js`;
  - `backend/api.py`.

  Add `tests/fixtures/v1/SHA256SUMS`, plus a test in `tests/meta/` that checks it, the same pin
  `v1_reference` has.
- **Repoint the readers** the spec lists, plus `tests/unit/test_default_params.py` (new since the
  spec):
  - `tests/engine/golden/scenarios.py`;
  - `tests/image/test_kill_drill.py`;
  - `tests/image/test_venue.py`;
  - `tests/integration/durability/harness.py`;
  - `tests/integration/realapp/harness.py`;
  - `tests/integration/test_import_v1.py`;
  - `tests/unit/test_v1_files.py`;
  - `tests/unit/test_theme_manifest.py`;
  - `tests/unit/test_market_events.py`.
- **Then delete `legacy/`.** Drop its entries from:
  - `pyproject.toml` (ruff and mypy excludes);
  - `.editorconfig`;
  - `.dockerignore`;
  - `tests/meta/test_repo_hygiene.py`'s `ADDED_FOR_V2`.

  `scripts/ci/check_image.py` `FORBIDDEN_DIRS` keeps `legacy`. It costs nothing and still guards
  the image.
- **Code comments citing `legacy/v1/…:line`:**
  - `app/cli/v1_files.py`;
  - `app/core/config.py`;
  - `app/db/runs.py`;
  - `app/runtime/market_events.py`;
  - `app/runtime/theme.py`;
  - `tests/api/test_v1_keys.py`.

  Each becomes `v1 backend/api.py:167-190 (tag v2-rebuild-complete)`.
- **Docs:**
  - Specs and the defect register stay as they are; the tag resolves them.
  - `CLAUDE.md` drops `legacy/v1/` from Project and Never.
  - `README.md` drops its mention.
- **Gate:** `engine-guardian` confirms that the golden replay and capture `--check` are
  unchanged. Scenarios now read the copied config, so the diff must be empty.
- **Allowed `git grep legacy/v1` hits:** `docs/specs/`, `docs/adr/` (history).

### C6 — v1-migration code (only if D5 says remove)

Scope is exactly R7's D5 list. If C5 landed first, `tests/fixtures/v1/` shrinks to what is left.

### C7 — Small dead weight

- Delete the R7-listed `.gitkeep`s.
- Delete the R8-approved dead code and unused web dependencies. Removing a dependency is not
  adding one, but name each one in the PR.
- If `pnpm-lock.yaml` and `uv.lock` change, they change only by removal.

### C8 — Front-door docs

Rewrite these so they describe the repository as it now is:
- `README.md`;
- `docs/README.md`;
- `CLAUDE.md`;
- `.claude/README.md`.

What they cover:
- what it is;
- how to run, test and deploy it;
- the manual `/backlog → /spec → /plan → /audit → /build → /verify → /review` loop for new work;
- where history lives (the tag).

`CLAUDE.md` changes are a **hard stop for text approval**.

**Order:**
- C1 and C2 can run any time after P3.
- C3 → C4 → C5 → C6 → C7 → C8 run in sequence. They edit overlapping files, and C8 describes the
  end state.

---

## Hard stops (owner only)

- Pushing, opening and merging PRs, pushing the tag, and deleting remote branches.
- ADR status text (C3) and `CLAUDE.md` text (C8).
- Any change under `exchange/`, the golden fixtures, `tests/engine/v1_reference/` or
  `db/migrations/`. None is planned. If a task seems to need one, it stops.
- Anything touching Render or the suspended v1 service.

## Done when

- `docs/rebuild-review.md` exists with every finding triaged.
- The C-tasks the owner approved are merged, each with a pasted green `check.sh`.
- `git grep` for each removed path shows only the allowed hits.
- The golden check is unchanged from P2.

---

## Audit

There is no spec (D7), so the criteria are D1–D7 and "Done when".

| Criterion | Tasks |
|---|---|
| D1 Phase 8 closed with waivers | R1 |
| D2 build-process docs deleted, `phase-8-human-steps.md` kept | C4 |
| D3 specs and register kept | none needed (C4, C5 keep them) |
| D4 remove `legacy/v1/` | C5 |
| D5 v1-migration code | R7, R8 triage, C6 |
| D6 swarm machinery | C3 |
| D7 plan is the spec | this audit |
| Done when: review triaged | P2, R1–R8 |
| Done when: C-tasks merged, `git grep` clean, golden unchanged | C3–C8, P2 baseline |

Human audit, 2026-10-17. The owner answered "accept all lines" for the whole checklist, so every
line is ticked on that instruction. Findings raised at the audit and accepted with it:

- **Scope of this PASS.** It covers P, R and C as written. Triage (R8) was not done at the time,
  so `A1` does not exist yet and gets its own `/audit`. C6 depends on D5, and C7's dead-code half
  depends on triage. Both are bounded by R7's lists and the owner's R8 decisions.
- **P1–P3 and R1–R8 ran before this audit** (tag `v2-rebuild-complete`, `docs/rebuild-review.md`
  on `docs/rebuild-review`). They are read-only or local, and the audit accepts them as done.
- **Tasks that map to no D:** P1, C1, C2 and C8. They are accepted as serving the Approach and
  "Done when".
- **C4 and C5 are over the 10-file limit** (C4: about 21 citing files; C5: about 20). Accepted as
  one task each, because the edits are mechanical path rewrites checked by `git grep`.
- **C8's output is prose.** It is checked by the owner's text approval (a hard stop), not by a
  test.
- **The P2 note calls the `test_ws` flake "known".** That is out of date: it was fixed in
  `61f9f76`, and triage item R6-01 carries the correction.
- No new dependency (`vulture`/`knip` are ask-first). No data change: no migration, and every
  deletion is reversible from the tag. Nothing touches Render, secrets or the v1 service. C4
  edits only a comment in `.github/workflows/ci.yml`.

- [x] Every AC maps to at least one task
- [x] Every task maps to at least one AC
- [x] Each task's expected output is what we actually need
- [x] Existing patterns reused; nothing reinvented
- [x] No new dependency without an approval note
- [x] Data changes additive and reversible
- [x] Errors, empty states and permissions are tasks, not afterthoughts
- [x] Each task reviewable in one sitting
- [x] Verification named per task
- [x] Nothing touches prod, secrets or infra it should not

Audited by: MartijnBoot (human, `/audit` "accept all lines")  Date: 2026-10-17
