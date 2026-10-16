# Runbook: deploy to Render

Deploying is a manual step. Merging to `main` makes CI push an image to GHCR and deploys
nothing, so a merge during a live event never redeploys it (SD6, ADR 0009).

## Prerequisites

- The SHA you want is in GHCR: the `push` job of CI's run on `main` was green.
- Once, by the human (H1): the Render services exist, and these are set in GitHub:
  - secret `RENDER_DEPLOY_HOOK_URL` (the web service's deploy hook, with its `?key=...`);
  - secret `BB_SMOKE_KEY`: an admin key labelled `smoke`
    (in the Render web service's shell, `python -m app.cli.keys create --role admin --label
    smoke`: the image has no `uv`. From a dev machine instead, export Render's external
    `DATABASE_URL` with the `postgresql+asyncpg://` scheme and any `JWT_SECRET` first, or the
    key lands in the local database. It prints `bb_<key_id>_<secret>` once);
  - variable `RENDER_URL`, for example `https://borrelbeurs.onrender.com`.

## First deploy (H1)

1. In `render.yaml`, replace `REPLACE_WITH_FIRST_DEPLOY_SHA` with the first SHA CI pushed.
2. Confirm the plans (SD10): a paid Starter web service (a free one sleeps, which stops the
   ticker) and paid Postgres (a free one expires after 90 days). Applying the Blueprint costs
   money.
3. Make the GHCR package readable to Render: public, or registry credentials in Render.
4. Apply the Blueprint. Set `DATABASE_URL` by hand: Render's **internal** database URL with
   its scheme changed to `postgresql+asyncpg://` (for example `postgres://u:p@host/db` becomes
   `postgresql+asyncpg://u:p@host/db`). The app accepts no other shape and rewrites nothing.
5. Turn Blueprint auto-sync off. `render.yaml` pins `image.url` to the first SHA; with
   auto-sync on, a later merge that edits the file would put that old SHA back, a silent
   rollback. From here the image changes only through the "Deploy a SHA" workflow.
6. Run "Deploy a SHA" below with the same SHA.

## Deploy a SHA

1. Actions tab, workflow **deploy**, Run workflow, `sha` = the full 40-character SHA.
   Or: `gh workflow run deploy.yml -f sha=<sha>`.
2. The workflow, in order: refuses a SHA that is not 40 lower-hex characters; refuses one with
   no image in GHCR (`docker manifest inspect`); calls the deploy hook with that image; runs
   `python scripts/smoke.py $RENDER_URL --expect-sha <sha> --wait-seconds 600`.
3. A new instance boots while the old one still holds the lock. It waits in standby
   (`lock_wait` in its log; `/healthz` says `standby`), then takes over when the old one exits.
   On Render the API answers 503 for about a minute (Render keeps the old instance up ~60 s
   before stopping it); phones retry and reconnect by themselves.

## Verify

- The workflow run is green, and its last step printed seven passing smoke steps.
- Smoke waits for that window to end: its first step passes only once `/healthz` says `ok`,
  not `standby`.
- `curl -s $RENDER_URL/healthz` shows `"build_sha": "<sha>"` and status `ok`.

## When a step fails

- *Validate the SHA / manifest inspect:* wrong SHA, or CI has not pushed it. Check the `push`
  job. Never deploy an image that is not in GHCR.
- *Deploy hook returns an error:* the secret is wrong or the hook was regenerated.
- *Smoke times out on `build_sha`:* the new instance is not live. Read Render's logs for
  `boot_failed` (see `incident.md`), then roll back (`rollback.md`).
- *Smoke fails after the SHA matches:* the new build is up but broken. Roll back.
