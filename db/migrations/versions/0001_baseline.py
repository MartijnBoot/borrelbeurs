"""baseline: create nothing, so that a version table exists

(ASCII only in this first line on purpose -- Alembic echoes it to the console
during `upgrade`, and a Windows terminal in cp1252 renders an em dash as a
replacement character.)

Phase 0 ships no application tables; Phase 2 does (docs/design/data-model.md).
This revision exists so that `alembic_version` is present on a fresh database
and Phase 2's first real migration has a parent to hang from. Without it, that
migration would be both "the first schema change" and "the thing that
bootstraps versioning", and rolling it back would leave no record that it ever
ran.

Empty in both directions, so `upgrade head` on a fresh database and
`downgrade base` on a migrated one are each a no-op that succeeds — which is
what makes the reversibility check in the plan's verification meaningful
rather than tautological.

Revision ID: 0001
Revises:
Create Date: 2026-09-27

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change. Alembic still records `0001` in `alembic_version`."""


def downgrade() -> None:
    """No schema change. Alembic still clears `alembic_version`."""
