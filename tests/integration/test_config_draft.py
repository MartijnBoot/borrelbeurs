"""Draft config writes against real Postgres: concurrency (Phase 6 T10: AC13, SD6).

Revision numbers are allocated under a row lock on `run`, so concurrent writers
get consecutive revisions with no gap or collision, and the params merge happens
under that same lock, so two writers of different fields both persist (R14).
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from app.core.config import Settings
from app.db.runs import create_run
from app.db.session import create_engine
from app.runtime.config import ConfigPatch, write_draft_config


def _run(settings: Settings, url: str, body: Any) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _params_and_revisions(engine: Any, run_id: int) -> tuple[dict[str, Any], list[int]]:
    async with engine.connect() as conn:
        params = (
            await conn.execute(text("SELECT params FROM run WHERE run_id = :r"), {"r": run_id})
        ).scalar_one()
        revisions = (
            await conn.execute(
                text(
                    "SELECT revision FROM run_config_revision WHERE run_id = :r ORDER BY revision"
                ),
                {"r": run_id},
            )
        ).scalars()
        return dict(params), [int(r) for r in revisions]


def _patch(params: dict[str, Any]) -> ConfigPatch:
    return ConfigPatch.model_validate({"params": params})


def test_two_concurrent_writes_of_different_fields_both_persist(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: Any) -> tuple[list[int], dict[str, Any], list[int]]:
        run_id = await create_run(engine, name="Concept", author="seed")
        written = await asyncio.gather(
            write_draft_config(engine, run_id, _patch({"eta": 0.9}), author="a"),
            write_draft_config(engine, run_id, _patch({"K": 20.0}), author="b"),
        )
        params, revisions = await _params_and_revisions(engine, run_id)
        return sorted(written), params, revisions

    written, params, revisions = _run(settings, database_url, body)

    assert written == [2, 3]
    assert (params["eta"], params["K"]) == (0.9, 20.0)
    assert revisions == [1, 2, 3]


def test_the_same_field_written_twice_holds_the_later_value(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: Any) -> dict[str, Any]:
        run_id = await create_run(engine, name="Concept", author="seed")
        await write_draft_config(engine, run_id, _patch({"eta": 0.9}), author="a")
        await write_draft_config(engine, run_id, _patch({"eta": 0.7}), author="b")
        params, _ = await _params_and_revisions(engine, run_id)
        return params

    assert _run(settings, database_url, body)["eta"] == 0.7


def test_fifty_concurrent_writes_get_revisions_2_to_51(
    settings: Settings, database_url: str
) -> None:
    """AC13: no gap, no collision."""

    async def body(engine: Any) -> tuple[list[int], list[int]]:
        run_id = await create_run(engine, name="Concept", author="seed")
        written = await asyncio.gather(
            *(
                write_draft_config(engine, run_id, _patch({"eta": 1.0 + i / 100}), author=f"w{i}")
                for i in range(50)
            )
        )
        _, revisions = await _params_and_revisions(engine, run_id)
        return sorted(written), revisions

    written, revisions = _run(settings, database_url, body)

    assert written == list(range(2, 52))
    assert revisions == list(range(1, 52))
