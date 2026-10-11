# Runbook: incidents

Where the logs are: Render, the service's Logs tab. Venue, `logs.cmd` (or
`docker logs borrelbeurs-venue-app`). They are JSON lines; the events below are the `message`.

## `/healthz` is stale or 503

The ticker has not completed an iteration recently. Look for `advisory_lock_lost` and
database errors. If the database is reachable, the app restarts itself (`restart: on-failure`)
when it loses the lock (exit 70). If it stays stale: restart it (`stop.cmd` then `start.cmd`;
on Render, redeploy the same SHA). Nothing acknowledged is lost.

## Standby that never takes over

Log shows `lock_wait` with a growing `waited_s`; `/healthz` says `standby`. Another instance
holds the advisory lock. Find it, in
`docker exec -it borrelbeurs-venue-db psql -U borrelbeurs` (venue) or Render's database
shell:
`SELECT pid, application_name, state FROM pg_stat_activity WHERE datname = current_database();`
If an old instance is gone but its session is not (a stuck connection), end that backend with
`SELECT pg_terminate_backend(<pid>);`. Do not terminate a live instance's session.

## `schema ahead of image`

Log shows `boot_failed`, exit 3, `/readyz` never 200, and the app wrote nothing. The database
is newer than this image and the newer migration is not backward-compatible. Run a newer image
(the one that migrated it). See `rollback.md`, "The floor".

## A full disk (venue)

Dumps are up to 288 files of the database size, plus exports. `docker system df` and
`C:\BorrelBeurs\data\` show where it went. Delete the oldest dumps in `data\backups\` (keep the
newest few) and old `-auto.xlsx` files. Never delete a `.partial` that is being written.
