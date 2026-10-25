"""Static assets and the API boundary (Phase 3 T28: SD1; AC2, AC6f).

The SPA's files are public (SD1), so what they may hold is the question: only
what is in `web/dist`. Run data lives under `/api` and `/ws` alone, and an
unknown `/api` path is a JSON 404, never the SPA's HTML (AC6f).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main
from app.main import create_app
from tests.api.conftest import BASE_URL
from tests.meta.test_route_authorization import PUBLIC_ROUTES, flatten
from tests.support.clock import FakeClock

INDEX = b"<!doctype html><title>BorrelBeurs</title>"
ASSET = b"console.log('bb');"
KOERS = b"<!doctype html><title>Koers</title>"


@pytest.fixture
def static_client(
    api_env: str, clock: FakeClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "koers").mkdir()
    (dist / "index.html").write_bytes(INDEX)
    (dist / "assets" / "app.js").write_bytes(ASSET)
    (dist / "koers" / "index.html").write_bytes(KOERS)
    (tmp_path / "secret.txt").write_text("outside dist", encoding="utf-8")
    monkeypatch.setattr(app.main, "WEB_DIST", dist)
    with TestClient(create_app(clock=clock, run_migrations=False), base_url=BASE_URL) as client:
        yield client


def test_unauthenticated_static_requests_get_only_files_from_dist(
    static_client: TestClient,
) -> None:
    """AC2: the root, a page route and an asset serve exactly their dist files, nothing else."""
    root = static_client.get("/")
    koers = static_client.get("/koers", follow_redirects=True)
    asset = static_client.get("/assets/app.js")

    assert (root.status_code, root.content) == (200, INDEX)
    assert (koers.status_code, koers.content) == (200, KOERS)
    assert (asset.status_code, asset.content) == (200, ASSET)
    assert static_client.get("/../secret.txt").status_code == 404


def test_every_non_public_route_is_under_api_or_ws(static_client: TestClient) -> None:
    """AC2: run data is reachable only through `/api/...` and `/ws`."""
    public_paths = {path for _, path in PUBLIC_ROUTES}
    paths = {
        getattr(route, "path", "")
        for route in flatten(static_client.app.routes)  # type: ignore[attr-defined]
    }
    data_paths = {p for p in paths if p not in public_paths}

    assert data_paths, "the walk found no routes"
    assert all(p.startswith("/api/") or p == "/ws" for p in data_paths), sorted(data_paths)


@pytest.mark.parametrize("path", ["/api/unknown", "/api/state/extra", "/api/"])
def test_an_unknown_api_path_is_a_json_404_not_the_spa(
    static_client: TestClient, path: str
) -> None:
    """AC6f."""
    response = static_client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert INDEX not in response.content


# --- history-mode fallback (Phase 4 T6: PD8; AC20-AC23) ------------------------


@pytest.fixture
def spa_client(
    api_env: str, clock: FakeClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """The real Vite shape: one `index.html`, hashed assets, no per-route directories."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_bytes(INDEX)
    (dist / "assets" / "x.js").write_bytes(ASSET)
    monkeypatch.setattr(app.main, "WEB_DIST", dist)
    with TestClient(create_app(clock=clock, run_migrations=False), base_url=BASE_URL) as client:
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/login",
        "/login?next=%2Fkoers",
        "/koers",
        "/bar",
        "/manipulation",
        "/settings",
        "/analytics",
        "/kassa",
    ],
)
def test_a_reload_of_an_spa_route_serves_index_html(spa_client: TestClient, path: str) -> None:
    """PD8: `/login` and every route in `ROLE_ROUTES` render the app on a reload."""
    response = spa_client.get(path)

    assert (response.status_code, response.content) == (200, INDEX)


def test_the_spa_routes_are_login_plus_the_role_table() -> None:
    """PD8: the server's own table, not a copy."""
    assert {
        "/login",
        "/",
        "/koers",
        "/bar",
        "/manipulation",
        "/settings",
        "/analytics",
        "/kassa",
    } == app.main.SPA_ROUTES


@pytest.mark.parametrize("path", ["/probe", "/koers/x", "/login/", "/settings.json"])
def test_any_other_unknown_path_stays_a_plain_404(spa_client: TestClient, path: str) -> None:
    response = spa_client.get(path)

    assert response.status_code == 404
    assert INDEX not in response.content


def test_an_unknown_api_path_is_still_a_json_404(spa_client: TestClient) -> None:
    response = spa_client.get("/api/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_an_existing_asset_is_served(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/x.js")

    assert (response.status_code, response.content) == (200, ASSET)


def test_the_fallback_is_for_get_only(spa_client: TestClient) -> None:
    assert spa_client.post("/koers", headers={"origin": BASE_URL}).status_code in {404, 405}


# --- Cache-Control (Phase 8 T2: AC27) -----------------------------------------
#
# A deploy must reach every phone on its next load: `index.html` names the hashed
# bundles, so it is never cached, and the hashed bundles never change, so they are
# cached for good. The upload route `/assets/{id}` sets its own (app/api/assets.py).

NO_STORE = "no-store"
IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.mark.parametrize("path", ["/", "/login", "/koers"])
def test_index_html_is_never_cached(spa_client: TestClient, path: str) -> None:
    response = spa_client.get(path)

    assert (response.status_code, response.content) == (200, INDEX)
    assert response.headers["cache-control"] == NO_STORE


def test_a_revalidated_index_html_keeps_no_store(spa_client: TestClient) -> None:
    """The 304 branch builds a new response; the header must survive it."""
    etag = spa_client.get("/").headers["etag"]

    response = spa_client.get("/", headers={"if-none-match": etag})

    assert response.status_code == 304
    assert response.headers["cache-control"] == NO_STORE


def test_a_hashed_asset_is_cached_for_good(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/x.js")

    assert (response.status_code, response.content) == (200, ASSET)
    assert response.headers["cache-control"] == IMMUTABLE


def test_other_root_files_are_left_alone(
    api_env: str, clock: FakeClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_bytes(INDEX)
    (dist / "favicon.svg").write_bytes(b"<svg/>")
    monkeypatch.setattr(app.main, "WEB_DIST", dist)
    with TestClient(create_app(clock=clock, run_migrations=False), base_url=BASE_URL) as client:
        response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_the_built_frontend_carries_both_headers(
    api_env: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC27 on the real `pnpm build` output, which `check.sh` builds before this step."""
    dist = app.main.WEB_DIST
    bundles = sorted((dist / "assets").glob("*.js")) if dist.is_dir() else []
    if not bundles:
        pytest.skip("web/dist is not built; scripts/check.sh builds it before this step")
    with TestClient(create_app(clock=clock, run_migrations=False), base_url=BASE_URL) as client:
        index = client.get("/settings")
        bundle = client.get(f"/assets/{bundles[0].name}")

    assert index.status_code == 200
    assert index.headers["cache-control"] == NO_STORE
    assert bundle.status_code == 200
    assert bundle.headers["cache-control"] == IMMUTABLE
