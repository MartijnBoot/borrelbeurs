"""short keys: revoke every long key; a key's hash is unique

B-08, T2 (SD3, SD6; plan PD9).

- Every `auth_key` row with no `revoked_at` gets one (SD6). Rows already revoked
  keep theirs; nothing is deleted, so the list shows every old key as revoked.
  Their sessions get 401 on their next request, by the existing row check.
- `auth_key.secret_hash` becomes `UNIQUE`, across every row, revoked ones
  included (SD3). A short key is found by its fixed-salt hash, so two rows with
  one hash would make a login ambiguous. The long keys' hashes carry per-row
  random salts, so they are already distinct.

`min_code_revision` is unchanged, and honestly so (AC13): a pre-B-08 image mints
by inserting `'pending'` and updating it to the real hash in the same
transaction. A second concurrent insert of `'pending'` waits on the first
transaction; by its commit the first row no longer holds `'pending'`, so the
second insert proceeds. Both mints commit (`test_migration_0015.py`).

`downgrade()` drops the constraint only. It does not un-revoke: it cannot tell
which rows the upgrade revoked, and a revived long key is what SD6 rules out.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-27

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"


def upgrade() -> None:
    op.execute("UPDATE auth_key SET revoked_at = now() WHERE revoked_at IS NULL")
    op.create_unique_constraint("auth_key_secret_hash_key", "auth_key", ["secret_hash"])


def downgrade() -> None:
    op.drop_constraint("auth_key_secret_hash_key", "auth_key", type_="unique")
