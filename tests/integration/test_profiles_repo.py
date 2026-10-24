"""The settings-profile repository (B-04 T1: SD5, SD7, SD8, SD14, SD15; PD4, PD5, PD6)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db.profiles import (
    ProfileExists,
    ProfileNotFound,
    ProfileRow,
    delete_profile,
    get_profile,
    list_profiles,
    save_profile,
)
from app.db.session import create_engine

T = TypeVar("T")

WILD = {"eta": 0.9, "candle_interval_s": 30}
CALM = {"eta": 0.2, "candle_interval_s": 120}


def _transaction(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _save(
    settings: Settings,
    url: str,
    name: str,
    values: dict[str, Any],
    *,
    overwrite: bool = False,
    source: str = "Proef",
    by: str = "admin-1",
) -> tuple[ProfileRow, bool]:
    return _transaction(
        settings,
        url,
        lambda conn: save_profile(
            conn,
            name=name,
            settings=values,
            source_run_name=source,
            saved_by=by,
            overwrite=overwrite,
        ),
    )


def test_a_save_inserts_a_profile(settings: Settings, database_url: str) -> None:
    row, created = _save(settings, database_url, "  Wilde beurs ", WILD)

    assert created is True
    stored = _transaction(settings, database_url, lambda conn: get_profile(conn, row.profile_id))
    assert stored == row
    assert (stored.name, stored.settings, stored.source_run_name, stored.saved_by) == (
        "Wilde beurs",
        WILD,
        "Proef",
        "admin-1",
    )


def test_the_same_name_differently_cased_and_spaced_exists(
    settings: Settings, database_url: str
) -> None:
    """SD5, PD5: compared trimmed and case-folded; 409 carries the id, nothing changes."""
    first, _ = _save(settings, database_url, "Wilde beurs", WILD)

    with pytest.raises(ProfileExists) as raised:
        _save(settings, database_url, "  WILDE BEURS  ", CALM, source="Ander")

    assert raised.value.code == "profile_exists"
    assert raised.value.status_code == 409
    assert raised.value.extra == {"profile_id": first.profile_id}
    assert _transaction(settings, database_url, list_profiles) == [first]


def test_an_overwrite_replaces_the_values_and_keeps_the_stored_name(
    settings: Settings, database_url: str
) -> None:
    first, _ = _save(settings, database_url, "Wilde beurs", WILD)

    row, created = _save(
        settings, database_url, "wilde BEURS", CALM, overwrite=True, source="Ander", by="admin-2"
    )

    assert created is False
    assert row.profile_id == first.profile_id
    assert (row.name, row.settings, row.source_run_name, row.saved_by) == (
        "Wilde beurs",
        CALM,
        "Ander",
        "admin-2",
    )
    assert row.saved_at > first.saved_at
    assert _transaction(settings, database_url, list_profiles) == [row]


def test_an_overwrite_of_a_missing_name_inserts(settings: Settings, database_url: str) -> None:
    """SD15: a profile deleted in the meantime is simply created."""
    row, created = _save(settings, database_url, "Rustig", CALM, overwrite=True)

    assert created is True
    assert _transaction(settings, database_url, list_profiles) == [row]


def test_two_concurrent_saves_of_one_new_name_make_one_row(
    settings: Settings, database_url: str
) -> None:
    """SD15: the unique index lets exactly one insert win; the other gets `profile_exists`."""

    async def body() -> list[Any]:
        engine = create_engine(settings.model_copy(update={"database_url": database_url}))
        try:

            async def one(values: dict[str, Any]) -> ProfileRow:
                async with engine.begin() as conn:
                    row, _ = await save_profile(
                        conn,
                        name="Wilde beurs",
                        settings=values,
                        source_run_name="Proef",
                        saved_by="admin-1",
                        overwrite=False,
                    )
                    # Hold the transaction open so the other insert has to wait on it.
                    await conn.execute(text("SELECT pg_sleep(0.2)"))
                    return row

            return await asyncio.gather(one(WILD), one(CALM), return_exceptions=True)
        finally:
            await engine.dispose()

    outcomes = asyncio.run(body())

    rows = [o for o in outcomes if isinstance(o, ProfileRow)]
    refused = [o for o in outcomes if isinstance(o, ProfileExists)]
    assert (len(rows), len(refused)) == (1, 1), outcomes
    assert refused[0].extra == {"profile_id": rows[0].profile_id}
    assert _transaction(settings, database_url, list_profiles) == rows


def test_the_list_is_ordered_by_case_folded_name(settings: Settings, database_url: str) -> None:
    """SD12, PD6: sorted in Python by the case-folded name, not by the collation."""
    for name in ("gamma", "Beta", "alpha"):
        _save(settings, database_url, name, WILD)

    names = [row.name for row in _transaction(settings, database_url, list_profiles)]

    assert names == ["alpha", "Beta", "gamma"]


def test_a_delete_removes_the_profile(settings: Settings, database_url: str) -> None:
    keep, _ = _save(settings, database_url, "Rustig", CALM)
    gone, _ = _save(settings, database_url, "Wilde beurs", WILD)

    _transaction(settings, database_url, lambda conn: delete_profile(conn, gone.profile_id))

    assert _transaction(settings, database_url, list_profiles) == [keep]


@pytest.mark.parametrize("action", ["get", "delete"])
def test_an_unknown_profile_is_not_found(
    settings: Settings, database_url: str, action: str
) -> None:
    call = get_profile if action == "get" else delete_profile

    with pytest.raises(ProfileNotFound) as raised:
        _transaction(settings, database_url, lambda conn: call(conn, 999_999))

    assert (raised.value.status_code, raised.value.code) == (404, "profile_not_found")


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_the_database_refuses_a_name_outside_1_to_100_characters(
    settings: Settings, database_url: str, name: str
) -> None:
    """SD14: the same rule as a run name, `run_name_check`."""
    with pytest.raises(IntegrityError, match="settings_profile_name_check"):
        _save(settings, database_url, name, WILD)
