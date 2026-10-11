"""schema_compat: the oldest code revision that still runs against this schema

Phase 8, T3 (SD3, plan PD2).

- One row, `id = 1` by constraint, as `theme` (0008).
- `min_code_revision` names the oldest revision whose *code* still runs
  correctly against the schema the newest migration left. Boot reads it before
  migrating: a database at a revision the image does not know is served as it
  is when the image knows this one, and refused otherwise
  (`app/db/schema_compat.py`).
- Seeded `'0011'`: this is the first image that reads the table, so it is the
  rollback floor. From `0012` on, each migration declares
  `min_code_revision` -- `"unchanged"` when expand-only, its own id when it
  contracts -- and `tests/meta/test_schema_compat_coverage.py` enforces it.

Expand-only: an image before this one never reads the table. `downgrade()`
drops it.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schema_compat",
        sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
        sa.Column("min_code_revision", sa.Text, nullable=False),
        sa.CheckConstraint("id = 1", name="schema_compat_id_check"),
    )
    op.execute("INSERT INTO schema_compat (id, min_code_revision) VALUES (1, '0011')")


def downgrade() -> None:
    op.drop_table("schema_compat")
