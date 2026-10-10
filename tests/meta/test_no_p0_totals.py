"""AC13 (D-20) -- revenue at the fixed bar price is `bar_price_total`, never `p0_*`.

v1 reported "revenue at p0" as `p0_total` / `p0_per_drink`, but it meant the
bar price (D-20). Phase 7 names it `bar_price_total` / `bar_price_per_drink`
everywhere, and the old names must not come back in any served schema, the
export or the web source. Three places are scanned:

- the OpenAPI document `create_app()` serves;
- every file under `web/src/` (the generated `schema.d.ts` included);
- every file under `app/jobs/`, where the workbook is written.

**A guard that cannot fail is worse than no guard**: the scan must reach real
files in each tree, and the detector must flag each banned name in a sample.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

import app.main

REPO_ROOT = Path(__file__).resolve().parents[2]
BANNED: Final = ("p0_total", "p0_per_drink")
SCANNED_TREES: Final = (Path("web") / "src", Path("app") / "jobs")
SUFFIXES: Final = frozenset({".py", ".ts", ".tsx", ".css", ".json", ".html"})
MUST_SEE: Final = (
    Path("web") / "src" / "api" / "generated" / "schema.d.ts",
    Path("app") / "jobs" / "export_xlsx.py",
)


def banned_names(text: str) -> list[str]:
    return [name for name in BANNED if name in text]


def scanned_files() -> list[Path]:
    files: list[Path] = []
    for tree in SCANNED_TREES:
        for path in sorted((REPO_ROOT / tree).rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES and "node_modules" not in path.parts:
                files.append(path.relative_to(REPO_ROOT))
    return files


def test_the_served_schema_names_no_p0_total() -> None:
    schema = json.dumps(app.main.create_app().openapi())

    assert "bar_price_total_cents" in schema  # the scan reads the real document
    assert banned_names(schema) == []


def test_the_web_source_and_the_export_name_no_p0_total() -> None:
    found = [
        f"{path.as_posix()}: {name}"
        for path in scanned_files()
        for name in banned_names((REPO_ROOT / path).read_text(encoding="utf-8"))
    ]

    assert found == [], "\n".join(["p0_* names, which AC13 forbids:", *found])


def test_the_scan_reaches_the_real_trees() -> None:
    files = scanned_files()

    for path in MUST_SEE:
        assert path in files, f"{path.as_posix()} was not scanned"


@pytest.mark.parametrize(
    "sample",
    ['{"p0_total": 1}', "export const p0_per_drink = {}", "row['p0_total_cents']"],
)
def test_the_detector_flags_each_banned_name(sample: str) -> None:
    assert banned_names(sample) != []


def test_the_detector_permits_the_new_names() -> None:
    assert banned_names('{"bar_price_total_cents": 1, "p0_cents": 250}') == []
