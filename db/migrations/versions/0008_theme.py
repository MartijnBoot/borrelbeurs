"""theme: the one active display theme, a single row

Phase 4, T2 (SD5, plan PD4).

- `id` is the singleton key: `SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1)`,
  so "one row" is a database fact rather than a convention (PD4).
- `preset` is one of the five server-side presets (`app/runtime/theme.py`).
- `revision` starts at 1 and grows by one per write; clients apply a theme
  only when its revision is higher than the one they hold (SD9). No row means
  Blauw at revision 0, so the table starts empty and nothing is backfilled.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "theme",
        sa.Column(
            "id",
            sa.SmallInteger,
            primary_key=True,
            autoincrement=False,
            server_default=sa.text("1"),
        ),
        sa.Column("preset", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="theme_id_check"),
        sa.CheckConstraint(
            "preset IN ('oudgeld', 'blauw', 'groen', 'paars', 'rood')", name="theme_preset_check"
        ),
        sa.CheckConstraint("revision >= 1", name="theme_revision_check"),
    )


def downgrade() -> None:
    op.drop_table("theme")
