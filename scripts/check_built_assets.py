"""Fail if the built web bundle references another origin (AC2, D-13).

    uv run python scripts/check_built_assets.py web/dist

v1 loaded Inter from Google Fonts and lightweight-charts from a CDN, so a
borrel without internet had no board. Phase 4 bundles everything; this check
keeps it that way by scanning the built output -- what is actually served --
for an absolute URL with a host (`http://`, `https://`, `//host`) in a
**reference position**, one regex per file type:

- HTML: `src`, `href` and `srcset` on any tag (`<link>` included), and the
  CSS positions inside inline `<style>`;
- CSS: `url(...)` and `@import`;
- JS: `import(...)`, `import ... from`, `export ... from`, a side-effect
  `import "..."`, `fetch(...)`, `importScripts(...)`, `new Worker(...)` /
  `new SharedWorker(...)`, and `new URL(<url>, import.meta.url)` -- the form
  that loads a file. A bare `new URL("http://localhost")` is a parse base, not
  a request (react-router ships one), and does not count (human decision,
  2026-10-05);
- `.webmanifest`: each icon's `src`.

A URL anywhere else is an inert string -- the SVG/XLink/MathML namespaces
React carries, docs links in error messages, the chart library's attribution
anchor `href` set from JS -- and passes. Requests at runtime are proved
separately, in a browser with every non-origin request blocked (T24, AC1).

Exit 0: clean. Exit 1: findings, one `path:line: position: url` per line on
stderr. Exit 2: no `index.html` in the directory -- a missing build must not
pass as a clean one.

Stdlib only, so the gate needs nothing beyond the project's Python.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# An absolute URL with a host: a scheme of http(s) or protocol-relative.
_ABS = r"(?:https?:)?//[^\s/'\"`)>]"
_Q = r"[\"'`]"
_URL_TAIL = r"[^\"'`\s)]*"

_CSS = [
    ("css url()", re.compile(rf"url\(\s*[\"']?(?P<url>{_ABS}[^\"')\s]*)")),
    ("css @import", re.compile(rf"@import\s+[\"'](?P<url>{_ABS}[^\"']*)")),
]

_JS = [
    ("js import()", re.compile(rf"\bimport\(\s*{_Q}(?P<url>{_ABS}{_URL_TAIL})")),
    (
        "js import/export from",
        re.compile(
            rf"\b(?:import|export)\s*[\w$\s{{}},*]*?\bfrom\s*{_Q}(?P<url>{_ABS}{_URL_TAIL})"
        ),
    ),
    ("js side-effect import", re.compile(rf"\bimport\s*{_Q}(?P<url>{_ABS}{_URL_TAIL})")),
    ("js fetch()", re.compile(rf"\bfetch\(\s*{_Q}(?P<url>{_ABS}{_URL_TAIL})")),
    ("js importScripts()", re.compile(rf"\bimportScripts\(\s*{_Q}(?P<url>{_ABS}{_URL_TAIL})")),
    (
        "js new Worker()",
        re.compile(rf"\bnew\s+(?:Shared)?Worker\(\s*{_Q}(?P<url>{_ABS}{_URL_TAIL})"),
    ),
    (
        "js new URL(…, import.meta.url)",
        re.compile(rf"\bnew\s+URL\(\s*{_Q}(?P<url>{_ABS}{_URL_TAIL}){_Q}\s*,\s*import\.meta\.url"),
    ),
]

_HTML_ATTR = re.compile(
    r"\b(?P<attr>src|href|srcset)\s*=\s*(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>[^\s>]+))",
    re.I,
)
_ABS_VALUE = re.compile(rf"^\s*{_ABS}")


_Hits = Iterator[tuple[int, str, str]]


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    position: str
    url: str


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan(text: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> _Hits:
    for position, pattern in patterns:
        for match in pattern.finditer(text):
            yield match.start(), position, match.group("url")


def _scan_html(text: str) -> _Hits:
    for match in _HTML_ATTR.finditer(text):
        attr = match.group("attr").lower()
        value = match.group("dq") or match.group("sq") or match.group("bare") or ""
        candidates = (
            [c.split()[0] for c in value.split(",") if c.strip()] if attr == "srcset" else [value]
        )
        for url in candidates:
            if _ABS_VALUE.match(url):
                yield match.start(), f"html {attr}", url.strip()
    yield from _scan(text, _CSS)


def _scan_css(text: str) -> _Hits:
    return _scan(text, _CSS)


def _scan_js(text: str) -> _Hits:
    return _scan(text, _JS)


def _scan_manifest(text: str) -> _Hits:
    try:
        icons = json.loads(text).get("icons", [])
    except (ValueError, AttributeError):
        return
    for icon in icons:
        src = icon.get("src", "") if isinstance(icon, dict) else ""
        if isinstance(src, str) and _ABS_VALUE.match(src):
            yield text.find(src), "webmanifest icon", src


def _scanner(path: Path) -> Callable[[str], _Hits] | None:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return _scan_html
    if suffix == ".css":
        return _scan_css
    if suffix in {".js", ".mjs"}:
        return _scan_js
    if suffix == ".webmanifest" or path.name == "manifest.json":
        return _scan_manifest
    return None


def find_references(dist: Path) -> list[Finding]:
    """Every absolute URL with a host in a reference position under `dist`."""
    findings: list[Finding] = []
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        scan = _scanner(path)
        if scan is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for offset, position, url in scan(text):
            findings.append(Finding(path, _line(text, max(offset, 0)), position, url))
    return findings


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print("usage: check_built_assets.py <dist>", file=sys.stderr)
        return 2
    dist = Path(argv[0])
    if not (dist / "index.html").is_file():
        print(f"check_built_assets: no index.html in {dist} -- build first", file=sys.stderr)
        return 2
    findings = find_references(dist)
    for f in findings:
        print(f"{f.path.relative_to(dist)}:{f.line}: {f.position}: {f.url}", file=sys.stderr)
    if findings:
        print(
            f"check_built_assets: {len(findings)} non-origin reference(s) in {dist}",
            file=sys.stderr,
        )
        return 1
    print(f"check_built_assets: no non-origin references in {dist}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
