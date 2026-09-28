"""AC1 — the DSN in `.env.example` must reach the database `docker-compose.yml` starts.

AC1 promises that a developer copies `.env.example`, starts Postgres and
applies migrations "without further manual steps". Two files have to agree for
that to be true: the committed `DATABASE_URL` and the compose service's
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / published port. Nothing
in either file references the other, so drift between them is silent — and it
surfaces as an authentication failure at the first `alembic upgrade`, which
looks like a bug in `scripts/setup.sh` rather than in whichever file moved.

**Why this reads the YAML as text.** Parsing it properly would need PyYAML, and
a new dependency is a hard stop here. The trade is honest rather than clever: a
regex over `key: value` lines catches the drift this guard exists for (someone
edits one file and not the other) and would miss a sufficiently creative
reformatting of `docker-compose.yml` — anchors, flow mappings, a `.env`
indirection. `docker compose config` is the real parser and it runs in the
task's verification; this test is the one that runs on every commit.

Deliberately not asserted here: the healthcheck, the named volume and the app
service. Those are verified by starting the thing, which a unit-speed test
cannot do, and restating them as string matches would be assertion theatre.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def _committed_database_url() -> str:
    """The `DATABASE_URL` line from `.env.example`, read rather than retyped."""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.strip() == "DATABASE_URL":
            return value.strip()
    raise AssertionError(f"{ENV_EXAMPLE.name} no longer defines DATABASE_URL")


def _compose_text() -> str:
    return COMPOSE_FILE.read_text(encoding="utf-8")


def _assert_mapping_entry(text: str, key: str, value: str) -> None:
    """Assert a `key: value` line exists, tolerating quotes and indentation."""
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*[\"']?{re.escape(value)}[\"']?\s*$", re.M)
    assert pattern.search(text), (
        f"docker-compose.yml has no `{key}: {value}`. .env.example's DATABASE_URL "
        f"expects it; without it, copying .env.example and running "
        f"`alembic upgrade head` fails to authenticate (AC1)."
    )


def test_compose_credentials_match_the_committed_database_url() -> None:
    """R19 — user, password and database name come from `.env.example`."""
    parts = urlsplit(_committed_database_url())
    text = _compose_text()

    assert parts.username, "the committed DATABASE_URL carries no username"
    assert parts.password, "the committed DATABASE_URL carries no password"
    database = parts.path.lstrip("/")
    assert database, "the committed DATABASE_URL names no database"

    _assert_mapping_entry(text, "POSTGRES_USER", parts.username)
    _assert_mapping_entry(text, "POSTGRES_PASSWORD", parts.password)
    _assert_mapping_entry(text, "POSTGRES_DB", database)


def _published_database_mapping() -> re.Match[str] | None:
    """The `ports:` entry that maps the host port the committed DSN dials.

    Group `bind` is the optional host address in front of it, which is the
    difference between "reachable from this machine" and "reachable from this
    network".
    """
    port = urlsplit(_committed_database_url()).port or 5432
    pattern = rf"^\s*-\s*[\"']?(?:(?P<bind>[0-9.]+):)?{port}:5432[\"']?\s*$"
    return re.search(pattern, _compose_text(), re.M)


def test_compose_publishes_the_port_the_committed_url_dials() -> None:
    """The host port in the DSN must be the one compose publishes."""
    port = urlsplit(_committed_database_url()).port or 5432

    assert _published_database_mapping(), (
        f"docker-compose.yml does not publish host port {port}, which is the port "
        f".env.example's DATABASE_URL connects to."
    )


def test_the_database_port_is_published_on_loopback_only() -> None:
    """The dev credentials are committed, so they may not be offered to a LAN.

    This file says in its own header that `borrelbeurs:borrelbeurs` "must never
    be used anywhere reachable from a network", and ADR 0004 puts this compose
    file on a venue laptop that joins whatever network the venue has. A bare
    `5432:5432` publishes on every interface and contradicts both.
    """
    mapping = _published_database_mapping()
    assert mapping, "no published database port to check"

    assert mapping.group("bind") == "127.0.0.1", (
        f"the database port is published as {mapping.group(0).strip()}; bind it to "
        f"127.0.0.1 so the committed development credentials stay on this machine."
    )


def test_the_postgres_image_is_digest_pinned() -> None:
    """Plan D3 and ADR 0004 — the offline laptop needs the exact same image.

    A floating `postgres:16-alpine` tag is a different image on the venue
    machine than the one that was tested, and `docker save` bundles whatever the
    tag pointed at last.
    """
    text = _compose_text()

    assert re.search(r"^\s*image:\s*postgres:16-alpine@sha256:[0-9a-f]{64}\s*$", text, re.M), (
        "the Postgres service must pin `postgres:16-alpine@sha256:<digest>` (plan D3)"
    )


def test_the_guard_is_reading_real_files() -> None:
    """Both inputs must exist, or every assertion above passes vacuously."""
    for path in (ENV_EXAMPLE, COMPOSE_FILE):
        assert path.is_file(), f"{path} is missing; this guard is checking nothing"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("POSTGRES_USER", "somebody-else", id="wrong-user"),
        pytest.param("POSTGRES_DB", "wrong_database", id="wrong-database"),
    ],
)
def test_the_detector_notices_drift(key: str, value: str) -> None:
    """The guard's own regression test: a mismatched value must fail."""
    with pytest.raises(AssertionError):
        _assert_mapping_entry(_compose_text(), key, value)
