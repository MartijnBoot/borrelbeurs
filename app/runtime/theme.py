"""The theme token manifest, pure (Phase 4 SD5-SD7, ADR 0005; plan PD2, PD3).

The server owns the theme: it renders `/theme.css` and sends the active preset's
tokens over the WebSocket, so the client holds no preset table (SD6). Every
value below is ported verbatim from v1's `legacy/v1/static/theme.js` (`THEMES`,
`THEME_META`); `tests/unit/test_theme_manifest.py` parses that file and fails on
any transcription error.

**24 tokens (PD2).** v1 has 22 per preset. SD6 splits its `--up`/`--down`
pair, which v1 used for both the candles and the tile pulse, into four:
`--candle-up = up`, `--candle-down = down`, and the tiles the other way round,
`--tile-rising = down`, `--tile-falling = up` -- a rising price is bad news for
the drinker, so it pulses in the "down" colour, as the board's legend says.

**The font (PD3)** is a field rather than a token: Oud Geld is EB Garamond, as
v1's override was, every other preset Inter. Both are self-hosted (D-13).

No I/O, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

PresetName = Literal["oudgeld", "blauw", "groen", "paars", "rood"]

DEFAULT_PRESET: Final[PresetName] = "blauw"

TOKEN_NAMES: Final[tuple[str, ...]] = (
    "--bg",
    "--panel",
    "--panel2",
    "--grid",
    "--text",
    "--muted",
    "--accent",
    "--primary",
    "--ok",
    "--danger",
    "--warn",
    "--candle-up",
    "--candle-down",
    "--tile-rising",
    "--tile-falling",
    "--pill",
    "--pillb",
    "--input-bg",
    "--input-border",
    "--header-top",
    "--header-bot",
    "--ticker-bg",
    "--news-bg",
    "--sma-line",
)

_INTER: Final = "Inter, system-ui, sans-serif"
_GARAMOND: Final = "'EB Garamond', Georgia, serif"


@dataclass(frozen=True)
class Preset:
    label: str
    # v1's settings-page preview colours (`THEME_META`).
    swatches: tuple[str, str, str, str]
    tokens: Mapping[str, str]
    font_family: str


@dataclass(frozen=True)
class Theme:
    """The active theme: a preset's tokens and font at a revision (0 = no stored row)."""

    preset: PresetName
    revision: int
    tokens: Mapping[str, str]
    font_family: str


def _preset(
    label: str,
    swatches: tuple[str, str, str, str],
    v1: Mapping[str, str],
    font_family: str = _INTER,
) -> Preset:
    """A preset from v1's 22 values, with SD6's split in place of `--up`/`--down`."""
    split = {
        "--candle-up": v1["--up"],
        "--candle-down": v1["--down"],
        "--tile-rising": v1["--down"],
        "--tile-falling": v1["--up"],
    }
    values = {**v1, **split}
    tokens = MappingProxyType({name: values[name] for name in TOKEN_NAMES})
    return Preset(label, swatches, tokens, font_family)


