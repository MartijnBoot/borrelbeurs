"""The theme token manifest, pure (Phase 4 T1: SD5-SD7; AC9, AC10 server halves; PD2, PD3).

The values are checked against v1's `theme.js` itself, parsed here, so a
transcription error in `app/runtime/theme.py` fails rather than ships.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.runtime.theme import (
    DEFAULT_PRESET,
    HEX,
    PRESETS,
    TOKEN_NAMES,
    CustomTheme,
    render_css,
    resolve,
)

THEME_JS = Path(__file__).resolve().parents[2] / "legacy" / "v1" / "static" / "theme.js"
# SD6's split: new token -> the v1 token whose value it takes.
SPLIT = {
    "--candle-up": "--up",
    "--candle-down": "--down",
    "--tile-rising": "--down",
    "--tile-falling": "--up",
}


def _v1_presets() -> dict[str, dict[str, str]]:
    """`THEMES` from v1's theme.js: preset name -> {token: value}, in source order."""
    source = THEME_JS.read_text(encoding="utf-8")
    block = source[source.index("var THEMES = {") : source.index("function _loadCustomVars")]
    presets: dict[str, dict[str, str]] = {}
    for name, body in re.findall(r"(\w+): \{(.*?)\n    \}", block, flags=re.DOTALL):
        presets[name] = dict(re.findall(r"'(--[\w-]+)': '(#[0-9a-f]{6})'", body))
    return presets


V1 = _v1_presets()


def test_v1_has_five_presets_of_22_tokens() -> None:
    assert sorted(V1) == ["blauw", "groen", "oudgeld", "paars", "rood"]
    assert {len(tokens) for tokens in V1.values()} == {22}


def test_the_manifest_has_24_tokens_and_every_preset_the_same_keys() -> None:
    """PD2: v1's 22 minus --up/--down plus the four split tokens."""
    assert len(TOKEN_NAMES) == 24
    assert len(set(TOKEN_NAMES)) == 24
    for preset in PRESETS.values():
        assert tuple(preset.tokens) == TOKEN_NAMES


def test_the_manifest_keeps_v1_order_with_the_split_in_place_of_up_down() -> None:
    v1_order = list(next(iter(V1.values())))
    at = v1_order.index("--up")
    expected = [*v1_order[:at], *SPLIT, *v1_order[at + 2 :]]
    assert list(TOKEN_NAMES) == expected


def test_the_presets_are_v1s_five_with_dutch_labels() -> None:
    assert sorted(PRESETS) == sorted(V1)
    labels = {name: preset.label for name, preset in PRESETS.items()}
    assert labels == {
        "oudgeld": "Oud Geld",
        "blauw": "Blauw",
        "groen": "Groen",
        "paars": "Paars",
        "rood": "Rood",
    }


@pytest.mark.parametrize(
    ("preset", "token"),
    [(p, t) for p in sorted(V1) for t in V1[p] if t not in ("--up", "--down")],
)
def test_every_shared_value_is_v1s_verbatim(preset: str, token: str) -> None:
    assert PRESETS[preset].tokens[token] == V1[preset][token]  # type: ignore[index]


@pytest.mark.parametrize("preset", sorted(V1))
def test_the_split_maps_up_and_down_per_sd6(preset: str) -> None:
    """Candles keep up/down; tiles pulse rising in v1's down colour, falling in its up."""
    tokens = PRESETS[preset].tokens  # type: ignore[index]
    for new, old in SPLIT.items():
        assert tokens[new] == V1[preset][old]


@pytest.mark.parametrize(
    ("preset", "font"),
    [
        ("oudgeld", "'EB Garamond', Georgia, serif"),
        ("blauw", "Inter, system-ui, sans-serif"),
        ("groen", "Inter, system-ui, sans-serif"),
        ("paars", "Inter, system-ui, sans-serif"),
        ("rood", "Inter, system-ui, sans-serif"),
    ],
)
def test_the_font_per_preset(preset: str, font: str) -> None:
    """PD3: Oud Geld is EB Garamond (v1's override), every other preset Inter."""
    assert PRESETS[preset].font_family == font  # type: ignore[index]


def test_the_swatches_are_v1s_theme_meta() -> None:
    assert PRESETS["oudgeld"].swatches == ("#0e0c07", "#16130a", "#c9a84c", "#7dab6e")
    assert PRESETS["rood"].swatches == ("#0f0505", "#1a0808", "#f87171", "#ef4444")


def test_the_default_preset_is_blauw() -> None:
    """SD5: no stored row means Blauw."""
    assert DEFAULT_PRESET == "blauw"


def test_resolve_carries_the_presets_tokens_font_and_revision() -> None:
    theme = resolve("rood", 7)
    assert theme.preset == "rood"
    assert theme.revision == 7
    assert theme.tokens == PRESETS["rood"].tokens
    assert theme.font_family == PRESETS["rood"].font_family


def test_resolve_refuses_an_unknown_preset() -> None:
    with pytest.raises(KeyError):
        resolve("eigen", 1)  # type: ignore[arg-type]


def test_resolve_refuses_a_negative_revision() -> None:
    with pytest.raises(ValueError):
        resolve("blauw", -1)


@pytest.mark.parametrize("preset", sorted(V1))
def test_render_css_holds_every_token_and_the_body_rule(preset: str) -> None:
    theme = resolve(preset, 1)  # type: ignore[arg-type]
    css = render_css(theme)
    root = css[css.index(":root{") : css.index("}") + 1]
    for name in TOKEN_NAMES:
        assert f"{name}:{theme.tokens[name]};" in root
    assert f"body{{background:var(--bg);color:var(--text);font-family:{theme.font_family}}}" in css


def test_blauw_at_revision_0_renders_inter_and_blauws_background() -> None:
    """AC9 server half: the fallback theme is Blauw, in Inter."""
    css = render_css(resolve(DEFAULT_PRESET, 0))
    assert "--bg:#070b16;" in css
    assert "font-family:Inter, system-ui, sans-serif" in css


def test_oud_geld_renders_the_eb_garamond_stack() -> None:
    """AC10 server half."""
    assert "font-family:'EB Garamond', Georgia, serif" in render_css(resolve("oudgeld", 1))


# --- Phase 6 T17: the custom theme (SD28) --------------------------------------


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_preset_value_matches_hex(preset: str) -> None:
    """SD28: only a hex colour reaches `/theme.css`; the presets already are."""
    for name, value in PRESETS[preset].tokens.items():  # type: ignore[index]
        assert HEX.fullmatch(value), (preset, name, value)


def test_custom_resolves_from_the_stored_tokens_and_font() -> None:
    tokens = {name: f"#{i:06x}" for i, name in enumerate(TOKEN_NAMES)}

    theme = resolve("custom", 3, custom=CustomTheme(tokens=tokens, font="garamond"))

    assert (theme.preset, theme.revision) == ("custom", 3)
    assert dict(theme.tokens) == tokens
    assert theme.font_family == PRESETS["oudgeld"].font_family
    css = render_css(theme)
    assert all(f"{name}:{value};" in css for name, value in tokens.items())


def test_custom_without_stored_tokens_is_refused() -> None:
    with pytest.raises(ValueError, match="custom"):
        resolve("custom", 1)
