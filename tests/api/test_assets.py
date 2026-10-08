"""Image uploads and serving (Phase 6 T18: SD29; AC31-AC34; PD1, PD10).

`POST /api/theme/images/{slot}` takes multipart `file`, typed by magic bytes
only (AC31), and never reads more than the limit plus one chunk (AC33). One
transaction stores the asset, points the slot at it, deletes the slot's previous
asset and bumps the theme revision, so no asset outlives its slot (AC34).
`GET /assets/{asset_id}` serves it publicly with SD29's headers (AC32).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine
from tests.api.conftest import Login
from tests.unit.test_images import GIF89, JPEG, PNG, SVG, WEBP

MB = 1024 * 1024
ORPHANS = """SELECT count(*) FROM asset WHERE asset_id NOT IN (
    SELECT unnest(ARRAY[bg_asset_id, header_asset_id, logo_asset_id, promo_asset_id])
    FROM theme WHERE id = 1) OR NOT EXISTS (SELECT 1 FROM theme)"""


def _sql(settings: Settings, url: str, sql: str) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text(sql))).scalar_one()
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _upload(
    client: TestClient, slot: str, data: bytes, *, name: str = "x.png", kind: str = "image/png"
) -> Any:
    return client.post(f"/api/theme/images/{slot}", files={"file": (name, data, kind)})


@pytest.mark.parametrize(
    ("data", "content_type"),
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (GIF89, "image/gif"), (WEBP, "image/webp")],
)
def test_each_type_is_accepted_and_served_with_sd29s_headers(
    client: TestClient, login: Login, data: bytes, content_type: str
) -> None:
    """AC31, AC32: the stored type comes from the bytes, not the name or the client's type."""
    admin = login("admin")

    response = _upload(admin, "logo", data, name="whatever.bin", kind="application/octet-stream")

    assert response.status_code == 201, response.text
    asset_id = response.json()["asset_id"]
    client.cookies.clear()
    served = client.get(f"/assets/{asset_id}")
    assert served.status_code == 200
    assert served.content == data
    assert served.headers["content-type"] == content_type
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-security-policy"] == "default-src 'none'"
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_an_svg_named_png_is_415_and_stores_nothing(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC31."""
    response = _upload(login("admin"), "bg", SVG, name="logo.png", kind="image/png")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert _sql(settings, api_env, "SELECT count(*) FROM asset") == 0


def test_an_upload_bumps_the_theme_and_broadcasts_it(client: TestClient, login: Login) -> None:
    admin = login("admin")
    hub = client.app.state.hub  # type: ignore[attr-defined]
    before = hub.seq

    assert _upload(admin, "promo", PNG).status_code == 201

    frames = [json.loads(f) for f in hub.replay_after(hub.boot_id, before)]
    assert [f["type"] for f in frames] == ["theme"]
    assert frames[0]["data"]["revision"] == 1
    assert client.app.state.theme.revision == 1  # type: ignore[attr-defined]


def test_replacing_then_removing_leaves_no_orphan(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC34."""
    admin = login("admin")
    first = _upload(admin, "bg", PNG).json()["asset_id"]
    _upload(admin, "logo", GIF89)

    second = _upload(admin, "bg", JPEG).json()["asset_id"]

    assert _sql(settings, api_env, ORPHANS) == 0
    assert _sql(settings, api_env, "SELECT count(*) FROM asset") == 2
    assert client.get(f"/assets/{first}").status_code == 404
    removed = admin.delete("/api/theme/images/bg")
    assert removed.status_code == 200, removed.text
    assert _sql(settings, api_env, ORPHANS) == 0
    assert _sql(settings, api_env, "SELECT count(*) FROM asset") == 1
    assert client.get(f"/assets/{second}").status_code == 404
    assert _sql(settings, api_env, "SELECT revision FROM theme") == 4


def test_removing_an_empty_slot_changes_nothing(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    response = login("admin").delete("/api/theme/images/promo")

    assert response.status_code == 200, response.text
    assert _sql(settings, api_env, "SELECT count(*) FROM theme") == 0


def test_an_unknown_slot_is_422(client: TestClient, login: Login) -> None:
    assert _upload(login("admin"), "favicon", PNG).status_code == 422


def test_a_missing_file_field_is_422(client: TestClient, login: Login) -> None:
    response = login("admin").post("/api/theme/images/bg", files={"other": ("x.png", PNG)})

    assert response.status_code == 422


def test_an_unknown_asset_is_404(client: TestClient) -> None:
    assert client.get("/assets/999999").status_code == 404


def test_a_six_mb_body_without_content_length_is_413(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC33: chunked, so only the bounded reader can stop it."""
    admin = login("admin")
    boundary = "b0undary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()

    def body() -> Iterator[bytes]:
        yield head + PNG
        for _ in range(6 * 16):
            yield b"\x00" * (64 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode()

    response = admin.post(
        "/api/theme/images/bg",
        content=body(),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"
    assert _sql(settings, api_env, "SELECT count(*) FROM asset") == 0


def test_a_six_mb_content_length_is_413_before_any_read(client: TestClient, login: Login) -> None:
    """AC33: refused on the header; the app never asks for a body chunk."""
    login("admin")
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    received = 0
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"\x00" * (64 * 1024), "more_body": True}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/theme/images/bg",
        "raw_path": b"/api/theme/images/bg",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 443),
        "client": ("testclient", 50000),
        "headers": [
            (b"host", b"testserver"),
            (b"origin", b"https://testserver"),
            (b"cookie", cookie.encode()),
            (b"content-type", b"multipart/form-data; boundary=b0undary"),
            (b"content-length", str(6 * MB).encode()),
        ],
        "state": dict(client.app_state),
    }

    async def call() -> None:
        await client.app(scope, receive, send)

    client.portal.call(call)  # type: ignore[union-attr]

    assert sent[0]["status"] == 413
    assert received == 0


@pytest.mark.parametrize("role", ["display", "bar"])
def test_other_roles_may_not_upload_or_remove(client: TestClient, login: Login, role: str) -> None:
    session = login(role)

    assert _upload(session, "bg", PNG).status_code == 403
    assert session.delete("/api/theme/images/bg").status_code == 403
