# Rebuild review

Basis: [plans/rebuild-review-and-cleanup.md](plans/rebuild-review-and-cleanup.md) (Parts P and R) ·
[plans/rebuild-route.md](plans/rebuild-route.md) ·
[specs/defect-register.md](specs/defect-register.md)
Reviewed: `main` at `74a7e71`, tagged `v2-rebuild-complete` (2026-10-17).
Status: **Awaiting the owner's triage.** The "proposed" column is the reviewer's suggestion; the
owner sets the decision in the [triage table](#triage-table). No clean-up task starts before that
and a PASS from `/audit` on the plan plus any amendment the triage adds.

Every R-task ran read-only in a context that did not write the code: `codebase-analyst` for R1,
R2 (non-engine rows), R3, R4 (one per spec), R5, R6 and R7; `engine-guardian` for R2's engine rows;
`fresh-eyes-reviewer` for `ce75f21` (#16). Each claim carries a `file:line`. Claims that would
change a decision were re-checked by the orchestrator (marked *verified*). Tests that need the
database, the browser or a built image were not run by the analysts; their results come from the
P2 gate below (and CI run 39022233263 on the same commit, all six jobs green).

The owner's decisions D1–D7 are recorded on the branch `docs/review-cleanup-decisions` (`77752ad`).
Per D1, Phase 8's offline run, rollback rehearsal, mock borrel and v1 key rotation are recorded
here as **waived by the owner (2026-10-17)**, never as met.

---

## Summary

**The rebuild meets its contract, with the waivers D1 records.**
- Phases −1 to 7 meet their exit criteria. Phase 8 meets "runs on Render"; its offline, rollback
  and mock-borrel halves are waived.
- **The pricing maths is unchanged.** The golden fixtures replay exactly in the pinned Linux image
  and in CI, and the engine imports nothing it should not (engine-guardian).
- All 48 defects in the register have a pinning test or a recorded reason they do not need one.
  No acceptance criterion in phases 0–8 is without a test.

**What needs the owner first:**
1. **An open defect from #16** (R4.6-02 = R6R-01). `DEFAULT_PARAMS` sets `idle_decay_minutes` and
   `idle_rise_minutes` to 0.1, below SD8's server floor of 0.5. A first run stores values the
   settings API refuses, later runs copy them forward, and once changed they cannot be set back.
   Decide: raise the defaults, or lower SD8's floor to v1's 0.1.
2. **Phase 0's repository governance never reached `main`** (R4.0-01, *verified*). Commit `ff74f4d`
   (Dependabot, CODEOWNERS, PR template, issue templates, the review-waiver ADR and its test) lives
   only on `origin/feature/phase-0-t12-repo-governance`, though the checklist ticks it. Its ADR
   number 0012 is now taken.
3. **Branch protection is not doing what was recorded** (R4.0-02, R4.0-03). Two merge commits went
   straight to `main` (`15d7f25`, `94c304b`, *verified*), and a required check may still be named
   `docker`, a job since renamed `image`. Only the owner can read the protection settings.
4. **The weekly full-history secret scan has been red on both scheduled runs** (R1-01, *verified*).
5. **The golden gate is invisible on Windows** (R2E-03). `check.sh` on the owner's laptop is green
   with all 12 golden tests skipped; only CI and `scripts/golden_linux.sh` run them, and `CLAUDE.md`
   gives a command that prints DIFFERS on Windows (R2E-04).
6. **The only automated rollback check never runs** (R4.8-01 = R1-05). The previous-image boot
   drill always skips in CI; with H3 waived, nothing checks the rollback path.
7. **Two invariants are worded more strongly than the code delivers** (R2-01, R2-07). Float euro
   values live in `price_tick.prices` and `order_line.p_cont` (every ledger and charged amount is
   integer cents), and an order makes 2–3 DB round trips inside the state lock. Reword or change.
8. **The venue TV sees revenue** (R2-04). The `display` role receives per-drink earnings and order
   totals over the WebSocket. It matches the spec's role table; the owner decides whether to keep it.

**What changes the clean-up plan before `/audit`:**
- **C3 deletes the only live copy of the hard-stop list** (`.claude/commands/rebuild.md:175-199`;
  the other copy is in ADR 0009, which C3 supersedes). Move it first (R7-01).
- **C3's scope misses swarm text in six `.claude/` files**, so its own `git grep swarm` check would
  fail (R5-11). Two agents (`task-builder`, `task-verifier`) and some `settings.json` permissions
  only served the swarm (R7-11, R7-12). `.claude/**` edits need the owner in auto mode.
- **C1's merge-tree test deletes none of the ~40 stale branches**: squash-merged branches that
  `main` later amended all fail it (R7-04).
- **D5 costs more than it looks** (R7-02, R7-03). The "v1 key import" is two guard tests (keep
  them). `import_v1` is how four test harnesses and the venue runbook create a run, so removing it
  is a rewrite of those, not an 861-line deletion.
- **C2 must not bulk-clean**: `git clean -fdX` would delete `.env.local` and
  `.claude/settings.local.json` (R7-08).
- **C5 must be gated on Linux** (`golden_linux.sh` or CI), not on a Windows `check.sh`, and must
  repoint `test_default_params`, not delete it (R2E-08, R2E-09, R6R-03).
- **The plan's P2 note is out of date**: the `test_ws` flake was fixed in `61f9f76` on 2026-10-04
  (R6-01, *verified*).

---

## P2 — Baseline gate on `main` (`74a7e71`)

`docker compose` `db` up and healthy (`127.0.0.1:5432`); `.env.local` uses `127.0.0.1`.

| run | command | result |
|---|---|---|
| 1 | `./scripts/check.sh` | **FAILED at step 12/13**: `tests/integration` 386 passed, **1 failed** (`test_heavy_reads.py::test_every_heavy_read_is_fast_enough_and_off_the_live_engine`, asyncpg `TimeoutError` in its *seed* insert, `tests/integration/test_heavy_reads.py:109`); `tests/api` and e2e did not run. Steps 1–11 green. Run while 16 review agents loaded the machine. |
| 2 | `./scripts/check.sh` (rerun once, machine quiet) | **all 13 steps passed**: unit 668, meta 255, engine 219 (+12 golden skipped on win32), vitest 605, integration 387, api 654 (`test_ws` green), e2e 33 |
| — | `uv run python -m tests.engine.golden.capture --check` (Windows) | exit 1, all six scenarios `DIFFERS`. Expected: the golden numbers are captured on Linux (`scripts/golden_linux.sh:4-6`) |
| — | `bash scripts/golden_linux.sh` (pinned Linux image) | exit 0: `s1_live`…`s6_idle` all `ok`; `tests/engine` 231 passed |

The run-1 failure is the AC31 test's seed insert hitting the 5 s live-connection timeout under load
(P2-01 below). The plan's P2 note expected a `test_ws` `CancelledError`; that flake was fixed in
`61f9f76` and did not appear.

| id | finding | evidence | proposed |
|---|---|---|---|
| P2-01 | `test_heavy_reads` seeds 60 000 order lines through the live engine (5 s `DATABASE_TIMEOUT_SECONDS`); under machine load the seed times out and the gate goes red | `tests/integration/test_heavy_reads.py:109,159`; run 1 output below | register (seed through the heavy-read engine, or raise the seed's timeout) |

The full outputs are in [Appendix A](#appendix-a--p2-gate-output), colour codes stripped, otherwise
verbatim.

---

## R1 — Phase exit criteria

Ran (analyst): `tests/engine` 219 passed, 12 skipped (golden, Linux-only); `tests/meta` 255 passed;
`tests/unit` 668 passed. CI run 39022233263 on 74a7e71 (HEAD): all six jobs green; its `check` job
ran tests/engine 231 passed (golden on Linux), vitest 605, integration 387, api 654, Playwright
33, "all 13 steps passed".

| phase | exit criterion (route) | proving check | evidence | status |
|---|---|---|---|---|
| −1 | ✅ Done — commit `b617a56` | none automated; `b617a56` is in v1's repo | `docs/adr/0007-v1-authorization-hotfix.md:3,36-37` (31-check suite against v1) | **met (manual)**; moot since v1 is suspended |
| 0 | `scripts/setup.sh` then one command gives a running shell app; CI green | setup.sh: nothing runs it; app: `tests/integration/test_health.py:64`; CI: `.github/workflows/ci.yml:101` runs `./scripts/check.sh` | push CI green on HEAD; **both scheduled full-history runs red** (38257678855, 37312514862 — verified) | **met** for push CI; setup.sh half **met (manual, `docs/plans/manual-checklist.md:157`)**; scheduled CI red (R1-01) |
| 1 | Pure engine reproduces v1's outputs exactly | `tests/engine/test_golden_replay.py:47-56`; `test_golden_capture.py:34`; `test_purity.py:121`; differential vs v1 `test_properties.py:174` | `golden_linux.sh` (P2): s1–s6 ok, 231 passed; CI 231 passed; skipped on Windows | **met** (guarded on Linux only, R1-03) |
| 2 | Live config round-trips through Postgres; restart preserves prices | `tests/integration/test_import_v1.py:129`; `test_durability.py:189,242`; `test_rehydrate.py:174,201`; `test_real_process.py:78` | P2 gate step 12 (integration) | **met** |
| 3 | Every route authorized; integration tests green against real Postgres | `tests/meta/test_route_authorization.py:114`; `tests/api/test_authorization_matrix.py:91,139`; `tests/api/test_ws.py:68,291` | meta passed; api: P2 gate | **met** |
| 4 | Big screen works end to end; theme propagates across machines | `web/e2e/theme.spec.ts:57,77,105`; `web/e2e/offline.spec.ts:28,64`; `web/e2e/board.spec.ts` | P2 gate (e2e) / CI 33 passed | **met** (two browser contexts, not two machines) |
| 5 | Price shown equals price charged, enforced by a property test | `web/src/features/bar/model/money.property.test.ts:369-376` (10 000 cases); `web/e2e/bar.spec.ts:66,97` | P2 step 11 (vitest 605 passed); CI log "10000 cases" | **met** |
| 6 | An admin can configure a borrel from scratch | `web/e2e/admin.spec.ts:85` (empty DB); `tests/integration/test_drink_lifecycle.py:186,414`; `test_config_live.py:157` | P2 gate | **met** |
| 7 | Two past borrels comparable; xlsx export matches the database | `tests/integration/test_export_workbook.py:159`; `test_analytics_compare.py:133` | P2 gate step 12 | **met** |
| 8 | Runs on Render *and* offline; rollback rehearsed; mock borrel passed | Render: H1 record `docs/runbooks/rehearsals/2026-10-17-render-deploy.md:3,10`; deploy run 39018016714 on `0ad12c6`. Offline: CI proxy `tests/image/test_venue.py:276`. Rollback: `tests/image/test_boot_image.py:153-159` always SKIPPED in CI | as cited | **Render: met (manual).** **Offline run + mock borrel (H2): waived by the owner, 2026-10-17** (`docs/plans/phase-8-human-steps.md:257`, `docs/backlog.md:49-62`). **Rollback (H3): waived by the owner, 2026-10-17** (`phase-8-human-steps.md:282-285`). **Key rotation (H4): waived by the owner, 2026-10-17** (`phase-8-human-steps.md:92-96`). Mock borrel: never run, no record |

| id | finding | evidence | proposed |
|---|---|---|---|
| R1-01 | The weekly full-history secret scan is red — both scheduled CI runs ever failed (gitleaks `generic-api-key`, most likely a test fixture key in `web/src/features/keys/KeysSection.test.tsx:27`); push scans only scan HEAD (`--log-opts=-1`) so they miss it | `.github/workflows/ci.yml:19-20`; `.gitleaks.toml:19-21`; runs 38257678855, 37312514862 | fix |
| R1-02 | Nothing automated runs `scripts/setup.sh` (CI installs its own way); `setup.sh` never builds `web/dist`, and the app mounts the SPA only if it exists | `scripts/setup.sh:54-76`; `app/main.py:273`; `README.md:20-25` | register |
| R1-03 | Golden replay/capture skip on non-Linux: the owner's Windows `check.sh` never runs the gate on the entire rebuild (same as R2E-03) | `tests/engine/test_golden_replay.py:29-32` | see R2E-03 |
| R1-04 | "Every branch of the pricing logic has a test" (Phase 1 spec) has no coverage measurement; rests on scenario branch-hit asserts | no `cov`/`fail_under` in `pyproject.toml`, `scripts/check.sh`, `ci.yml` | accept |
| R1-05 | Previous-image boot test always SKIPPED in CI (same as R4.8-01) — with H3 waived nothing checks the rollback path | `tests/image/test_boot_image.py:153-159`; `.github/workflows/ci.yml:202` | fix |
| R1-06 | `manual-checklist.md` ticks "rotate the v1 access keys" and the Phase 8 exit criterion; the human-steps notes say H2/H3 not met, H4 not done. "Waived" lives only in a commit message and the unmerged D1 | `docs/plans/manual-checklist.md:270-271`; `docs/plans/phase-8-human-steps.md:92-96,257,285` | fix (this report records "waived" on `main`; the checklist goes in C4) |
| R1-07 | Manual exit checks for Phases 4–7 are ticks with no output; Phase 5's two-phone/AP-pull check never recorded; Phase 4's tick omits the offline part | `docs/plans/manual-checklist.md:209,225,237,249` | accept |
| R1-08 | Stale status on `main`: route table row 8 shows no waiver; `phase-8-human-steps.md:5` says "Not started"; checklist cites AC17 for key rotation (it is AC32) | `docs/plans/rebuild-route.md:24`; `docs/plans/phase-8-human-steps.md:5`; `docs/plans/manual-checklist.md:270` | fix (route line, human-steps status — both files stay) |
| R1-09 | Phase 1 and 2 exit proofs read `legacy/v1/config/exchange_config.json` directly (C5 must copy first) | `tests/engine/golden/scenarios.py:42`; `tests/integration/test_import_v1.py:35-36` | C5 note |
| R1-10 | Render serves `0ad12c6` (n+4); `ce75f21` is on `main` but undeployed, and its own CI run was cancelled (HEAD's run is green and contains it) | run 39022019887 cancelled; deploy run 39018016714 | accept |

---

## R2 — Cross-phase invariants

#### Engine rows (engine-guardian) — both hold; verdict **unchanged**

| invariant | enforcing check | output | gap? |
|---|---|---|---|
| `exchange` imports no clock, no I/O, no framework | `tests/engine/test_purity.py:121` (ban), `:126` (rglob walk must reach every `exchange/**/*.py`), `:166,187` (detector tested on `from time import`, `__import__`, `importlib`, function-local, relative and transitive imports) | engine-guardian, Windows: `tests/engine` 219 passed, 12 skipped; gate step 10 the same | yes — R2E-01, R2E-02 (ban-list breadth; scope is fine) |
| Golden fixtures pass | `tests/engine/test_golden_replay.py:47-56` (`np.array_equal` on y, p_cont, p_q, cum_orders, flow_ema, t_round, rng_counter); `test_golden_capture.py:40` (v1_reference sha256 pin, every platform), `:47` (fixture glob ⇔ SCENARIOS), `:52-57` (fixtures reproduce from v1, Linux only), `:104` (each scenario reaches its branch); `tests/engine/test_numeric_pin.py:21` | `scripts/golden_linux.sh` on 74a7e71: s1–s6 ok, 231 passed (P2); CI run 39022233263 on 74a7e71: 231 passed, no skips. On Windows the 12 golden tests skip and bare `capture --check` prints DIFFERS for all six (P2) | yes — R2E-03…R2E-07 |

Also confirmed sound: RNG is `default_rng(SeedSequence([run_seed, rng_counter]))`
(`exchange/steps.py:304-313`), no `Generator` held in state; Brownian uses configured
`bm_dt_minutes` (`steps.py:286-297`); `Params.from_dict(v1 params) == DEFAULT_PARAMS` (all 24
keys); the app's spec path is pinned bitwise to replay's (`tests/unit/test_mapping.py:51`).

| id | finding | evidence | proposed |
|---|---|---|---|
| R2E-01 | Import ban stops at 8 names: `pathlib`, `io`, `sys`, `socket`, `subprocess`, `threading`, `secrets`, `uuid`, `pydantic`, `starlette`, `httpx`, first-party `app`/`db`, and builtin `open()` would pass. Today `exchange/` imports only `dataclasses`, `typing`, `math`, `collections.abc`, `numpy` | `tests/engine/test_purity.py:32-35` | backlog (widening is the owner's call, per `:32`) |
| R2E-02 | numpy allowed wholesale: global `np.random.*`, unseeded `default_rng()`, `np.load` pass the ban (behavioural tests catch unseeded noise; nothing catches numpy I/O) | `tests/engine/test_purity.py:219-220`; `exchange/steps.py:311` | backlog |
| R2E-03 | The golden gate skips silently off Linux: `check.sh` on the owner's Windows laptop is green with all 12 golden tests skipped; only CI and `golden_linux.sh` exercise it, and nothing fails if CI ever skipped them | `tests/engine/test_golden_replay.py:29-32,47`; `tests/engine/test_golden_capture.py:34-37,52`; `.github/workflows/ci.yml:34,101` | register (fail CI on a golden skip, or have `check.sh` call `golden_linux.sh` off Linux) |
| R2E-04 | `CLAUDE.md` gives bare `capture --check` as the golden diff; on Windows it reports DIFFERS for every scenario (seen in P2). `scripts/golden_linux.sh` is not mentioned | `CLAUDE.md:22-23`; `scripts/golden_linux.sh:1-9` | fix (C8) |
| R2E-05 | numpy SIMD pin applies only in tests (`NPY_DISABLE_CPU_FEATURES`), never in the app: production is not proven ULP-identical to the fixtures on every CPU (v1 ran unpinned too; rehydrate loads state, it does not replay) | `tests/engine/golden/__init__.py:14-18` | accept (or register) |
| R2E-06 | Replay compares 7 fields per event, not `last_order_ts`, `jumps`, `last_idle_ms`, `last_bm_ms`; only an effect after a scenario's last event escapes | `tests/engine/test_golden_replay.py:23-24` | accept |
| R2E-07 | Golden replay drives `exchange` through test glue (`replay.spec_from_config`), not the app path (`spec_from_rows`, s0 calibration `app/db/runs.py:528-532`, slot mapping `app/runtime/orders.py:210`); pieces are pinned, the whole is not | `tests/unit/test_mapping.py:51`; `tests/unit/test_codec.py:74,94` | backlog |
| R2E-08 | `DEFAULT_PARAMS` is pinned only by `test_default_params`, whose docstring says delete it with `legacy/`; the integration test compares it with itself | `tests/unit/test_default_params.py:5,17,22`; `tests/integration/test_runs.py:308,312` | fix in C5 (same as R6R-03) |
| R2E-09 | C5 note: `scenarios.py` reads `legacy/` at import time; 11 test modules fail at collection without it (all fixed by repointing `scenarios.py`). The safety net for the copy is `test_golden_capture.py:54`, Linux-only — gate C5 on `golden_linux.sh` or CI, not on a Windows `check.sh` | `tests/engine/golden/scenarios.py:41-43` | C5 note |

#### Non-engine rows (codebase-analyst)

Ran six unit/meta files (`test_route_authorization`, `test_grace`, `test_codec`, `test_mapping`,
`test_check_built_assets`, `test_no_file_io`): 124 passed. Every row has an enforcing check and
every row has a gap; two rows are broken as worded today (money, state lock).

| invariant | enforcing check | output | gap? |
|---|---|---|---|
| (2) No float holds a euro amount in the DB | `tests/integration/test_schema.py:123` (every column of the DB migrated to head, via `information_schema`), `:109` (every table reached), `:140` (detector flags an injected column) | P2 gate (step 12 passed this file) | yes — R2-01 (live, by design), R2-02 |
| (2) Per-drink values keyed by `drink_id` | `tests/integration/test_engine_state.py:162`; `tests/integration/test_rehydrate.py:305,397`; `tests/unit/test_codec.py:79,135,168,178,188` | codec 14 passed; integration P2 gate | minor: specific columns only; no live violation |
| (3) Every route has an explicit authz dependency | `tests/meta/test_route_authorization.py:114` (walks `create_app().routes` incl. WS and mounts), `:177`; `tests/api/test_authorization_matrix.py:91,137` | meta 4 passed; matrix P2 gate (step 12 stopped before `tests/api`) | yes — R2-03 |
| (3) WS handshake checks role | `app/realtime/ws.py:85-101`; `tests/api/test_ws.py:68,259,291`; `tests/api/test_ws_revoke.py:38` | P2 gate (not reached in run 1) | R2-04, R2-05 |
| (3) Inside the state lock: pure numpy + one short DB transaction | **no direct check**; related `tests/integration/test_holder.py:75,211,306`; `tests/meta/test_no_file_io.py` | 22 passed / P2 gate | yes — R2-06 (review-only), live R2-07, R2-08 |
| (4) No runtime request leaves the origin; CI check on built output | `scripts/check_built_assets.py` (`scripts/check.sh:112`, `.github/workflows/ci.yml:157-162`); `tests/unit/test_check_built_assets.py`; runtime `web/e2e/offline.spec.ts:28`, `web/e2e/analytics.spec.ts:57` | unit 32 passed; P2 step 9 "no non-origin references in web\dist" | yes — R2-09, R2-10, R2-11 |
| (5) Displayed price = charged price, or rejected | `tests/unit/test_grace.py:39,60,67,76`; `tests/integration/test_place_order.py:368,391`; `tests/api/test_orders.py:147`; `web/src/features/bar/model/money.property.test.ts:370`; `web/e2e/bar.spec.ts:66,98` | grace 45 passed; rest P2 gate | partial — R2-12, R2-13 |

| id | finding | evidence | proposed |
|---|---|---|---|
| R2-01 | Money invariant broken as worded: SD10 stores float `p_cont`/`p_q` (euros) in `price_tick.prices` jsonb; `step_quant` (euros) in `run.params` and revision config; `order_line.p_cont` is `double precision` (allowlisted); analytics rebuilds displayed cents from the jsonb float. Every ledger and charged amount is integer cents | `db/migrations/versions/0003_state_ledger_news.py:77,110`; `app/db/codec.py:149`; `app/db/analytics.py:332,354`; `docs/specs/phase-2-persistence.md:70` vs `:163`; `tests/integration/test_schema.py:64-71` | register + reword the invariant ("no ledger or charged amount") |
| R2-02 | Money detector reads type names only: `json`/`jsonb` and `ARRAY` (`real[]`) are blind spots | `tests/integration/test_schema.py:60,89-93,98-106` | backlog |
| R2-03 | Route audit trusts a hand-settable `__require_role__` marker; a probe no-op dependency with the marker passes. The behavioural matrix catches it only once the route has a row | `tests/meta/test_route_authorization.py:55-58`; `app/realtime/ws.py:101` | backlog |
| R2-04 | WS admits every role and filters nothing by role: `display` (the venue TV) receives per-drink earnings and order totals over WS and `GET /api/state`, while `GET /api/earnings/series` is bar/admin only. Matches the SD1 table | `app/realtime/messages.py:149,169-176`; `app/api/state.py:25`; `app/api/earnings.py:48` | owner decides: accept or backlog |
| R2-05 | Standby accepts `/ws` and closes 1013 before any origin/session check (no data sent; Phase 8 SD4) | `app/api/standby.py:43-47` | accept |
| R2-06 | Nothing checks the state-lock rule; a second transaction, network call or heavy job in a step passes every test | `app/runtime/holder.py:443-466` | register as review-only, or backlog a transactions-per-mutate test |
| R2-07 | An order does 2–3 DB round trips in the lock: idempotency lookup, `write_order`'s transaction, a re-read on a taken key (lookup required by SD20) | `app/runtime/orders.py:165-166,233,257-258`; `app/db/orders.py:79` | accept + reword ("one write transaction") |
| R2-08 | `holder.adopt` (go-live) holds the lock across a full rehydrate (REPEATABLE READ reads, optional gap write, a third connection), unbounded by `step_timeout_s` and unlogged by `lock_hold_ms`; `release` calls `landed()` under the lock on failure | `app/runtime/holder.py:376-390,420-424,453-455,465`; `app/runtime/golive.py:49-56`; `app/runtime/rehydrate.py:69-124` | register / backlog |
| R2-09 | Built-asset scanner misses `new WebSocket("wss://…")`, `sendBeacon`, `XMLHttpRequest.open`, `EventSource`, `fetch(variable)`, `fetch(new URL(abs))`, and `.svg` external `href` — a probe dist with all of them exited 0 | `scripts/check_built_assets.py:44,53-72,134-144` | backlog |
| R2-10 | Runtime offline e2e never loads `/bar` or `/manipulation` with off-origin requests blocked; `context.route('**/*')` does not intercept WebSockets | `web/e2e/offline.spec.ts:35-61`; `web/e2e/analytics.spec.ts:57-65` | fix |
| R2-11 | `/docs` and `/redoc` load from `cdn.jsdelivr.net`; mounted only when `APP_ENV` is local or ci | `app/main.py:103,167,200,203` | accept (state the invariant's scope: production and venue) |
| R2-12 | No integration test moves the market (jump) between quote and order and checks the charged line; the 50-order concurrency test checks only `ledger == sum(receipts)` | `tests/integration/test_place_order.py:368-388`; `tests/integration/test_order_concurrency.py:137,205` | backlog |
| R2-13 | Money property test seeds from `Date.now()` per run (seed printed; `PROPERTY_SEED` replays) | `web/src/features/bar/model/money.property.test.ts:40` | accept |

---

## R3 — Defect register closure

48 defects (D-01…D-48; verified unique count). Ran 22 unit/meta/engine files: 591 passed.
DB-backed, web and e2e pins: evidence P2 gate.

**Totals:** 41 fixed with a pinning test (D-18, D-35 with a caveat each); 2 accepted by decision and
pinned (D-22 idle gate kept as v1; D-23 flow_ema, ADR 0012); 3 designed out and pinned (D-11
sidecar, D-12 xlsx store, D-27 token shutdown); D-40 fixed for production, deliberately not at the
venue; D-42 v2 side fixed, **v1 key rotation not done (risk accepted, H4 waived)**. No defect is
"fixed" without a pinning test.

| D-nn | defect | status | pin / tracking |
|---|---|---|---|
| D-01 | engine state never persisted | fixed | `tests/integration/test_durability.py:189`; `test_real_process.py:78` |
| D-02 | `POST /drinks` rebuilds state | fixed | `tests/integration/test_drink_lifecycle.py:186,414`; `tests/engine/test_lifecycle_helpers.py:194` |
| D-03 | placeholder/`+""` zeroes a/d/s0/c | fixed | `web/src/features/settings/DemandSection.test.tsx:97-105`; `tests/api/test_config.py:163,241` |
| D-04 | add-drink sends 0 for blanks | fixed | `tests/api/test_drinks.py:62`; `DrinksSection.test.tsx:111` |
| D-05 | charged a price never shown | fixed | `money.property.test.ts:370`; `tests/integration/test_place_order.py:183,368`; `web/e2e/bar.spec.ts:66` |
| D-06 | no idempotency key | fixed | `tests/integration/test_place_order.py:267,291,308`; `tests/api/test_orders.py:56` |
| D-07 | stale check before lock | fixed | `tests/integration/test_place_order.py:237`; `test_order_concurrency.py:105` |
| D-08 | version is a timestamp | fixed | `tests/integration/test_order_concurrency.py:105` (~:207) |
| D-09 | money as floats | fixed | `tests/integration/test_schema.py:123,140`; `tests/unit/test_v1_files.py:73` (see R2-01 for floats outside money columns) |
| D-10 | two revenue sources | fixed | `tests/integration/test_schema.py:147`; `test_orders.py:330` |
| D-11 | `bar_price` lost on first save | fixed / sidecar designed out | `tests/integration/test_rehydrate.py:372`; `test_runs.py` (~:157) |
| D-12 | xlsx rewritten per line | designed out, pinned | `tests/integration/test_orders.py:205`; `tests/meta/test_no_file_io.py` |
| D-13 | four runtime CDN deps | fixed | `tests/unit/test_check_built_assets.py`; `web/e2e/offline.spec.ts:28` (real offline run deferred, `docs/backlog.md:49`) |
| D-14 | theme/candle interval in localStorage | fixed | `web/src/lint-rules.test.ts:121`; `web/e2e/theme.spec.ts` |
| D-15 | market event has no end | fixed | `tests/integration/test_ticker.py:399`; `test_manipulation.py:176,313` |
| D-16 | news level case mismatch | fixed | `tests/integration/test_schema.py:209`; `test_news.py:63`; `tests/unit/test_v1_files.py:155,160` |
| D-17 | no WS liveness | fixed | `web/src/features/exchange/model/client.test.ts:131-153` |
| D-18 | `GET /state` advances engine | fixed (weak pin, R3-05) | `tests/api/test_state.py:39` |
| D-19 | theme editor shows 13 tokens | fixed | `ThemeEditor.test.tsx:56`; `tests/api/test_theme.py:216` |
| D-20 | `p0_total` from bar price | fixed | `tests/integration/test_bar_price_snapshot.py:35,73`; `tests/meta/test_no_p0_totals.py:49,56` |
| D-21 | `calibrate_s0_to_p0` name lies | fixed (renamed) | `tests/engine/test_spec.py:173` |
| D-22 | idle gate uses `refresh_minutes` | accepted (kept as v1), pinned | `tests/engine/test_steps_idle_brownian.py:173` |
| D-23 | `flow_ema` never decays | accepted (ADR 0012), pinned | `tests/engine/test_steps_idle_brownian.py:209` |
| D-24 | drinks by index, no dup check | fixed | `tests/integration/test_rehydrate.py:397`; `test_runs.py:97,131` |
| D-25 | names into `innerHTML` | fixed | `Tile.test.tsx:62`; `Marquee.test.tsx:47`; `lint-rules.test.ts:89`; `web/e2e/board.spec.ts:101` |
| D-26 | home health strip throws | fixed | `HomePage.test.tsx:98,127` |
| D-27 | `/shutdown` token never sent | designed out, pinned | `tests/api/test_admin.py:67,118`; `tests/meta/test_no_v1_key_import.py:131` |
| D-28 | three price tracks as one | fixed | `tests/unit/test_messages.py:174`; `test_publish.py:208`; `test_history_ring.py:92` |
| D-29 | `.svg` upload XSS | fixed | `tests/api/test_assets.py:54,74`; `tests/unit/test_images.py` |
| D-30 | xlsx re-read per broadcast | fixed | `tests/integration/test_rehydrate.py:435`; `tests/unit/test_publish.py:286` |
| D-31 | per-sale series rebroadcast | fixed | `tests/integration/test_earnings_series.py:182`; `tests/unit/test_messages.py:90` |
| D-32 | history every tick | fixed | `tests/unit/test_messages.py:79,90` |
| D-33 | dead broadcast fields | fixed | `tests/unit/test_messages.py:118,137` |
| D-34 | serial broadcast blocks | fixed | `tests/unit/test_hub.py:99,131` |
| D-35 | sync file I/O in async handlers | fixed (scan gap, R3-04) | `tests/meta/test_no_file_io.py` |
| D-36 | WS "state" forces advance | fixed | `tests/api/test_ws.py:216` |
| D-37 | no API authz | fixed | `tests/meta/test_route_authorization.py:114`; `tests/api/test_authorization_matrix.py:139` |
| D-38 | `/static` served admin pages | fixed | `tests/api/test_static.py:43,57` |
| D-39 | `JWT_SECRET` random fallback | fixed | `tests/unit/test_config.py:94,346` |
| D-40 | cookie not `Secure` | fixed for production; not at venue by design (R3-06) | `tests/unit/test_config.py:453`; `tests/api/test_auth.py:44` |
| D-41 | `allow_origins=["*"]`, CSRF premise | fixed | `tests/api/test_auth.py:210,230` |
| D-42 | plaintext keys committed | v2 fixed; **v1 rotation not done, risk accepted** | `tests/integration/test_schema.py:323`; `tests/meta/test_repo_hygiene.py:144,154`; `tests/api/test_v1_keys.py:62`; rotation: `docs/plans/phase-8-human-steps.md:91-96` |
| D-43 | 1.65 GB image | fixed (CI only) | `.github/workflows/ci.yml:142`; `tests/unit/test_check_image.py` |
| D-44 | bar role can `POST /config` | fixed | `tests/api/test_authorization_matrix.py:139`; `ManipulationPage.test.tsx:104` |
| D-45 | bound change rescales prices | fixed | `tests/integration/test_drink_lifecycle.py:304,333`; `test_config_live.py:157,204` |
| D-46 | empty jump target → `p_min` | fixed | `ManipulationPage.test.tsx:195`; `tests/integration/test_manipulation.py:250` |
| D-47 | upload size checked after read | fixed | `tests/api/test_assets.py:142,170`; `tests/unit/test_images.py:71` |
| D-48 | image slots in localStorage | fixed | `KoersPage.test.tsx:119`; `tests/api/test_theme.py:299` |

| id | finding | evidence | proposed |
|---|---|---|---|
| R3-01 | Register's D-42 evidence says "v1's keys rotated by human" — they were not (v1 suspended, keys kept, risk accepted) | `docs/specs/defect-register.md:140` vs `docs/plans/phase-8-human-steps.md:91-96` | register (correct the row) |
| R3-02 | Checklist ticks "rotate the v1 access keys"; and the open rotation is in no backlog entry — `phase-8-human-steps.md` is its only record (it stays, per D2) | `docs/plans/manual-checklist.md:270`; `docs/backlog.md:44-62` | backlog |
| R3-03 | Register has no status column; only D-20/21/22/23/31 say "Resolved"; 31 Phase 2–5 rows never record v2 re-proving them | `docs/specs/defect-register.md:13-99` | register (this table can be its status column) |
| R3-04 | File-I/O meta test scans `app/db`, `app/runtime`, `app/jobs` only — not `app/api` or `app/realtime`, exactly where D-35 lived (clean today) | `tests/meta/test_no_file_io.py:36` | fix |
| R3-05 | D-18 test checks only in-memory `version`, not `rng_counter` (AC15 names both; the WS test checks it) | `tests/api/test_state.py:39-50` vs `tests/api/test_ws.py:23-25` | fix |
| R3-06 | D-40 partly back by design: venue sets `SESSION_COOKIE_SECURE=false`; refusal only when `APP_ENV=production`; not recorded in the register | `deploy/venue/compose.yml:57`; `app/core/config.py:207`; `docs/specs/defect-register.md:81` | register |
| R3-07 | D-18 test and route docstrings cite D-06; `git grep D-18` finds nothing | `tests/api/test_state.py:42`; `app/api/state.py:5` | fix |
| R3-08 | Docstrings say display-track dedupe "is D-28 and Phase 3's"; Phase 3 dropped dedupe; no such code exists | `app/runtime/history.py:6`; `tests/unit/test_history_ring.py:93` | fix |
| R3-09 | D-03 lint bans unary `+` but allows `Number()` (`Number("")` is 0 too); behaviour tests are the real pin | `web/src/lint-rules.test.ts:214`; `web/eslint.config.js:54-60` | accept |
| R3-10 | D-43 image size pinned in CI only, not `check.sh` (cannot build images) | `.github/workflows/ci.yml:142` | accept |

---

## R4 — Acceptance-criteria traceability

One analyst per spec. Every AC in phases 0–8 has at least one test; "weak" means the test exists but cannot fail, or covers only part of the AC.

#### Phase 0 — foundations (`phase-0-foundations.md`, AC1–AC7)

7 ACs: 2 covered (AC2, AC3), 3 weak (AC4, AC5, AC6), 2 manual (AC1, AC7). Ran engine, config-boundary,
repo-hygiene, compose/env, config, app-shell and check-image tests: 388 passed, 12 skipped (golden).

#### Phase 1 — engine (`phase-1-engine.md`, AC1–AC10)

10 ACs: 8 covered, 2 weak (AC7, AC10). AC1 (golden replay) runs on Linux only — locally just the
same-machine differential against v1 (`tests/engine/test_properties.py:174`, 500 random sequences).

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.0-01 | **Phase 0 T12 never reached `main`** (verified): `ff74f4d` (dependabot, CODEOWNERS, PR template, issue templates, single-operator review-waiver ADR, `tests/meta/test_repo_governance.py`) is only on `origin/feature/phase-0-t12-repo-governance`; `.github/` on `main` holds only the two workflows. The checklist ticks it; its ADR number 0012 is now taken | `docs/plans/manual-checklist.md:148`; `git ls-files .github` | fix (renumber the ADR) |
| R4.0-02 | AC5 "block the merge" contradicted by history: merge commits `15d7f25` (2026-10-16) and `94c304b` (2026-10-11) went straight to `main` (verified) | `docs/plans/manual-checklist.md:146`; `git log --merges --first-parent origin/main` | register (owner checks branch protection with `gh api`) |
| R4.0-03 | Required-check names may not match: protection recorded `check`/`secret-scan`/`docker`; job `docker` was renamed `image` in `1110f93` | `docs/plans/manual-checklist.md:146`; `.github/workflows/ci.yml:126-127` | register (unverified; owner) |
| R4.0-04 | AC4 "local and CI run the same checks": not on Windows (golden skips) — same as R2E-03 | `tests/engine/test_golden_replay.py:29-32` | see R2E-03 |
| R4.0-05 | No test pins `ci.yml`'s shape (that `check` runs `./scripts/check.sh`, that `secret-scan` and the image build exist) | `.github/workflows/ci.yml:100-101,103-138` | backlog |
| R4.0-06 | Image check has no rule for AC6's uploads/earnings; excluded only from the build context via v1 paths | `scripts/ci/check_image.py:36-37,59-63`; `.dockerignore:8-9` | backlog |
| R4.0-07 | `test_the_detector_notices_a_dropped_entry` cannot fail (removes an item from a set, then asserts it is absent) | `tests/meta/test_repo_hygiene.py:93-96` | fix |
| R4.0-08 | AC1 (`setup.sh`) has no automated test (same as R1-02) | `scripts/setup.sh` | accept |
| R4.0-09 | AC7 push-protection evidence is a tick only; the rejection message the plan asked to keep is nowhere | `docs/plans/manual-checklist.md:151`; `docs/plans/phase-0-foundations.md:312` | register |
| R4.0-10 | Stale docstring: "`db/` is empty today and will stay that way until T7" | `tests/meta/test_config_boundary.py:21-22,227` | accept (C-task clean-up) |
| R4.1-01 | AC10 ("≈ no net relative price movement") not tested as written; owner decisions of 2026-10-01 replaced it (uniform pre-barrier pressure; equal orders lift every price), recorded only in a test docstring | `tests/engine/test_steps_orders.py:7-24,312-333`; `docs/specs/phase-1-engine.md:60-61` | fix (docs: amend AC10) |
| R4.1-02 | AC7 "jump overrides Brownian for its duration" is false at the published price by design (D5: one noise draw on a jumping drink); spec unamended | `tests/engine/test_steps_jumps.py:194,204,215` | accept + spec note |
| R4.1-03 | AC1 evidenced only on Linux CI (same as R2E-03) | `tests/engine/test_golden_replay.py:47` | see R2E-03 |
| R4.1-04 | AC4 case `tick-idle-fires` has no check that idle actually fires | `tests/engine/test_advance.py:55,75` | backlog |


#### Phase 2 — data model + persistence (`phase-2-persistence.md`, AC1–AC23)

23 ACs: 18 covered, 5 weak (AC3, AC6, AC8, AC9, AC11), none manual-only or untested. Ran
`tests/unit/test_gap.py test_v1_files.py test_mapping.py test_history_ring.py test_earnings.py
test_codec.py tests/meta/test_no_file_io.py` (128 passed). DB-backed citations: evidence P2 gate.
AC1's durability test kills at 6 points and compares every state field bitwise
(`tests/integration/test_durability.py:172-239`); Phase 8 repeats it in the image kill drill.

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.2-01 | AC6 text never amended to the audited PD1 formula; tests check `(wall−t0)+budget+(now−R)`, the AC says `(kill−t0)+(now−R)`; a jump with < budget left does complete during the gap, untested | `docs/specs/phase-2-persistence.md:152-155`; `tests/unit/test_gap.py:110-131` | fix (docs: amend AC6) |
| R4.2-02 | AC8 says "active drinks"; since Phase 6 SD15 rehydrate compares against all drinks | `docs/specs/phase-2-persistence.md:158-159`; `app/runtime/rehydrate.py:88` | accept |
| R4.2-03 | AC3 bit-exactness through Postgres tested only with ordinary values; nothing pins `engine_state` columns as `json` (a jsonb switch would lose -0.0 and pass) | `tests/integration/test_engine_state.py:129-156`; `app/db/models.py:157-169` | backlog |
| R4.2-04 | AC11 "no other column stores revenue" broken in letter by Phase 7's allowlisted `export.total_cents` | `tests/integration/test_schema.py:73-78,147-152` | accept / register |
| R4.2-05 | AC9 detector checks column types only; euro floats inside JSON (`price_tick.prices`) are out of reach (audited scope) | `tests/integration/test_schema.py:58-106` | accept |
| R4.2-06 | Durability test hardcodes `WRITE_ORDER_STATEMENTS = 4` for the no-response path; only the 5-statement path is pinned | `tests/integration/test_durability.py:47-48,179-184`; `app/db/orders.py:123-128` | backlog |
| R4.2-07 | Rehydrate "write nothing" snapshot counts rows in 7 tables and compares only `engine_state` content; UPDATEs elsewhere would pass | `tests/integration/test_rehydrate.py:36,156-164` | backlog |
| R4.2-08 | AC19 on the real v1 files leaves halves untested: v1 `news.json` is `[]`, no `bar_price` key; revision 1 checked for params/name/bar price only | `tests/integration/test_import_v1.py:150-152,163-165` | backlog |

#### Phase 3 — API, auth, realtime (`phase-3-api-realtime.md`, 41 ACs incl. lettered)

41 ACs: 34 covered, 5 weak (AC3, AC6b, AC18d, AC22; AC14a partial), AC18 split (b covered, a
superseded by Phase 8 SD4 standby), none untested. Ran the DB-free Phase 3 unit/meta set plus
config, app-shell and errors tests: 342 passed. `tests/api`, `tests/integration`: evidence P2 gate.

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.3-01 | AC6b/SD9: the 403-without-Origin check is exercised only for POST and a foreign-Origin PUT; dropping DELETE/PATCH from `UNSAFE_METHODS` fails no test | `app/api/security.py:255`; `tests/api/test_auth.py:210-220`; `tests/api/test_theme.py:139` | fix |
| R4.3-02 | AC3 "before accept" cannot fail: TestClient raises the same `WebSocketDisconnect(1008)` either way (code is correct by inspection) | `tests/api/test_ws.py:86-89`; `app/realtime/ws.py:82-94,278` | backlog |
| R4.3-03 | AC18d "at most one tick lost" never asserted — the newest tick time is read and discarded; the checklist ticked this known debt `[x]` while the test is unchanged | `tests/integration/test_real_process.py:117,143`; `docs/plans/manual-checklist.md:196` | fix |
| R4.3-04 | AC18e sub-assertion `len(set(versions)) == len(ticks)` cannot fail (the PK guarantees it); never compares price vectors. Real proof is `:208-213` | `tests/integration/test_order_concurrency.py:196-197` | fix (delete or replace) |
| R4.3-05 | AC18(a) fail-fast on a held lock is deliberately untrue since Phase 8 SD4 (standby); the Phase 3 spec still states it and its header still says `Status: Draft` | `docs/specs/phase-3-api-realtime.md:3,388-390,464-465` | register (spec note) |
| R4.3-06 | AC14a key-length lower bound and 128 untested; the parametrise id `"seven-chars"` labels a 5-char value | `tests/api/test_orders.py:91-92` | fix (trivial) |
| R4.3-07 | AC labels in docstrings wrong or ambiguous (static tests tagged AC2 not AC6f; `test_boot.py` header claims AC4; unprefixed ids collide across phases) | `tests/api/test_static.py:46,58`; `tests/integration/test_boot.py:1`; `tests/api/test_auth.py:264` | backlog |
| R4.3-08 | Spec's manual verification (compose up, keys, go-live, order, `docker kill`, restart) has no record; the CI image kill drill covers the substance | `docs/plans/manual-checklist.md:194`; `tests/image/test_kill_drill.py:118` | accept |
| R4.3-09 | AC22 backpressure test drives `hub.broadcast` directly, not the real ticker beside a non-reading client; ticked `[x]` as debt, unchanged | `tests/unit/test_hub.py:99-128`; `docs/plans/manual-checklist.md:197` | backlog |

#### Phase 4 — React shell, theme, auth, koers (`phase-4-web-koers.md`, AC1–AC37)

37 ACs: 30 covered, 6 weak (AC11, AC14, AC23, AC26, AC29, AC37), 1 covered with a wording caveat
(AC35); none manual-only, none untested. Ran `tests/unit/test_check_built_assets.py
tests/unit/test_theme_manifest.py` (165 passed) and `tests/meta/test_route_authorization.py`
(4 passed). Web, e2e and DB-backed citations: evidence P2 gate. No `.skip`/`.only`/`.fixme` in
`web/`; Playwright `retries: 0` (`web/playwright.config.ts:15`).

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.4-01 | AC23 ("Nog niet beschikbaar" for an unbuilt route) and AC1's "placeholder" page are dead: every route is built; the string exists in no source; `auth.test.tsx` describe still claims AC23 | `docs/specs/phase-4-web-koers.md:228,286-287`; `web/src/features/auth/auth.test.tsx:188`; `web/e2e/auth.spec.ts:35` | accept (note supersession) |
| R4.4-02 | Built-output check scans only `.html/.htm/.css/.js/.mjs/.webmanifest`; not `.svg` hrefs, CSS `url(https://…)` in JS strings, or JS-set `src`/`href` | `scripts/check_built_assets.py:22-25,134-144` | accept (runtime e2e `web/e2e/offline.spec.ts:61` is the backstop) |
| R4.4-03 | AC11 test never asserts the grid / scale-border colours | `web/src/features/koers/ui/DrinkChart.test.tsx:172-176` | backlog |
| R4.4-04 | Storage lint catches bare and `window.` access only, not `globalThis.`/`self.`/destructured | `web/eslint.config.js:140-151`; `web/src/lint-rules.test.ts:122-127` | backlog |
| R4.4-05 | AC14 server pong tested only with a live run (handler does not branch on it) | `tests/api/test_ws.py:162`; `app/realtime/ws.py:197-198` | accept |
| R4.4-06 | AC26 colour tokens untested: only `data-pulse` and animation names checked; a swapped `var()` passes | `web/src/features/koers/Tile.test.tsx:73,79`; `web/src/features/koers/KoersPage.module.css:102,107` | backlog |
| R4.4-07 | AC29 test builds its own keyed `<List>`; production `key={id}` in `KoersPage` is never exercised — an index key would pass | `web/src/features/koers/ui/DrinkChart.test.tsx:200-214`; `web/src/features/koers/KoersPage.tsx:58` | fix (test only) |
| R4.4-08 | AC35 says SMA "for every bar"; code and test emit none before bar 5 (SD11, v1) — spec wording only | `docs/specs/phase-4-web-koers.md:318`; `web/src/features/exchange/model/sma.test.ts:7-9` | accept |
| R4.4-09 | AC37 compares only quantised `p_q`; a sub-quantum `p_cont` move passes | `tests/integration/test_ticker.py:257-259` | backlog |
| R4.4-10 | `web/package.json` runs `vitest --passWithNoTests`: deleting every vitest file keeps the gate green (pytest has `ALLOW_EMPTY` guarding the same case) | `web/package.json` (`"test"`); `scripts/check.sh` (~74) | fix |

#### Phase 5 — bar + order path (`phase-5-bar-orders.md`, AC1–AC28)

28 ACs: 21 covered, 6 weak (AC5, AC7, AC16, AC17, AC19, AC28), none untested; the spec's manual exit
check has no record. Ran `tests/unit/test_security.py tests/unit/test_earnings.py` (45 passed).
SD20 property test defaults to 10 000 cases (`money.property.test.ts:39`), nothing overrides it.
AC6's polled-snapshot promote is only structural (shared `applySnapshot`,
`web/src/features/exchange/model/applyMessage.ts:264,293`); AC26 is proven in two halves
(`tests/integration/test_restart_replay.py:102` + `orderIntents.test.ts:164`), as the plan
accepts; AC27's "themed shell" is not asserted.

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.5-01 | SD1/SD4 timings (`HOLD_MS`, `HOLD_MAX_MS`, `AGE_SHOW_MS`, `STALE_MS`) never asserted by value; a 60 s v1-length hold passes every test (retry delays are pinned, `orderIntents.test.ts:127`) | `web/src/features/bar/model/constants.ts:9-17`; `holdBuffer.test.ts:79,135,177,184` | fix |
| R4.5-02 | SD8's 8 s request timeout not pinned; test only checks a signal exists | `web/src/features/bar/api/orders.ts:15,63`; `orders.test.ts:49` | fix |
| R4.5-03 | AC16: the tests named "pending tap" make no tap — they flip `status:'offline'`; guarantee rests on types | `FinancialPanel.test.tsx:111-116`; `RevenueChart.test.tsx:172-178`; `web/src/features/bar/model/barController.ts:30-33` | fix (or accept) |
| R4.5-04 | AC17 lint is a name heuristic (`*` with `qty`/`quantity`); with qty ≡ 1 (SD5), Σ `unit_price_cents` is revenue with no `*` | `web/eslint.config.js:42-53`; `web/src/lint-rules.test.ts:150-165` | register |
| R4.5-05 | AC19's Σ qty half never compared with the DB; e2e checks revenue only, qty reads in-memory `/api/state` | `web/e2e/bar.spec.ts:197-211` | fix |
| R4.5-06 | AC28 "admin sees pad and panel" never exercised; only the route list | `web/e2e/bar.spec.ts:230`; `tests/api/test_auth.py:69` | fix |
| R4.5-07 | Spec's manual exit check (two phones, AP pull, receipts vs `order_line`) has no record; checklist ticked it on `/verify` of the property test; the deferred H2 backlog item omits both | `docs/specs/phase-5-bar-orders.md:370-373`; `docs/plans/manual-checklist.md:226`; `docs/backlog.md:55-61` | backlog |
| R4.5-08 | Property test checks AC1 against `view.displayed`, the field the tap reads — proves agreement, not that the hold kept the right quote | `web/src/features/bar/model/money.property.test.ts:142-146,253-266` | accept |
| R4.5-09 | SD16 drift: an order in the open history bucket plots at the bucket's end time; documented in code, not spec | `web/src/features/bar/RevenueChart.tsx:11-14`; `docs/specs/phase-5-bar-orders.md:179-182` | register |

#### Phase 6 — manipulation + settings (`phase-6-admin.md`, AC1–AC43)

43 ACs: 37 covered, 6 weak (AC7, AC20, AC23, AC25, AC27, AC40), none untested. Ran 8 engine/unit/meta
files: 193 passed, 6 skipped (golden). DB-backed, web and e2e: evidence P2 gate.

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.6-01 | `ce75f21` contradicts SD2 and plan T8 ("`Params()`'s defaults") — same as R6R-02 | `docs/specs/phase-6-admin.md:106-107`; `app/db/runs.py:54-69,461` | see R6R-02 |
| R4.6-02 | **Open defect:** `DEFAULT_PARAMS` idle minutes 0.1 < SD8's 0.5 floor; a first run stores params `PATCH config` refuses, and later runs copy them forward; no test checks a created run's params against SD8 — same as R6R-01 | `app/db/runs.py:64,66`; `app/runtime/config.py:106,126-127`; `tests/api/test_config.py:274` | fix after the owner decides (raise defaults or lower SD8's floor) |
| R4.6-03 | C5 hazard on `test_default_params` — same as R6R-03 / R2E-08 | `tests/unit/test_default_params.py:5,17,21` | fix in C5 |
| R4.6-04 | `DRAINING_WRITES` is a hand list missing `POST /api/theme/images/{slot}`; the route **does** declare `refuse_while_draining` (verified, `app/api/theme.py:214`) so it is not a live defect, but nothing would fail if the guard were dropped, and no completeness check exists | `tests/api/test_draining.py:7-8,23-50`; `app/api/theme.py:209-214` | fix (add the row + a completeness check over every non-GET route) |
| R4.6-05 | AC25 "within 2 s" never asserted (Playwright 5 s default); only the display is open before go-live; home reached with a reload | `web/e2e/admin.spec.ts:164-166,180,185,202`; `web/playwright.config.ts` | backlog |
| R4.6-06 | AC7 UI half tested through the `canEditIdle` prop; role wiring untested (server 403 is covered) | `web/src/features/manipulation/ManipulationPage.test.tsx:95-113`; `web/src/app/routes.tsx:39` | accept |
| R4.6-07 | Manual exit is a single tick; nothing recorded of the separate display machine, mid-borrel add/remove, or bar totals vs DB | `docs/plans/manual-checklist.md:236`; `docs/specs/phase-6-admin.md:730-733` | register |
| R4.6-08 | AC tags have no phase prefix; "AC19" means Phase 3 and Phase 6 in the same file (same as R4.3-07) | `tests/integration/test_place_order.py:1,537` | backlog |
| R4.6-09 | AC16's golden half unproven by the Windows gate (same as R2E-03) | `tests/engine/test_golden_replay.py:47` | see R2E-03 |
| R4.6-10 | AC20 tested through `rehydrate()`, not a real boot after add+remove; AC27 atomicity has no failure injected before commit | `tests/integration/test_drink_lifecycle.py:445-452`; `tests/integration/test_go_live_in_process.py:239,261,284` | accept |

#### Phase 7 — analytics + run lifecycle (`phase-7-analytics.md`, AC1–AC37)

37 ACs: 31 covered, 6 weak (AC1, AC3, AC4, AC14, AC31 export half, AC35), none untested. Ran
`tests/meta/test_no_p0_totals.py tests/meta/test_route_authorization.py
tests/unit/test_check_built_assets.py` (43 passed). DB-backed, web and e2e citations: evidence P2
gate. Manual exit check ticked at `docs/plans/manual-checklist.md:249-258` with no figures recorded.

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.7-01 | AC1 "in one transaction": no fault test breaks the close between `UPDATE run`, `end_open_events` and the export `INSERT`; atomicity holds by construction only | `tests/integration/test_close_in_process.py:161-196`; `app/db/runs.py:574-598` | backlog |
| R4.7-02 | AC3 "within 2 s" asserted nowhere; e2e uses Playwright's default 5 s expect timeout | `tests/api/test_close.py:169-186`; `web/e2e/analytics.spec.ts:189`; `web/playwright.config.ts:10-25` | fix |
| R4.7-03 | AC4 "and appear in the final export" not checked under the race; the race test checks only that a final export row exists | `tests/api/test_close.py:252`; `tests/integration/test_export_worker.py:184-210` | fix |
| R4.7-04 | AC14 cites Phase 5's money property test, which runs against a simulated server and cannot see `bar_price_cents`; the real guard is the server order test | `web/src/features/bar/model/money.property.test.ts:370`; `tests/integration/test_place_order.py:207` | accept (re-cite) |
| R4.7-05 | AC35: analytics reads never tested while draining; `DRAINING_WRITES` is a hand list with no completeness check (its missing theme-image row is R4.6-04; the route itself is guarded, verified) | `tests/api/test_draining.py:7-8,23-52` | backlog (reads); completeness check under R4.6-04 |
| R4.7-06 | AC8: per-run table list hand-written twice (test `PER_RUN` and `delete_run`); a new `run_id` table would be missed by both and the test would pass | `tests/integration/test_delete_run.py:34-47`; `app/db/runs.py:610-629` | backlog |
| R4.7-07 | AC13 names `bar_price_per_drink`; code uses `bar_price_total` per plan PD11 — spec wording drift | `docs/specs/phase-7-analytics.md:310`; `app/jobs/export_xlsx.py:87,184` | accept (amend spec wording) |
| R4.7-08 | AC31 "not on the live 5 s connection" proven for analytics routes only; the export builds in a child process the listener cannot see | `tests/integration/test_heavy_reads.py:183-189,228-229`; `app/jobs/export_xlsx.py:212` | backlog |
| R4.7-09 | Phase 7 manual exit check ticked with no run ids, totals or SQL output | `docs/plans/manual-checklist.md:249-258` | accept (automated cent gate `tests/integration/test_export_workbook.py:159` covers it) |

#### Phase 8 — deploy + cutover (`phase-8-deploy-cutover.md`, AC1–AC32, amendments A1–A3)

32 ACs, none untested. Waived by the owner (D1, 2026-10-17): AC30 (mock borrel, H2), AC31 (rollback
rehearsal, H3), and AC32's human half (H4). Ran 18 Phase 8 unit/meta files (290 passed). CI run
39022233263 on 74a7e71: all six jobs green — `image` 227.7 MB (limit 300), `image-drill` 7 passed
1 skipped, `venue` 4 passed. Deploy runs 39016701680, 39018016714 green (H1 record).
`tests/image` drills run only in CI (`.github/workflows/ci.yml:202,241`); several ACs (AC7, AC17,
AC19, AC20, AC22) are image-only.

| id | finding | evidence | proposed |
|---|---|---|---|
| R4.8-01 | AC9's "previous image on the new head" never runs: CI passes no `--previous-image`, so it always skips; the skip reason ("once GHCR holds an SD3 image") stopped being true when `1110f93` was pushed | `tests/image/test_boot_image.py:153-159`; `.github/workflows/ci.yml:202` | fix |
| R4.8-02 | AC5 "tag by full SHA, push from `main` only" pinned by no test; editing the `if:` or the tag passes | `.github/workflows/ci.yml:248,266`; `tests/meta/test_no_latest.py:71` | fix |
| R4.8-03 | CI `image` job steps behind AC2/3/4/7 pinned by no test (dropping a step, `--exit-code 1` or `--max-mb 300` passes); `check_image` size branch untested | `.github/workflows/ci.yml:137-162`; `scripts/ci/check_image.py:111-113` | backlog |
| R4.8-04 | Comment "the SBOM is written either way" is false: `set -euo pipefail` exits on a failed scan before the SBOM, and upload uses `if-no-files-found: ignore` | `.github/workflows/ci.yml:144,154`; `scripts/ci/scan_image.sh:16,49-53` | fix (comment) |
| R4.8-05 | Venue drill's dump check is weak: `pg_restore --list` misses truncation (the reason `restore.sh` moved to `--file=/dev/null`); its `.partial` check cannot fail | `tests/image/test_venue.py:329-338`; `deploy/venue/backup.sh:21-22` | backlog |
| R4.8-06 | AC21 "neither reads the other's output" holds only through compose mounts | `deploy/venue/compose.yml:33,63,86` | accept |
| R4.8-07 | `start.cmd`/`stop.cmd`/`restore.cmd` never run in any test (text-checked only); AC19's no-uplink, URL print and phone login exist only in H2 | `tests/meta/test_venue_stack.py:110-116,157-185` | accept (waived with H2) |
| R4.8-08 | AC22 "rehydrate with the gap rule" after a restore not asserted, only the order count | `tests/image/test_venue.py:368-373` | accept (gap rule pinned in `test_kill_drill.py:154`) |
| R4.8-09 | AC29 Render half partly evidenced: lock_wait and handover shown, contiguous versions / no double tick on Render never; F-H1-3 ~60 s of 503 on orders during overlap. D1 covers H2–H4, not this H1 gap | `docs/plans/phase-8-human-steps.md:180,202-203,209-218` | register |
| R4.8-10 | AC28 "refuse a SHA not in GHCR" never exercised; only step order pinned | `.github/workflows/deploy.yml:58-59`; `tests/meta/test_render_blueprint.py:139-146` | accept |
| R4.8-11 | AC12 "no tick in standby" vacuous in the direct tests (no live run); shown only indirectly by handover contiguity | `tests/integration/test_real_process.py:212-213`; `tests/integration/test_boot.py:606-647` | backlog |
| R4.8-12 | AC32 human half not done: v1 Render service suspended, not deleted — leaked keys valid again if resumed; no key-rotation record | `docs/plans/phase-8-human-steps.md:89-96` | register (owner-accepted exposure) |
| R4.8-13 | AC30, AC31 not met: Phase 8's offline and rollback halves are waived, not met | `docs/specs/phase-8-deploy-cutover.md:576-580`; `docs/plans/phase-8-human-steps.md:257,282-285` | register (D1) |

---

## R5 — Docs against code

Every command in `CLAUDE.md` and `README.md` still exists and parses; flags match. Checked with
`--help` (each CLI parses before it opens a DB connection), `bash -n` on the scripts, `pytest
--collect-only` on the fast tests (1154 collected), static reads otherwise. Nothing run against
production. The problems are stale wording and docs that describe code that was never built.

**Commands** — `setup.sh` (`bash -n` ok, matches), `check.sh` (13 steps, ok; wording stale, R5-01),
alembic paths (static, `db/alembic.ini:16`, revisions 0001–0011), fast pytest (1154 collected),
`capture --check`/`--write` (flags exist; prints DIFFERS on Windows, R5-18), uvicorn
(`app/main.py:279`), `import_v1 --help` (exact match), `keys create/list/revoke --help` (exact
match), `runs go-live --help` (match), `make_bundle.sh` (`bash -n`, needs a 40-hex sha),
`smoke.py` (static; `--wait-seconds` used by `deploy.yml:79` undocumented), `tests/image --image`
(static), `deploy` workflow (`workflow_dispatch`, required `sha`). `dev.ps1` exists, documented
nowhere (R5-17).

**Spot-checks** — about 50 claims across `docs/design/*`, ADRs 0001–0012 and `docs/runbooks/*`.
Holding: boot order, catch-up budget 30 s, lock-hold warning 50 ms, key format, export process,
heavy-read timeout, Render and venue deploy shape, standby, every `data-model.md` table except
`schema_compat`, the WS envelope and message set, polling fallback, bar timing constants, ADR
0003/0005/0006/0011/0012, every runbook. Not holding: R5-04…R5-08, R5-12, R5-14, R5-15.

| id | finding | evidence | proposed (C-task) |
|---|---|---|---|
| R5-01 | `CLAUDE.md` says CI "will" run `check.sh` (T11) — it does; its step list omits 4 of 13 steps | `CLAUDE.md:16-18`; `.github/workflows/ci.yml:101`; `scripts/check.sh:110-118` | fix (C8) |
| R5-02 | `README.md` "Status: Phase 8 … in progress" | `README.md:6-8` | fix (C8) |
| R5-03 | `README.md` says nothing reads `legacy/v1/`; golden scenarios and 9+ tests do | `README.md:45`; `tests/engine/golden/scenarios.py:42` | fix (C5) |
| R5-04 | `GET /api/history?since=&bucket=` documented, never built; Phase 3/4 specs defer it to Phase 7, which never mentions it | `docs/design/realtime-protocol.md:145-149`; `docs/specs/phase-3-api-realtime.md:299`; `docs/specs/phase-4-web-koers.md:216` | fix (doc → `/api/analytics/price-curve`, `app/api/analytics.py:136`) or backlog |
| R5-05 | ADR 0008 shows the old order body (`expected: [...]`); code takes `quote_version` + per-line `unit_price_cents` | `docs/adr/0008-honour-the-quoted-price.md:21-25`; `app/api/orders.py:30-48` | fix (addendum line) |
| R5-06 | ADR 0001 says background jobs incl. xlsx export are in-process asyncio; export builds in a spawned process since Phase 7 | `docs/adr/0001-setup-decision-record.md:22`; `app/jobs/export_xlsx.py:36-37,247` | fix (amendment note) |
| R5-07 | `data-model.md` lists no `schema_compat` (migration 0011) — the table rollback depends on | `docs/design/data-model.md:22-37`; `db/migrations/versions/0011_schema_compat.py:39-44` | fix |
| R5-08 | `frontend-architecture.md` layout lists `lib/` ws transport, `useElementSize`, `styles/tokens.css`, `theme/ThemeSection` — none exist there; omits `features/analytics`, `features/keys` | `docs/design/frontend-architecture.md:28-42` | fix |
| R5-09 | `docs/README.md` "Working on this" / "Status" describe the swarm and Phase 0 T1 | `docs/README.md:23-27,39-48` | fix (C3 + C8) |
| R5-10 | ADR 0009/0010 still "Status: Accepted" | `docs/adr/0009-autonomous-swarm-delivery.md:3`; `docs/adr/0010-the-swarm-owns-its-own-delivery-mechanics.md:3` | fix (C3, text is a hard stop) |
| R5-11 | **Swarm/orchestrator text in 6 `.claude` files C3 does not list** — C3's own "allowed `git grep swarm` hits" check would fail | `.claude/agents/phase-planner.md:11,20,26,93,95-113`; `plan-auditor.md:12,68,88,108`; `task-builder.md:3,23-25,65,73,83`; `task-verifier.md:13,29,49,58`; `.claude/commands/plan.md:33,56`; `.claude/commands/build.md:18` | fix (amend C3's scope; note `.claude/**` edits need the owner in auto mode) |
| R5-12 | `architecture.md` puts boot in `main.py`; it is `app/runtime/boot.py` | `docs/design/architecture.md:60`; `app/runtime/boot.py:180-268` | fix |
| R5-13 | Docs cite v1 as `exchange/engine.py:NNN`, which exists nowhere; lines resolve in `tests/engine/v1_reference/engine.py` | `docs/design/architecture.md:12,77-82,129,134,177-178,185` | accept (or one note line) |
| R5-14 | `realtime-protocol.md`: `market_event` omits `op`/`event_id`; backpressure says `asyncio.Queue`, code uses `deque` + `Event` and closes 1013 when still full | `docs/design/realtime-protocol.md:53,135-137`; `app/realtime/messages.py:179-185`; `app/realtime/hub.py:24-30,80-96` | fix |
| R5-15 | `frontend-architecture.md` contradicts itself on `react/no-danger` vs `no-restricted-syntax` | `docs/design/frontend-architecture.md:45-48,203-205` | fix |
| R5-16 | ADR 0004 "`DATABASE_URL` is the only difference" — `APP_ENV`, `TRUSTED_PROXY_IPS`, `EXPORT_DIR`, `SESSION_COOKIE_SECURE` differ too (ADR 0001's amendment carries it) | `docs/adr/0004-postgres-everywhere-offline-first.md:14-15` | accept |
| R5-17 | `dev.ps1` tracked but undocumented, while `README.md` says "There is no PowerShell equivalent and there will not be one" | `dev.ps1:1-8`; `README.md:12-13` | owner decides (C8) |
| R5-18 | `CLAUDE.md`'s golden command prints DIFFERS on Windows; `scripts/golden_linux.sh` unmentioned (= R2E-04) | `CLAUDE.md:22-23` | fix (C8) |
| R5-19 | `.claude/README.md` describes the swarm and points the hard-stop list at `commands/rebuild.md`, which C3 deletes — the hard-stop list needs a new home | `.claude/README.md:6-31,50,82,97-98` | fix (C3 + C8) |
| R5-20 | `/human` reads `docs/plans/phase-$1-human-steps.md`; only `phase-8-human-steps.md` exists (it stays, per D2) | `.claude/commands/human.md:8` | accept |
| R5-21 | `rebuild-route.md` swarm paragraph | `docs/plans/rebuild-route.md:67-79` | fix (C3, listed) |
| R5-22 | `ci.yml` comment cites `docs/plans/manual-checklist.md T12` | `.github/workflows/ci.yml:122` | fix (C4, listed) |
| R5-23 | Kept docs with false status: Phase 3 spec "Status: Draft"; `phase-8-human-steps.md` "Not started" | `docs/specs/phase-3-api-realtime.md:3`; `docs/plans/phase-8-human-steps.md:5` | fix |
| R5-24 | `/audit` names `infra/`, which does not exist (template text) | `.claude/commands/audit.md:30` | accept |

---

## R6 — Carried-over open items

| item | status | evidence | documented at |
|---|---|---|---|
| 1. `test_ws` `CancelledError` flake | **fixed** in `61f9f76` (2026-10-04, ancestor of `main`; verified): cleanup uses `asyncio.wait` and retrieves each task's exception instead of `gather` re-raising a child's cancellation | `app/realtime/ws.py:282-299`; regression test `tests/api/test_ws.py:140-159` (300 open/close cycles, `leaked == 0`) | still described as open in `docs/plans/rebuild-review-and-cleanup.md:83-84,152`, `docs/plans/phase-6-admin.md:1381`, `docs/plans/phase-7-analytics.md:855`, `docs/plans/phase-8-deploy-cutover.md:1008` |
| 2. T5 clock offset never shrinks | **still true**, by design | `app/runtime/clock.py:78-80` (`max`); raised at `app/runtime/ticker.py:196-206`, `app/runtime/boot.py:204`; pinned by `tests/unit/test_app_clock.py:44-55` | `docs/adr/0003-single-writer-owns-time.md:145-147` |
| 3. T6 dropped-lock fencing | **still true** for the standby path and the boot window; fast path well tested (`tests/integration/test_advisory_lock.py:63-100`, `test_boot.py:321-360`, `test_real_process.py:269-290`) | no test drops the lock after a standby boot (`app/runtime/boot.py:275-318`); watchdog starts at `boot.py:251-261`, after migrate `:193` and rehydrate `:200`; writes are not fenced, detection is a probe per tick (`app/db/advisory_lock.py:66-91`) | nowhere in the repo (out-of-repo memory only) |
| 4. T11 smoke traceback | **still true** | only `_poll` catches connection errors (`scripts/smoke.py:114`); steps 3–7 (`:133-160`) and `main` (`:184-188`) do not; a non-JSON 200 raises `AttributeError` (`:139-140,145,156`); untested | nowhere in the repo |
| 5. DB-clock columns | **still true**, except `run.ended_at` (app clock, `app/db/runs.py:587`) | DB `now()`: `market_event.ended_at` (`app/db/market_events.py:49,61` — `:61` in the same transaction as the app-clock `run.ended_at`), `news.deleted_at` (`app/db/news.py:69`), `drink.removed_at` (`app/db/runs.py:365`), `run.started_at` (`app/db/runs.py:554`); only nullness is read today | `docs/specs/phase-7-analytics.md:75-77` (`started_at` only) |
| 6. `/theme.css` 304 behind Cloudflare | **not reproducible** — a 304 was later observed; code unchanged | strong ETag + `no-cache`, exact-string `If-None-Match` (`app/api/theme.py:110-117`); tested `tests/api/test_theme.py:61-72` | raised and withdrawn: `docs/plans/phase-8-human-steps.md:150-152,189` |
| 7. per-request `correlation_id` | **still true** — never set; every log line carries `"-"` | `app/core/logging.py:32,54`; no middleware sets it (`app/main.py:254,256`) | deferred at `docs/plans/phase-3-api-realtime.md:822`, `docs/specs/phase-8-deploy-cutover.md:395-396`; required by `docs/way-of-working.md:837,839`; not in `docs/backlog.md` |
| 8. fresh-eyes verdict on #16 | **done in this review** — PASS with findings (below) | | |

| id | finding | evidence | proposed |
|---|---|---|---|
| R6-01 | `test_ws` flake is fixed but four plans and this plan's P2 note still call it open; progress ledger never recorded the fix | `61f9f76`; `docs/plans/rebuild-review-and-cleanup.md:83-84` | fix (docs) |
| R6-02 | Possible leftover WS cancellation race: `with suppress(CancelledError): await receiving` also swallows a cancellation aimed at the `talking` task, so `run()` may continue into `hub.connect`; hub close is a fire-and-forget `create_task` with a fixed `sleep(0)×3` — not reproduced | `app/realtime/ws.py:185-188,256-257,290,297-299`; `app/realtime/hub.py:103-111` | register (low) |
| R6-03 | ADR 0003 says the offset lasts "until the next restart"; after a back-step then a forward correction, stamps run ahead of real time, the ticker sees a forward gap, and a restart re-raises the offset from the stored future stamp | `docs/adr/0003-single-writer-owns-time.md:146-147`; `app/runtime/clock.py:80`; `app/runtime/ticker.py:181-184`; `app/runtime/boot.py:204` | register (correct ADR text; decide on shrinking) |
| R6-04 | Lost-lock detection untested after a standby boot, absent during migrate/rehydrate; writes not fenced by the lock (a commit can land up to one probe interval after loss). Phase 3 AC18 proven only for the fast path | `app/runtime/boot.py:192-200,251-261,275-318`; `app/db/advisory_lock.py:80-91`; `docs/specs/phase-3-api-realtime.md:390` | register (defect) + test for the standby path |
| R6-05 | `smoke.py` prints a traceback, not `FAIL <step>`, on a connection error after step 2, and `AttributeError` on a non-JSON 200 | `scripts/smoke.py:91-95,114,133-160,184-188` | fix (failing unit test first) |
| R6-06 | Two clocks in one transaction and one row (`run.ended_at` app clock vs `market_event.ended_at` DB `now()`; `end_event` row mixes `t_end_ms` app clock with `ended_at` DB clock); plus `news.deleted_at`, `drink.removed_at`, `run.started_at` | `app/db/runs.py:587,593`; `app/db/market_events.py:49,61`; `app/db/news.py:69`; `app/db/runs.py:365,554` | register / accept |
| R6-07 | Docstrings claim per-request correlation ids exist ("Phase 3 adds the middleware…"); never built, and now tracked nowhere | `app/core/logging.py:1-7,30-31`; `app/core/errors.py:9-11` | fix (docstrings) + backlog (feature) |
| R6-08 | `/theme.css` `If-None-Match` uses exact string comparison, not RFC weak comparison — always correct (falls back to 200) | `app/api/theme.py:115` | accept |
| R6-09 | Phase 8 T1–T11 review's open items (#3–#5 above, and plan T5 "10 ticks" vs test's `AFTER_STEP = 71`) exist only outside the repo | `docs/plans/phase-8-deploy-cutover.md:305-306`; `tests/integration/test_ticker.py:270-271` | register (this report is now their record) |

#### ce75f21 (#16) — fresh-eyes-reviewer verdict: **PASS with findings**, no correctness gaps

Sound: `DEFAULT_PARAMS` (`app/db/runs.py:57-69`) matches all 24 v1 `params` keys (11 differ from
`Params()`); the unit test compares with `Params.from_dict(v1 file)`, which rejects unknown keys
(`exchange/spec.py:63-66`). `Params` is frozen with tuple fields (`exchange/spec.py:31,46,49`).
The fallback is taken only on an empty `run` table (`latest_params`, `app/db/runs.py:427-434`,
spans every status; delete is hard); copy-first (`:461`) and the SD2 refusals (`:451-457`) are
unchanged. `tests/integration/test_runs.py:308,312` would fail on a regression to `Params()`. Ran
`tests/unit/test_default_params.py tests/engine`: 221 passed, 12 skipped (golden, Linux-only).

| id | finding | evidence | proposed |
|---|---|---|---|
| R6R-01 | `DEFAULT_PARAMS` idle_decay_minutes / idle_rise_minutes = 0.1, below SD8's server minimum 0.5 (`ParamsPatch`): a first run starts in a state the API cannot produce, and once changed it cannot be set back (422). `import_v1` already writes the same values | `app/db/runs.py:64,66`; `app/runtime/config.py:106,126-127`; `docs/specs/phase-6-admin.md:193` | register (owner: lower SD8's minimum to 0.1, or accept) |
| R6R-02 | Spec SD2 still says a first run starts from `Params()` defaults | `docs/specs/phase-6-admin.md:106-107` | register (amend SD2) |
| R6R-03 | `test_default_params` docstring says it "goes when legacy/v1/ does", contradicting C5's repoint; the constant's comment names the legacy path | `tests/unit/test_default_params.py:5,17`; `app/db/runs.py:55` | fix in C5 (repoint, reword) |

---

## R7 — Dead weight inventory

Method: stdlib `ast` name/attribute/import/string scan cross-checked with `git grep` for Python; a
small import resolver for `web/src`. No tool was added to the repo; nothing was changed.

#### 1. Tracked files nothing reads

| path | size | references | proposed |
|---|---|---|---|
| `app/.gitkeep`, `db/.gitkeep`, `tests/.gitkeep`, `web/src/features/.gitkeep` | 0 B each | none | C7 |
| `tests/engine/.gitkeep` | 0 B | only plans C4 deletes | C7 |
| `docs/plans/digests/README.md` (the directory's only file) | 10 lines | `.claude/README.md:31`; `.claude/commands/rebuild.md:19,246`; `docs/README.md:48`; `scripts/swarm.ps1:184`; this plan | C3 |
| `dev.ps1` | 94 lines | only a `.gitignore:60` comment | keep; document in C8 |

These are the only five `.gitkeep`s (`git ls-files '*.gitkeep'`).

#### 2. Python that nothing calls outside tests

Every route is mounted (`app/main.py:77-90,257-263`) and has a caller in `web/src`,
`scripts/smoke.py`, `deploy/venue/start.cmd` or `render.yaml:31`; every CLI module is a documented
`-m` entry point; no `__all__` under `app/`, `db/`, `scripts/`.

| path | size | references | proposed |
|---|---|---|---|
| `app/db/runs.py:287` `set_bar_price` | 9 lines | tests only (`tests/integration/test_runs.py:34,156-179`; `test_rehydrate.py:26,383`); stale docstring `app/db/runs.py:13` | C7 if approved (it pins Phase 2 AC12 in tests); fix the docstring either way |
| `app/api/security.py:188` `LoginLimiter.tracked_ips` | 3 lines | `tests/unit/test_security.py:156` | keep (test probe) |
| `app/db/models.py:411` `SchemaCompat` | 11 lines | no Python reader (boot uses raw SQL) | keep (puts the table in `Base.metadata` for the schema test) |
| `db/migrations/compat.py:34` `set_min_code_revision` | 10 lines | migration template + 1 test | keep (AC11 contract) |
| `app/api/news.py:50` `GET /api/news` | 6 lines | no web caller; tests | keep (Phase 3 SD26) |

#### 3. Web

| path | references | proposed |
|---|---|---|
| `web/src/features/exchange/model/selectors.ts:30,31,45` `selectPrice`, `selectBars`, `selectQuote` | none, not even tests | C7 |
| `web/src/lib/config.ts` (`config`, `isDev`) | imported by nothing; named by the lint rule that makes it the only env reader (`web/eslint.config.js:9,27,32,159`) | keep (AC3 slot) or C7 with its lint override |
| `SERVER_MESSAGE_TYPES` (`schemas.ts:187`) | drift test only | keep |
| ~50 exported `*Props`/constants used only in-file | — | accept |

**No unused `web/package.json` dependencies** (`@testing-library/dom` is a required peer of
`@testing-library/react@16`; `@types/*` via tsconfig; `prettier`, `openapi-typescript` via scripts).

#### 4. `.claude/` after D6

| item | remaining references after C3 | proposed |
|---|---|---|
| `.claude/commands/rebuild.md` (329 lines) | `.claude/README.md:14,50,98`; `docs/plans/rebuild-route.md:69,83` | C3 — **but it holds the only live hard-stop list (`:175-199`); move it first** (R7-01) |
| `.claude/agents/task-builder.md` (101), `task-verifier.md` (58) | nothing dispatches them once `/rebuild` goes | C3 or keep (owner) |
| `phase-planner`, `plan-auditor`, `spec-interviewer`, `fresh-eyes-reviewer`, `engine-guardian`, `codebase-analyst` | used by `/plan`, `/build`, `/spec`, `/review`, `/analyse` | keep (swarm text in them → C3, see R5-11) |
| `.claude/settings.json:23-35,39,43` (push, rebase, `merge --squash`, worktree, `gh pr create/merge`) | served the autonomous loop; `/build` now never pushes or merges (`.claude/commands/build.md:49`) | C3, owner approval (`.claude/**` edits are refused in auto mode) |

#### 5. What D5 would remove

| item | lines | non-test callers |
|---|---|---|
| `app/cli/import_v1.py` | 95 | none in `app/`; **but it is how 4 harnesses seed a run** (`tests/integration/durability/harness.py:49,122`, `tests/integration/realapp/harness.py:71`, `tests/image/test_kill_drill.py:41`, `tests/image/test_venue.py:243`) and the venue runbook's seed step (`docs/runbooks/venue.md:21-22`) |
| `app/cli/v1_files.py` | 212 | only `import_v1.py:26` |
| `tests/integration/test_import_v1.py` | 318 | — |
| `tests/unit/test_v1_files.py` | 236 | — |
| "v1 key import (Phase 8 T9)" | **no production code exists** — T9 is two guard tests (`tests/api/test_v1_keys.py` 80, `tests/meta/test_no_v1_key_import.py` 161) proving v1 keys get 401 | keep: they pin D-42 / AC32 |

Straight deletion: 861 lines plus 2 in `CLAUDE.md` and 2 in the runbook — but the four harnesses and
the venue seed procedure would need another path (`create_run` or `POST /api/runs`; the Phase 6 UI
covers the venue). If C6 removed the import, C5's `tests/fixtures/v1/` drops `static/news.json` and
keeps three files; `tests/meta/test_no_file_io.py:18-19,126` could stop exempting all of `app/cli/`.

#### 6. Untracked local weight (disk)

| item | size | regenerate |
|---|---|---|
| `bundle/` | 376 MB | `bash scripts/make_bundle.sh <sha>` |
| `../bb-gate` (registered worktree, detached at `c4dfe4c`) | 465 MB | `git worktree add` |
| `../borrelbeurs-v2-gate` (not a repo or worktree; a stray `web/` copy) | 208 MB | not needed |
| `web/node_modules` / `.venv` | 228 MB / 204 MB | `pnpm install` / `uv sync` |
| `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `web/dist`, `web/test-results`, 26 `__pycache__` | ~28 MB | next `check.sh` |
| `.swarm-logs/` (20 files), `.dev/*.log` | 105 KB, 17 KB | not needed / `./dev.ps1 up` |
| Docker `bierbeurs:latest` (v1's image) | 1.65 GB | v1 is suspended |
| Docker `borrelbeurs:local`, `ghcr.io/…:1cb111f…`, `:e23835e…` | 347 MB each (shared layers) | build / pull |
| Docker `docker:29-dind` 462 MB, `aquasec/trivy:0.75.0`+`latest` 260 MB, `rhysd/actionlint` 102 MB, `dockerignore-probe` 7 MB | | pull on demand |
| keep: `postgres:16-alpine`, `python:3.11-slim`, `node:22-slim`; ignore every `mvr-intake-*` (another project) | | |

`git clean -ndX` lists 38 entries — **including `.env.local` and `.claude/settings.local.json`**
(R7-08). 113 local and 44 remote branches.

#### 7. Branches — P1's merge-tree test

116 pass (81 local, 35 remote); 41 fail (32 local, 9 remote). Failing, by kind:
- **not on `main`:** `origin/feature/phase-0-t12-repo-governance` (`ff74f4d`, R4.0-01 / R7-05);
  `docs/review-cleanup-decisions` (`77752ad`, this review's D1–D7, unmerged by design).
- **on `main` by squash, then amended there** (false FAILs): 20 `feature/phase-8-t1…t21` branches,
  `fix/golden-linux-pin`, `fix/phase-8-review-t12-t21`, `feature/phase-8-t23-…`, `…-t24-…`,
  `backup/t24-pre-rebase`, `docs/phase-8-amendment-a2`, `docs/phase-8-h1-step6-notes`,
  `origin/fix/phase-7-review` (+ their `origin/` copies).
- **superseded:** `docs/phase-8-h1-done-h2-deferred`, `docs/phase-8-plan`, `docs/phase-4-plan`,
  `origin/feature/phase-1-t10-defect-records`.

| id | finding | evidence | proposed |
|---|---|---|---|
| R7-01 | The only live hard-stop list is in `rebuild.md`, which C3 deletes; the other copy is in ADR 0009, which C3 supersedes | `.claude/commands/rebuild.md:175-199`; `docs/adr/0009-autonomous-swarm-delivery.md:78` | fix in C3 (move the list, e.g. into CLAUDE.md "Never", first) |
| R7-02 | D5's "v1 key import (T9)" is a misnomer: T9 is two guard tests, no import code | `tests/api/test_v1_keys.py`; `tests/meta/test_no_v1_key_import.py` | keep |
| R7-03 | `import_v1` seeds runs for 4 harnesses and the venue runbook — removing it is a rewrite, not a deletion | as in §5 | owner (D5) |
| R7-04 | P1's merge-tree test reports false FAILs for squash-merged branches that `main` later amended, so C1 as written deletes none of ~40 stale branches | 32 local + 9 remote FAILs | fix C1's method (add a PR/subject mapping; owner confirms the list) |
| R7-05 | = R4.0-01 (T12 governance not on `main`; ADR 0012 collision) | `ff74f4d` | see R4.0-01 |
| R7-06 | = R5-03 (README says nothing reads `legacy/v1/`) | `README.md:45` | C5 |
| R7-07 | `runs.py` docstring: `set_bar_price` is "the only drink write" — it has no production caller and is not the only write | `app/db/runs.py:13-14`; writes at `:267,365,370,534` | fix (or C7 with `set_bar_price`) |
| R7-08 | The denylist blocks `git clean -fdx`, but `git clean -fdX` would delete `.env.local` and `.claude/settings.local.json` | `.claude/settings.json:122`; `git clean -ndX` | C2: remove only named paths, never a bulk clean |
| R7-09 | Unused selectors | `web/src/features/exchange/model/selectors.ts:30,31,45` | C7 |
| R7-10 | `web/src/lib/config.ts` imported by nothing | `web/src/lib/config.ts:13-15` | accept or C7 |
| R7-11 | `task-builder` and `task-verifier` agents orphaned once `/rebuild` goes | `.claude/agents/task-builder.md`, `task-verifier.md` | C3 or keep |
| R7-12 | Swarm-era permissions in `.claude/settings.json` | `.claude/settings.json:23-35,39,43` | C3 (owner) |
| R7-13 | Stray `../borrelbeurs-v2-gate` (208 MB) and `../bb-gate` worktree (465 MB) | `git worktree list` | C1/C2 |
| R7-14 | v1 image `bierbeurs:latest` 1.65 GB + one-off tool images | `docker image ls` | C2 (owner names them) |
| R7-15 | Five `.gitkeep`s and `docs/plans/digests/` | §1 | C7 / C3 |
| R7-16 | `dev.ps1` undocumented (= R5-17) | `.gitignore:60` | C8 |
| R7-17 | `test_no_file_io` exempts all of `app/cli/` for `v1_files` | `tests/meta/test_no_file_io.py:18-19,126` | C6 (narrow it if D5 removes the import) |

---

## Triage table

One line per finding; evidence is in its section above. Duplicates point to one id. The owner
fills in **Decision**: fix (becomes a task in amendment A1), register (defect-register entry),
backlog (a `B-nn` via `/backlog`), accept, or a C-task. Register and backlog entries are written in
the same commit as the triaged report.

### Proposed: fix

| id | finding (short) | where it lands | Decision |
|---|---|---|---|
| R4.6-02 = R6R-01 | `DEFAULT_PARAMS` idle minutes 0.1 below SD8's 0.5 floor | owner picks the direction | |
| R6R-02 = R4.6-01 | SD2 still says a first run starts from `Params()` | spec amendment | |
| R4.0-01 = R7-05 | Phase 0 T12 governance not on `main`; ADR 0012 collision | A1 | |
| R1-01 | weekly full-history secret scan red | A1 | |
| R4.8-01 = R1-05 | previous-image boot drill always skipped in CI | A1 | |
| R4.8-02 | push-from-`main`-only and full-SHA tag pinned by no test | A1 | |
| R4.8-04 | "SBOM written either way" comment is false | A1 | |
| R2-10 | offline e2e never loads `/bar`/`/manipulation`; WS not intercepted | A1 | |
| R4.4-10 | `vitest --passWithNoTests` keeps the gate green with no tests | A1 | |
| R3-04 | file-I/O meta test misses `app/api`, `app/realtime` | A1 | |
| R3-05 | D-18 test checks `version` only, not `rng_counter` | A1 | |
| R3-07 | D-18 test and route cite D-06 | A1 | |
| R3-08 | docstrings describe a dedupe that does not exist | A1 | |
| R4.0-07 | hygiene detector test cannot fail | A1 | |
| R4.3-01 | CSRF Origin check untested for DELETE/PATCH | A1 | |
| R4.3-03 | AC18d "at most one tick lost" never asserted | A1 | |
| R4.3-04 | AC18e sub-assertion cannot fail | A1 | |
| R4.3-06 | key-length lower bound untested; mislabelled param id | A1 | |
| R4.4-07 | AC29 test never exercises the production `key={id}` | A1 | |
| R4.5-01 | bar timing constants never pinned by value | A1 | |
| R4.5-02 | 8 s order request timeout not pinned | A1 | |
| R4.5-03 | AC16 "pending tap" tests make no tap | A1 (or accept) | |
| R4.5-05 | AC19 Σ qty never compared with the DB | A1 | |
| R4.5-06 | AC28 admin-sees-pad never exercised | A1 | |
| R4.6-04 | `DRAINING_WRITES` hand list misses a route; no completeness check | A1 | |
| R4.7-02 | AC3 "within 2 s" never asserted | A1 | |
| R4.7-03 | AC4 "appears in the final export" unchecked under the race | A1 | |
| R6-05 | `smoke.py` traceback instead of `FAIL <step>` | A1 | |
| R6-07 | docstrings claim correlation ids exist (feature: backlog) | A1 + backlog | |
| R7-07 | `runs.py` docstring: `set_bar_price` "the only drink write" | A1 or C7 | |
| R6-01 | `test_ws` flake fixed but still described as open (this plan's P2 note) | plan text | |
| R1-08 | route table row 8 shows no waiver; `phase-8-human-steps.md` "Not started" | docs (both files stay) | |
| R5-23 | Phase 3 spec header still "Draft" | docs | |
| R4.1-01 | Phase 1 AC10 text superseded by 2026-10-01 decisions | spec amendment | |
| R4.2-01 | Phase 2 AC6 text never amended to PD1 | spec amendment | |
| R5-04 | `GET /api/history` documented, never built | design doc | |
| R5-05 | ADR 0008 shows the old order body | ADR addendum | |
| R5-06 | ADR 0001: export "in-process"; it is a separate process | ADR amendment | |
| R5-07 | `data-model.md` lacks `schema_compat` | design doc | |
| R5-08 | `frontend-architecture.md` layout lists files that do not exist | design doc | |
| R5-12 | `architecture.md` puts boot in `main.py` | design doc | |
| R5-14 | `realtime-protocol.md` `market_event` fields / backpressure mechanism | design doc | |
| R5-15 | `frontend-architecture.md` contradicts itself on `react/no-danger` | design doc | |
| R2E-04 = R5-18 | `CLAUDE.md` golden command DIFFERS on Windows; `golden_linux.sh` unmentioned | C8 | |
| R5-01, R5-02, R5-09, R5-19 | stale `CLAUDE.md`/`README.md`/`docs/README.md`/`.claude/README.md` text | C8 (+C3) | |
| R5-10, R5-21 | ADR 0009/0010 status; route swarm paragraph | C3 | |
| R5-22 | `ci.yml` comment cites `manual-checklist.md` | C4 | |
| R5-03 = R7-06 | README says nothing reads `legacy/v1/` | C5 | |
| R6R-03 = R2E-08 = R4.6-03 | `test_default_params` must be repointed, not deleted | C5 | |
| R1-06 | checklist ticks Phase 8 items the records call waived | this report is the record; checklist goes in C4 | |

### Proposed: register

| id | finding (short) | Decision |
|---|---|---|
| P2-01 | `test_heavy_reads` seed times out under load | |
| R2E-03 = R1-03 = R4.0-04 = R4.1-03 = R4.6-09 | golden tests skip silently off Linux | |
| R4.0-02 | merge commits pushed straight to `main` | |
| R4.0-03 | required check may be named `docker` (renamed `image`) | |
| R4.0-09 | AC7 push-protection evidence never kept | |
| R2-01 | float euro values stored outside money columns; reword the invariant | |
| R2-06 | state-lock rule enforced by review only | |
| R2-08 | go-live holds the state lock across a full rehydrate, unbounded | |
| R6-02 | possible leftover WS cancellation race (not reproduced) | |
| R6-03 | ADR 0003 understates the clock offset's cost | |
| R6-04 | lost lock undetected after a standby boot and during migrate/rehydrate; writes not fenced | |
| R6-06 | two clocks in one transaction and one row | |
| R6-09 | Phase 8 T1–T11 review items existed only outside the repo (now recorded here) | |
| R3-01 | register's D-42 row says v1 keys were rotated; they were not | |
| R3-03 | register has no status column (R3's table can be it) | |
| R3-06 | D-40: venue cookie not `Secure` by design, unrecorded | |
| R4.2-04 | `export.total_cents` breaks Phase 2 AC11's letter | |
| R4.3-05 | Phase 3 AC18(a) superseded by Phase 8 standby; spec unannotated | |
| R4.5-04 | AC17 lint is a name heuristic | |
| R4.5-09 | SD16 drift: open-bucket orders plot at the bucket end | |
| R4.6-07 | Phase 6 manual exit records nothing of its steps | |
| R4.8-09 | AC29 Render half partly evidenced (F-H1-3: ~60 s of 503 on orders) | |
| R4.8-12 | v1 service suspended, keys valid again if resumed | |
| R4.8-13 | Phase 8 AC30, AC31 waived, not met | |
| R1-02 | nothing automated runs `setup.sh`; it never builds `web/dist` | |

### Proposed: backlog

| id | finding (short) | Decision |
|---|---|---|
| R2-02 | money detector blind to `json`/`jsonb`/`ARRAY` | |
| R2-03 | route audit trusts a hand-settable marker | |
| R2-09 | built-asset scanner misses WS, beacon, XHR, EventSource, svg | |
| R2-12 | no test moves the market between quote and order | |
| R2E-01 | engine import ban covers 8 names only; builtin `open()` passes | |
| R2E-02 | numpy allowed wholesale (global RNG, `np.load`) | |
| R2E-07 | golden replay bypasses the app's spec and slot mapping | |
| R3-02 | v1 key rotation tracked in no backlog entry | |
| R4.0-05 | no test pins `ci.yml`'s shape | |
| R4.0-06 | image check has no uploads/earnings rule | |
| R4.1-04 | AC4 idle case lacks an anti-vacuity check | |
| R4.2-03 | nothing pins `engine_state` columns as `json` | |
| R4.2-06 | durability test hardcodes a statement count | |
| R4.2-07 | rehydrate "write nothing" snapshot is partial | |
| R4.2-08 | AC19 on the real v1 files leaves halves untested | |
| R4.3-02 | AC3 "before accept" cannot fail under TestClient | |
| R4.3-07 = R4.6-08 | AC tags have no phase prefix | |
| R4.3-09 | AC22 backpressure test bypasses the ticker | |
| R4.4-03 | AC11 grid colour unasserted | |
| R4.4-04 | storage lint misses `globalThis.`/`self.` | |
| R4.4-06 | AC26 colour tokens unasserted | |
| R4.4-09 | AC37 compares `p_q` only | |
| R4.5-07 | Phase 5 manual check (two phones, AP pull) unrecorded; fold into H2 | |
| R4.6-05 | AC25 "within 2 s" unasserted | |
| R4.7-01 | AC1 one-transaction close has no fault test | |
| R4.7-05 | analytics reads never tested while draining | |
| R4.7-06 | per-run table list hand-written twice | |
| R4.7-08 | export's heavy engine unproven by the listener | |
| R4.8-03 | CI image-job steps pinned by no test | |
| R4.8-05 | venue dump check weak | |
| R4.8-11 | "no tick in standby" vacuous without a live run | |

### Proposed: accept

R1-04, R1-07, R1-10, R2-05, R2-07 (+ reword the invariant), R2-11, R2-13, R2E-05, R2E-06, R3-09,
R3-10, R4.0-08, R4.0-10, R4.1-02 (+ spec note), R4.2-02, R4.2-05, R4.3-08, R4.4-01, R4.4-02,
R4.4-05, R4.4-08, R4.5-08, R4.6-06, R4.6-10, R4.7-04, R4.7-07, R4.7-09, R4.8-06, R4.8-07, R4.8-08,
R4.8-10, R5-13, R5-16, R5-20, R5-24, R6-08, R7-02 (keep the T9 guard tests).

| Decision on the accept list (or ids to move) | |
|---|---|

### Owner decides

| id | question | Decision |
|---|---|---|
| R2-04 | Should the `display` role (venue TV) receive revenue and order totals? | |
| R5-17 = R7-16 | `dev.ps1`: document it, or remove it (README says there is no PowerShell equivalent)? | |
| R7-03 (D5) | Remove `import_v1` + `v1_files` (861 lines, plus reseeding 4 harnesses and the venue runbook), or keep? | |
| R7-10 | `web/src/lib/config.ts` (imported by nothing; the lint-designated env reader): keep or C7? | |
| R7-11 | `task-builder` / `task-verifier` agents: keep for manual dispatch, or remove in C3? | |
| R7-12 | Swarm-era permissions in `.claude/settings.json`: remove in C3? | |

### Clean-up plan amendments (before `/audit`)

| id | change | Decision |
|---|---|---|
| R7-01 | C3: move the hard-stop list (e.g. into `CLAUDE.md` "Never") before deleting `rebuild.md` | |
| R5-11 | C3: add the six `.claude/` files with swarm text to its scope | |
| R7-04 | C1: add a PR/subject mapping to the merge-tree test; owner confirms the list | |
| R7-08 | C2: remove named paths only; never `git clean -X` | |
| R2E-09 | C5: gate on `golden_linux.sh` or CI; repointing `scenarios.py` fixes 11 modules at once | |
| R1-09 | C5: Phase 1 and 2 exit proofs read `legacy/v1/` directly (already in C5's list) | |
| R7-13, R7-14 | C1/C2: add `../borrelbeurs-v2-gate` (208 MB), `bierbeurs:latest` (1.65 GB) to the owner's list | |
| R7-09, R7-15 | C7: three unused selectors; five `.gitkeep`s (digests go in C3) | |
| R7-17 | C6: narrow `test_no_file_io`'s `app/cli/` exemption if D5 removes the import | |

---

## Appendix A — P2 gate output

Verbatim from `main` at `74a7e71`, terminal colour codes stripped.

### Run 1 — `./scripts/check.sh`

<details><summary>Run 1: FAILED at step 12/13</summary>

```text

==> [1/13] ruff format --check
332 files already formatted

==> [2/13] ruff check
All checks passed!

==> [3/13] web format:check

> web@0.0.0 format:check C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> prettier --check .

Checking formatting...
All matched files use Prettier code style!

==> [4/13] web lint

> web@0.0.0 lint C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> eslint .

[boundaries][warning]: Rule "boundaries/entry-point" is deprecated and will be removed in future versions.
  Please migrate to the "boundaries/dependencies" rule with appropriate selectors. More info: https://www.jsboundaries.dev/docs/rules/entry-point/#migration-to-boundariesdependencies


==> [5/13] mypy app db exchange tests
Success: no issues found in 255 source files

==> [6/13] web tsc -b

==> [7/13] web api types drift
✨ openapi-typescript 7.13.0
🚀 C:\Users\MARTIJ~1\AppData\Local\Temp\bb-openapi-1optuw4x.json → src/api/generated/schema.d.ts [114.1ms]

==> [8/13] web build

> web@0.0.0 build C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> tsc -b && vite build

vite v8.3.1 building client environment for production...
transforming...

/theme.css doesn't exist at build time, it will remain unchanged to be resolved at runtime
✓ 332 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                            0.54 kB │ gzip:   0.34 kB
dist/assets/inter-latin-400-normal-C38fXH4l.woff2         23.66 kB
dist/assets/eb-garamond-latin-400-normal-BCNrxLz_.woff2   23.82 kB
dist/assets/inter-latin-800-normal-BYj_oED-.woff2         24.40 kB
dist/assets/inter-latin-600-normal-LgqL8muc.woff2         24.45 kB
dist/assets/eb-garamond-latin-500-normal-DehAIUv0.woff2   25.26 kB
dist/assets/eb-garamond-latin-700-normal-D7LhwqnD.woff2   25.29 kB
dist/assets/eb-garamond-latin-600-normal-DHwxsLHv.woff2   25.34 kB
dist/assets/eb-garamond-latin-400-normal-maQnHeKB.woff    28.60 kB
dist/assets/eb-garamond-latin-700-normal-DcHu0PDI.woff    30.10 kB
dist/assets/eb-garamond-latin-500-normal-DZU8xF9o.woff    30.20 kB
dist/assets/eb-garamond-latin-600-normal-xCe6GkOx.woff    30.40 kB
dist/assets/inter-latin-400-normal-CyCys3Eg.woff          30.69 kB
dist/assets/inter-latin-600-normal-CiBQ2DWP.woff          31.26 kB
dist/assets/inter-latin-800-normal-D1mf63XC.woff          31.29 kB
dist/assets/logo-D76si8Zt.png                             63.76 kB
dist/assets/index-CjciWAmm.css                            21.08 kB │ gzip:   4.82 kB
dist/assets/index-CSGAbELF.js                            623.37 kB │ gzip: 192.54 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 636ms

==> [9/13] built output references
check_built_assets: no non-origin references in web\dist

==> [10/13] pytest tests/unit tests/meta tests/engine
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 668 items

tests\unit\test_app_clock.py ........                                    [  1%]
tests\unit\test_app_shell.py .....................                       [  4%]
tests\unit\test_candles.py ..................                            [  7%]
tests\unit\test_check_built_assets.py ................................   [ 11%]
tests\unit\test_check_image.py ............................              [ 16%]
tests\unit\test_codec.py ..............                                  [ 18%]
tests\unit\test_config.py .............................................. [ 25%]
...............                                                          [ 27%]
tests\unit\test_default_params.py ..                                     [ 27%]
tests\unit\test_earnings.py .....                                        [ 28%]
tests\unit\test_errors.py ...                                            [ 28%]
tests\unit\test_fake_clock.py ..........                                 [ 30%]
tests\unit\test_gap.py .....................                             [ 33%]
tests\unit\test_grace.py .............................................   [ 40%]
tests\unit\test_history_ring.py .............                            [ 42%]
tests\unit\test_hostdir.py ........                                      [ 43%]
tests\unit\test_hub.py ...............                                   [ 45%]
tests\unit\test_images.py .............                                  [ 47%]
tests\unit\test_key_format.py .........................                  [ 51%]
tests\unit\test_logging.py ....                                          [ 51%]
tests\unit\test_mapping.py .......                                       [ 52%]
tests\unit\test_market_events.py ...........                             [ 54%]
tests\unit\test_messages.py ............................................ [ 61%]
...                                                                      [ 61%]
tests\unit\test_migrate_cancel.py .                                      [ 61%]
tests\unit\test_publish.py ............                                  [ 63%]
tests\unit\test_schema_compat.py .........                               [ 64%]
tests\unit\test_security.py ........................................     [ 70%]
tests\unit\test_smoke_etag.py .......                                    [ 71%]
tests\unit\test_smoke_health.py .........                                [ 73%]
tests\unit\test_theme_manifest.py ...................................... [ 78%]
........................................................................ [ 89%]
.......................                                                  [ 93%]
tests\unit\test_v1_files.py ............................................ [ 99%]
..                                                                       [100%]

============================== warnings summary ===============================
<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 668 passed, 1 warning in 9.98s ========================
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 255 items

tests\meta\test_clock_seam.py ..............                             [  5%]
tests\meta\test_compose_matches_env_example.py .......                   [  8%]
tests\meta\test_config_boundary.py .............................         [ 19%]
tests\meta\test_dockerfile.py .....                                      [ 21%]
tests\meta\test_guard_migrations_hook.py ..........................      [ 31%]
tests\meta\test_import_side_effects.py ................................. [ 44%]
                                                                         [ 44%]
tests\meta\test_migration_scaffolding.py .....                           [ 46%]
tests\meta\test_no_file_io.py ......................                     [ 55%]
tests\meta\test_no_latest.py ................                            [ 61%]
tests\meta\test_no_p0_totals.py .......                                  [ 64%]
tests\meta\test_no_v1_key_import.py ......                               [ 66%]
tests\meta\test_render_blueprint.py ......................               [ 75%]
tests\meta\test_repo_hygiene.py .......................                  [ 84%]
tests\meta\test_route_authorization.py ....                              [ 85%]
tests\meta\test_schema_compat_coverage.py .......                        [ 88%]
tests\meta\test_trivyignore.py ......                                    [ 90%]
tests\meta\test_venue_stack.py .......................                   [100%]

============================== warnings summary ===============================
<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 255 passed, 1 warning in 7.17s ========================
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 231 items

tests\engine\test_advance.py ......................                      [  9%]
tests\engine\test_golden_capture.py ..ssssss....................         [ 21%]
tests\engine\test_golden_replay.py ssssss..                              [ 25%]
tests\engine\test_lifecycle_helpers.py ......                            [ 27%]
tests\engine\test_mask.py .....................                          [ 36%]
tests\engine\test_numeric_pin.py .                                       [ 37%]
tests\engine\test_pricing.py ........                                    [ 40%]
tests\engine\test_properties.py ....                                     [ 42%]
tests\engine\test_purity.py ..........................                   [ 53%]
tests\engine\test_spec.py ....................................           [ 69%]
tests\engine\test_state.py ...........                                   [ 74%]
tests\engine\test_steps_idle_brownian.py ...............                 [ 80%]
tests\engine\test_steps_jumps.py .....................                   [ 89%]
tests\engine\test_steps_orders.py ........................               [100%]

=========================== short test summary info ===========================
SKIPPED [6] tests\engine\test_golden_capture.py:52: the golden numbers are captured on Linux; run scripts/golden_linux.sh
SKIPPED [6] tests\engine\test_golden_replay.py:47: the golden numbers are captured on Linux; run scripts/golden_linux.sh
====================== 219 passed, 12 skipped in 16.33s =======================

==> [11/13] web test

> web@0.0.0 test C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> vitest --passWithNoTests "--run"


 RUN  v5.0.2 C:/Users/MartijnBoot/Documents/GitHub-Personal/borrelbeurs-v2/web


 Test Files  58 passed (58)
      Tests  605 passed (605)
   Start at  11:55:32
   Duration  42.54s (environment 64%, import 22%, tests 11%, transform 3%)

    Isolate  58 workers spawned · ~7.16s startup each (spawn + environment, per file)
             at least ~20.52s faster with isolate: false — reuses workers across files instead of one per file


==> [12/13] pytest tests/integration tests/api
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 387 items

tests\integration\test_advisory_lock.py .....                            [  1%]
tests\integration\test_analytics_compare.py ........                     [  3%]
tests\integration\test_analytics_runs.py ........                        [  5%]
tests\integration\test_bar_price_snapshot.py ..                          [  5%]
tests\integration\test_boot.py ...................                       [ 10%]
tests\integration\test_cli_keys.py ........                              [ 12%]
tests\integration\test_cli_runs.py ......                                [ 14%]
tests\integration\test_close_in_process.py ....                          [ 15%]
tests\integration\test_config_draft.py ...                               [ 16%]
tests\integration\test_config_live.py ........                           [ 18%]
tests\integration\test_db_restart.py .                                   [ 18%]
tests\integration\test_delete_run.py ......                              [ 20%]
tests\integration\test_drink_lifecycle.py ..........                     [ 22%]
tests\integration\test_durability.py .......                             [ 24%]
tests\integration\test_earnings_series.py ......                         [ 26%]
tests\integration\test_engine_state.py ............                      [ 29%]
tests\integration\test_export_hostdir.py ........                        [ 31%]
tests\integration\test_export_queue.py .......                           [ 33%]
tests\integration\test_export_timing.py .                                [ 33%]
tests\integration\test_export_workbook.py ........                       [ 35%]
tests\integration\test_export_worker.py .......                          [ 37%]
tests\integration\test_go_live_in_process.py .....                       [ 38%]
tests\integration\test_handover.py ..                                    [ 39%]
tests\integration\test_health.py .....                                   [ 40%]
tests\integration\test_heavy_reads.py F                                  [ 40%]
tests\integration\test_holder.py ...............                         [ 44%]
tests\integration\test_import_v1.py ........                             [ 46%]
tests\integration\test_manipulation.py ..........                        [ 49%]
tests\integration\test_market_events_repo.py ......                      [ 50%]
tests\integration\test_migrations.py .................                   [ 55%]
tests\integration\test_news.py ........                                  [ 57%]
tests\integration\test_order_concurrency.py .                            [ 57%]
tests\integration\test_orders.py .............                           [ 60%]
tests\integration\test_place_order.py ..........................         [ 67%]
tests\integration\test_products.py ....                                  [ 68%]
tests\integration\test_proxy_keying.py ..                                [ 68%]
tests\integration\test_real_process.py ....                              [ 70%]
tests\integration\test_rehydrate.py ...............                      [ 73%]
tests\integration\test_restart_replay.py .                               [ 74%]
tests\integration\test_runs.py .................                         [ 78%]
tests\integration\test_schema.py ....................................... [ 88%]
.............                                                            [ 91%]
tests\integration\test_smoke_script.py .....                             [ 93%]
tests\integration\test_stamp_monotonic.py .                              [ 93%]
tests\integration\test_theme_repo.py .......                             [ 95%]
tests\integration\test_ticker.py ..................                      [100%]

================================== FAILURES ===================================
________ test_every_heavy_read_is_fast_enough_and_off_the_live_engine _________

on = 'postgresql+asyncpg://borrelbeurs:borrelbeurs@127.0.0.1:5432/bb_test_de6a54514d70'
settings = Settings(port=8000, log_level='INFO', app_env='local', login_rate_per_minute=10, session_cookie_secure=True, database_timeout_seconds=5.0, heavy_read_timeout_seconds=60.0, build_sha='unknown', trusted_proxy_ips='', export_dir=None)

    def test_every_heavy_read_is_fast_enough_and_off_the_live_engine(
        on: str, settings: Settings
    ) -> None:
        """AC31."""
        scoped = settings.model_copy(update={"database_url": on})
        assert scoped.heavy_read_timeout_seconds == 60.0  # the default, not raised for the test
        timings: dict[str, float] = {}
    
        async def seed_and_build() -> tuple[int, int, str, int, int]:
            engine, heavy = create_engine(scoped), create_heavy_read_engine(scoped)
            try:
                began = time.perf_counter()
                async with engine.begin() as conn:
                    run_id, product, key = await _seed(conn)
                timings["seed"] = time.perf_counter() - began
                async with heavy.connect() as conn:
                    began = time.perf_counter()
                    snapshot = await read_snapshot(conn, run_id)
                    timings["read_snapshot"] = time.perf_counter() - began
                began = time.perf_counter()
                data = await asyncio.to_thread(build_workbook, snapshot, generated_at_ms=T0)
                timings["build_workbook"] = time.perf_counter() - began
                return run_id, product, key, snapshot.line_count, len(data)
            finally:
                await engine.dispose()
                await heavy.dispose()
    
>       run_id, product, key, line_count, size = asyncio.run(seed_and_build())
                                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\integration\test_heavy_reads.py:173: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:190: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\asyncio\base_events.py:654: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
tests\integration\test_heavy_reads.py:159: in seed_and_build
    run_id, product, key = await _seed(conn)
                           ^^^^^^^^^^^^^^^^^
tests\integration\test_heavy_reads.py:109: in _seed
    await conn.execute(
.venv\Lib\site-packages\sqlalchemy\ext\asyncio\engine.py:668: in execute
    result = await greenlet_spawn(
.venv\Lib\site-packages\sqlalchemy\util\concurrency.py:212: in greenlet_spawn
    result = context.switch(value)
             ^^^^^^^^^^^^^^^^^^^^^
.venv\Lib\site-packages\sqlalchemy\engine\base.py:1448: in execute
    return meth(
.venv\Lib\site-packages\sqlalchemy\sql\elements.py:533: in _execute_on_connection
    return connection._execute_clauseelement(
.venv\Lib\site-packages\sqlalchemy\engine\base.py:1668: in _execute_clauseelement
    ret = self._execute_context(
.venv\Lib\site-packages\sqlalchemy\engine\base.py:1822: in _execute_context
    return self._exec_single_context(
.venv\Lib\site-packages\sqlalchemy\engine\base.py:1962: in _exec_single_context
    self._handle_dbapi_exception(
.venv\Lib\site-packages\sqlalchemy\engine\base.py:2335: in _handle_dbapi_exception
    raise exc_info[1].with_traceback(exc_info[2])
.venv\Lib\site-packages\sqlalchemy\engine\base.py:1943: in _exec_single_context
    self.dialect.do_execute(
.venv\Lib\site-packages\sqlalchemy\engine\default.py:1180: in do_execute
    cursor.execute(statement, parameters)
.venv\Lib\site-packages\sqlalchemy\dialects\postgresql\asyncpg.py:656: in execute
    await_(self._prepare_and_execute(operation, parameters))
.venv\Lib\site-packages\sqlalchemy\util\concurrency.py:167: in await_
    return current.parent.switch(awaitable)  # type: ignore[no-any-return]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv\Lib\site-packages\sqlalchemy\util\concurrency.py:205: in greenlet_spawn
    value = await result
            ^^^^^^^^^^^^
.venv\Lib\site-packages\sqlalchemy\dialects\postgresql\asyncpg.py:618: in _prepare_and_execute
    self._handle_exception(error)
.venv\Lib\site-packages\sqlalchemy\dialects\postgresql\asyncpg.py:568: in _handle_exception
    self._adapt_connection._handle_exception(error)
.venv\Lib\site-packages\sqlalchemy\dialects\postgresql\asyncpg.py:847: in _handle_exception
    super()._handle_exception(error)
.venv\Lib\site-packages\sqlalchemy\connectors\asyncio.py:412: in _handle_exception
    self._handle_exception_no_connection(self.dbapi, error)
.venv\Lib\site-packages\sqlalchemy\dialects\postgresql\asyncpg.py:841: in _handle_exception_no_connection
    super()._handle_exception_no_connection(dbapi, error)
.venv\Lib\site-packages\sqlalchemy\connectors\asyncio.py:409: in _handle_exception_no_connection
    raise error.with_traceback(exc_info[2])
.venv\Lib\site-packages\sqlalchemy\dialects\postgresql\asyncpg.py:605: in _prepare_and_execute
    self._rows = deque(await prepared_stmt.fetch(*parameters))
                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv\Lib\site-packages\asyncpg\prepared_stmt.py:177: in fetch
    data = await self.__bind_execute(args, 0, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv\Lib\site-packages\asyncpg\prepared_stmt.py:268: in __bind_execute
    data, status, _ = await self.__do_execute(
.venv\Lib\site-packages\asyncpg\prepared_stmt.py:257: in __do_execute
    return await executor(protocol)
           ^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

>   ???
E   TimeoutError

asyncpg/protocol/protocol.pyx:205: TimeoutError
-------------------------- Captured stdout teardown ---------------------------
{"timestamp": "2026-10-17T10:00:10.320672+00:00", "level": "ERROR", "logger": "sqlalchemy.pool.impl.AsyncAdaptedQueuePool", "message": "The garbage collector is trying to clean up non-checked-in connection <AdaptedConnection <asyncpg.connection.Connection object at 0x000002CC7FE8BB50>>, which will be terminated.  Please ensure that SQLAlchemy pooled connections are returned to the pool explicitly, either by calling ``close()`` or by using appropriate context managers to manage their lifecycle.", "correlation_id": "-"}
============================== warnings summary ===============================
<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/integration/test_heavy_reads.py::test_every_heavy_read_is_fast_enough_and_off_the_live_engine
============ 1 failed, 386 passed, 2 warnings in 741.97s (0:12:21) ============

scripts/check.sh: FAILED at step 12/13 (pytest tests/integration tests/api)
check.sh exit=1
```

</details>

### Run 2 — `./scripts/check.sh` (rerun once)

<details><summary>Run 2: all 13 steps passed</summary>

```text

==> [1/13] ruff format --check
332 files already formatted

==> [2/13] ruff check
All checks passed!

==> [3/13] web format:check

> web@0.0.0 format:check C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> prettier --check .

Checking formatting...
All matched files use Prettier code style!

==> [4/13] web lint

> web@0.0.0 lint C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> eslint .

[boundaries][warning]: Rule "boundaries/entry-point" is deprecated and will be removed in future versions.
  Please migrate to the "boundaries/dependencies" rule with appropriate selectors. More info: https://www.jsboundaries.dev/docs/rules/entry-point/#migration-to-boundariesdependencies


==> [5/13] mypy app db exchange tests
Success: no issues found in 255 source files

==> [6/13] web tsc -b

==> [7/13] web api types drift
✨ openapi-typescript 7.13.0
🚀 C:\Users\MARTIJ~1\AppData\Local\Temp\bb-openapi-3ochdt8u.json → src/api/generated/schema.d.ts [117.4ms]

==> [8/13] web build

> web@0.0.0 build C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> tsc -b && vite build

vite v8.3.1 building client environment for production...
transforming...

/theme.css doesn't exist at build time, it will remain unchanged to be resolved at runtime
✓ 332 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                            0.54 kB │ gzip:   0.34 kB
dist/assets/inter-latin-400-normal-C38fXH4l.woff2         23.66 kB
dist/assets/eb-garamond-latin-400-normal-BCNrxLz_.woff2   23.82 kB
dist/assets/inter-latin-800-normal-BYj_oED-.woff2         24.40 kB
dist/assets/inter-latin-600-normal-LgqL8muc.woff2         24.45 kB
dist/assets/eb-garamond-latin-500-normal-DehAIUv0.woff2   25.26 kB
dist/assets/eb-garamond-latin-700-normal-D7LhwqnD.woff2   25.29 kB
dist/assets/eb-garamond-latin-600-normal-DHwxsLHv.woff2   25.34 kB
dist/assets/eb-garamond-latin-400-normal-maQnHeKB.woff    28.60 kB
dist/assets/eb-garamond-latin-700-normal-DcHu0PDI.woff    30.10 kB
dist/assets/eb-garamond-latin-500-normal-DZU8xF9o.woff    30.20 kB
dist/assets/eb-garamond-latin-600-normal-xCe6GkOx.woff    30.40 kB
dist/assets/inter-latin-400-normal-CyCys3Eg.woff          30.69 kB
dist/assets/inter-latin-600-normal-CiBQ2DWP.woff          31.26 kB
dist/assets/inter-latin-800-normal-D1mf63XC.woff          31.29 kB
dist/assets/logo-D76si8Zt.png                             63.76 kB
dist/assets/index-CjciWAmm.css                            21.08 kB │ gzip:   4.82 kB
dist/assets/index-CSGAbELF.js                            623.37 kB │ gzip: 192.54 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 1.83s

==> [9/13] built output references
check_built_assets: no non-origin references in web\dist

==> [10/13] pytest tests/unit tests/meta tests/engine
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 668 items

tests\unit\test_app_clock.py ........                                    [  1%]
tests\unit\test_app_shell.py .....................                       [  4%]
tests\unit\test_candles.py ..................                            [  7%]
tests\unit\test_check_built_assets.py ................................   [ 11%]
tests\unit\test_check_image.py ............................              [ 16%]
tests\unit\test_codec.py ..............                                  [ 18%]
tests\unit\test_config.py .............................................. [ 25%]
...............                                                          [ 27%]
tests\unit\test_default_params.py ..                                     [ 27%]
tests\unit\test_earnings.py .....                                        [ 28%]
tests\unit\test_errors.py ...                                            [ 28%]
tests\unit\test_fake_clock.py ..........                                 [ 30%]
tests\unit\test_gap.py .....................                             [ 33%]
tests\unit\test_grace.py .............................................   [ 40%]
tests\unit\test_history_ring.py .............                            [ 42%]
tests\unit\test_hostdir.py ........                                      [ 43%]
tests\unit\test_hub.py ...............                                   [ 45%]
tests\unit\test_images.py .............                                  [ 47%]
tests\unit\test_key_format.py .........................                  [ 51%]
tests\unit\test_logging.py ....                                          [ 51%]
tests\unit\test_mapping.py .......                                       [ 52%]
tests\unit\test_market_events.py ...........                             [ 54%]
tests\unit\test_messages.py ............................................ [ 61%]
...                                                                      [ 61%]
tests\unit\test_migrate_cancel.py .                                      [ 61%]
tests\unit\test_publish.py ............                                  [ 63%]
tests\unit\test_schema_compat.py .........                               [ 64%]
tests\unit\test_security.py ........................................     [ 70%]
tests\unit\test_smoke_etag.py .......                                    [ 71%]
tests\unit\test_smoke_health.py .........                                [ 73%]
tests\unit\test_theme_manifest.py ...................................... [ 78%]
........................................................................ [ 89%]
.......................                                                  [ 93%]
tests\unit\test_v1_files.py ............................................ [ 99%]
..                                                                       [100%]

============================== warnings summary ===============================
<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 668 passed, 1 warning in 14.99s =======================
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 255 items

tests\meta\test_clock_seam.py ..............                             [  5%]
tests\meta\test_compose_matches_env_example.py .......                   [  8%]
tests\meta\test_config_boundary.py .............................         [ 19%]
tests\meta\test_dockerfile.py .....                                      [ 21%]
tests\meta\test_guard_migrations_hook.py ..........................      [ 31%]
tests\meta\test_import_side_effects.py ................................. [ 44%]
                                                                         [ 44%]
tests\meta\test_migration_scaffolding.py .....                           [ 46%]
tests\meta\test_no_file_io.py ......................                     [ 55%]
tests\meta\test_no_latest.py ................                            [ 61%]
tests\meta\test_no_p0_totals.py .......                                  [ 64%]
tests\meta\test_no_v1_key_import.py ......                               [ 66%]
tests\meta\test_render_blueprint.py ......................               [ 75%]
tests\meta\test_repo_hygiene.py .......................                  [ 84%]
tests\meta\test_route_authorization.py ....                              [ 85%]
tests\meta\test_schema_compat_coverage.py .......                        [ 88%]
tests\meta\test_trivyignore.py ......                                    [ 90%]
tests\meta\test_venue_stack.py .......................                   [100%]

============================== warnings summary ===============================
<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 255 passed, 1 warning in 7.88s ========================
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 231 items

tests\engine\test_advance.py ......................                      [  9%]
tests\engine\test_golden_capture.py ..ssssss....................         [ 21%]
tests\engine\test_golden_replay.py ssssss..                              [ 25%]
tests\engine\test_lifecycle_helpers.py ......                            [ 27%]
tests\engine\test_mask.py .....................                          [ 36%]
tests\engine\test_numeric_pin.py .                                       [ 37%]
tests\engine\test_pricing.py ........                                    [ 40%]
tests\engine\test_properties.py ....                                     [ 42%]
tests\engine\test_purity.py ..........................                   [ 53%]
tests\engine\test_spec.py ....................................           [ 69%]
tests\engine\test_state.py ...........                                   [ 74%]
tests\engine\test_steps_idle_brownian.py ...............                 [ 80%]
tests\engine\test_steps_jumps.py .....................                   [ 89%]
tests\engine\test_steps_orders.py ........................               [100%]

=========================== short test summary info ===========================
SKIPPED [6] tests\engine\test_golden_capture.py:52: the golden numbers are captured on Linux; run scripts/golden_linux.sh
SKIPPED [6] tests\engine\test_golden_replay.py:47: the golden numbers are captured on Linux; run scripts/golden_linux.sh
====================== 219 passed, 12 skipped in 17.13s =======================

==> [11/13] web test

> web@0.0.0 test C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> vitest --passWithNoTests "--run"


 RUN  v5.0.2 C:/Users/MartijnBoot/Documents/GitHub-Personal/borrelbeurs-v2/web


 Test Files  58 passed (58)
      Tests  605 passed (605)
   Start at  13:12:31
   Duration  45.32s (environment 71%, import 20%, tests 6%, transform 3%)

    Isolate  58 workers spawned · ~8.29s startup each (spawn + environment, per file)
             at least ~23.76s faster with isolate: false — reuses workers across files instead of one per file


==> [12/13] pytest tests/integration tests/api
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 387 items

tests\integration\test_advisory_lock.py .....                            [  1%]
tests\integration\test_analytics_compare.py ........                     [  3%]
tests\integration\test_analytics_runs.py ........                        [  5%]
tests\integration\test_bar_price_snapshot.py ..                          [  5%]
tests\integration\test_boot.py ...................                       [ 10%]
tests\integration\test_cli_keys.py ........                              [ 12%]
tests\integration\test_cli_runs.py ......                                [ 14%]
tests\integration\test_close_in_process.py ....                          [ 15%]
tests\integration\test_config_draft.py ...                               [ 16%]
tests\integration\test_config_live.py ........                           [ 18%]
tests\integration\test_db_restart.py .                                   [ 18%]
tests\integration\test_delete_run.py ......                              [ 20%]
tests\integration\test_drink_lifecycle.py ..........                     [ 22%]
tests\integration\test_durability.py .......                             [ 24%]
tests\integration\test_earnings_series.py ......                         [ 26%]
tests\integration\test_engine_state.py ............                      [ 29%]
tests\integration\test_export_hostdir.py ........                        [ 31%]
tests\integration\test_export_queue.py .......                           [ 33%]
tests\integration\test_export_timing.py .                                [ 33%]
tests\integration\test_export_workbook.py ........                       [ 35%]
tests\integration\test_export_worker.py .......                          [ 37%]
tests\integration\test_go_live_in_process.py .....                       [ 38%]
tests\integration\test_handover.py ..                                    [ 39%]
tests\integration\test_health.py .....                                   [ 40%]
tests\integration\test_heavy_reads.py .                                  [ 40%]
tests\integration\test_holder.py ...............                         [ 44%]
tests\integration\test_import_v1.py ........                             [ 46%]
tests\integration\test_manipulation.py ..........                        [ 49%]
tests\integration\test_market_events_repo.py ......                      [ 50%]
tests\integration\test_migrations.py .................                   [ 55%]
tests\integration\test_news.py ........                                  [ 57%]
tests\integration\test_order_concurrency.py .                            [ 57%]
tests\integration\test_orders.py .............                           [ 60%]
tests\integration\test_place_order.py ..........................         [ 67%]
tests\integration\test_products.py ....                                  [ 68%]
tests\integration\test_proxy_keying.py ..                                [ 68%]
tests\integration\test_real_process.py ....                              [ 70%]
tests\integration\test_rehydrate.py ...............                      [ 73%]
tests\integration\test_restart_replay.py .                               [ 74%]
tests\integration\test_runs.py .................                         [ 78%]
tests\integration\test_schema.py ....................................... [ 88%]
.............                                                            [ 91%]
tests\integration\test_smoke_script.py .....                             [ 93%]
tests\integration\test_stamp_monotonic.py .                              [ 93%]
tests\integration\test_theme_repo.py .......                             [ 95%]
tests\integration\test_ticker.py ..................                      [100%]

============================== warnings summary ===============================
<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/integration/test_heavy_reads.py::test_every_heavy_read_is_fast_enough_and_off_the_live_engine
  C:\Users\MartijnBoot\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\Lib\weakref.py:590: SAWarning: The garbage collector is trying to clean up non-checked-in connection <AdaptedConnection <asyncpg.connection.Connection object at 0x00000191E3443E20>>, which will be terminated.  Please ensure that SQLAlchemy pooled connections are returned to the pool explicitly, either by calling ``close()`` or by using appropriate context managers to manage their lifecycle.
    return info.func(*info.args, **(info.kwargs or {}))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 387 passed, 3 warnings in 524.53s (0:08:44) =================
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 654 items

tests\api\test_admin.py ......                                           [  0%]
tests\api\test_analytics.py ....                                         [  1%]
tests\api\test_analytics_compare.py .....                                [  2%]
tests\api\test_anchor_s0.py .....                                        [  3%]
tests\api\test_assets.py ...............                                 [  5%]
tests\api\test_auth.py .........................                         [  9%]
tests\api\test_authorization_matrix.py ................................. [ 14%]
........................................................................ [ 25%]
........................................................................ [ 36%]
................                                                         [ 38%]
tests\api\test_close.py ...............                                  [ 40%]
tests\api\test_config.py ............................................... [ 48%]
..........                                                               [ 49%]
tests\api\test_connections.py ...                                        [ 50%]
tests\api\test_delete_run.py .......                                     [ 51%]
tests\api\test_draining.py ............................................. [ 58%]
.................                                                        [ 60%]
tests\api\test_drinks.py ..............................................  [ 67%]
tests\api\test_earnings_series.py ...........                            [ 69%]
tests\api\test_exports.py ...............                                [ 71%]
tests\api\test_go_live.py ........                                       [ 72%]
tests\api\test_keys.py .............                                     [ 74%]
tests\api\test_market.py ................                                [ 77%]
tests\api\test_news.py ..............                                    [ 79%]
tests\api\test_orders.py ..................                              [ 82%]
tests\api\test_runs.py .............                                     [ 84%]
tests\api\test_standby.py .........                                      [ 85%]
tests\api\test_state.py .....                                            [ 86%]
tests\api\test_static.py ............................                    [ 90%]
tests\api\test_theme.py .............................                    [ 95%]
tests\api\test_v1_keys.py .......                                        [ 96%]
tests\api\test_ws.py ...............                                     [ 98%]
tests\api\test_ws_fixture.py .                                           [ 98%]
tests\api\test_ws_revoke.py .                                            [ 98%]
tests\api\test_ws_theme.py ........                                      [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

<string>:1
  <string>:1: SADeprecationWarning: Type object <class 'sqlalchemy.sql.sqltypes.Integer'> does not include operator 'or_' in its operator classes.  Using built-in operators (not including custom or overridden operators) outside of a type's stated operator classes is deprecated and will raise InvalidRequestError in a future release

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 654 passed, 2 warnings in 502.16s (0:08:22) =================

==> [13/13] web e2e

> web@0.0.0 e2e C:\Users\MartijnBoot\Documents\GitHub-Personal\borrelbeurs-v2\web
> playwright test


Running 33 tests using 1 worker

  ok  1 [chromium] › e2e\admin.spec.ts:85:1 › an admin builds a borrel from nothing, and every screen follows live (4.6s)
analytics.spec: 9.6 s
  ok  2 [chromium] › e2e\analytics.spec.ts:150:1 › two borrels: close, copy, compare, export and delete (9.7s)
  ok  3 [chromium] › e2e\auth.spec.ts:21:5 › login (AC21) › display lands on /koers (570ms)
  ok  4 [chromium] › e2e\auth.spec.ts:21:5 › login (AC21) › bar lands on /bar (449ms)
  ok  5 [chromium] › e2e\auth.spec.ts:21:5 › login (AC21) › admin lands on / (387ms)
  ok  6 [chromium] › e2e\auth.spec.ts:27:3 › login (AC21) › a wrong key says so, and stays on the login page (310ms)
  ok  7 [chromium] › e2e\auth.spec.ts:37:5 › navigation (AC22, AC23) › display's menu lists exactly its routes (475ms)
  ok  8 [chromium] › e2e\auth.spec.ts:37:5 › navigation (AC22, AC23) › bar's menu lists exactly its routes (482ms)
  ok  9 [chromium] › e2e\auth.spec.ts:37:5 › navigation (AC22, AC23) › admin's menu lists exactly its routes (428ms)
  ok 10 [chromium] › e2e\auth.spec.ts:44:3 › navigation (AC22, AC23) › display at /settings sees "Geen toegang" (480ms)
  ok 11 [chromium] › e2e\auth.spec.ts:51:3 › navigation (AC22, AC23) › bar at /bar sees the bar page (Phase 5) (446ms)
  ok 12 [chromium] › e2e\auth.spec.ts:58:1 › a session lost while on /koers goes to login and back (AC20, PD10) (748ms)
  ok 13 [chromium] › e2e\bar.spec.ts:66:3 › the bar page (Phase 5) › a tap posts the held quote and confirms at the receipt price (AC1, AC3) (580ms)
  ok 14 [chromium] › e2e\bar.spec.ts:97:3 › the bar page (Phase 5) › a 409 asks to confirm at its price; confirming posts a new key at it (AC12, AC13) (1.2s)
  ok 15 [chromium] › e2e\bar.spec.ts:155:3 › the bar page (Phase 5) › a double tap posts two orders with distinct keys (AC9) (732ms)
  ok 16 [chromium] › e2e\bar.spec.ts:170:3 › the bar page (Phase 5) › an aborted request is retried with the same key and body, and books once (AC10) (2.5s)
  ok 17 [chromium] › e2e\bar.spec.ts:195:3 › the bar page (Phase 5) › two bar sessions converge on the database total (AC19) (1.1s)
  ok 18 [chromium] › e2e\bar.spec.ts:216:3 › the bar page (Phase 5) › at 640 px there is no chart and no series request (AC24) (474ms)
  ok 19 [chromium] › e2e\bar.spec.ts:230:3 › the bar page (Phase 5) › display on /bar sees "Geen toegang" (AC28) (420ms)
  ok 20 [chromium] › e2e\board.spec.ts:59:3 › 1920×1080 with 6 drinks fits one viewport (AC24) (677ms)
  ok 21 [chromium] › e2e\board.spec.ts:59:3 › 1920×1080 with 9 drinks fits one viewport (AC24) (737ms)
  ok 22 [chromium] › e2e\board.spec.ts:75:1 › 390×844 portrait is one scrolling column (AC25) (556ms)
  ok 23 [chromium] › e2e\board.spec.ts:91:1 › 690×390 landscape is two columns (AC25) (536ms)
  ok 24 [chromium] › e2e\board.spec.ts:101:1 › an HTML drink name and news text are literal text (AC32) (571ms)
  ok 25 [chromium] › e2e\board.spec.ts:118:1 › no live run shows the empty state, then a snapshot shows the board in place (AC34) (607ms)
  ok 26 [chromium] › e2e\board.spec.ts:137:1 › a crash ends at t_end_ms on server time, with the client 5 min slow and no end frame (AC30) (6.5s)
  ok 27 [chromium] › e2e\board.spec.ts:169:3 › a price change pulses during a crash, alongside the event's animation (AC26) (2.0s)
  ok 28 [chromium] › e2e\board.spec.ts:169:3 › a price change pulses during a bubble, alongside the event's animation (AC26) (2.0s)
  ok 29 [chromium] › e2e\offline.spec.ts:28:1 › every Phase 4 page works with every non-origin request blocked (AC1) (849ms)
  ok 30 [chromium] › e2e\offline.spec.ts:64:1 › a lost socket shows the banner and polls every 5 s; reconnecting ends both (AC16) (25.0s)
  ok 31 [chromium] › e2e\theme.spec.ts:57:1 › a preset picked on /settings re-themes /koers within 2 s, without navigation (AC3) (1.4s)
  ok 32 [chromium] › e2e\theme.spec.ts:77:1 › picking Oud Geld sets EB Garamond on the display, loaded (AC10) (1.0s)
  ok 33 [chromium] › e2e\theme.spec.ts:105:1 › with every script blocked, /koers is painted in the stored theme (AC4) (229ms)

  33 passed (1.7m)

scripts/check.sh: all 13 steps passed
check.sh exit=0
```

</details>

### `uv run python -m tests.engine.golden.capture --check` (Windows)

```text
s1_live: DIFFERS at records[2].y[5]
s2_jump: DIFFERS at records[4].y[0]
s3_bounds: DIFFERS at records[1].y[5]
s4_default: DIFFERS at records[1].y[1]
s5_crash: DIFFERS at records[15].y[2]
s6_idle: DIFFERS at records[2].y[2]
capture --check exit=1
```

### `bash scripts/golden_linux.sh` (pinned Linux image)

```text
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv

[notice] A new release of pip is available: 24.0 -> 26.2.1
[notice] To update, run: pip install --upgrade pip
s1_live: ok
s2_jump: ok
s3_bounds: ok
s4_default: ok
s5_crash: ok
s6_idle: ok
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
...............                                                          [100%]
231 passed in 26.78s
golden_linux.sh exit=0
```
