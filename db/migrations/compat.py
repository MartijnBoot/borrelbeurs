"""The one write a contract migration makes to `schema_compat` (Phase 8 SD3, PD2).

A migration after `0011` that drops, renames or narrows something older code
still uses declares `min_code_revision = "<its own id>"` and calls this from
`upgrade()`:

    from db.migrations.compat import set_min_code_revision

    min_code_revision = "0012"

    def upgrade() -> None:
        ...
        set_min_code_revision(op, min_code_revision)

An expand-only migration declares `min_code_revision = "unchanged"` and calls
nothing. `tests/meta/test_schema_compat_coverage.py` holds every migration to one
of the two.
"""

from __future__ import annotations

from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.sql.base import Executable


class _Op(Protocol):
    """What this needs of `alembic.op`."""

    def execute(self, sqltext: Executable | str) -> None: ...


def set_min_code_revision(op: _Op, revision: str) -> None:
    """Record that code older than `revision` no longer runs against this schema."""
    op.execute(
        sa.text("UPDATE schema_compat SET min_code_revision = :revision WHERE id = 1").bindparams(
            revision=revision
        )
    )
