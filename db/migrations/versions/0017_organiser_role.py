"""organiser role: a fifth access-key role for whoever sets up the night

B-13, T1 (SD1, SD16; plan PD1).

- `auth_key_role_check` gains `organiser`, as 0013 added `kassa`. No column,
  table or backfill: every existing key keeps its role.

`min_code_revision` is unchanged. An image before this one boots on this schema
and every key of the four old roles works there. Only an `organiser` row
misbehaves: that image's login cannot map the role to its addresses, and its
`GET /api/keys` cannot list the row, so the admin's key list errors until the
row is revoked and deleted (`app.cli.keys list`/`revoke` still work). Raising
the floor would refuse the old image's boot outright, which is worse at a venue.

`downgrade()` restores the four-role CHECK, so it fails loudly, changing
nothing, while any `organiser` row exists, revoked or not.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"

_OLD_ROLES = "'display', 'bar', 'admin', 'kassa'"


def upgrade() -> None:
    op.drop_constraint("auth_key_role_check", "auth_key", type_="check")
    op.create_check_constraint(
        "auth_key_role_check", "auth_key", f"role IN ({_OLD_ROLES}, 'organiser')"
    )


def downgrade() -> None:
    op.drop_constraint("auth_key_role_check", "auth_key", type_="check")
    op.create_check_constraint("auth_key_role_check", "auth_key", f"role IN ({_OLD_ROLES})")
