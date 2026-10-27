# Runbook: roll back to the previous image

Target: five minutes or less, from the decision to the previous build serving.

## The floor (SD3), read this first

Once a database is at revision `0011` or later, **no image older than the one that introduced
`0011` can boot against it**, and there is no downgrade-and-roll-back path. An image newer than
the floor boots against a schema ahead of it when its migrations declare themselves compatible
(`schema_ahead` in the log) and refuses to boot when they do not (`boot_failed`,
`schema ahead of image`, exit 3, nothing written). Rolling back is therefore "run the previous
SHA" and nothing else; it never touches the database. The floor excludes nothing yet: the image
that introduced `0011` was the first to serve a real database. Once a later migration takes a
step older images cannot read, the way out past it is a newer image or a restore of the last
dump taken before that step (`restore.md`).

**Past B-08.** Rolling back to an image older than B-08 still boots (migration `0015` keeps
the compatibility revision), but no key works: B-08 revoked the old long keys, and the old
image cannot read a short one. The way back in is a long key minted with that image's own CLI
(`python -m app.cli.keys create --role admin --label <who>`, in the Render shell or with
`docker compose ... run --rm --no-deps app` at the venue).

## Render

1. Find the previous good SHA: the last green **deploy** run, or `git log` on `main`.
2. Run the **deploy** workflow with that SHA (`deploy.md`, "Deploy a SHA").
3. Verify: the run is green and `/healthz` reports that `build_sha`.

## Venue laptop

1. Stop the app: double-click `stop.cmd`.
2. In the bundle folder's `.env`, set `BB_IMAGE_SHA` back to the previous SHA. That image must
   be on the laptop: the previous bundle's `images.tar` (`docker load -i images.tar`) or one
   already listed by `docker image ls ghcr.io/martijnboot/borrelbeurs`.
3. Double-click `start.cmd`. It waits for `/readyz` and prints the phone URL.
4. Verify: open the board on a phone, and check that `http://127.0.0.1/healthz` names the SHA.
   (The bundle carries no `scripts/smoke.py` and the laptop has no Python; run the smoke from
   a dev machine on the router's network if you need it.)

## When it fails

- `boot_failed` / `schema ahead of image`: the previous image is below the floor for this
  database. Use a newer image, or restore the last dump taken before that schema step
  (`restore.md`).
- The image is missing: `start.cmd` loads `images.tar` from its own folder; use the previous
  bundle.
