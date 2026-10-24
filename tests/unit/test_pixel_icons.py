"""B-02 T2 -- the contact sheet and the favicon (SD8, SD9; AC3, AC12; PD8-PD11).

`scripts/pixel_icons.py` reads the grids the app draws (`pixelIcons.json`) and
writes the owner's contact sheet and the favicon PNG. Its SVG must paint exactly
the grid's `#` cells, as `PixelIcon` does (`PixelIcon.test.tsx`), so the owner
approves what the app shows.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.runtime.theme import resolve
from scripts.pixel_icons import (
    DEFAULT_FAVICON,
    DEFAULT_SHEET,
    FAVICON_FILL,
    FAVICON_OUTLINE,
    PRESETS,
    SPOTS,
    encode_png,
    favicon_rgba,
    load_grids,
    main,
    svg,
)

ROOT = Path(__file__).resolve().parents[2]
TRANSPARENT = (0, 0, 0, 0)


def _cells(grid: list[str]) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c == "#"}


def _painted(markup: str) -> set[tuple[int, int]]:
    (d,) = re.findall(r' d="([^"]*)"', markup)
    runs = re.findall(r"M(\d+) (\d+)h(\d+)v1h-(\d+)z", d)
    assert "".join(f"M{x} {y}h{w}v1h-{b}z" for x, y, w, b in runs) == d
    cells: list[tuple[int, int]] = []
    for x, y, w, back in runs:
        assert back == w
        cells += [(int(x) + i, int(y)) for i in range(int(w))]
    assert len(cells) == len(set(cells)), "a cell painted twice"
    return set(cells)


def _rgb(hex_: str) -> tuple[int, int, int, int]:
    return (int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16), 255)


@pytest.mark.parametrize("name", [n for n in load_grids() if n != "favicon"])
def test_svg_paints_exactly_the_grid_cells(name: str) -> None:
    grid = load_grids()[name]
    markup = svg(grid, 4 * len(grid))
    n = len(grid)
    assert f'viewBox="0 0 {n} {n}"' in markup
    assert 'fill="currentColor"' in markup
    assert 'shape-rendering="crispEdges"' in markup
    assert _painted(markup) == _cells(grid)


@pytest.mark.parametrize(
    ("grids", "fault"),
    [
        ({"x": ["#.", "#"]}, "x"),
        ({"x": ["#.", ".."], "y": ["..", ".."]}, "y"),
        ({"x": ["#o", ".."]}, "x"),
        ({"x": []}, "x"),
    ],
    ids=["ragged", "empty-drawing", "bad-character", "no-rows"],
)
def test_a_bad_grid_is_refused_by_name(
    tmp_path: Path, grids: dict[str, list[str]], fault: str
) -> None:
    path = tmp_path / "grids.json"
    path.write_text(json.dumps(grids), encoding="utf-8")

    with pytest.raises(ValueError, match=f"'{fault}'"):
        load_grids(path)


def test_the_favicon_outline_is_every_on_pixel_with_an_off_neighbour() -> None:
    """PD8: 8-neighbour, and outside the grid counts as off."""
    grid = [
        ".....",
        ".###.",
        ".###.",
        ".###.",
        "....#",
    ]
    o, f, t = _rgb(FAVICON_OUTLINE), _rgb(FAVICON_FILL), TRANSPARENT

    assert favicon_rgba(grid) == [
        [t, t, t, t, t],
        [t, o, o, o, t],
        [t, o, f, o, t],
        [t, o, o, o, t],
        [t, t, t, t, o],
    ]


def test_the_favicon_colours_are_sd8s() -> None:
    blauw = resolve("blauw", 0).tokens
    assert (FAVICON_FILL, FAVICON_OUTLINE) == ("#60a5fa", "#070b16")
    assert (blauw["--accent"], blauw["--bg"]) == (FAVICON_FILL, FAVICON_OUTLINE)


def _decode_png(data: bytes) -> tuple[int, int, list[list[tuple[int, ...]]]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    chunks: dict[bytes, bytes] = {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + body)
        chunks[kind] = chunks.get(kind, b"") + body
        pos += 12 + length
    assert list(chunks) == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour, *_ = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (depth, colour) == (8, 6)
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = 1 + 4 * width
    rows = []
    for y in range(height):
        line = raw[y * stride : (y + 1) * stride]
        assert line[0] == 0
        rows.append([tuple(line[1 + 4 * x : 5 + 4 * x]) for x in range(width)])
    return width, height, rows


def test_the_favicon_png_is_the_grid_at_four_times() -> None:
    rgba = favicon_rgba(load_grids()["favicon"])

    width, height, pixels = _decode_png(encode_png(rgba, scale=4))

    assert (width, height) == (64, 64)
    assert pixels == [[rgba[y // 4][x // 4] for x in range(64)] for y in range(64)]
    assert {p for row in pixels for p in row} == {
        TRANSPARENT,
        _rgb(FAVICON_FILL),
        _rgb(FAVICON_OUTLINE),
    }


class _Sheet(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.icons: list[tuple[str, str, str]] = []
        self.favicons: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "svg" and "data-icon" in a:
            self.icons.append((str(a["data-preset"]), str(a["data-icon"]), str(a["data-scale"])))
        if tag == "img" and "data-favicon" in a:
            self.favicons.append((str(a["data-favicon"]), str(a["data-scale"])))


def test_the_sheet_shows_every_icon_on_every_preset_at_three_scales(tmp_path: Path) -> None:
    """AC3."""
    out = tmp_path / "sheet" / "icons.html"

    assert main(["sheet", "--out", str(out)]) == 0

    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [out]
    html = out.read_text(encoding="utf-8")
    sheet = _Sheet()
    sheet.feed(html)
    names = [n for n in load_grids() if n != "favicon"]
    assert sorted(sheet.icons) == sorted(
        (preset, name, scale) for preset in PRESETS for name in names for scale in ("1", "2", "4")
    )
    assert sorted(sheet.favicons) == sorted(
        (bg, scale) for bg in ("light", "dark") for scale in ("1", "2", "4")
    )
    for preset in PRESETS:
        assert resolve(preset, 0).tokens["--bg"] in html
    for _label, replaced, _colour in SPOTS.values():
        assert replaced in html


def test_every_drawn_icon_has_a_spot_and_the_presets_are_the_five() -> None:
    assert set(SPOTS) == set(load_grids()) - {"favicon"}
    assert PRESETS == ("oudgeld", "blauw", "groen", "paars", "rood")


def test_the_sheet_is_not_part_of_the_built_app() -> None:
    """AC3: written under the gitignored `.dev/`, never under `web/`."""
    assert DEFAULT_SHEET == ROOT / ".dev" / "pixel-icons.html"
    assert not DEFAULT_SHEET.is_relative_to(ROOT / "web")


def test_the_committed_favicon_is_the_grid_pixel_for_pixel() -> None:
    """AC12, PD9: a redraw of the `favicon` grid fails here until the PNG is regenerated
    (`uv run python -m scripts.pixel_icons favicon`). Pixels, not bytes: another zlib
    build may deflate the same pixels differently."""
    assert DEFAULT_FAVICON == ROOT / "web" / "public" / "favicon.png"
    expected = encode_png(favicon_rgba(load_grids()["favicon"]))
    assert _decode_png(DEFAULT_FAVICON.read_bytes()) == _decode_png(expected)
