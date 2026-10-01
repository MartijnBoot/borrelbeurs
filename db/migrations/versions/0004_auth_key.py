"""auth_key: access keys, minted by CLI, global rather than per run

Phase 3, T2 (SD5).

- The secret is stored only as its argon2id hash, `secret_hash` (AC6c). The
  plaintext key `bb_<key_id>_<secret>` is printed once by `app.cli.keys` and
  never written anywhere.
- `role` is one of three (SD2); `label` is 1-100 characters.
- `revoked_at` is checked on every authenticated request (SD8);
  `last_used_at` is written by a successful login only (SD6).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_key",
        sa.Column("key_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("secret_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('display', 'bar', 'admin')", name="auth_key_role_check"),
        sa.CheckConstraint("char_length(label) BETWEEN 1 AND 100", name="auth_key_label_check"),
    )


def downgrade() -> None:
    op.drop_table("auth_key")
