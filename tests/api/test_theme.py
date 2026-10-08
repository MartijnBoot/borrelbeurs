"""`GET /theme.css` and `PUT /api/theme` (Phase 4 T4: SD5, SD8, SD9; AC5, AC8, AC9, AC10; PD5)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import create_engine
from app.db.theme import ThemeRow, get_theme
from app.runtime.theme import PRESETS, TOKEN_NAMES, resolve
from tests.api.conftest import Login
from tests.api.test_assets import _upload
from tests.unit.test_images import PNG

BLAUW_BG = PRESETS["blauw"].tokens["--bg"]
INTER = PRESETS["blauw"].font_family
GARAMOND = PRESETS["oudgeld"].font_family


def _stored(settings: Settings, url: str) -> ThemeRow | None:
    async def scenario() -> ThemeRow | None:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                return await get_theme(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _theme_frames(client: TestClient, after_seq: int) -> list[dict[str, Any]]:
    hub = client.app.state.hub  # type: ignore[attr-defined]
    frames = hub.replay_after(hub.boot_id, after_seq)
    assert frames is not None
    return [f for f in map(json.loads, frames) if f["type"] == "theme"]


def test_a_fresh_database_serves_blauw_in_inter(client: TestClient) -> None:
    """AC9: no stored row, so Blauw at revision 0."""
    response = client.get("/theme.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert f"--bg:{BLAUW_BG};" in response.text
    assert f"font-family:{INTER}" in response.text
    assert response.headers["etag"] == '"theme-0-blauw"'


def test_theme_css_is_public(client: TestClient) -> None:
    """SD8: no session needed; the login page paints themed too."""
    client.cookies.clear()

    assert client.get("/theme.css").status_code == 200


def test_theme_css_revalidates_with_its_etag(client: TestClient) -> None:
    """SD8: `no-cache` plus an ETag from the revision, so a reload revalidates cheaply."""
    first = client.get("/theme.css")
    etag = first.headers["etag"]

    again = client.get("/theme.css", headers={"if-none-match": etag})
    stale = client.get("/theme.css", headers={"if-none-match": '"theme-99"'})

    assert first.headers["cache-control"] == "no-cache"
    assert (again.status_code, again.content) == (304, b"")
    assert again.headers["etag"] == etag
    assert stale.status_code == 200


def test_an_etag_from_before_a_reset_never_revalidates_another_preset(
    client: TestClient, login: Login
) -> None:
    """AC4: a recreated `theme` table restarts revisions at 1, so the ETag names the preset too.

    Without it, a browser that cached Oud Geld at revision 1 would get a 304 for
    Rood at revision 1 on the same origin and keep painting Oud Geld.
    """
    login("admin").put("/api/theme", json={"preset": "oudgeld"})
    cached = client.get("/theme.css").headers["etag"]
    client.app.state.theme = resolve("rood", 1)  # type: ignore[attr-defined]

    after = client.get("/theme.css", headers={"if-none-match": cached})

    assert after.status_code == 200
    assert f"--bg:{PRESETS['rood'].tokens['--bg']};" in after.text


def test_an_admin_put_stores_returns_and_serves_the_preset(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC10: after Oud Geld, the CSS carries the EB Garamond stack, at a new ETag."""
    response = login("admin").put("/api/theme", json={"preset": "oudgeld"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["preset"], body["revision"], body["font_family"]) == ("oudgeld", 1, GARAMOND)
    assert body["tokens"] == dict(PRESETS["oudgeld"].tokens)
    css = client.get("/theme.css")
    assert f"font-family:{GARAMOND}" in css.text
    assert css.headers["etag"] == '"theme-1-oudgeld"'
    stored = _stored(settings, api_env)
    assert stored is not None and (stored.preset, stored.revision) == ("oudgeld", 1)


@pytest.mark.parametrize("role", ["display", "bar"])
def test_only_an_admin_may_put(
    client: TestClient, login: Login, settings: Settings, api_env: str, role: str
) -> None:
    """AC8: 403, and the stored theme is unchanged."""
    response = login(role).put("/api/theme", json={"preset": "rood"})

    assert response.status_code == 403
    assert _stored(settings, api_env) is None
    assert f"--bg:{BLAUW_BG};" in client.get("/theme.css").text


@pytest.mark.parametrize(
    "body",
    [{"preset": "eigen"}, {"preset": "Blauw"}, {}, {"preset": "rood", "tokens": {}}],
    ids=["eigen", "capitalised", "empty", "extra-key"],
)
def test_an_invalid_body_is_422_and_changes_nothing(
    client: TestClient, login: Login, settings: Settings, api_env: str, body: dict[str, Any]
) -> None:
    """AC8: only the five preset names, nothing else in the body."""
    response = login("admin").put("/api/theme", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert _stored(settings, api_env) is None


def test_a_cross_origin_put_is_refused(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """SD9 of Phase 3: the OriginGuard covers this route like every other unsafe one."""
    admin = login("admin")

    response = admin.put(
        "/api/theme", json={"preset": "rood"}, headers={"origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert _stored(settings, api_env) is None


def test_with_no_live_run_a_put_broadcasts_exactly_one_theme(
    client: TestClient, login: Login
) -> None:
    """AC5 (server half): the hub carries the theme whether or not a run is live."""
    admin = login("admin")
    hub = client.app.state.hub  # type: ignore[attr-defined]
    assert client.app.state.holder.run_id is None  # type: ignore[attr-defined]
    before = hub.seq

    admin.put("/api/theme", json={"preset": "paars"})

    frames = _theme_frames(client, before)
    assert len(frames) == 1
    assert frames[0]["seq"] == before + 1
    assert (frames[0]["run_id"], frames[0]["version"]) == (None, None)
    assert (frames[0]["data"]["preset"], frames[0]["data"]["revision"]) == ("paars", 1)


def test_with_a_live_run_the_broadcast_names_the_run(live_client: TestClient, login: Login) -> None:
    admin = login("admin")
    hub = live_client.app.state.hub  # type: ignore[attr-defined]
    run_id = live_client.app.state.holder.run_id  # type: ignore[attr-defined]
    before = hub.seq

    admin.put("/api/theme", json={"preset": "groen"})

    frames = _theme_frames(live_client, before)
    assert [(f["run_id"], f["version"]) for f in frames] == [(run_id, None)]


def test_two_puts_give_increasing_revisions(client: TestClient, login: Login) -> None:
    admin = login("admin")

    first = admin.put("/api/theme", json={"preset": "rood"}).json()
    second = admin.put("/api/theme", json={"preset": "rood"}).json()

    assert (first["revision"], second["revision"]) == (1, 2)
    assert client.get("/theme.css").headers["etag"] == '"theme-2-rood"'


def test_a_put_never_takes_the_engine_state_lock(live_client: TestClient, login: Login) -> None:
    """SD9: with the holder's lock held elsewhere, the PUT still completes."""
    admin = login("admin")
    holder = live_client.app.state.holder  # type: ignore[attr-defined]
    portal = live_client.portal
    assert portal is not None
    portal.call(holder._lock.acquire)
    try:
        response = admin.put("/api/theme", json={"preset": "rood"})
    finally:
        portal.call(holder._lock.release)

    assert response.status_code == 200


# --- Phase 6 T17: the custom theme (SD28, PD8) ---------------------------------

CUSTOM = {name: f"#{0x101010 + i:06x}" for i, name in enumerate(TOKEN_NAMES)}


def test_saving_a_custom_theme_serves_every_token_and_broadcasts_once(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    """AC30 (server): all 24 values and the Garamond stack; one `theme` at a higher revision."""
    admin = login("admin")
    admin.put("/api/theme", json={"preset": "rood"})
    hub = client.app.state.hub  # type: ignore[attr-defined]
    before = hub.seq

    response = admin.put(
        "/api/theme", json={"preset": "custom", "tokens": CUSTOM, "font": "garamond"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["preset"], body["revision"], body["font_family"]) == ("custom", 2, GARAMOND)
    assert body["tokens"] == CUSTOM
    css = client.get("/theme.css").text
    assert all(f"{name}:{value};" in css for name, value in CUSTOM.items())
    assert f"font-family:{GARAMOND}" in css
    frames = _theme_frames(client, before)
    assert len(frames) == 1 and frames[0]["data"]["revision"] == 2
    stored = _stored(settings, api_env)
    assert stored is not None and stored.preset == "custom"


def test_custom_alone_reuses_the_stored_tokens(client: TestClient, login: Login) -> None:
    admin = login("admin")
    admin.put("/api/theme", json={"preset": "custom", "tokens": CUSTOM, "font": "inter"})
    admin.put("/api/theme", json={"preset": "groen"})

    response = admin.put("/api/theme", json={"preset": "custom"})

    assert response.status_code == 200, response.text
    assert (response.json()["tokens"], response.json()["font_family"]) == (CUSTOM, INTER)


def test_custom_with_none_stored_is_409(
    client: TestClient, login: Login, settings: Settings, api_env: str
) -> None:
    response = login("admin").put("/api/theme", json={"preset": "custom"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_custom_theme"
    assert _stored(settings, api_env) is None


@pytest.mark.parametrize(
    "body",
    [
        {"preset": "custom", "tokens": {**CUSTOM, "--bg": "red"}, "font": "inter"},
        {"preset": "custom", "tokens": {**CUSTOM, "--bg": "#12345"}, "font": "inter"},
        {"preset": "custom", "tokens": {**CUSTOM, "--bg": "#fff;}"}, "font": "inter"},
        {
            "preset": "custom",
            "tokens": {k: v for k, v in CUSTOM.items() if k != "--bg"},
            "font": "inter",
        },
        {"preset": "custom", "tokens": {**CUSTOM, "--extra": "#fff"}, "font": "inter"},
        {"preset": "custom", "tokens": CUSTOM, "font": "comic"},
        {"preset": "custom", "tokens": CUSTOM},
        {"preset": "custom", "font": "inter"},
        {"preset": "blauw", "tokens": CUSTOM, "font": "inter"},
    ],
    ids=[
        "named-colour",
        "five-digits",
        "css-injection",
        "missing-token",
        "extra-token",
        "unknown-font",
        "tokens-without-font",
        "font-without-tokens",
        "tokens-on-a-preset",
    ],
)
def test_an_invalid_custom_body_is_422_and_changes_nothing(
    client: TestClient, login: Login, settings: Settings, api_env: str, body: dict[str, Any]
) -> None:
    response = login("admin").put("/api/theme", json=body)

    assert response.status_code == 422, response.text
    assert _stored(settings, api_env) is None


def test_theme_css_paints_the_uploaded_images(client: TestClient, login: Login) -> None:
    """Phase 6 T19 (PD9; AC35): a set slot is a `--img-*` variable, and bg/header get rules."""
    admin = login("admin")
    logo = _upload(admin, "logo", PNG).json()["asset_id"]
    promo = _upload(admin, "promo", PNG).json()["asset_id"]

    css = client.get("/theme.css").text
    assert f'--img-logo:url("/assets/{logo}");' in css
    assert f'--img-promo:url("/assets/{promo}");' in css
    assert "--img-bg" not in css
    assert "--img-header" not in css
    assert "body::before" not in css

    bg = _upload(admin, "bg", PNG).json()["asset_id"]
    header = _upload(admin, "header", PNG).json()["asset_id"]
    css = client.get("/theme.css").text
    assert f'--img-bg:url("/assets/{bg}");' in css
    assert f'--img-header:url("/assets/{header}");' in css
    assert "body::before{" in css and "opacity:.12" in css
    assert "header{background-image:var(--img-header)" in css

    admin.delete("/api/theme/images/logo")
    assert "--img-logo" not in client.get("/theme.css").text
