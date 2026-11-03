"""A run's config over HTTP (Phase 6 SD5, SD6, SD8; PD4, PD6, PD7).

`GET /api/runs/{run_id}/config` is the config document (`app/runtime/config.py`).
`POST /api/runs/{run_id}/anchor-s0` anchors every active drink's `s0` on the
current prices (SD26: no confirmation, as in v1), live only, and returns
`{revision}`; a draft is 409 `run_not_live`.
`PATCH /api/runs/{run_id}/config {name?, candle_interval_s?, params?}` merges
only the keys present into a draft and returns `{revision}`: the new one, or the
current one when nothing changed. A violation of SD8 is 422 naming the field.

On the run this process holds live, the PATCH is one engine transition with
one `config` broadcast (SD7); on a draft it is a plain transaction.

`POST /api/runs/{run_id}/profile {profile_id}` loads a profile's 22 settings onto
a draft (B-04 SD3) and returns `{revision}`, the current one when nothing
changed: 409 `run_not_draft` for a live or ended run, 404 `profile_not_found`,
422 naming a stored value outside today's rules, each writing nothing.

404 `run_not_found`; 409 `run_ended`. Admin, and the organiser (B-13 SD5, SD6).
The writes refuse while draining (SD24).

For an organiser the PATCH is cut by field (B-13 SD7): the body may hold only
`ORGANISER_CONFIG_FIELDS`. Any other key, a `params` key included, is 403
`forbidden` naming it, with `fields` listing every one. The check is a
dependency, so it runs before the body is validated against `ConfigPatch`: a
refused field is 403 whatever its value, and nothing is written or broadcast.
"""

from __future__ import annotations

import json
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, JsonValue

from app.api.deps import (
    Forbidden,
    Principal,
    clock_of,
    db_engine,
    refuse_while_draining,
    require_role,
)
from app.runtime.config import (
    ConfigData,
    ConfigPatch,
    RevisionData,
    anchor_s0,
    load_profile_onto_draft,
    read_config,
    write_draft_config,
    write_live_config,
)
from app.runtime.holder import MarketHolder

router = APIRouter(prefix="/runs", tags=["config"])

# B-13 SD7: what an organiser's `PATCH /config` may carry; a `params` key is dotted.
ORGANISER_CONFIG_FIELDS: Final = frozenset(
    {"name", "wallet_required", "credit_limit_cents", "params.step_quant"}
)
_TOP_LEVEL: Final = frozenset(field for field in ORGANISER_CONFIG_FIELDS if "." not in field)


def _refused_fields(body: object) -> list[str]:
    """The body's fields outside `ORGANISER_CONFIG_FIELDS`, dotted and sorted.

    A body or `params` that is not an object names no field: it is left to
    `ConfigPatch`'s 422, as for admin.
    """
    if not isinstance(body, dict):
        return []
    refused = [key for key in body if key != "params" and key not in _TOP_LEVEL]
    params = body.get("params")
    if isinstance(params, dict):
        dotted = (f"params.{key}" for key in params)
        refused += [field for field in dotted if field not in ORGANISER_CONFIG_FIELDS]
    return sorted(refused)


_config_writer = require_role("organiser", "admin")


async def config_writer(
    request: Request, principal: Annotated[Principal, Depends(_config_writer)]
) -> Principal:
    """`PATCH /config`'s role check, then SD7's field check for an organiser."""
    if principal.role != "organiser":
        return principal
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        return principal  # not JSON: FastAPI's own 422
    refused = _refused_fields(body)
    if refused:
        fields: list[JsonValue] = list(refused)
        raise Forbidden(f"the organiser may not set {refused[0]}", extra={"fields": fields})
    return principal


class LoadProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: int


@router.get("/{run_id}/config")
async def get_config(
    run_id: int,
    request: Request,
    _: Annotated[Principal, Depends(require_role("organiser", "admin"))],
) -> ConfigData:
    return await read_config(db_engine(request), run_id)


@router.patch("/{run_id}/config")
async def patch_config(
    run_id: int,
    body: ConfigPatch,
    request: Request,
    principal: Annotated[Principal, Depends(config_writer)],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RevisionData:
    holder: MarketHolder = request.app.state.holder
    if holder.run_id == run_id:
        revision = await write_live_config(
            holder, run_id, body, author=principal.label, clock=clock_of(request)
        )
    else:
        revision = await write_draft_config(
            db_engine(request), run_id, body, author=principal.label
        )
    return RevisionData(revision=revision)


@router.post("/{run_id}/anchor-s0")
async def post_anchor_s0(
    run_id: int,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RevisionData:
    holder: MarketHolder = request.app.state.holder
    revision = await anchor_s0(holder, run_id, author=principal.label, clock=clock_of(request))
    return RevisionData(revision=revision)


@router.post("/{run_id}/profile")
async def post_profile_load(
    run_id: int,
    body: LoadProfileRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_role("organiser", "admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> RevisionData:
    revision = await load_profile_onto_draft(
        db_engine(request), run_id, body.profile_id, author=principal.label
    )
    return RevisionData(revision=revision)
