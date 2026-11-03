"""price tick wall ts: an index for boot's history-window read

The 2026-11-03 Render outage.

- `price_tick_run_wall_ts` on `(run_id, wall_ts_ms)`. Rehydrate reads the ticks
  within the history window of the latest one (`load_ticks_in_window`); with only
  the primary key `(run_id, version)` that read scanned every tick of the run. A
  run live for weeks outgrew the 5 s statement timeout, and no boot succeeded.

Built plainly, not `CONCURRENTLY`: migrations run at boot under the advisory lock,
so nothing else writes `price_tick` meanwhile, and the migration engine has no
statement timeout to outlast.

Expand-only: an image before this one never names the index, and only reads
faster for it, so `min_code_revision` is unchanged. `downgrade()` drops it.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
min_code_revision = "unchanged"


def upgrade() -> None:
    op.create_index("price_tick_run_wall_ts", "price_tick", ["run_id", "wall_ts_ms"])


def downgrade() -> None:
    op.drop_index("price_tick_run_wall_ts", table_name="price_tick")
