"""Phase 6 admin: run names, config ticks, uploaded images, the custom theme

Phase 6, T1 (SD2, SD7, SD28, SD29; plan PD3).

- `run.name` is required (SD2). Existing rows are backfilled as
  `'Borrel ' || run_id` (PD3) -- an imported run's file stem is not
  recoverable from the row -- then the column becomes `NOT NULL`.
- `price_tick.source` gains `'config'`: every live admin write is one
  transition with its own tick (SD7).
- `asset` holds an uploaded image as `bytea` (ADR 0004), at most 5 MB, its
  byte count checked against the data itself (SD29).
- `theme` gains the custom tokens and font (SD28) and one nullable pointer per
  image slot (SD29). `preset = 'custom'` needs both tokens and font.

Every new column is nullable or backfilled, so the step is additive.
`downgrade()` restores the old CHECKs, so it fails loudly on a `config` tick or
a `custom` theme: going back past live data is a restore, not a migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_SOURCES = "'tick', 'order', 'jump', 'idle', 'reset', 'gap'"
_OLD_PRESETS = "'oudgeld', 'blauw', 'groen', 'paars', 'rood'"
_SLOTS = ("bg", "header", "logo", "promo")


def upgrade() -> None:
    op.add_column("run", sa.Column("name", sa.Text, nullable=True))
    op.execute("UPDATE run SET name = 'Borrel ' || run_id")
    op.alter_column("run", "name", nullable=False)
    op.create_check_constraint(
        "run_name_check", "run", "char_length(btrim(name)) BETWEEN 1 AND 100"
    )

    op.drop_constraint("price_tick_source_check", "price_tick", type_="check")
    op.create_check_constraint(
        "price_tick_source_check", "price_tick", f"source IN ({_OLD_SOURCES}, 'config')"
    )

    op.create_table(
        "asset",
        sa.Column("asset_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("data", postgresql.BYTEA, nullable=False),
        sa.Column("bytes", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "content_type IN ('image/png', 'image/jpeg', 'image/webp', 'image/gif')",
            name="asset_content_type_check",
        ),
        sa.CheckConstraint(
            "bytes BETWEEN 1 AND 5242880 AND bytes = octet_length(data)",
            name="asset_bytes_check",
        ),
    )

    op.add_column("theme", sa.Column("custom_tokens", postgresql.JSONB, nullable=True))
    op.add_column("theme", sa.Column("custom_font", sa.Text, nullable=True))
    op.create_check_constraint(
        "theme_custom_font_check", "theme", "custom_font IN ('inter', 'garamond')"
    )
    for slot in _SLOTS:
        op.add_column(
            "theme",
            sa.Column(
                f"{slot}_asset_id",
                sa.BigInteger,
                sa.ForeignKey("asset.asset_id", name=f"theme_{slot}_asset_id_fkey"),
                nullable=True,
            ),
        )
    op.drop_constraint("theme_preset_check", "theme", type_="check")
    op.create_check_constraint(
        "theme_preset_check", "theme", f"preset IN ({_OLD_PRESETS}, 'custom')"
    )
    op.create_check_constraint(
        "theme_custom_check",
        "theme",
        "preset <> 'custom' OR (custom_tokens IS NOT NULL AND custom_font IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("theme_custom_check", "theme", type_="check")
    op.drop_constraint("theme_preset_check", "theme", type_="check")
    op.create_check_constraint("theme_preset_check", "theme", f"preset IN ({_OLD_PRESETS})")
    for slot in reversed(_SLOTS):
        op.drop_column("theme", f"{slot}_asset_id")
    op.drop_constraint("theme_custom_font_check", "theme", type_="check")
    op.drop_column("theme", "custom_font")
    op.drop_column("theme", "custom_tokens")

    op.drop_table("asset")

    op.drop_constraint("price_tick_source_check", "price_tick", type_="check")
    op.create_check_constraint(
        "price_tick_source_check", "price_tick", f"source IN ({_OLD_SOURCES})"
    )

    op.drop_constraint("run_name_check", "run", type_="check")
    op.drop_column("run", "name")
