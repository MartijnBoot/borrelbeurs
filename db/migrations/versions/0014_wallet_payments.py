"""wallet payments: the run's switch and credit limit; payment and refund entries

B-06, T1 (SD1, SD2, SD8, SD9, SD10; plan PD2, PD3).

- `run.wallet_required` is "Wallet verplicht" (SD1). Existing runs get `false`
  from the server default, so a deploy never changes a borrel in progress; the
  app's `create_run` sets `true` explicitly.
- `run.credit_limit_cents` is "Rood staan tot" (SD2): 0 to 5000, a multiple of 50.
- `wallet_entry.kind` gains `payment` (an order paid from the wallet, at most
  zero, because a drink may cost nothing: PD2) and `refund` (at least zero).
- The sign rule is relaxed for debt (SD8): `closing` may write a debt off
  (positive), and a move carries a negative balance (`move_out` positive,
  `move_in` negative). Those three kinds only refuse zero.
- `wallet_entry.order_id` names a payment's order, unique, `ON DELETE SET NULL`
  so deleting a run keeps the payment's amount and time (SD10, AC24). Only a
  `payment` may carry it. There is no CHECK that a payment has one: the
  `SET NULL` must be able to clear it.
- `wallet_entry.refunds_entry_id` names the refunded payment, unique, so a
  payment is refunded at most once (SD9). Exactly the `refund` entries carry it.

Expand-only: an image before this one never writes the new kinds and ignores the
new columns, so `min_code_revision` is unchanged. `downgrade()` restores the
B-05 CHECKs, so it fails loudly while any payment or refund, positive closing, or
debt-carrying move exists, and drops the new constraints and columns.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"

_OLD_KINDS = "'topup', 'reversal', 'move_out', 'move_in', 'closing'"
_OLD_AMOUNT = (
    "(kind IN ('topup', 'move_in') AND amount_cents > 0) OR "
    "(kind IN ('reversal', 'move_out', 'closing') AND amount_cents < 0)"
)


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("wallet_required", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "run",
        sa.Column("credit_limit_cents", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "run_credit_limit_cents_check",
        "run",
        "credit_limit_cents BETWEEN 0 AND 5000 AND credit_limit_cents % 50 = 0",
    )

    op.add_column(
        "wallet_entry",
        sa.Column(
            "order_id",
            sa.BigInteger,
            sa.ForeignKey("order.order_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "wallet_entry",
        sa.Column(
            "refunds_entry_id",
            sa.BigInteger,
            sa.ForeignKey("wallet_entry.entry_id"),
            nullable=True,
        ),
    )
    op.create_unique_constraint("wallet_entry_order_id_key", "wallet_entry", ["order_id"])
    op.create_unique_constraint(
        "wallet_entry_refunds_entry_id_key", "wallet_entry", ["refunds_entry_id"]
    )

    op.drop_constraint("wallet_entry_kind_check", "wallet_entry", type_="check")
    op.create_check_constraint(
        "wallet_entry_kind_check", "wallet_entry", f"kind IN ({_OLD_KINDS}, 'payment', 'refund')"
    )
    op.drop_constraint("wallet_entry_amount_check", "wallet_entry", type_="check")
    op.create_check_constraint(
        "wallet_entry_amount_check",
        "wallet_entry",
        "(kind = 'topup' AND amount_cents > 0) OR "
        "(kind = 'reversal' AND amount_cents < 0) OR "
        "(kind = 'payment' AND amount_cents <= 0) OR "
        "(kind = 'refund' AND amount_cents >= 0) OR "
        "(kind IN ('move_out', 'move_in', 'closing') AND amount_cents <> 0)",
    )
    op.create_check_constraint(
        "wallet_entry_order_check", "wallet_entry", "order_id IS NULL OR kind = 'payment'"
    )
    op.create_check_constraint(
        "wallet_entry_refund_check",
        "wallet_entry",
        "(kind = 'refund') = (refunds_entry_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("wallet_entry_refund_check", "wallet_entry", type_="check")
    op.drop_constraint("wallet_entry_order_check", "wallet_entry", type_="check")
    op.drop_constraint("wallet_entry_amount_check", "wallet_entry", type_="check")
    op.create_check_constraint("wallet_entry_amount_check", "wallet_entry", _OLD_AMOUNT)
    op.drop_constraint("wallet_entry_kind_check", "wallet_entry", type_="check")
    op.create_check_constraint("wallet_entry_kind_check", "wallet_entry", f"kind IN ({_OLD_KINDS})")
    op.drop_constraint("wallet_entry_refunds_entry_id_key", "wallet_entry", type_="unique")
    op.drop_constraint("wallet_entry_order_id_key", "wallet_entry", type_="unique")
    op.drop_column("wallet_entry", "refunds_entry_id")
    op.drop_column("wallet_entry", "order_id")
    op.drop_constraint("run_credit_limit_cents_check", "run", type_="check")
    op.drop_column("run", "credit_limit_cents")
    op.drop_column("run", "wallet_required")
