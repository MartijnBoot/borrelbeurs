"""wallets: player wallets, their append-only ledger, the wallet settings; the kassa role

B-05, T1 (SD7, SD9, SD13, SD14, SD15, SD19; plan PD4).

- `wallet` is one player's wallet. `name`, `name_key`, `qr_token`, `short_code`
  and `cookie_hash` are all set while it lives and all NULL once `deleted_at` is
  stamped (`wallet_deleted_check`, SD15), so a deleted row identifies nobody.
  Each of the four lookups has a plain unique index: NULLs are distinct, so a
  deleted wallet frees its name and codes.
- `name_key` is `name.strip().casefold()`, computed in Python as `drink.name_key`
  is (SD3). `cookie_hash` is the SHA-256 of the cookie value (PD5); the value
  itself is never stored (SD19).
- `wallet_entry` is append-only, in integer cents; the balance is the sum of a
  wallet's entries (SD9). The sign of `amount_cents` is fixed by its kind. Only a
  `reversal` names the entry it reverses (once, by a unique constraint), and only
  a `move_in` names its `move_out`, because an append-only row cannot be updated
  to point at a later one.
- `wallet_entry.run_id` is the run live when the entry was written, or NULL
  (SD13). It is the schema's first `ON DELETE SET NULL`: deleting a run keeps its
  entries (Phase 7 SD3).
- `wallet_settings` is a singleton shaped as `theme` (`id = 1`). No row is
  seeded: a missing row means the defaults (closed sign-up, 30 days, 12 months).
- `auth_key_role_check` gains `kassa` (SD7).

Expand-only: an image before this one never reads the new tables, so
`min_code_revision` is unchanged. `downgrade()` restores the three-role CHECK, so
it fails loudly while a `kassa` key exists, and drops the three tables.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"

_OLD_ROLES = "'display', 'bar', 'admin'"
_CODES = ("name", "name_key", "qr_token", "short_code", "cookie_hash")


def upgrade() -> None:
    op.drop_constraint("auth_key_role_check", "auth_key", type_="check")
    op.create_check_constraint(
        "auth_key_role_check", "auth_key", f"role IN ({_OLD_ROLES}, 'kassa')"
    )

    op.create_table(
        "wallet",
        sa.Column("wallet_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("name_key", sa.Text, nullable=True),
        sa.Column("qr_token", sa.Text, nullable=True),
        sa.Column("short_code", sa.Text, nullable=True),
        sa.Column("cookie_hash", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 40", name="wallet_name_check"),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND "
            + " AND ".join(f"{c} IS NOT NULL" for c in _CODES)
            + ") OR (deleted_at IS NOT NULL AND "
            + " AND ".join(f"{c} IS NULL" for c in _CODES)
            + ")",
            name="wallet_deleted_check",
        ),
    )
    for column in ("name_key", "qr_token", "short_code", "cookie_hash"):
        op.create_index(f"wallet_{column}", "wallet", [column], unique=True)

    op.create_table(
        "wallet_entry",
        sa.Column("entry_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("wallet_id", sa.BigInteger, sa.ForeignKey("wallet.wallet_id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column(
            "run_id", sa.BigInteger, sa.ForeignKey("run.run_id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "reverses_entry_id",
            sa.BigInteger,
            sa.ForeignKey("wallet_entry.entry_id"),
            nullable=True,
        ),
        sa.Column(
            "counterpart_entry_id",
            sa.BigInteger,
            sa.ForeignKey("wallet_entry.entry_id"),
            nullable=True,
        ),
        sa.Column("actor_key_id", sa.BigInteger, sa.ForeignKey("auth_key.key_id"), nullable=True),
        sa.Column("actor_label", sa.Text, nullable=True),
        sa.Column("idempotency_key", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind IN ('topup', 'reversal', 'move_out', 'move_in', 'closing')",
            name="wallet_entry_kind_check",
        ),
        sa.CheckConstraint(
            "(kind IN ('topup', 'move_in') AND amount_cents > 0) OR "
            "(kind IN ('reversal', 'move_out', 'closing') AND amount_cents < 0)",
            name="wallet_entry_amount_check",
        ),
        sa.CheckConstraint(
            "(kind = 'reversal') = (reverses_entry_id IS NOT NULL)",
            name="wallet_entry_reversal_check",
        ),
        sa.CheckConstraint(
            "(kind = 'move_in') = (counterpart_entry_id IS NOT NULL)",
            name="wallet_entry_counterpart_check",
        ),
        sa.UniqueConstraint("reverses_entry_id", name="wallet_entry_reverses_entry_id_key"),
        sa.UniqueConstraint("idempotency_key", name="wallet_entry_idempotency_key_key"),
    )
    op.create_index("wallet_entry_wallet_id", "wallet_entry", ["wallet_id"])
    op.create_index("wallet_entry_run_id", "wallet_entry", ["run_id"])

    op.create_table(
        "wallet_settings",
        sa.Column(
            "id",
            sa.SmallInteger,
            primary_key=True,
            autoincrement=False,
            server_default=sa.text("1"),
        ),
        sa.Column("signup_code", sa.Text, nullable=True),
        sa.Column("unfunded_days", sa.Integer, nullable=False),
        sa.Column("inactive_months", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1", name="wallet_settings_id_check"),
        sa.CheckConstraint(
            "char_length(btrim(signup_code)) BETWEEN 1 AND 40",
            name="wallet_settings_signup_code_check",
        ),
        sa.CheckConstraint(
            "unfunded_days BETWEEN 1 AND 365", name="wallet_settings_unfunded_days_check"
        ),
        sa.CheckConstraint(
            "inactive_months BETWEEN 1 AND 60", name="wallet_settings_inactive_months_check"
        ),
    )


def downgrade() -> None:
    op.drop_table("wallet_settings")
    op.drop_table("wallet_entry")
    op.drop_table("wallet")
    op.drop_constraint("auth_key_role_check", "auth_key", type_="check")
    op.create_check_constraint("auth_key_role_check", "auth_key", f"role IN ({_OLD_ROLES})")
