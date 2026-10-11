#!/usr/bin/env bash
# Build the venue bundle (Phase 8 T16; SD11, AC20): everything the laptop at a borrel
# needs, with no internet, on a USB stick.
#
#   bash scripts/make_bundle.sh <sha> [--local <image-ref>]
#
# Writes bundle/borrelbeurs-<sha>/ (gitignored):
#   images.tar      `docker save` of the app image and the pinned Postgres, linux/amd64
#   compose.yml, backup.sh, restore.sh, LEESMIJ.md, the six .cmd files (deploy/venue/)
#   .env.example    deploy/venue's, with BB_IMAGE_SHA filled in
#   SHA256SUMS      of every file above (`sha256sum -c SHA256SUMS`)
#
# The app image is ghcr.io/martijnboot/borrelbeurs:<sha>, pulled for linux/amd64 --
# the image CI built, tested and pushed (SD6). `--local <ref>` instead retags a local
# build under that name, for the venue drill (tests/image/test_venue.py); nothing is
# pushed. Postgres is the digest deploy/venue/compose.yml pins, used from the local
# store when present, pulled otherwise.

set -euo pipefail

usage() {
  echo "usage: make_bundle.sh <40-hex sha> [--local <image-ref>]" >&2
  exit 2
}

[ "$#" -ge 1 ] || usage
SHA="$1"
LOCAL=""
if [ "$#" -eq 3 ] && [ "$2" = "--local" ]; then
  LOCAL="$3"
elif [ "$#" -ne 1 ]; then
  usage
fi
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "make_bundle.sh: not a 40-hex commit sha: $SHA" >&2; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENUE=deploy/venue
APP="ghcr.io/martijnboot/borrelbeurs:$SHA"
POSTGRES="$(grep -oE 'postgres:16-alpine@sha256:[0-9a-f]{64}' "$VENUE/compose.yml" | head -n 1)"
[ -n "$POSTGRES" ] || { echo "make_bundle.sh: no pinned Postgres in $VENUE/compose.yml" >&2; exit 1; }
OUT="bundle/borrelbeurs-$SHA"

if [ -n "$LOCAL" ]; then
  docker tag "$LOCAL" "$APP"
else
  docker pull --platform linux/amd64 "$APP"
fi
docker image inspect "$POSTGRES" >/dev/null 2>&1 || docker pull --platform linux/amd64 "$POSTGRES"

# The venue laptop is amd64; an image of any other platform would not run there.
for image in "$APP" "$POSTGRES"; do
  platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")"
  if [ "$platform" != "linux/amd64" ]; then
    echo "make_bundle.sh: $image is $platform, not linux/amd64" >&2
    exit 1
  fi
done

# `docker save` records names, not digests: Postgres saved by its digest would load
# with no name at all, and compose's digest-pinned `image:` (pull_policy: never) would
# find nothing. Saved by its tag, the tar keeps the tag *and* the pinned index digest,
# so the loaded image answers to `postgres:16-alpine@sha256:...`. Not `--platform`:
# that would save the amd64 manifest alone and drop the index digest compose pins.
PG_TAG="${POSTGRES%@*}"
if [ "$(docker image inspect --format '{{.Id}}' "$PG_TAG" 2>/dev/null)" != "${POSTGRES#*@}" ]; then
  docker tag "$POSTGRES" "$PG_TAG"
fi

rm -rf "$OUT"
mkdir -p "$OUT"
echo "==> images.tar: $APP, $POSTGRES"
docker save --output "$OUT/images.tar" "$APP" "$PG_TAG"

cp "$VENUE/compose.yml" "$VENUE/backup.sh" "$VENUE/restore.sh" "$VENUE/LEESMIJ.md" "$OUT/"
cp "$VENUE"/{start,stop,status,backup-now,restore,logs}.cmd "$OUT/"
sed "s/^BB_IMAGE_SHA=.*/BB_IMAGE_SHA=$SHA/" "$VENUE/.env.example" > "$OUT/.env.example"
grep -q "^BB_IMAGE_SHA=$SHA\$" "$OUT/.env.example"

(cd "$OUT" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum > SHA256SUMS)
echo "==> $OUT"
(cd "$OUT" && sha256sum -c --quiet SHA256SUMS && cat SHA256SUMS)
