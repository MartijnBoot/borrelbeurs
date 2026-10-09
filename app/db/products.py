"""Products: a drink's identity across runs and renames (Phase 7 SD1, PD7).

A product is what analytics key on. Adding a drink resolves its `name_key` to
the most recently created product with that key that has no *active* drink in
the run; otherwise a new product is created. So a removed drink re-added under
its name lands on the same product, the same drink in another run joins it, and
two active drinks of one run never share one (`drink_product_live`). A rename
keeps the drink's product: `update_drink` never writes `product_id`.

`add_drink` is the one place this is called, so an import, a draft add and a
live add all resolve the same way. Like the other repositories it takes the
caller's connection and never commits.
"""

from __future__ import annotations

from sqlalchemy import and_, exists, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Drink, Product


async def resolve_product(conn: AsyncConnection, run_id: int, name_key: str, name: str) -> int:
    """The product a drink named `name` (key `name_key`) added to `run_id` belongs to."""
    taken = exists().where(
        and_(
            Drink.run_id == run_id,
            Drink.product_id == Product.product_id,
            Drink.removed_at.is_(None),
        )
    )
    found = (
        await conn.execute(
            select(Product.product_id)
            .where(Product.name_key == name_key, ~taken)
            .order_by(Product.created_at.desc(), Product.product_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if found is not None:
        return int(found)
    created = await conn.execute(
        insert(Product).values(name_key=name_key, name=name).returning(Product.product_id)
    )
    return int(created.scalar_one())
