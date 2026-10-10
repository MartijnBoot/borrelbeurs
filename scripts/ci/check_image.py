"""Check a built image for what must not ship in it, and for its size (Phase 8 T11; AC2, AC3).

    uv run python scripts/ci/check_image.py borrelbeurs:local --max-mb 300

Prints the image's uncompressed size and every forbidden path in its filesystem, both
read from `docker export` of a created -- never started -- container as a tar stream.
The size is the sum of its files: `docker image inspect`'s `.Size` is the compressed
content size under Docker Desktop's containerd image store, and uncompressed under
the classic one CI uses, so it measures nothing reliably. Exits 1 on any forbidden path
or a size over `--max-mb` (D-43: v1's image shipped a 1.7 GB tar of itself, its `.git`,
its keys and its tests).

A path is forbidden by its components, not by substring, so `pipes.py` is not `pip`
(plan PD9). Image-wide, `site-packages` included:

- an archive: `*.tar`, `*.tar.gz`;
- `.git`, `.env*`, `keys.json`, `.jwt_secret`;
- a directory named `tests`, `legacy` or `node_modules`;
- a package directory or `*.dist-info` named `pip`, `setuptools` or `uv`;
- `bin/pip*`, `bin/uv`.

`forbidden` is pure and unit-tested (`tests/unit/test_check_image.py`); the rest
drives docker.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
from collections.abc import Iterable, Iterator
from pathlib import PurePosixPath

FORBIDDEN_DIRS = frozenset({"tests", "legacy", "node_modules"})
FORBIDDEN_FILES = frozenset({"keys.json", ".jwt_secret"})
TOOL_PACKAGES = frozenset({"pip", "setuptools", "uv"})
TOOL_DIST_INFO = re.compile(r"^(pip|setuptools|uv)-[^/]+\.dist-info$")


def forbidden(path: str, *, is_dir: bool) -> str | None:
    """Why `path` must not be in the image, or `None`. `path` is as `docker export` lists it."""
    parts = PurePosixPath(path.strip("/")).parts
    if not parts:
        return None
    name = parts[-1]
    directories = parts if is_dir else parts[:-1]
    for part in directories:
        if part in FORBIDDEN_DIRS:
            return f"a `{part}` directory"
        if part in TOOL_PACKAGES or TOOL_DIST_INFO.match(part):
            return f"the `{part}` packaging tool"
    for part in parts:
        if part == ".git":
            return "a git repository"
        if part.startswith(".env"):
            return "an environment file"
    if not is_dir:
        if name.endswith((".tar", ".tar.gz")):
            return "an archive"
        if name in FORBIDDEN_FILES:
            return "a secret file"
        if len(parts) >= 2 and parts[-2] == "bin" and (name.startswith("pip") or name == "uv"):
            return "a packaging tool binary"
    return None


def violations(entries: Iterable[tuple[str, bool]]) -> list[str]:
    """`path: reason` for every forbidden `(path, is_dir)` entry."""
    found = []
    for path, is_dir in entries:
        reason = forbidden(path, is_dir=is_dir)
        if reason is not None:
            found.append(f"{path}: {reason}")
    return found


def _filesystem(image: str) -> Iterator[tuple[str, bool, int]]:
    """`(path, is_dir, size)` for every entry of the image's filesystem, from a created
    (not started) container."""
    container = subprocess.run(
        ["docker", "create", image], check=True, capture_output=True, text=True
    ).stdout.strip()
    try:
        export = subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE)
        assert export.stdout is not None
        with tarfile.open(fileobj=export.stdout, mode="r|") as stream:
            for member in stream:
                yield member.name, member.isdir(), member.size if member.isfile() else 0
        if export.wait() != 0:
            raise RuntimeError(f"docker export {container} failed")
    finally:
        subprocess.run(["docker", "rm", "--force", container], check=False, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("image")
    parser.add_argument("--max-mb", type=float, required=True)
    args = parser.parse_args(argv)

    entries = list(_filesystem(args.image))
    size_mb = sum(size for _, _, size in entries) / 1_000_000
    print(f"image size: {size_mb:.1f} MB uncompressed (limit {args.max_mb:g} MB)")
    found = violations((path, is_dir) for path, is_dir, _ in entries)
    for line in found:
        print(f"forbidden: {line}")
    if found:
        print(f"check_image: {len(found)} forbidden path(s)")
    if size_mb > args.max_mb:
        print("check_image: over the size limit")
    return 1 if found or size_mb > args.max_mb else 0


if __name__ == "__main__":
    sys.exit(main())
