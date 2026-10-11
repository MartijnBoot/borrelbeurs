#!/bin/sh
# BorrelBeurs venue backup (Phase 8 SD13): pg_dump every BB_BACKUP_INTERVAL_S seconds.
#
# Runs in the `backup` service, on the pinned Postgres image, against `db`. Each dump
# is `pg_dump -Fc` into /backups, written as `.borrelbeurs-<stamp>.dump.partial` and
# renamed, so a dump with a final name is always complete. The newest 288 are kept
# (24 h at 5 minutes). A failed dump is logged and the loop goes on. It needs only
# the database, never the app.
#
#   backup.sh         loop forever (the service's entrypoint)
#   backup.sh once    one dump now (backup-now.cmd)
set -u

KEEP=288
INTERVAL="${BB_BACKUP_INTERVAL_S:-300}"
DIR=/backups

dump_once() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  final="$DIR/borrelbeurs-$stamp.dump"
  partial="$DIR/.borrelbeurs-$stamp.dump.partial"
  if pg_dump -Fc --file="$partial" && mv "$partial" "$final"; then
    echo "backup: wrote $(basename "$final")"
  else
    rm -f "$partial"
    echo "backup: FAILED at $stamp" >&2
    return 1
  fi
  # Newest first by name (the stamp sorts as time); delete beyond KEEP.
  ls -1 "$DIR"/borrelbeurs-*.dump 2>/dev/null | sort -r | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old"
  done
}

mkdir -p "$DIR"
if [ "${1:-}" = "once" ]; then
  dump_once
  exit $?
fi
while true; do
  dump_once || true
  sleep "$INTERVAL"
done
