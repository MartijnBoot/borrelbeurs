"""Phase 7 lifecycle: products, the bar price per sale, exports, a series index

Phase 7, T1 (SD1, SD5, SD6, SD9, SD13).

- `product` gives a drink an identity that outlives its run and its name
  (SD1). `name_key` is the key the product was created with and is not
  unique: a product is found by the newest one whose key matches and that has
  no active drink in the run.
- `drink.product_id` is backfilled with one product per distinct `name_key`,
  named after that key's earliest drink. `drink_product_live` keeps two active
  drinks of one run from sharing a product; it holds after the backfill
  because `drink_name_live` already makes active keys unique per run.
- `order_line.bar_price_cents` is the bar price in force when the line sold
  (SD5, D-20), backfilled from the drink's current value.
- `export` holds a built workbook as `bytea` (ADR 0004), like `asset`. No
  cascade from `run`: deleting a run deletes its exports explicitly.
- `order_run_wall_ts` serves the earnings series of any run (SD9).

Expand-only (SD13): both new drink and line columns stay nullable, so a
rolled-back image that writes neither keeps working. `downgrade()` drops
everything in reverse; product identity is lost, which is correct: going back
past live data is a restore, not a migration.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("product_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("name_key", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column(
        "drink",
        sa.Column(
            "product_id",
            sa.BigInteger,
            sa.ForeignKey("product.product_id", name="drink_product_id_fkey"),
            nullable=True,
        ),
    )
    op.execute(
        "INSERT INTO product (name_key, name, created_at) "
        "SELECT DISTINCT ON (name_key) name_key, name, added_at FROM drink "
        "ORDER BY name_key, added_at, drink_id"
    )
    op.execute(
        "UPDATE drink SET product_id = product.product_id FROM product "
        "WHERE product.name_key = drink.name_key"
    )
    op.create_index(
        "drink_product_live",
        "drink",
        ["run_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.add_column("order_line", sa.Column("bar_price_cents", sa.Integer, nullable=True))
    op.create_check_constraint(
        "order_line_bar_price_cents_check", "order_line", "bar_price_cents >= 0"
    )
    op.execute(
        "UPDATE order_line SET bar_price_cents = drink.bar_price_cents FROM drink "
        "WHERE drink.drink_id = order_line.drink_id"
    )

    op.create_table(
        "export",
        sa.Column("export_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("run.run_id", name="export_run_id_fkey"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("requested_by", sa.Text, nullable=False),
        sa.Column("data", postgresql.BYTEA, nullable=True),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("bytes", sa.Integer, nullable=True),
        sa.Column("line_count", sa.Integer, nullable=True),
        sa.Column("total_cents", sa.BigInteger, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('manual', 'final')", name="export_kind_check"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="export_status_check"
        ),
        sa.CheckConstraint("data IS NULL OR bytes = octet_length(data)", name="export_bytes_check"),
        sa.CheckConstraint("status <> 'done' OR data IS NOT NULL", name="export_done_check"),
    )

    op.create_index("order_run_wall_ts", "order", ["run_id", "wall_ts_ms"])


def downgrade() -> None:
    op.drop_index("order_run_wall_ts", table_name="order")
    op.drop_table("export")
    op.drop_constraint("order_line_bar_price_cents_check", "order_line", type_="check")
    op.drop_column("order_line", "bar_price_cents")
    op.drop_index("drink_product_live", table_name="drink")
    op.drop_column("drink", "product_id")
    op.drop_table("product")
