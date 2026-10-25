"""settings_profile: named sets of the 22 settings a profile holds

B-04, T1 (SD1, SD5, SD7, SD8, SD14; plan PD4).

- `settings` is the 22 values under their `PATCH config` wire names, as JSONB;
  the app checks them against today's rules on every save and apply (SD9), so
  the database does not.
- `name_key` is `name.strip().casefold()`, computed in Python as `drink.name_key`
  is; the unique index makes a second save under one name a conflict (SD5, SD15).
- No foreign key to `run` (SD7): `source_run_name` is copied text.

Expand-only: an image before this one never reads the table, so
`min_code_revision` is unchanged. `downgrade()` drops it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"


def upgrade() -> None:
    op.create_table(
        "settings_profile",
        sa.Column("profile_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_key", sa.Text, nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False),
        sa.Column("source_run_name", sa.Text, nullable=False),
        sa.Column(
            "saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("saved_by", sa.Text, nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 100", name="settings_profile_name_check"
        ),
    )
    op.create_index("settings_profile_name_key", "settings_profile", ["name_key"], unique=True)


def downgrade() -> None:
    op.drop_table("settings_profile")
