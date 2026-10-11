# Runbook: restore a database

## Venue: restore a dump

Dumps are `C:\BorrelBeurs\data\backups\borrelbeurs-<stamp>.dump`: every 5 minutes, the newest
288 kept. Restoring replaces **all** data.

1. Double-click `restore.cmd`, or run `restore.cmd <file name>` for a specific dump. Without a
   name it uses the newest.
2. Type `HERSTEL` when asked.
3. The script stops `app` and `backup`, checks the archive, drops and recreates the database,
   restores the dump, and starts the stack again.
4. Verify: `status.cmd` shows all three services up, and the board shows the orders you expect.

### When the restore fails

A failed restore **never starts the app**. `restore.cmd` prints `HERSTEL MISLUKT`, leaves `app`
and `backup` stopped, and exits non-zero. A truncated dump is refused before anything is
dropped. Retry with the previous dump: `restore.cmd borrelbeurs-<earlier stamp>.dump`. If
`dropdb` or `createdb` fail, read `docker logs borrelbeurs-venue-db`.

## Move data between Render and the venue (SD10)

Each deployment is its own database; nothing syncs them.

- **Render to venue:** `pg_dump -Fc --no-owner "<Render external URL, plain postgres:// scheme>" > render.dump`.
  Copy it to `C:\BorrelBeurs\data\backups\borrelbeurs-<stamp>.dump` and run `restore.cmd` with
  that name.
- **Venue to Render:** take a dump (`backup-now.cmd`), then
  `pg_restore --clean --if-exists --no-owner -d "<Render external URL>" borrelbeurs-<stamp>.dump`
  with the Render app stopped.
