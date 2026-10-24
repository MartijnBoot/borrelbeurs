"""Setting profiles over HTTP (B-04 SD2, SD5, SD6, SD12, SD14, SD15).

`GET /api/profiles` lists every profile by case-folded name: its id, name,
saved-at and source borrel, never its values (SD12). `POST /api/profiles {name,
run_id, overwrite?}` saves that run's 22 settings (`save_profile_from_run`): 201
created, 200 overwritten; 409 `profile_exists` carrying the `profile_id` when the
name is taken and `overwrite` is not set, 404 `run_not_found`, 409 `run_ended`,
422 naming a run value outside today's rules. `DELETE /api/profiles/{profile_id}`
removes one, 204, or 404 `profile_not_found`.

Admin only. The writes refuse while draining (SD24).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from app.api.deps import Principal, db_engine, refuse_while_draining, require_role
from app.db.profiles import ProfileRow, delete_profile, list_profiles
from app.runtime.config_patch import RunName
from app.runtime.profiles import save_profile_from_run

router = APIRouter(prefix="/profiles", tags=["profiles"])


class SaveProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RunName
    run_id: int
    overwrite: StrictBool = False


class ProfileData(BaseModel):
    profile_id: int
    name: str
    saved_at: datetime
    source_run_name: str


def _data(row: ProfileRow) -> ProfileData:
    return ProfileData(
        profile_id=row.profile_id,
        name=row.name,
        saved_at=row.saved_at,
        source_run_name=row.source_run_name,
    )


@router.get("")
async def get_profiles(
    request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> list[ProfileData]:
    async with db_engine(request).connect() as conn:
        return [_data(row) for row in await list_profiles(conn)]


@router.post("", status_code=201)
async def post_profile(
    body: SaveProfileRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> ProfileData:
    row, created = await save_profile_from_run(
        db_engine(request),
        name=body.name,
        run_id=body.run_id,
        overwrite=body.overwrite,
        author=principal.label,
    )
    if not created:
        response.status_code = 200
    return _data(row)


@router.delete("/{profile_id}", status_code=204)
async def delete_one_profile(
    profile_id: int,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> Response:
    async with db_engine(request).begin() as conn:
        await delete_profile(conn, profile_id)
    return Response(status_code=204)
