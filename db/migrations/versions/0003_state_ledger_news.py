"""state, ledger and news: engine_state, price_tick, order, order_line, news

Phase 2, T4 (SD4: the other five of the eight tables).

- `engine_state`'s per-drink values and jumps are `json`, not `jsonb` (PD7):
  `jsonb` stores numbers as `numeric`, which drops the sign of `-0.0`, and the
  floats must round-trip bit-exact (AC3). `json` keeps the text as written.
- `price_tick.prices` is `{drink_id: {"p_cont", "p_q"}}`, one row per accepted
  transition (SD10), keyed by `(run_id, version)`.
- Revenue is stored once, as `order_line.line_total_cents` (AC11, PD4); the
  `"order"` row carries no total.
- `news.level` is one of four lowercase values (SD13).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _run_fk(*, primary_key: bool = False) -> sa.Column[int]:
    return sa.Column(
        "run_id",
        sa.BigInteger,
        sa.ForeignKey("run.run_id"),
        nullable=False,
        primary_key=primary_key,
    )


def upgrade() -> None:
    op.create_table(
        "engine_state",
        _run_fk(primary_key=True),
        *(
            sa.Column(name, postgresql.JSON, nullable=False)
            for name in ("y", "cum_orders", "flow_ema", "last_order_ts", "jumps")
        ),
        *(
            sa.Column(name, sa.BigInteger, nullable=False)
            for name in (
                "last_idle_ms",
                "last_bm_ms",
                "rng_counter",
                "version",
                "tick_index",
                "t_round",
                "wall_ts_ms",
            )
        ),
        _now("updated_at"),
    )

    op.create_table(
        "price_tick",
        _run_fk(primary_key=True),
        sa.Column("version", sa.BigInteger, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("prices", postgresql.JSONB, nullable=False),
        sa.Column("wall_ts_ms", sa.BigInteger, nullable=False),
        _now("created_at"),
        sa.CheckConstraint(
            "source IN ('tick', 'order', 'jump', 'idle', 'reset', 'gap')",
            name="price_tick_source_check",
        ),
    )

    op.create_table(
        "order",
        sa.Column("order_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        _run_fk(),
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False),
        sa.Column("wall_ts_ms", sa.BigInteger, nullable=False),
        _now("created_at"),
        sa.UniqueConstraint("idempotency_key", name="order_idempotency_key_key"),
    )

    op.create_table(
        "order_line",
        sa.Column("order_line_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "order_id",
            sa.BigInteger,
            sa.ForeignKey("order.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("drink_id", sa.BigInteger, sa.ForeignKey("drink.drink_id"), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("unit_price_cents", sa.Integer, nullable=False),
        sa.Column("line_total_cents", sa.Integer, nullable=False),
        sa.Column("p_cont", sa.Double, nullable=False),
        sa.CheckConstraint("qty > 0", name="order_line_qty_check"),
        sa.CheckConstraint("unit_price_cents >= 0", name="order_line_unit_price_cents_check"),
        sa.CheckConstraint(
            "line_total_cents = qty * unit_price_cents", name="order_line_total_check"
        ),
        sa.UniqueConstraint("order_id", "drink_id", name="order_line_order_id_drink_id_key"),
    )

    op.create_table(
        "news",
        sa.Column("news_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        _run_fk(),
        sa.Column("ts_ms", sa.BigInteger, nullable=False),
        sa.Column("level", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        _now("created_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "level IN ('info', 'success', 'warning', 'danger')", name="news_level_check"
        ),
    )


def downgrade() -> None:
    op.drop_table("news")
    op.drop_table("order_line")
    op.drop_table("order")
    op.drop_table("price_tick")
    op.drop_table("engine_state")
