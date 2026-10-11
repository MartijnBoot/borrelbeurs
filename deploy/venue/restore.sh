#!/bin/sh
# BorrelBeurs venue restore (Phase 8 PD14): replace the database with one dump.
#
#   restore.sh                 the newest /backups/borrelbeurs-*.dump
#   restore.sh <file name>     that dump, from /backups
#
# Run inside the `db` container by restore.cmd, which has stopped `app` and `backup`
# first and starts the stack again only when this exits 0. It drops and recreates the
# database, then restores into it; any failure exits non-zero, and the app stays
# stopped (restore.md: retry with the previous dump).
set -eu

DIR=/backups
DB="${POSTGRES_DB:-borrelbeurs}"
USER_="${POSTGRES_USER:-borrelbeurs}"

if [ "$#" -ge 1 ] && [ -n "$1" ]; then
  dump="$DIR/$(basename "$1")"
else
  dump="$(ls -1 "$DIR"/borrelbeurs-*.dump 2>/dev/null | sort -r | head -n 1 || true)"
fi
if [ -z "$dump" ] || [ ! -f "$dump" ]; then
  echo "restore: no dump found in $DIR" >&2
  exit 2
fi
# Read the whole archive before dropping anything. `--list` reads only the table of
# contents at the head of the file, so a dump cut short in its data passes it; writing
# the script to /dev/null walks every data block and fails on a truncated one.
pg_restore --file=/dev/null "$dump"

echo "restore: $(basename "$dump") -> $DB"
dropdb --username="$USER_" --if-exists --force "$DB"
createdb --username="$USER_" "$DB"
pg_restore --username="$USER_" --dbname="$DB" --no-owner --exit-on-error "$dump"
echo "restore: done"
