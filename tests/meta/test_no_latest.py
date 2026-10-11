"""AC5 -- no image is referenced as `latest`, or with no tag at all (Phase 8 T15; SD6).

What is deployed, scanned and bundled has to be the image that was tested. A floating
tag names a different image on the venue laptop, on Render and in CI from one day to
the next; `docker save` bundles whatever it pointed at last.

Scanned: `.github/workflows/`, `render.yaml` (once T17 adds it), `deploy/`, `docker/`
and `scripts/`. Never `legacy/`, which is v1 as it was. Two kinds of reference:

- the value of an `image:` / `url:` key or a Dockerfile `FROM` must carry a tag or a
  digest (`${VAR}` tags count: the compose file requires the variable);
- anywhere, a `<name>:latest` is refused.

GitHub's `ubuntu-latest` runner label is not an image and does not match either rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED = (".github/workflows", "render.yaml", "deploy", "docker", "scripts")
TEXT_SUFFIXES = {".yml", ".yaml", ".sh", ".cmd", ".py", ".md", ".example", ""}

# YAML only: in Python, `url: str` is an annotation.
KEYED = re.compile(r"^[ \t]*(?:-[ \t]*)?(?:image|url):[ \t]*[\"']?(?P<ref>[^\s\"'#]+)", re.M)
# Dockerfiles only: in Python, `from x import y` would match.
FROM = re.compile(r"^[ \t]*FROM[ \t]+(?:--platform=\S+[ \t]+)?(?P<ref>\S+)", re.M)
LATEST = re.compile(r"(?P<ref>[\w.\-/]+:latest)\b")


def _files() -> Iterator[Path]:
    for entry in SCANNED:
        path = REPO_ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            for found in sorted(path.rglob("*")):
                if found.is_file() and (
                    found.suffix in TEXT_SUFFIXES or "Dockerfile" in found.name
                ):
                    yield found


def _is_image(ref: str) -> bool:
    """A `url:` is often a web address; an image reference has no scheme."""
    return "://" not in ref and not ref.startswith(("$", "/", "."))


def _untagged(ref: str) -> bool:
    last = ref.rsplit("/", 1)[-1]
    return "@sha256:" not in ref and ":" not in last


def problems(text: str, name: str) -> list[str]:
    """Every floating image reference in `text`, the contents of a file called `name`."""
    found = [m["ref"] for m in LATEST.finditer(text)]
    keyed = [KEYED] if name.endswith((".yml", ".yaml")) else []
    for pattern in keyed + ([FROM] if "Dockerfile" in name else []):
        for match in pattern.finditer(text):
            ref = match["ref"]
            if _is_image(ref) and _untagged(ref):
                found.append(ref)
    return found


def test_no_scanned_file_names_a_floating_image() -> None:
    offenders = {
        str(path.relative_to(REPO_ROOT)): refs
        for path in _files()
        if (refs := problems(path.read_text(encoding="utf-8", errors="replace"), path.name))
    }
    assert not offenders, offenders


def test_the_guard_is_reading_real_files() -> None:
    names = {path.relative_to(REPO_ROOT).as_posix() for path in _files()}
    for expected in ("docker/Dockerfile", "deploy/venue/compose.yml", ".github/workflows/ci.yml"):
        assert expected in names, f"{expected} was not scanned; this guard is checking nothing"


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("compose.yml", "    image: postgres:latest\n"),
        ("compose.yml", "    image: postgres\n"),
        ("Dockerfile", "FROM python\n"),
        ("Dockerfile", "FROM --platform=linux/amd64 node AS web\n"),
        ("make_bundle.sh", "docker pull aquasec/trivy:latest\n"),
        ("render.yaml", "  image:\n    url: ghcr.io/martijnboot/borrelbeurs\n"),
    ],
)
def test_the_detector_notices_a_floating_reference(name: str, text: str) -> None:
    assert problems(text, name), text


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("ci.yml", "    runs-on: ubuntu-latest\n"),
        ("compose.yml", "    image: postgres:16-alpine@sha256:" + "0" * 64 + "\n"),
        ("Dockerfile", "FROM node:22-slim@sha256:" + "0" * 64 + " AS web-build\n"),
        ("compose.yml", "    image: ghcr.io/martijnboot/borrelbeurs:${BB_IMAGE_SHA:?set it}\n"),
        ("render.yaml", "    url: ghcr.io/martijnboot/borrelbeurs:REPLACE_WITH_FIRST_DEPLOY_SHA\n"),
        ("render.yaml", "  url: https://example.org/path\n"),
        ("smoke.py", "from pathlib import Path\n"),
        ("smoke.py", "    url: str\n"),
    ],
)
def test_the_detector_lets_a_pinned_reference_pass(name: str, text: str) -> None:
    assert not problems(text, name), text
