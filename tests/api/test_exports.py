"""The export routes (Phase 7 T12: AC7, AC17, AC20, AC25, AC35; SD6, SD12; PD8, PD10).

The queue rule itself is pinned in `tests/integration/test_export_queue.py`.
Here the routes, with the export worker **paused** -- `boot.run_worker` is
swapped for one that only waits -- so an export stays where a test put it,
except in the one test that asks for the `live_worker` and builds for real.
Bar and display get 403 in the authorization matrix; the POST's 503 while
draining is in `test_draining.py`.
"""

from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Any

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.runtime.boot as boot
from app.api.exports import XLSX, filename
from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import Login

T0_2025_10_01_1000 = 1_759_312_800_000


@pytest.fixture
def live_worker() -> None:
    """Requested by a test that wants the real export worker running."""


@pytest.fixture(autouse=True)
def _paused_worker(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "live_worker" in request.fixturenames:
        return

    async def paused(**_: Any) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(boot, "run_worker", paused)


def _sql(settings: Settings, url: str, statement: str, **params: Any) -> list[tuple[Any, ...]]:
    async def scenario() -> list[tuple[Any, ...]]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(statement), params)
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _done_export(settings: Settings, url: str, run_id: int, data: bytes) -> int:
    """A finished export holding `data`, created at 2025-10-01 10:00 UTC."""
    [(export_id,)] = _sql(
        settings,
        url,
        "INSERT INTO export (run_id, kind, status, requested_by, data, sha256, bytes,"
        " line_count, total_cents, created_at, finished_at)"
        " VALUES (:r, 'manual', 'done', 't', :d, 'x', :n, 0, 0,"
        " to_timestamp(:c / 1000.0), now()) RETURNING export_id",
        r=run_id,
        d=data,
        n=len(data),
        c=T0_2025_10_01_1000,
    )
    return int(export_id)


def test_a_request_is_202_queued_and_wakes_the_worker(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    """AC17: answered before any build (the worker is paused), then the worker is woken."""
    admin = login("admin", label="Bestuur")
    wakeup = live_client.app.state.export_wakeup  # type: ignore[attr-defined]
    wakeup.clear()

    response = admin.post(f"/api/runs/{live_run}/exports")

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["run_id"], body["kind"], body["status"], body["requested_by"]) == (
        live_run,
        "manual",
        "queued",
        "Bestuur",
    )
    assert body["bytes"] is None and body["finished_at_ms"] is None
    assert "data" not in body
    assert wakeup.is_set()


def test_the_same_run_twice_is_one_export_and_a_full_slot_is_409(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC20 over HTTP: coalesced on the run; `export_busy` with two others in flight."""
    admin = login("admin")
    first = admin.post(f"/api/runs/{live_run}/exports").json()
    again = admin.post(f"/api/runs/{live_run}/exports").json()
    _sql(
        settings,
        api_env,
        "INSERT INTO run (name, params, run_seed) VALUES ('Oud', '{}', 1), ('Ouder', '{}', 2)",
    )
    others = [
        r
        for (r,) in _sql(settings, api_env, "SELECT run_id FROM run WHERE run_id <> :r", r=live_run)
    ]

    second = admin.post(f"/api/runs/{others[0]}/exports")
    busy = admin.post(f"/api/runs/{others[1]}/exports")

    assert again == first
    assert second.status_code == 202
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "export_busy"


def test_the_list_is_newest_first_without_data(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    admin = login("admin")
    done = _done_export(settings, api_env, live_run, b"PK-old")
    queued = admin.post(f"/api/runs/{live_run}/exports").json()["export_id"]

    response = admin.get(f"/api/runs/{live_run}/exports")

    assert response.status_code == 200, response.text
    assert [e["export_id"] for e in response.json()] == [queued, done]
    assert all("data" not in e for e in response.json())
    assert response.json()[1]["created_at_ms"] == T0_2025_10_01_1000


def test_one_export_and_its_404s(live_client: TestClient, live_run: int, login: Login) -> None:
    admin = login("admin")
    export_id = admin.post(f"/api/runs/{live_run}/exports").json()["export_id"]

    found = admin.get(f"/api/exports/{export_id}")
    missing = admin.get("/api/exports/999999")
    unknown_run = admin.post("/api/runs/999999/exports")
    unknown_list = admin.get("/api/runs/999999/exports")

    assert (found.status_code, found.json()["export_id"]) == (200, export_id)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "export_not_found")
    assert (unknown_run.status_code, unknown_run.json()["error"]["code"]) == (404, "run_not_found")
    assert unknown_list.status_code == 404


def test_the_file_of_an_unfinished_export_is_409(
    live_client: TestClient, live_run: int, login: Login
) -> None:
    admin = login("admin")
    export_id = admin.post(f"/api/runs/{live_run}/exports").json()["export_id"]

    response = admin.get(f"/api/exports/{export_id}/file")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "export_not_ready"


def test_the_file_carries_the_xlsx_headers(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC25, PD10: content type, attachment filename (run name, created_at in UTC), nosniff."""
    export_id = _done_export(settings, api_env, live_run, b"PK\x03\x04 workbook")

    response = login("admin").get(f"/api/exports/{export_id}/file")

    assert response.status_code == 200
    assert response.content == b"PK\x03\x04 workbook"
    assert response.headers["content-type"] == XLSX
    assert response.headers["content-disposition"] == (
        'attachment; filename="borrel-borrel-20251001-1000.xlsx"'
    )
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Vrijmibo", "borrel-vrijmibo-20251001-1000.xlsx"),
        ("Café Ölé  &  Co!", "borrel-cafe-ole-co-20251001-1000.xlsx"),
        ("  --Borrel 7--  ", "borrel-borrel-7-20251001-1000.xlsx"),
        ("日本語", "borrel-run-42-20251001-1000.xlsx"),
        ("a" * 39 + " b", "borrel-" + "a" * 39 + "-20251001-1000.xlsx"),
        ('Quote" and \\ slash', "borrel-quote-and-slash-20251001-1000.xlsx"),
    ],
)
def test_the_filename_is_pd10s(name: str, expected: str) -> None:
    result = filename(name, 42, T0_2025_10_01_1000 + 59_999)

    assert result == expected
    assert re.fullmatch(r"borrel-[a-z0-9-]{1,40}-\d{8}-\d{4}\.xlsx", result)


