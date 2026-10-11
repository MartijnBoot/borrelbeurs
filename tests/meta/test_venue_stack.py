"""AC24 and SD11's shape -- the venue stack is what the plan says it is (Phase 8 T15; PD14).

`deploy/venue/compose.yml` runs the image CI built, offline, beside a Postgres no other
machine can reach. The properties that make that true are each one line of YAML, and
each is easy to lose in an edit: a `build:` that turns a deploy into a build, a
`ports:` on `db` that offers the committed credentials to the router's Wi-Fi, a
`pull_policy` that reaches for the internet the venue does not have, a restart policy
that brings "Sluit app" back up or leaves a lost lock down.

Read as text, like `test_compose_matches_env_example.py` and for the same reason (no
YAML parser without a new dependency). `docker compose config` is the real parser; it
runs in the task's verification, and T16's venue drill runs the stack itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENUE = REPO_ROOT / "deploy" / "venue"
COMPOSE_FILE = VENUE / "compose.yml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CMD_FILES = ("start", "stop", "status", "backup-now", "restore", "logs")
PREFIX = "borrelbeurs-venue-"
POSTGRES = re.compile(r"postgres:16-alpine@sha256:[0-9a-f]{64}")


def _text() -> str:
    return COMPOSE_FILE.read_text(encoding="utf-8")


def _service(text: str, name: str) -> str:
    """The lines of one service under `services:`, up to the next one at its indent."""
    match = re.search(rf"^  {re.escape(name)}:\n((?:(?:    .*)?\n)*)", text, re.M)
    assert match, f"compose.yml has no service `{name}`"
    return match.group(1)


def _value(block: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$", block, re.M)
    return match.group(1) if match else None


def test_the_project_is_named_apart_from_the_dev_stack() -> None:
    assert re.search(r"^name:\s*borrelbeurs-venue\s*$", _text(), re.M)


def test_nothing_is_built_and_nothing_is_pulled() -> None:
    """SD11: the image CI tested, from the bundle -- never a build, never a pull."""
    text = _text()
    assert not re.search(r"^\s*build:", text, re.M)
    for name in ("db", "app", "backup"):
        assert _value(_service(text, name), "pull_policy") == "never", name


def test_the_app_runs_the_pushed_image_by_sha() -> None:
    block = _service(_text(), "app")
    image = _value(block, "image") or ""
    assert image.startswith("ghcr.io/martijnboot/borrelbeurs:${BB_IMAGE_SHA:?"), image


def test_the_app_runs_with_the_venue_profile() -> None:
    """SD11: venue profile, plain-http cookie, exports to the host, no proxy trusted."""
    block = _service(_text(), "app")
    assert _value(block, "APP_ENV") == "venue"
    assert _value(block, "SESSION_COOKIE_SECURE") == "false"
    assert _value(block, "EXPORT_DIR") == "/exports"
    assert "TRUSTED_PROXY_IPS" not in _text()


def test_postgres_publishes_no_port() -> None:
    """AC24: only `app` and `backup` reach the database, on the stack's own network."""
    assert _value(_service(_text(), "db"), "ports") is None


@pytest.mark.parametrize(
    ("service", "policy"),
    [("db", "unless-stopped"), ("app", "on-failure"), ("backup", "unless-stopped")],
)
def test_the_restart_policies(service: str, policy: str) -> None:
    """AC23: "Sluit app" (exit 0) stays down; a lost lock (70) or failed boot (3) restarts."""
    assert _value(_service(_text(), service), "restart") == policy


def test_every_name_carries_the_venue_prefix() -> None:
    """AC24: no container, volume or network can collide with the dev stack's."""
    text = _text()
    names = re.findall(r"^\s*(?:container_name|name):\s*(\S+)\s*$", text, re.M)
    project = {"borrelbeurs-venue"}
    assert {n for n in names if n not in project}, "no container, volume or network names"
    assert all(n.startswith(PREFIX) for n in names if n not in project), names
    for name in ("db", "app", "backup"):
        assert (_value(_service(text, name), "container_name") or "").startswith(PREFIX), name


def test_the_postgres_digest_is_the_one_dev_and_ci_pin() -> None:
    """One Postgres image everywhere: the bundle ships the one CI tested against."""
    dev = POSTGRES.findall(DEV_COMPOSE.read_text(encoding="utf-8"))
    ci = POSTGRES.findall(CI_WORKFLOW.read_text(encoding="utf-8"))
    text = _text()
    venue = [_value(_service(text, name), "image") for name in ("db", "backup")]
    assert dev and ci, "the dev compose file or ci.yml no longer pins Postgres"
    assert set(venue) == set(dev) == set(ci), (venue, dev, ci)


@pytest.mark.parametrize("name", CMD_FILES)
def test_each_wrapper_exists_and_drives_this_compose_file(name: str) -> None:
    path = VENUE / f"{name}.cmd"
    data = path.read_bytes()
    assert b'compose.yml"' in data and b"--env-file" in data, path
    # cmd.exe misreads labels and `goto` in LF-only batch files; the repo is `* -text`.
    assert data.count(b"\n") == data.count(b"\r\n"), f"{path.name} is not CRLF throughout"


def test_the_guard_is_reading_real_files() -> None:
    for path in (COMPOSE_FILE, DEV_COMPOSE, CI_WORKFLOW, VENUE / ".env.example"):
        assert path.is_file(), f"{path} is missing; this guard is checking nothing"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param("    restart: on-failure\n", "    restart: always\n", id="restart"),
        pytest.param("    pull_policy: never\n", "    pull_policy: missing\n", id="pull"),
        pytest.param(
            "    networks:\n      - venue\n    healthcheck:",
            '    ports:\n      - "5432:5432"\n    networks:\n      - venue\n    healthcheck:',
            id="db-port",
        ),
    ],
)
def test_the_detector_notices_drift(
    before: str, after: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard's own regression test: each edit above must fail one of the checks."""
    text = _text()
    assert before in text
    monkeypatch.setattr(f"{__name__}._text", lambda: text.replace(before, after, 1))
    checks = (
        test_nothing_is_built_and_nothing_is_pulled,
        test_postgres_publishes_no_port,
        lambda: test_the_restart_policies("app", "on-failure"),
    )
    failures = 0
    for check in checks:
        try:
            check()
        except AssertionError:
            failures += 1
    assert failures, f"no check noticed {after.strip()!r}"


def test_start_requires_the_containerd_image_store() -> None:
    """`docker load` on the classic store drops the pinned Postgres digest, so compose
    (`pull_policy: never`) finds no image offline; start.cmd must refuse that store."""
    data = (VENUE / "start.cmd").read_bytes()
    check = data.find(b"io.containerd.snapshotter")
    load = data.find(b"docker load -i")
    assert -1 < check < load, "start.cmd must check the image store before it loads images"
