"""Drills against a built image (Phase 8 PD8): `pytest tests/image --image <ref>`.

Without `--image` every test here is skipped, which is how `scripts/check.sh` (which
never names this directory) and a machine without Docker see it. CI's image jobs pass
the image they just built (T18).

Each test gets its own docker network, a Postgres on it with **no host port** (the
digest `docker-compose.yml` pins), and helpers to run the image's own CLIs and boot
it on a random host port. Every name carries a per-test suffix, and everything is
removed afterwards, even on failure -- the dev stack's `borrelbeurs-db`, its volume
and port 5432, and any other project's containers are never touched (R10).
"""

from __future__ import annotations

import json
import re
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DB_USER = DB_PASSWORD = DB_NAME = "borrelbeurs"
JWT_SECRET = "image-drill-" + "0" * 32  # test value; the drill database is thrown away


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--image", default=None, help="the image to drill, e.g. borrelbeurs:local")
    parser.addoption(
        "--previous-image", default=None, help="an older SD3 image to boot against head (PD3)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--image"):
        return
    skip = pytest.mark.skip(reason="no --image given; the image drills need a built image")
    for item in items:
        if Path(str(item.fspath)).resolve().is_relative_to(Path(__file__).parent):
            item.add_marker(skip)


def postgres_image() -> str:
    """The Postgres image the dev compose file pins, digest and all."""
    match = re.search(r"image:\s*(postgres:\S+@sha256:[0-9a-f]{64})", COMPOSE_FILE.read_text())
    assert match, f"no digest-pinned postgres image in {COMPOSE_FILE}"
    return match.group(1)


def docker(
    *args: str, check: bool = True, timeout: float = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class Stack:
    """One test's network and Postgres, and the app containers it starts."""

    image: str
    suffix: str
    network: str
    db: str
    containers: list[str] = field(default_factory=list)

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{self.db}:5432/{DB_NAME}"

    def env(self, **extra: str) -> list[str]:
        values = {
            "DATABASE_URL": self.database_url,
            "JWT_SECRET": JWT_SECRET,
            "APP_ENV": "ci",
            "SESSION_COOKIE_SECURE": "false",
            **extra,
        }
        return [arg for name, value in values.items() for arg in ("-e", f"{name}={value}")]

    def run_cli(self, *args: str, image: str | None = None) -> subprocess.CompletedProcess[str]:
        """A one-off `docker run` of the image on the drill network: a CLI, alembic."""
        return docker(
            "run",
            "--rm",
            "--network",
            self.network,
            *self.env(),
            image or self.image,
            *args,
            check=False,
        )

    def psql(self, sql: str) -> str:
        out = docker("exec", self.db, "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", sql)
        return out.stdout.strip()

    def start_app(self, *, image: str | None = None, name: str = "app", **env: str) -> App:
        """Start the app detached on a random host port; do not wait for it."""
        container = f"bb-drill-{name}-{self.suffix}"
        port = free_port()
        docker(
            "run",
            "--detach",
            "--name",
            container,
            "--network",
            self.network,
            "--publish",
            f"127.0.0.1:{port}:8000",
            *self.env(**env),
            image or self.image,
        )
        self.containers.append(container)
        return App(container=container, base=f"http://127.0.0.1:{port}")


@dataclass
class App:
    container: str
    base: str

    def get(self, path: str) -> tuple[int, Any]:
        try:
            with urllib.request.urlopen(f"{self.base}{path}", timeout=3) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            return 0, None

    def logs(self) -> str:
        out = docker("logs", self.container, check=False)
        return out.stdout + out.stderr

    def state(self) -> dict[str, Any]:
        out = docker("inspect", "--format", "{{json .State}}", self.container)
        result: dict[str, Any] = json.loads(out.stdout)
        return result

    def wait_ready(self, seconds: float = 90) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.get("/readyz")[0] == 200:
                return
            if self.state()["Status"] == "exited":
                raise AssertionError(f"the app exited:\n{self.logs()}")
            time.sleep(0.5)
        raise AssertionError(f"the app never became ready:\n{self.logs()}")

    def wait_exit(self, seconds: float = 90) -> int:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = self.state()
            if state["Status"] == "exited":
                return int(state["ExitCode"])
            time.sleep(0.5)
        raise AssertionError(f"the app never exited:\n{self.logs()}")


@pytest.fixture
def image(request: pytest.FixtureRequest) -> str:
    ref: str = request.config.getoption("--image")
    return ref


@pytest.fixture
def stack(image: str) -> Iterator[Stack]:
    suffix = secrets.token_hex(4)
    network = f"bb-drill-net-{suffix}"
    db = f"bb-drill-db-{suffix}"
    docker("network", "create", network)
    built = Stack(image=image, suffix=suffix, network=network, db=db)
    try:
        docker(
            "run",
            "--detach",
            "--name",
            db,
            "--network",
            network,
            "-e",
            f"POSTGRES_USER={DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-e",
            f"POSTGRES_DB={DB_NAME}",
            "-e",
            "POSTGRES_INITDB_ARGS=--locale=C --encoding=UTF8",
            postgres_image(),
        )
        deadline = time.monotonic() + 60
        while docker(
            "exec", db, "pg_isready", "-U", DB_USER, "-d", DB_NAME, check=False
        ).returncode:
            assert time.monotonic() < deadline, "the drill Postgres never became ready"
            time.sleep(0.5)
        # pg_isready answers during initdb's temporary server; wait for the real one.
        while docker(
            "exec", db, "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", "SELECT 1", check=False
        ).returncode:
            assert time.monotonic() < deadline, "the drill Postgres never answered"
            time.sleep(0.5)
        yield built
    finally:
        for container in [*built.containers, db]:
            docker("rm", "--force", "--volumes", container, check=False)
        docker("network", "rm", network, check=False)
