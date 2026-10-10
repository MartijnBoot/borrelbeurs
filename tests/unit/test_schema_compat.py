"""Phase 8 SD3, PD2: the boot rule as a table of cases.

`decide` is pure: which revisions this image's scripts know, what `alembic_version`
holds, and what `schema_compat.min_code_revision` holds. The reading and the acting
are `read_db_state` and `app/runtime/boot.py`, tested in `tests/integration/test_boot.py`.
"""

from __future__ import annotations

import pytest

from app.db.schema_compat import Decision, decide

KNOWN = frozenset({"0010", "0011", "0012"})


@pytest.mark.parametrize(
    ("db_revision", "min_code_revision", "expected"),
    [
        pytest.param(None, None, Decision.MIGRATE, id="fresh-database"),
        pytest.param("0010", None, Decision.MIGRATE, id="before-schema-compat"),
        pytest.param("0011", "0011", Decision.MIGRATE, id="known-behind-head"),
        pytest.param("0012", "0011", Decision.MIGRATE, id="known-at-head"),
        pytest.param("0012", "unknown", Decision.MIGRATE, id="known-revision-wins"),
        pytest.param("0013", "0011", Decision.AHEAD, id="ahead-floor-known"),
        pytest.param("0013", "0012", Decision.AHEAD, id="ahead-floor-is-our-head"),
        pytest.param("0013", "0013", Decision.REFUSE, id="ahead-contract-past-our-head"),
        pytest.param("0013", None, Decision.REFUSE, id="ahead-row-missing"),
    ],
)
def test_the_sd3_boot_rule(
    db_revision: str | None, min_code_revision: str | None, expected: Decision
) -> None:
    assert decide(KNOWN, db_revision, min_code_revision) is expected
