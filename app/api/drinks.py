"""A run's drinks over HTTP (Phase 6 SD5, SD9, SD12, SD13, SD16, SD17).

`POST /api/runs/{run_id}/drinks {name, p_min_cents, p0_cents, p_max_cents,
bar_price_cents?, a?, d?, s0?, c?}` adds a drink (`app/runtime/drinks.py`) and
returns `{drink_id, revision}`. `PATCH /api/runs/{run_id}/drinks/{drink_id}`
takes any subset of those fields and returns `{revision}`: the new one, or the
current one when nothing changed. `DELETE /api/runs/{run_id}/drinks/{drink_id}`
removes it (SD13) and returns `{revision}`. On the run this process holds live
each is one engine transition with one `config` broadcast; on a draft, a plain
transaction.

422 naming the field (SD8); 409 `duplicate_drink_name`; 404 `run_not_found`,
`drink_not_found`; 409 `run_ended`, `drink_removed`, `last_active_drink`.
Admin only. Refuses while draining (SD24).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import Principal, clock_of, db_engine, refuse_while_draining, require_role
from app.runtime.config import RevisionData
from app.runtime.drinks import (
    CreatedDrink,
    DrinkCreate,
    DrinkPatch,
    add_draft_drink,
    add_live_drink,
    edit_draft_drink,
    edit_live_drink,
    remove_draft_drink,
    remove_live_drink,
)
from app.runtime.holder import MarketHolder

router = APIRouter(prefix="/runs", tags=["drinks"])


@router.post("/{run_id}/drinks", status_code=201)
async def post_drink(
    run_id: int,
    body: DrinkCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> CreatedDrink:
    holder: MarketHolder = request.app.state.holder
    if holder.run_id == run_id:
        return await add_live_drink(
            holder, run_id, body, author=principal.label, clock=clock_of(request)
        )
    return await add_draft_drink(db_engine(request), run_id, body, author=principal.label)


@router.patch("/{run_id}/drinks/{drink_id}")
async def patch_drink(
    run_id: int,
    drink_id: int,
    body: DrinkPatch,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RevisionData:
    holder: MarketHolder = request.app.state.holder
    if holder.run_id == run_id:
        revision = await edit_live_drink(
            holder, run_id, drink_id, body, author=principal.label, clock=clock_of(request)
        )
    else:
        revision = await edit_draft_drink(
            db_engine(request), run_id, drink_id, body, author=principal.label
        )
    return RevisionData(revision=revision)


@router.delete("/{run_id}/drinks/{drink_id}")
async def delete_drink(
    run_id: int,
    drink_id: int,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RevisionData:
    holder: MarketHolder = request.app.state.holder
    if holder.run_id == run_id:
        revision = await remove_live_drink(
            holder, run_id, drink_id, author=principal.label, clock=clock_of(request)
        )
    else:
        revision = await remove_draft_drink(
            db_engine(request), run_id, drink_id, author=principal.label
        )
    return RevisionData(revision=revision)
