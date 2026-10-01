"""order: the acting key and the stored receipt

Phase 3, T2 (SD20).

- `actor_key_id` is the `auth_key` whose session placed the order.
- `response` is the receipt, exactly as returned, replayed for a repeated
  `Idempotency-Key` (SD20, plan PD6/PD7).
- Both are nullable: Phase 2's imported and test orders have neither.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order",
        sa.Column("actor_key_id", sa.BigInteger, sa.ForeignKey("auth_key.key_id"), nullable=True),
    )
    op.add_column("order", sa.Column("response", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("order", "response")
    op.drop_column("order", "actor_key_id")
