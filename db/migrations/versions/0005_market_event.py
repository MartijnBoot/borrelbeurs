"""market_event: crash, bubble and correction events of a run

Phase 3, T2 (SD23).

- `drink_ids` is the JSON array of the drinks the event jumped, by `drink_id`.
- `t_start_ms` / `t_end_ms` are absolute wall-clock milliseconds, shifted with
  the jump anchors by the gap rule (AC19a). A replaced event has its
  `t_end_ms` rewritten to the moment it ended.
- `ended_at` is NULL while the event is active; `market_event_active` serves the
  ticker's and rehydrate's per-run lookup of those.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_event",
        sa.Column("event_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("run.run_id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("drink_ids", postgresql.JSONB, nullable=False),
        sa.Column("t_start_ms", sa.BigInteger, nullable=False),
        sa.Column("t_end_ms", sa.BigInteger, nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('crash', 'bubble', 'correction')", name="market_event_kind_check"
        ),
        sa.CheckConstraint("t_end_ms > t_start_ms", name="market_event_times_check"),
    )
    op.create_index(
        "market_event_active",
        "market_event",
        ["run_id"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("market_event_active", table_name="market_event")
    op.drop_table("market_event")
