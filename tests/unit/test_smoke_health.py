"""`scripts/smoke.py` waits for a serving instance, not a standby one (Phase 8 T24, amendment A3).

On Render the new instance boots into standby (SD4), and its `/healthz` is 200 with the new
`build_sha` by design (SD5). The smoke run took that as healthy and logged in to `503 standby`
(defect D-H1-2): step 1 must also want `status == "ok"`.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.smoke import serving

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize("expect_sha", [SHA, None])
def test_a_serving_instance_of_the_right_build_passes(expect_sha: str | None) -> None:
    assert serving(200, {"status": "ok", "build_sha": SHA}, expect_sha)


@pytest.mark.parametrize(
    "status, body, expect_sha",
    [
        (200, {"status": "standby", "build_sha": SHA}, SHA),
        (200, {"status": "stale", "build_sha": SHA}, SHA),
        (200, {"status": "ok", "build_sha": "f" * 40}, SHA),
        (503, {"status": "ok", "build_sha": SHA}, SHA),
        (200, None, SHA),
        (200, {"status": "standby", "build_sha": SHA}, None),
        (200, None, None),
    ],
)
def test_anything_short_of_serving_that_build_is_refused(
    status: int, body: Any, expect_sha: str | None
) -> None:
    assert not serving(status, body, expect_sha)
