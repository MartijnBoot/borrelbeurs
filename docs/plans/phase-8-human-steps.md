# Plan: Phase 8 — the human steps (H1–H4)

Spec: [phase-8-deploy-cutover.md](../specs/phase-8-deploy-cutover.md), including Amendment A1 (no
v1 fallback) · Parent plan: [phase-8-deploy-cutover.md](phase-8-deploy-cutover.md) · Status:
**Not started** · Run it with `/human 8` (an agent walks you through it; you do the steps)

These are the steps only a person can do: a Render dashboard, GitHub secrets, a laptop at a
router, a hard power-off. The agent's job is to make them fast and honest: check what it can,
tell you the next step, collect the evidence, and draft the record. It does not do the steps.

**Exit (the spec's exit condition):** the same image digest serves on Render and on the offline
venue laptop; previous-image rollback has been rehearsed within 5 minutes; a full mock borrel
has been run offline; v1's keys grant nothing anywhere. Evidence: the four records under
`docs/runbooks/rehearsals/`.

## Rules for the agent

1. **One step at a time.** Say what to do, what to paste back, and wait. Never list the next
   five steps as if they were one.
2. **You do not do the human steps.** Never run the `deploy` workflow (CLAUDE.md), never set
   secrets or variables, never touch the Render dashboard, and **never touch `borrelbeurs-v1`**
   (hard stop, ADR 0009).
3. **Never connect to production.** Do not `curl` the Render URL or use its credentials. Ask
   the human to run the check and paste the output. Reading GitHub (`gh run`, `gh run view`) and
   `docker manifest inspect` on GHCR is fine: neither is production.
4. **No key material, ever.** Do not ask for a key, a `DATABASE_URL` or a deploy-hook URL, and
   do not write one into a file or a record. If the human pastes one, say so and do not repeat it.
5. **What the agent may do:** read-only checks; a branch with the one-line `render.yaml` SHA edit
   (the human merges); draft a record from the human's notes; tick this file's checkboxes and
   fill the "Notes" lines when the human confirms a step. Commit only when asked.
6. **Evidence over assurance.** A step is done when the human has pasted the output named under
   "Evidence", not when they say it went fine.
7. **Anything that broke** becomes a follow-up task or a defect-register entry in the record,
   never a silent fix (SD19).

## Order

Suggested: **H4** (short, no dependency), **H1**, **H2**, **H3**.
Dependencies: `H1←T17,T18,T19` · `H2←T16,T18,T19` · `H3←H1,H2` · `H4←T9,T19`. All the T-tasks
are merged (Phase 8 is on `main` since `1110f93`).

Record template (`docs/runbooks/rehearsals/README.md`), one file per rehearsal, named
`docs/runbooks/rehearsals/<yyyy-mm-dd>-<what>.md`: image SHA, who and where, what was done, timings
against target, what broke, follow-ups. No key material.

## Progress

- [ ] **H4** key rotation: `<date>-key-rotation.md`
- [ ] **H1** Render and GHCR: `<date>-render-deploy.md`
- [ ] **H2** the mock borrel: `<date>-mock-borrel.md`
- [ ] **H3** rollback rehearsals: `<date>-rollback.md`

Image SHAs in play (fill in as they exist). **n** = the first deployed image; **n+1** = a later
one for the mid-run deploy and for the rollback rehearsals.

- n: `1110f9349cd976fc468885af67940618d8e243ca` (CI run `38151806487`, `push` green, in GHCR;
  re-check with `docker manifest inspect ghcr.io/martijnboot/borrelbeurs:<sha>`)
- n+1: _the commit that merges the `render.yaml` pin (H1 step 1)_

---

## H4 — Rotate v1's keys (AC32 human half; SD18; D-42)

**Why now:** v1 is retired (A1), but its leaked keys are still in the history of the repository
you keep as a backup, and any v1 still running accepts them.

**Preconditions (agent checks):**
- `uv run pytest tests/api/test_v1_keys.py tests/meta/test_no_v1_key_import.py -q` passes: a v1
  key gets 401 on v2 and v2 cannot import v1 keys (T9). Show the output.

**Human does:**
1. List every place a v1 instance still runs or could run (the old venue laptop, a Render or
   other host, a colleague's machine, any saved `bierbeurs` image with a baked-in
   `config/keys.json`).
2. For each: stop it for good, **or** replace its `config/keys.json` with a new one generated
   where it runs. Never commit the new file.
3. Optional but recommended: make the `borrelbeurs-v1` repository private, or archive it.

**Evidence (human pastes, no keys):** the list from step 1 with the action taken per place, the
date, and the repository's visibility now.

**Record:** `key-rotation`. Fields: where v1 ran, what was done to each, date, repository status,
and the test output above. Tick the old line in `docs/plans/manual-checklist.md` ("rotate the v1
access keys") only if the human asks.

- Notes:

---

## H1 — Render and GHCR: setup, first deploy, a deploy mid-run (AC28 run, AC29; SD8, SD10)

**Runbook:** [deploy.md](../runbooks/deploy.md). It has the exact steps; this section is the
order and the evidence. Applying the Blueprint **costs money** (SD10): the human decides.

**Preconditions (agent checks):**
- `gh run list --branch main --workflow CI --limit 1` is green and its `push` job succeeded.
- `docker manifest inspect ghcr.io/martijnboot/borrelbeurs:<n>` succeeds. It is anonymous, so the
  package is public and Render needs no registry credentials; if it ever fails, GHCR visibility
  or Render credentials are the first thing to fix.

**Steps:**
1. *(agent prepares, human merges)* On a branch, replace `REPLACE_WITH_FIRST_DEPLOY_SHA` in
   `render.yaml` with SHA **n**. Run `uv run pytest tests/meta/test_render_blueprint.py
   tests/meta/test_no_latest.py -q`. The human opens and merges the PR. Merging deploys nothing,
   and CI pushes a new image: that merge commit is **n+1**. Record it above.
2. *(human)* Confirm the plans: Starter web service, `basic-256mb` Postgres (frankfurt).
3. *(human)* Apply the Blueprint in Render. Set `DATABASE_URL` by hand: Render's **internal**
   URL with the scheme changed to `postgresql+asyncpg://`.
4. *(human)* Turn Blueprint **auto-sync off**, or a later edit to `render.yaml` silently rolls
   the image back.
5. *(human)* In the Render web service shell: `python -m app.cli.keys create --role admin --label
   smoke`. Copy the key straight into the GitHub secret `BB_SMOKE_KEY`. Also set the secret
   `RENDER_DEPLOY_HOOK_URL` and the variable `RENDER_URL`. Never paste them into this chat.
6. *(human)* Actions, workflow **deploy**, Run workflow, `sha` = **n**. Wait for green.
7. *(human)* Start a borrel on Render and take orders from a phone.
8. *(human)* While it runs, deploy **n+1** the same way.
9. *(human)* Keep the Render logs from the deploy: they should show `lock_wait` on the new
   instance, the handover, and contiguous versions. Record whether Render overlapped the two
   instances; if it did not, say so (SD4 is then proven only by the integration test).

**Evidence (human pastes):**
- both `deploy` workflow run URLs and their conclusions (agent confirms with `gh run view`);
- the smoke step's output, seven passing steps (from the run log; agent can read it with `gh`);
- the log lines for `lock_wait`, the handover and the version numbers around it, pasted by the
  human from Render's logs;
- the output of `curl -s $RENDER_URL/healthz` run by the human, showing `build_sha` = n+1.

**Record:** `render-deploy`. Add the overlap finding and anything that broke.

- Notes:

---

## H2 — The mock borrel, offline (AC30; the real-world halves of AC19–AC22)

**Runbook:** [venue.md](../runbooks/venue.md) (laptop, router, during, after).

**Preconditions (agent checks):**
- The bundle builds for the SHA you will run: `bash scripts/make_bundle.sh <n>` (the agent may
  run it; the output goes to the gitignored `bundle/`), and `sha256sum -c SHA256SUMS` in it.
- Build a second bundle for **n+1** too, and keep both: H3 rolls back from one to the other at
  the venue.
- Docker Desktop on the laptop uses the containerd image store (`start.cmd` refuses otherwise).

**Setup (human):** travel router with no uplink, Wi-Fi password set, the laptop on its fixed
IP, the bundle copied from USB, `start.cmd` run once, keys and the run created, `go-live`.

**Run, at least 1 hour, at least two bar phones and one display, in this order of events:**
1. a drink added mid-run;
2. "Sluit app", then `start.cmd`;
3. a **hard power-off** (power button held, mains out), then a restart;
4. the laptop clock moved **+1 h and back**;
5. a manual export downloaded on a phone;
6. dumps (`data\backups\`) and auto exports (`data\exports\`, every 15 minutes) seen accruing;
7. the run closed.

**Afterwards:** restore the newest dump into a fresh volume ([restore.md](../runbooks/restore.md))
and check the order count against what the bar saw; copy `data\` to a USB stick.

**Evidence (human notes, per event):** the time, what was seen (the board after the power-off,
the prices after the clock step, the export on the phone), the order count before and after the
restore, and the image SHA from `http://127.0.0.1/healthz` on the laptop.

**Record:** `mock-borrel`. The timings (start to ready, power-off to ready) and everything that
broke. Anything broke is a follow-up, not a silent fix.

- Notes:

---

## H3 — Rollback rehearsals (AC31; SD3)

**Runbook:** [rollback.md](../runbooks/rollback.md). Target: **5 minutes or less**, from the
decision to the previous build serving, each of the two timed.

**Preconditions:** H1 done (two SHAs deployed on Render) and H2 done (both bundles exist).

**Steps:**
1. *Venue laptop.* With n+1 running, start a stopwatch at the decision. `stop.cmd`, set
   `BB_IMAGE_SHA` in `.env` back to n, `start.cmd`. Stop at the board loading on a phone and
   `http://127.0.0.1/healthz` naming n. (If n's image is not on the laptop, load the n bundle's
   `images.tar` first, and note that time separately.)
2. *Render.* Stopwatch at the decision. Run the **deploy** workflow with SHA n. Stop at the run
   green and `/healthz` reporting n.

**Evidence (human pastes):** both timings against the 5 minutes, the healthz output naming the
SHA each time, and the workflow run URL for the Render rollback.

**Record:** `rollback`. If either took longer than 5 minutes, record what cost the time; that is
a follow-up, not a pass.

- Notes:

---

## When all four are done

1. The four records exist under `docs/runbooks/rehearsals/`. The agent checks they name an image
   SHA and contain no key material (`grep -E "bb_[A-Za-z0-9]+_" docs/runbooks/rehearsals/*.md`
   finds nothing).
2. Tick the exit line of Phase 8 in `docs/plans/manual-checklist.md` (deploy to Render, run
   offline, rehearse a rollback, hold a mock borrel) **if the human asks**.
3. Phase 8 is done. The follow-up the spec lists, removing `legacy/v1/`, is a separate task
   (spec, Amendment A1).
