"""The image boot drill (Phase 8 T13: AC6, AC7, AC9, AC10 at image level; PD3).

The image under test boots against its own throwaway Postgres (`conftest.py`):

- **AC6:** it reports the `BUILD_SHA` it was built with, in `/healthz` and its start
  log, and `scripts/smoke.py --expect-sha` passes against it;
- **AC7:** the frontend it carries references nothing off-origin
  (`scripts/check_built_assets.py` on its own `/app/web/dist`);
- **AC9, new image on the old schema:** a database at `head-1`, migrated by the
  image's own alembic, is migrated at boot and passes smoke;
- **AC9, old image on the new schema** (PD3): no SD3 image older than this one exists
  yet, so the *database* is made one contract-free revision ahead -- stamped
  `ci_ahead_fixture` with the floor left at `0011` -- and the same image must log
  `schema_ahead` and pass smoke;
- **AC10:** with the floor raised to `ci_ahead_fixture` it refuses: non-zero exit,
  `boot_failed` / `schema ahead of image`, `alembic_version` unchanged;
- with `--previous-image`, that image boots against head too (unused in CI until a
  second SD3 image exists in GHCR, R3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from scripts.check_built_assets import main as check_built_assets
from tests.image.conftest import REPO_ROOT, App, Stack, docker

AHEAD = "ci_ahead_fixture"
SMOKE = REPO_ROOT / "scripts" / "smoke.py"


def _head_and_previous() -> tuple[str, str]:
    script = ScriptDirectory(str(REPO_ROOT / "db" / "migrations"))
    head = script.get_current_head()
    assert head is not None
    previous = script.get_revision(head).down_revision
    assert isinstance(previous, str)
    return head, previous


def _image_build_sha(image: str) -> str:
    out = docker("image", "inspect", "--format", "{{json .Config.Env}}", image)
    env = dict(str(item).split("=", 1) for item in json.loads(out.stdout))
    sha = env["BUILD_SHA"]
    # The image's own value proves nothing if the build arg was dropped (it says `unknown`):
    # in CI the commit being built is the expected one.
    expected = os.environ.get("GITHUB_SHA")
    if expected:
        assert sha == expected, (sha, expected)
    return sha


def _admin_key(stack: Stack) -> str:
    created = stack.run_cli(
        "python", "-m", "app.cli.keys", "create", "--role", "admin", "--label", "drill"
    )
    assert created.returncode == 0, created.stderr
    return created.stdout.strip()


def _smoke(app: App, key: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SMOKE), app.base, "--wait-seconds", "60", *args],
        env={**os.environ, "BB_SMOKE_KEY": key},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _migrate(stack: Stack, revision: str) -> None:
    done = stack.run_cli("alembic", "-c", "db/alembic.ini", "upgrade", revision)
    assert done.returncode == 0, done.stderr


def test_the_image_reports_its_build_and_passes_smoke(stack: Stack, image: str) -> None:
    """AC6."""
    sha = _image_build_sha(image)
    _migrate(stack, "head")
    key = _admin_key(stack)
    app = stack.start_app()
    app.wait_ready()

    result = _smoke(app, key, "--expect-sha", sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert app.get("/healthz")[1]["build_sha"] == sha
    assert f'"build_sha": "{sha}"' in app.logs()


def test_the_built_frontend_in_the_image_stays_on_origin(image: str, tmp_path: Path) -> None:
    """AC7 (ADR 0006): checked on what the image serves, not on a local build."""
    container = docker("create", image).stdout.strip()
    try:
        docker("cp", f"{container}:/app/web/dist", str(tmp_path / "dist"))
    finally:
        docker("rm", "--force", container, check=False)

    assert check_built_assets([str(tmp_path / "dist")]) == 0


def test_a_database_one_revision_behind_is_migrated_at_boot(stack: Stack) -> None:
    """AC9, new image on the previous release's schema."""
    head, previous = _head_and_previous()
    _migrate(stack, previous)
    key = _admin_key(stack)
    app = stack.start_app()
    app.wait_ready()

    assert stack.psql("SELECT version_num FROM alembic_version") == head
    result = _smoke(app, key)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_schema_ahead_but_compatible_is_served_as_it_is(stack: Stack) -> None:
    """AC9, an image on a schema one contract-free revision newer than it knows (PD3)."""
    _migrate(stack, "head")
    stack.psql(f"UPDATE alembic_version SET version_num = '{AHEAD}'")
    key = _admin_key(stack)
    app = stack.start_app()
    app.wait_ready()

    assert '"message": "schema_ahead"' in app.logs()
    assert stack.psql("SELECT version_num FROM alembic_version") == AHEAD
    result = _smoke(app, key)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_schema_ahead_and_incompatible_is_refused(stack: Stack) -> None:
    """AC10 at image level: exits non-zero, writing nothing."""
    _migrate(stack, "head")
    stack.psql(f"UPDATE alembic_version SET version_num = '{AHEAD}'")
    stack.psql(f"UPDATE schema_compat SET min_code_revision = '{AHEAD}'")
    app = stack.start_app()

    code = app.wait_exit()

    assert code != 0
    logs = app.logs()
    assert '"message": "boot_failed"' in logs and "schema ahead of image" in logs
    assert stack.psql("SELECT version_num FROM alembic_version") == AHEAD
    assert app.get("/readyz")[0] != 200


def test_the_previous_image_boots_against_head(
    stack: Stack, request: pytest.FixtureRequest
) -> None:
    """AC9's other direction with a real older image, once one exists (PD3, R3)."""
    previous: str | None = request.config.getoption("--previous-image")
    if not previous:
        pytest.skip("no --previous-image given; CI passes one once GHCR holds an SD3 image")
    _migrate(stack, "head")
    key = _admin_key(stack)
    app = stack.start_app(image=previous, name="previous")
    app.wait_ready()

    result = _smoke(app, key)
    assert result.returncode == 0, result.stdout + result.stderr
