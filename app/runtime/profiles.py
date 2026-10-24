"""Saving a run's settings as a named profile (B-04 SD2, SD5, SD9, SD15; plan PD3).

A save is one transaction: read the run (404 `run_not_found`, 409 `run_ended`),
snapshot its 22 as its config document shows them, check them against today's
rules (422 naming a field under `loc[0] == "run"`, SD9), and store exactly that
snapshot with the run's name as its source and the key label as its author.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.profiles import ProfileRow, save_profile
from app.db.runs import get_run
from app.runtime.config import readable
from app.runtime.config_patch import profile_patch, profile_settings
from exchange import Params


async def save_profile_from_run(
    engine: AsyncEngine, *, name: str, run_id: int, overwrite: bool, author: str
) -> tuple[ProfileRow, bool]:
    """Store `run_id`'s 22 under `name`; the profile and whether it was created."""
    async with engine.begin() as conn:
        run = readable(await get_run(conn, run_id))
        settings = profile_settings(Params.from_dict(run.params), run.candle_interval_ms)
        profile_patch(settings, source="run")
        return await save_profile(
            conn,
            name=name,
            settings=settings,
            source_run_name=run.name,
            saved_by=author,
            overwrite=overwrite,
        )