PRESETS: Final[Mapping[PresetName, Preset]] = MappingProxyType(
    {
        "oudgeld": _preset(
            "Oud Geld",
            ("#0e0c07", "#16130a", "#c9a84c", "#7dab6e"),
            {
                "--bg": "#0e0c07",
                "--panel": "#16130a",
                "--panel2": "#1a1710",
                "--grid": "#3a3320",
                "--text": "#e8dfc0",
                "--muted": "#9e9070",
                "--accent": "#c9a84c",
                "--primary": "#8b6914",
                "--ok": "#7dab6e",
                "--danger": "#b34a3a",
                "--warn": "#c8873a",
                "--up": "#7dab6e",
                "--down": "#b34a3a",
                "--pill": "#2a2510",
                "--pillb": "#4a4020",
                "--input-bg": "#110f08",
                "--input-border": "#3a3020",
                "--header-top": "#18150c",
                "--header-bot": "#0e0c07",
                "--ticker-bg": "#110f08",
                "--news-bg": "#16130a",
                "--sma-line": "#c9a84c",
            },
            _GARAMOND,
        ),
        "blauw": _preset(
            "Blauw",
            ("#070b16", "#0b1220", "#60a5fa", "#10b981"),
            {
                "--bg": "#070b16",
                "--panel": "#0b1220",
                "--panel2": "#0e1628",
                "--grid": "#1a2744",
                "--text": "#e6edf3",
                "--muted": "#9aa7bd",
                "--accent": "#60a5fa",
                "--primary": "#2563eb",
                "--ok": "#10b981",
                "--danger": "#dc2626",
                "--warn": "#f59e0b",
                "--up": "#10b981",
                "--down": "#ef4444",
                "--pill": "#111827",
                "--pillb": "#374151",
                "--input-bg": "#091226",
                "--input-border": "#243253",
                "--header-top": "#0b1325",
                "--header-bot": "#090f1c",
                "--ticker-bg": "#0a1324",
                "--news-bg": "#0b1325",
                "--sma-line": "#fbbf24",
            },
        ),
        "groen": _preset(
            "Groen",
            ("#020d0a", "#051a10", "#34d399", "#10b981"),
            {
                "--bg": "#020d0a",
                "--panel": "#051a10",
                "--panel2": "#071e12",
                "--grid": "#0d3320",
                "--text": "#d1fae5",
                "--muted": "#6ee7b7",
                "--accent": "#34d399",
                "--primary": "#059669",
                "--ok": "#10b981",
                "--danger": "#ef4444",
                "--warn": "#fbbf24",
                "--up": "#34d399",
                "--down": "#f87171",
                "--pill": "#052e16",
                "--pillb": "#14532d",
                "--input-bg": "#031a0c",
                "--input-border": "#166534",
                "--header-top": "#041810",
                "--header-bot": "#020f07",
                "--ticker-bg": "#031a0c",
                "--news-bg": "#041810",
                "--sma-line": "#fbbf24",
            },
        ),
        "paars": _preset(
            "Paars",
            ("#0d0a1a", "#12103a", "#c084fc", "#10b981"),
            {
                "--bg": "#0d0a1a",
                "--panel": "#12103a",
                "--panel2": "#0f0e2e",
                "--grid": "#2a2060",
                "--text": "#ede9fe",
                "--muted": "#a78bfa",
                "--accent": "#c084fc",
                "--primary": "#7c3aed",
                "--ok": "#10b981",
                "--danger": "#dc2626",
                "--warn": "#f59e0b",
                "--up": "#10b981",
                "--down": "#ef4444",
                "--pill": "#1e1b4b",
                "--pillb": "#4338ca",
                "--input-bg": "#0d0a1f",
                "--input-border": "#3730a3",
                "--header-top": "#12103a",
                "--header-bot": "#0a0820",
                "--ticker-bg": "#0d0a1f",
                "--news-bg": "#12103a",
                "--sma-line": "#fbbf24",
            },
        ),
        "rood": _preset(
            "Rood",
            ("#0f0505", "#1a0808", "#f87171", "#ef4444"),
            {
                "--bg": "#0f0505",
                "--panel": "#1a0808",
                "--panel2": "#150606",
                "--grid": "#3d1515",
                "--text": "#fee2e2",
                "--muted": "#fca5a5",
                "--accent": "#f87171",
                "--primary": "#dc2626",
                "--ok": "#10b981",
                "--danger": "#ef4444",
                "--warn": "#f59e0b",
                "--up": "#10b981",
                "--down": "#ef4444",
                "--pill": "#450a0a",
                "--pillb": "#7f1d1d",
                "--input-bg": "#1a0505",
                "--input-border": "#7f1d1d",
                "--header-top": "#1a0808",
                "--header-bot": "#0f0505",
                "--ticker-bg": "#1a0505",
                "--news-bg": "#1a0808",
                "--sma-line": "#fbbf24",
            },
        ),
    }
)


def resolve(preset: PresetName, revision: int) -> Theme:
    """The theme `preset` names, at `revision`; `KeyError` for a preset not in the manifest."""
    if revision < 0:
        raise ValueError(f"a theme revision is never negative, got {revision}")
    entry = PRESETS[preset]
    return Theme(preset, revision, entry.tokens, entry.font_family)


def render_css(theme: Theme) -> str:
    """`/theme.css`: the tokens on `:root`, and the body's background, text and font (SD7)."""
    tokens = "".join(f"{name}:{theme.tokens[name]};" for name in TOKEN_NAMES)
    body = f"background:var(--bg);color:var(--text);font-family:{theme.font_family}"
    return f":root{{{tokens}}}\nbody{{{body}}}\n"
