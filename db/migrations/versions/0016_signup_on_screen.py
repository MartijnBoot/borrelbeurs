"""signup on screen: the switch for the sign-up QR code on the koers screen

B-10, T2 (SD5; plan PD3).

- `wallet_settings.show_signup_on_screen` is "QR-code op het scherm", off by
  default. The existing row, if any, gets `false` from the server default, so a
  deploy shows nothing new on any screen until admin turns it on.

Expand-only: an image before this one never names the column. Its upsert sets
the three columns it knows and leaves this one alone, and its first insert takes
the default, so `min_code_revision` is unchanged. `downgrade()` drops the column;
a switch that was on is lost with it.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"


def upgrade() -> None:
    op.add_column(
        "wallet_settings",
        sa.Column("show_signup_on_screen", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("wallet_settings", "show_signup_on_screen")
