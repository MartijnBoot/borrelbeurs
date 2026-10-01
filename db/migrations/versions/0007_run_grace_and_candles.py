"""run: quote grace and candle interval

Phase 3, T2 (SD18, SD25).

- `quote_grace_versions` is ADR 0008's grace, a product parameter kept out of
  the engine's `Params`: how many versions old a quote may be and still be
  honoured within one price step (SD18).
- `candle_interval_ms` is ADR 0005's server-side bucket width (SD25).
- Both have defaults, so existing runs stay valid without a backfill.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("quote_grace_versions", sa.Integer, nullable=False, server_default=sa.text("2")),
    )
    op.add_column(
        "run",
        sa.Column(
            "candle_interval_ms", sa.Integer, nullable=False, server_default=sa.text("60000")
        ),
    )
    op.create_check_constraint("run_quote_grace_versions_check", "run", "quote_grace_versions >= 0")
    op.create_check_constraint("run_candle_interval_ms_check", "run", "candle_interval_ms > 0")


def downgrade() -> None:
    op.drop_constraint("run_candle_interval_ms_check", "run", type_="check")
    op.drop_constraint("run_quote_grace_versions_check", "run", type_="check")
    op.drop_column("run", "candle_interval_ms")
    op.drop_column("run", "quote_grace_versions")
