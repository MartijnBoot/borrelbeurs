"""Phase 4 T22 -- the built-output reference check (AC2, D-13).

`scripts/check_built_assets.py` fails on an absolute URL with a host in a
reference position of the built bundle. Each position gets a fixture `dist`
that must fail; the bare strings a real bundle carries -- XML namespace URIs,
docs links in error messages, an anchor `href` set from JS, react-router's
`new URL("http://localhost")` parse base -- must pass. `new URL(...)` counts
only in its loading form, `new URL(<url>, import.meta.url)` (human decision,
2026-10-05).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_built_assets import find_references, main

INDEX = (
    '<!doctype html><html><head><script type="module" src="/assets/i.js"></script></head></html>'
)


def _dist(tmp_path: Path, files: dict[str, str]) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    for name, text in files.items():
        (dist / name).write_text(text, encoding="utf-8")
    return dist


FAILING = {
    "html script src": ("index.html", '<script src="https://cdn.example.com/x.js"></script>'),
    "html link href": (
        "index.html",
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">',
    ),
    "html protocol-relative": ("index.html", "<img src=//cdn.example.com/a.png>"),
    "html srcset": ("index.html", '<img srcset="/a.png 1x, https://cdn.example.com/b.png 2x">'),
    "html inline style url": (
        "index.html",
        "<style>body{background:url(https://cdn.example.com/bg.png)}</style>",
    ),
    "css url": ("assets/a.css", "@font-face{src:url(https://fonts.gstatic.com/x.woff2)}"),
    "css quoted url": ("assets/a.css", "a{background:url('//cdn.example.com/a.png')}"),
    "css import": ("assets/a.css", '@import "https://fonts.googleapis.com/css2?family=Inter";'),
    "css import url": ("assets/a.css", "@import url(https://cdn.example.com/a.css);"),
    "js dynamic import": ("assets/a.js", 'const m=import("https://cdn.example.com/m.js")'),
    "js import from": ("assets/a.js", 'import{a as b}from"https://cdn.example.com/m.js";'),
    "js side-effect import": ("assets/a.js", "import'https://cdn.example.com/m.js';"),
    "js export from": ("assets/a.js", 'export*from"https://cdn.example.com/m.js";'),
    "js new URL with import.meta.url": (
        "assets/a.js",
        'const u=new URL("https://cdn.example.com/a.png",import.meta.url)',
    ),
    "js fetch": ("assets/a.js", "fetch(`https://api.example.com/x`)"),
    "js importScripts": ("assets/a.js", "importScripts('https://cdn.example.com/w.js')"),
    "js new Worker": ("assets/a.js", 'new Worker("https://cdn.example.com/w.js")'),
    "js new SharedWorker": ("assets/a.js", 'new SharedWorker("//cdn.example.com/w.js")'),
    "webmanifest icon": (
        "manifest.webmanifest",
        '{"icons":[{"src":"https://cdn.example.com/i.png","sizes":"192x192"}]}',
    ),
}

PASSING = {
    "svg namespace": ("assets/a.js", 'createElementNS("http://www.w3.org/2000/svg",t)'),
    "xlink and mathml namespaces": (
        "assets/a.js",
        'n="http://www.w3.org/1999/xlink";m=`http://www.w3.org/1998/Math/MathML`',
    ),
    "href in an inert JS string": (
        "assets/a.js",
        "this.a=document.createElement(`a`),this.a.href=`https://www.tradingview.com/?x=1`",
    ),
    "docs link in an error message": (
        "assets/a.js",
        "throw Error(`Minified error; visit https://react.dev/errors/`+e)",
    ),
    "new URL parse base": ("assets/a.js", "var Ge=new URL(`http://localhost`);"),
    "new URL with a relative URL": ("assets/a.js", 'new URL("./a.png",import.meta.url)'),
    "origin-relative references": (
        "index.html",
        '<link rel="stylesheet" href="/theme.css"><script src="/assets/i.js"></script>',
    ),
    "relative css url": ("assets/a.css", "@font-face{src:url(/assets/inter.woff2)}"),
    "data uri": ("assets/a.css", "a{background:url(data:image/png;base64,AAAA)}"),
    "js comment": ("assets/a.js", "// see https://example.com\nconst a=1"),
    "relative import": ("assets/a.js", 'import("./chunk.js");import{a}from"./b.js"'),
}


@pytest.mark.parametrize("case", sorted(FAILING))
def test_a_reference_position_with_a_host_fails(tmp_path: Path, case: str) -> None:
    name, text = FAILING[case]
    dist = _dist(tmp_path, {name: text})
    findings = find_references(dist)
    assert len(findings) == 1, findings
    assert findings[0].path == dist / name
    assert main([str(dist)]) == 1


@pytest.mark.parametrize("case", sorted(PASSING))
def test_an_inert_string_or_an_origin_reference_passes(tmp_path: Path, case: str) -> None:
    name, text = PASSING[case]
    dist = _dist(tmp_path, {name: text})
    assert find_references(dist) == []
    assert main([str(dist)]) == 0


def test_a_finding_names_file_line_and_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dist = _dist(tmp_path, {"assets/a.css": "a{}\nb{background:url(https://x.example/b.png)}"})
    assert main([str(dist)]) == 1
    err = capsys.readouterr().err
    assert "assets/a.css:2" in err.replace("\\", "/")
    assert "https://x.example/b.png" in err


def test_a_missing_or_empty_dist_is_an_error_not_a_pass(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2
    (tmp_path / "empty").mkdir()
    assert main([str(tmp_path / "empty")]) == 2
