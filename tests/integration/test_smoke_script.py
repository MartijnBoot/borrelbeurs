"""`scripts/smoke.py` against the real process (Phase 8 T10: SD12; the tool AC6, AC9, AC28 use).

The app runs as `python -m app.main` (`tests/integration/realapp/harness.py`) with
`BUILD_SHA` in its environment; the script runs as its own process, as the deploy
workflow runs it, with the key in `BB_SMOKE_KEY`. Its output must never hold the key.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.realapp.harness import REPO_ROOT, AppProcess, Client, mint_key, start_app

SHA = "0123456789abcdef0123456789abcdef01234567"
SMOKE = REPO_ROOT / "scripts" / "smoke.py"


@pytest.fixture
def app(database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppProcess]:
    monkeypatch.setenv("BUILD_SHA", SHA)
    running = start_app(database_url, tmp_path / "app.stderr")
    try:
        yield running
    finally:
        running.kill()


def _smoke(base: str, key: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "BB_SMOKE_KEY"}
    return subprocess.run(
        [sys.executable, str(SMOKE), base, *args],
        env={**env, "BB_SMOKE_KEY": key},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _theme(base: str) -> tuple[int, str]:
    status, _ = Client(base).request("GET", "/healthz")
    assert status == 200
    with urllib.request.urlopen(f"{base}/theme.css", timeout=5) as response:
        etag = response.headers["ETag"]
    _, revision, preset = etag.strip('"').split("-")
    return int(revision), preset


def test_the_right_build_passes_and_resaves_the_theme_unchanged(
    app: AppProcess, database_url: str
) -> None:
    key = mint_key(database_url, "admin")
    before = _theme(app.base)

    result = _smoke(app.base, key, "--expect-sha", SHA)

    assert result.returncode == 0, result.stdout + result.stderr
    assert [line.split()[1] for line in result.stdout.splitlines()[:7]] == [
        "healthz",
        "readyz",
        "login",
        "me",
        "runs/current",
        "theme",
        "logout",
    ]
    assert _theme(app.base) == (before[0] + 1, before[1])
    assert key not in result.stdout + result.stderr


def test_a_wrong_build_fails_once_the_wait_runs_out(app: AppProcess, database_url: str) -> None:
    key = mint_key(database_url, "admin")

    result = _smoke(app.base, key, "--expect-sha", "f" * 40, "--wait-seconds", "1")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith("FAIL /healthz")
    assert key not in result.stdout + result.stderr


def test_a_bar_key_fails_at_the_me_step(app: AppProcess, database_url: str) -> None:
    key = mint_key(database_url, "bar")

    result = _smoke(app.base, key)

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith("FAIL me:")
    assert key not in result.stdout + result.stderr


def test_the_etag_shape_smoke_relies_on(app: AppProcess) -> None:
    """PD13: the re-save reads the preset from this header; a change to it fails here."""
    with urllib.request.urlopen(f"{app.base}/theme.css", timeout=5) as response:
        etag = response.headers["ETag"]

    assert etag.startswith('"theme-') and etag.endswith('"')
    _, revision, preset = etag.strip('"').split("-")
    assert revision.isdigit() and preset.isalpha()
