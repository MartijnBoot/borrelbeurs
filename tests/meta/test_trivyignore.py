"""AC4 (Phase 8 T12, SD21): every Trivy waiver says why, and when it expires.

`.trivyignore` holds the IDs the image scan may ignore. Each entry is a `# reason:`
comment line followed by `<ID> exp:<yyyy-mm-dd>` -- Trivy's own expiry syntax, so an
expired waiver stops being honoured on its own. A bare ID, or one without a reason,
would be a silent, permanent waiver.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

TRIVYIGNORE = Path(__file__).resolve().parents[2] / ".trivyignore"
ENTRY = re.compile(r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]*) exp:(?P<exp>\d{4}-\d{2}-\d{2})$")
REASON = re.compile(r"^#\s*reason:\s*\S")


def faults(text: str) -> list[str]:
    """One line per entry that lacks its reason or its expiry."""
    found = []
    previous = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            match = ENTRY.match(line)
            if match is None:
                found.append(f"line {number}: {line!r} has no `exp:<yyyy-mm-dd>`")
            else:
                try:
                    date.fromisoformat(match["exp"])
                except ValueError:
                    found.append(f"line {number}: {match['exp']} is not a date")
            if not REASON.match(previous):
                found.append(f"line {number}: {line!r} has no `# reason:` line before it")
        previous = line
    return found


def test_the_committed_waivers_each_have_a_reason_and_an_expiry() -> None:
    assert faults(TRIVYIGNORE.read_text(encoding="utf-8")) == []


def test_a_well_formed_entry_passes() -> None:
    text = "# reason: not reachable from the app; MB, 2026-10-10\nCVE-2026-0001 exp:2026-12-31\n"

    assert faults(text) == []


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        pytest.param("CVE-2026-0001 exp:2026-12-31\n", "reason", id="no-reason"),
        pytest.param("# reason: upstream fix pending\nCVE-2026-0001\n", "exp:", id="no-expiry"),
        pytest.param(
            "# reason: upstream fix pending\n\nCVE-2026-0001 exp:2026-12-31\n",
            "reason",
            id="reason-not-adjacent",
        ),
        pytest.param(
            "# reason: x\nCVE-2026-0001 exp:2026-13-45\n", "not a date", id="impossible-date"
        ),
    ],
)
def test_an_entry_missing_either_fails(text: str, missing: str) -> None:
    (fault,) = faults(text)

    assert missing in fault
