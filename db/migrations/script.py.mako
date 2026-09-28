<%!
# A freshly generated revision has to pass scripts/check.sh before anyone
# edits it: `ruff format --check` and `ruff check` are its first two steps and
# it stops at the first failure. `repr()` renders a string with single quotes,
# which ruff format rewrites to double -- so the template renders its own
# literals instead. (F401 on the conventional `op`/`sa` imports is waived for
# this directory in pyproject.toml; the import order below is ruff's.)
def literal(value):
    if value is None:
        return "None"
    if isinstance(value, str):
        return '"%s"' % value
    items = list(value)
    return "(" + ", ".join('"%s"' % item for item in items) + ("," if len(items) == 1 else "") + ")"
%>"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports + "\n" if imports else ""}
revision: str = ${literal(up_revision)}
down_revision: str | None = ${literal(down_revision)}
branch_labels: str | Sequence[str] | None = ${literal(branch_labels)}
depends_on: str | Sequence[str] | None = ${literal(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
