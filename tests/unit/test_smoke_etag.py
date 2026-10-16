"""`scripts/smoke.py` reads the theme ETag as a proxy delivers it (Phase 8 T23, amendment A2).

Render's Cloudflare turns `ETag: "theme-0-blauw"` into `etag: W/"theme-0-blauw"` (weak, and a
lowercase name); the first deploy's smoke run failed on it (defect D-H1-1).
"""

from __future__ import annotations

import pytest

from scripts.smoke import SmokeFailed, theme_preset


@pytest.mark.parametrize(
    "headers",
    [
        {"ETag": '"theme-3-blauw"'},
        {"ETag": 'W/"theme-3-blauw"'},
        {"etag": 'W/"theme-3-blauw"'},
        {"ETAG": '"theme-3-blauw"'},
    ],
)
def test_the_revision_and_preset_come_out_of_any_delivery_of_the_etag(
    headers: dict[str, str],
) -> None:
    assert theme_preset(headers) == (3, "blauw")


@pytest.mark.parametrize(
    "headers, received",
    [
        ({"Content-Type": "text/css"}, "None"),
        ({"etag": '"theme-x-blauw"'}, '"theme-x-blauw"'),
        ({"ETag": '"other"'}, '"other"'),
    ],
)
def test_anything_else_fails_and_says_what_was_received(
    headers: dict[str, str], received: str
) -> None:
    with pytest.raises(SmokeFailed, match=received):
        theme_preset(headers)
