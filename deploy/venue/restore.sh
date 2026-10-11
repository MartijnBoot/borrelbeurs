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
# Check the archive before dropping anything: a truncated dump fails here.
pg_restore --list "$dump" >/dev/null

echo "restore: $(basename "$dump") -> $DB"
dropdb --username="$USER_" --if-exists --force "$DB"
createdb --username="$USER_" "$DB"
pg_restore --username="$USER_" --dbname="$DB" --no-owner --exit-on-error "$dump"
echo "restore: done"
