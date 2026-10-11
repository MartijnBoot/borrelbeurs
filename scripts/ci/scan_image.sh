#!/usr/bin/env bash
# Scan a local image with Trivy and write its SBOM (Phase 8 T12; AC4; SD20, SD21).
#
#   bash scripts/ci/scan_image.sh <image> <sbom-out>
#
# 1. Fails (exit 1) on any CRITICAL or HIGH vulnerability that has a fix, minus the
#    waivers in .trivyignore -- each with a reason and an expiry
#    (tests/meta/test_trivyignore.py). The first remedy is a newer base digest;
#    a waiver is a human decision.
# 2. Writes a CycloneDX SBOM of the image to <sbom-out>.
#
# Trivy runs as a container, digest-pinned here, against the local image through the
# docker socket: nothing is installed, nothing is pushed. Its vulnerability database
# is cached in a named volume between runs. Trivy is Apache-2.0, maintained by Aqua
# Security (plan "Data changes").
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: scan_image.sh <image> <sbom-out>" >&2
  exit 2
fi
IMAGE="$1"
SBOM="$2"

# aquasec/trivy 0.75.0 (2026-10-11).
TRIVY="aquasec/trivy@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa"
CACHE_VOLUME="borrelbeurs-trivy-cache"

# Host paths for `docker -v`. Git Bash's `pwd -W` gives C:/... (Docker Desktop
# would read /c/... as a path inside its VM); elsewhere plain `pwd`.
host_dir() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }
REPO_ROOT="$(host_dir "$(dirname "${BASH_SOURCE[0]}")/../..")"
SBOM_DIR="$(host_dir "$(dirname "$SBOM")")"
SBOM_NAME="$(basename "$SBOM")"

# Git Bash would rewrite the container-side paths below into Windows ones.
export MSYS_NO_PATHCONV=1

trivy() {
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$CACHE_VOLUME:/root/.cache/trivy" \
    -v "$REPO_ROOT/.trivyignore:/work/.trivyignore:ro" \
    -v "$SBOM_DIR:/out" \
    "$TRIVY" "$@"
}

echo "==> trivy: CRITICAL/HIGH with a fix, in $IMAGE"
trivy image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 \
  --ignorefile /work/.trivyignore --no-progress "$IMAGE"

echo "==> trivy: CycloneDX SBOM -> $SBOM"
trivy image --format cyclonedx --output "/out/$SBOM_NAME" --no-progress "$IMAGE"
if [ ! -s "$SBOM" ]; then
  echo "scan_image.sh: SBOM not written to $SBOM" >&2
  exit 1
fi