def test_the_reads_answer_while_draining(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC35: the GET routes still work while the process drains."""
    admin = login("admin")
    export_id = _done_export(settings, api_env, live_run, b"PK")
    live_client.app.state.draining = True  # type: ignore[attr-defined]
    try:
        statuses = [
            admin.get(path).status_code
            for path in (
                f"/api/runs/{live_run}/exports",
                f"/api/exports/{export_id}",
                f"/api/exports/{export_id}/file",
            )
        ]
    finally:
        live_client.app.state.draining = False  # type: ignore[attr-defined]

    assert statuses == [200, 200, 200]


def _until_done(client: TestClient, export_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        body: dict[str, Any] = client.get(f"/api/exports/{export_id}").json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.1)
    raise AssertionError(f"export {export_id} never finished")


def test_a_requested_export_is_built_and_downloads(
    live_worker: None, live_client: TestClient, live_run: int, login: Login
) -> None:
    """AC17 end to end: request, poll, download a workbook holding the run's sale."""
    admin = login("admin")
    state = admin.get("/api/state").json()
    drink, price = next(iter(state["prices"].items()))
    order = admin.post(
        "/api/orders",
        json={
            "quote_version": state["version"],
            "lines": [{"drink_id": int(drink), "qty": 3, "unit_price_cents": price["price_cents"]}],
        },
        headers={"Idempotency-Key": "k-export-0001"},
    )
    assert order.status_code == 201, order.text
    export_id = admin.post(f"/api/runs/{live_run}/exports").json()["export_id"]

    done = _until_done(admin, export_id)
    response = admin.get(f"/api/exports/{export_id}/file")

    assert (done["status"], done["line_count"]) == ("done", 1), done
    assert done["total_cents"] == order.json()["total_cents"]
    assert response.status_code == 200
    assert len(response.content) == done["bytes"]
    book = openpyxl.load_workbook(io.BytesIO(response.content))
    assert [row[3] for row in book["Sales"].iter_rows(min_row=2, values_only=True)] == [3]


def test_a_full_slot_never_refuses_a_close(
    live_client: TestClient, live_run: int, login: Login, settings: Settings, api_env: str
) -> None:
    """AC20: with one export running and one waiting, the close still queues its final."""
    _sql(
        settings,
        api_env,
        "INSERT INTO run (name, params, run_seed, status) VALUES ('Oud', '{}', 1, 'ended')",
    )
    _sql(
        settings,
        api_env,
        "INSERT INTO export (run_id, kind, status, requested_by)"
        " SELECT run_id, 'manual', s, 't' FROM run, (VALUES ('running'), ('queued')) v(s)"
        " WHERE run_id <> :r",
        r=live_run,
    )

    response = login("admin").post(f"/api/runs/{live_run}/close", json={"confirm_name": "Borrel"})

    assert response.status_code == 200, response.text
    assert _sql(
        settings, api_env, "SELECT kind, status FROM export WHERE run_id = :r", r=live_run
    ) == [("final", "queued")]
