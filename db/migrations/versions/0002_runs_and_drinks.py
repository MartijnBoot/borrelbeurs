"""runs and drinks: run, run_config_revision, drink

Phase 2, T1 (SD4: three of the eight tables). The other five arrive in 0003.

- `run_one_live` is a unique index over the constant `true`, restricted to
  `status = 'live'`: every live row has the same key, so a second one is a
  duplicate (SD6, AC22).
- `drink_name_live` makes `name_key` unique per run among drinks not removed
  (SD14). `name_key` is `name.strip().casefold()`, computed in Python, because
  `lower()` follows the collation and the compose server's `--locale=C` folds
  ASCII only (PD6).
- Euro amounts are `INTEGER` cents (AC9, PD3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "run",
        sa.Column("run_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("run_seed", sa.BigInteger, nullable=False),
        sa.Column("tick_interval_ms", sa.Integer, nullable=False, server_default=sa.text("1000")),
        sa.Column("params", postgresql.JSONB, nullable=False),
        _created_at("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'live', 'ended')", name="run_status_check"),
        sa.CheckConstraint("run_seed >= 0", name="run_run_seed_check"),
    )
    op.create_index(
        "run_one_live",
        "run",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status = 'live'"),
    )

    op.create_table(
        "run_config_revision",
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("run.run_id"), primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("author", sa.Text, nullable=False),
        _created_at("created_at"),
        sa.CheckConstraint("revision >= 1", name="run_config_revision_revision_check"),
    )

    op.create_table(
        "drink",
        sa.Column("drink_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("run.run_id"), nullable=False),
        sa.Column("slot", sa.Integer, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_key", sa.Text, nullable=False),
        sa.Column("p_min_cents", sa.Integer, nullable=False),
        sa.Column("p0_cents", sa.Integer, nullable=False),
        sa.Column("p_max_cents", sa.Integer, nullable=False),
        sa.Column("a", sa.Double, nullable=False),
        sa.Column("d", sa.Double, nullable=False),
        sa.Column("s0", sa.Double, nullable=False),
        sa.Column("c", sa.Double, nullable=False),
        sa.Column("bar_price_cents", sa.Integer, nullable=False),
        _created_at("added_at"),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("slot >= 0", name="drink_slot_check"),
        sa.CheckConstraint(
            "p_min_cents < p0_cents AND p0_cents < p_max_cents", name="drink_prices_check"
        ),
        sa.CheckConstraint("bar_price_cents >= 0", name="drink_bar_price_cents_check"),
        sa.UniqueConstraint("run_id", "slot", name="drink_run_id_slot_key"),
    )
    op.create_index(
        "drink_name_live",
        "drink",
        ["run_id", "name_key"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("drink_name_live", table_name="drink")
    op.drop_table("drink")
    op.drop_table("run_config_revision")
    op.drop_index("run_one_live", table_name="run")
    op.drop_table("run")
