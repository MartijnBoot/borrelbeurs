"""The pixel icons' contact sheet and favicon (B-02 SD8, SD9; plan PD8-PD11).

    uv run python -m scripts.pixel_icons sheet [--out PATH]
    uv run python -m scripts.pixel_icons favicon [--out PATH]

Both read `web/src/components/ui/pixelIcons.json`, the grids the app draws.

`sheet` writes `.dev/pixel-icons.html` (gitignored, never part of the built
app): every icon at 1x, 2x and 4x on each of the five presets, in the colour of
the spot it goes in, beside the emoji or symbol it replaces; and the favicon at
the same three scales on a light and a dark tab bar. The owner approves the
drawings from it before any icon is placed on a page (SD9).

`favicon` writes `web/public/favicon.png`: the `favicon` grid at 4x (64x64),
every on pixel with an off neighbour -- of its 8, or outside the grid -- in
the outline colour, every other on pixel in the fill, the rest transparent
(PD8). The colours are fixed (SD8); the favicon does not follow the theme.

The presets come from `app.runtime.theme`, the manifest `/theme.css` is
rendered from, not a copy. Stdlib otherwise, like `check_built_assets.py`.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import sys
import zlib
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import Final

from app.runtime.theme import BuiltinPreset, resolve

ROOT: Final = Path(__file__).resolve().parents[1]
GRIDS: Final = ROOT / "web" / "src" / "components" / "ui" / "pixelIcons.json"
DEFAULT_SHEET: Final = ROOT / ".dev" / "pixel-icons.html"
DEFAULT_FAVICON: Final = ROOT / "web" / "public" / "favicon.png"

PRESETS: Final[tuple[BuiltinPreset, ...]] = ("oudgeld", "blauw", "groen", "paars", "rood")

# SD8: preset `blauw`'s `--accent` and `--bg`.
FAVICON_FILL: Final = "#60a5fa"
FAVICON_OUTLINE: Final = "#070b16"

# Grid -> (spot, what it replaces, the spot's colour) -- SD4, SD10, plan PD10; B-04 SD11
# adds `floppy` and B-05 SD25 `wallet`, which replace nothing.
# A colour is a theme token, or `banner-crash` / `banner-bubble`: white on the
# banner's own background (`styles/keyframes.css`).
SPOTS: Final[dict[str, tuple[str, str, str]]] = {
    "broom": ("Systeemacties", "🧹", "--text"),
    "gear": ("Globale instellingen", "⚙️", "--text"),
    "palette": ("Kleurenschema", "🎨", "--text"),
    "picture": ("Afbeeldingen", "🖼️", "--text"),
    "cup": ("Drankjes beheren", "🥤", "--text"),
    "padlock": ("Min/Max/Startprijs", "🔒", "--text"),
    "chart": ("Vraag/Aanbod", "📈", "--text"),
    "key": ("Toegangssleutels", "🔑", "--text"),
    "newspaper": ("Nieuws", "📰", "--text"),
    "burst": ("Market events", "💥", "--text"),
    "bolt": ("Price jump", "⚡", "--text"),
    "hourglass": ("Idle", "⏳", "--text"),
    "beer": ("Bar — Bestellen", "🍺", "--text"),
    "banknote": ("Financieel overzicht", "💶", "--text"),
    "warning": ("MARKTCRASH", "⚠", "banner-crash"),
    "arrowUp": ("PRIJSBUBBEL", "▲", "banner-bubble"),
    "floppy": ("Instellingen \u203a Profielen", "(nieuw)", "--text"),
    "wallet": ("Instellingen \u203a Wallets", "(nieuw)", "--text"),
    "stop": ("Sluit app", "⛔", "--text"),
    "rise": ("Prijs stijgt", "▲", "--muted"),
    "fall": ("Prijs daalt", "▼", "--muted"),
    "chevronDown": ("Menu", "▾", "--accent"),
}

FAVICON_BACKGROUNDS: Final = {"light": "#ffffff", "dark": "#202124"}

Grid = list[str]
Rgba = tuple[int, int, int, int]


def load_grids(path: Path = GRIDS) -> dict[str, Grid]:
    """The grids by name; `ValueError` naming the first one that is not a drawing (AC1)."""
    grids: dict[str, Grid] = json.loads(path.read_text(encoding="utf-8"))
    for name, grid in grids.items():
        n = len(grid)
        if not (
            n > 0
            and all(isinstance(row, str) and re.fullmatch(r"[#.]+", row) for row in grid)
            and all(len(row) == n for row in grid)
            and any("#" in row for row in grid)
        ):
            raise ValueError(f"grid {name!r} is not square rows of '#' and '.' with a '#'")
    return grids


def svg(grid: Grid, px: int) -> str:
    """`grid` as `PixelIcon` draws it (PD2), `px` CSS pixels square."""
    d = "".join(
        f"M{m.start()} {y}h{len(m[0])}v1h-{len(m[0])}z"
        for y, row in enumerate(grid)
        for m in re.finditer("#+", row)
    )
    n = len(grid)
    return (
        f'<svg viewBox="0 0 {n} {n}" width="{px}" height="{px}" fill="currentColor"'
        f' shape-rendering="crispEdges"><path d="{d}"/></svg>'
    )


def _rgba(hex_: str) -> Rgba:
    return (int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16), 255)


def favicon_rgba(grid: Grid) -> list[list[Rgba]]:
    """PD8: outline where an on pixel has an off 8-neighbour, fill inside, transparent off."""
    n = len(grid)

    def on(x: int, y: int) -> bool:
        return 0 <= x < n and 0 <= y < n and grid[y][x] == "#"

    def pixel(x: int, y: int) -> Rgba:
        if not on(x, y):
            return (0, 0, 0, 0)
        inside = all(on(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        return _rgba(FAVICON_FILL if inside else FAVICON_OUTLINE)

    return [[pixel(x, y) for x in range(n)] for y in range(n)]


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def encode_png(rgba: list[list[Rgba]], scale: int = 4) -> bytes:
    """An RGBA PNG of `rgba`, each pixel `scale` x `scale`; byte-identical for the same input."""
    height, width = len(rgba) * scale, len(rgba[0]) * scale
    raw = b"".join(
        b"\x00" + b"".join(bytes(rgba[y // scale][x // scale]) for x in range(width))
        for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _spot_style(colour: str, tokens: dict[str, str]) -> str:
    if colour.startswith("banner-"):
        event = tokens["--danger" if colour == "banner-crash" else "--warn"]
        return (
            f"color:#fff;background:color-mix(in srgb, {event} 85%, black);"
            f"border:2px solid {event};border-radius:8px"
        )
    return f"color:{tokens[colour]}"


def sheet_html(grids: dict[str, Grid]) -> str:
    """The contact sheet (SD9, PD10)."""
    blocks = []
    for preset in PRESETS:
        tokens = dict(resolve(preset, 0).tokens)
        rows = []
        for name, (spot, replaced, colour) in SPOTS.items():
            grid = grids[name]
            n = len(grid)
            icons = "".join(
                svg(grid, n * scale).replace(
                    "<svg ", f'<svg data-preset="{preset}" data-icon="{name}" data-scale="{scale}" '
                )
                for scale in (1, 2, 4)
            )
            rows.append(
                f'<div class="row"><span class="cell" style="{_spot_style(colour, tokens)}">'
                f'<span class="was" style="font-size:{2 * n}px">{replaced}</span>{icons}</span>'
                f'<span class="name" style="color:{tokens["--muted"]}">{escape(spot)}'
                f" · {name} · {n}x{n}</span></div>"
            )
        blocks.append(
            f'<section style="background:{tokens["--bg"]};color:{tokens["--text"]}">'
            f"<h2>{preset}</h2>{''.join(rows)}</section>"
        )
    png = base64.b64encode(encode_png(favicon_rgba(grids["favicon"]))).decode()
    tabs = "".join(
        f'<div class="row" style="background:{bg}">'
        + "".join(
            f'<img data-favicon="{shade}" data-scale="{scale}" width="{16 * scale}"'
            f' height="{16 * scale}" alt="" src="data:image/png;base64,{png}">'
            for scale in (1, 2, 4)
        )
        + "</div>"
        for shade, bg in FAVICON_BACKGROUNDS.items()
    )
    return (
        '<!doctype html><html lang="nl"><head><meta charset="utf-8">'
        "<title>BorrelBeurs pixel icons</title><style>"
        "body{margin:0;font:14px system-ui,sans-serif;background:#888}"
        "section{padding:12px 20px}h2{margin:4px 0 10px}"
        ".row{display:flex;align-items:center;gap:16px;padding:4px 8px}"
        ".cell{display:flex;align-items:center;gap:12px;padding:6px 10px;min-width:180px}"
        ".was{line-height:1;min-width:2.2em}"
        "img{image-rendering:pixelated}"
        "</style></head><body>"
        + "".join(blocks)
        + f"<section><h2>favicon</h2>{tabs}</section></body></html>\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.pixel_icons", description=__doc__)
    parser.add_argument("what", choices=("sheet", "favicon"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    grids = load_grids()
    if args.what == "sheet":
        out = args.out or DEFAULT_SHEET
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(sheet_html(grids), encoding="utf-8", newline="\n")
    else:
        out = args.out or DEFAULT_FAVICON
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(encode_png(favicon_rgba(grids["favicon"])))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
