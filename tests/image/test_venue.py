"""The venue drill (Phase 8 T16: AC19-AC24) -- the bundle, run as the laptop runs it.

`scripts/make_bundle.sh <sha> --local <image>` builds the bundle once per session. On
CI only (`CI=true`) both images are then removed and `docker load`ed from its
`images.tar`, so the stack below can only be what the bundle carries; locally that
step is skipped, because the dev `borrelbeurs-db` runs the same Postgres image.

Each test brings the bundle's own `compose.yml` up with `--pull never`, data in
`tmp_path`, a random HTTP port and a dump every 5 s, and takes it down with its
volume afterwards. Its names are fixed (`borrelbeurs-venue-*`), so the drill refuses
to start when any of them already exists: that would be a real venue stack, and
`down -v` would throw its database away.

- **AC19/AC20:** the stack comes up without pulling; every container runs an image
  the bundle saved.
- **AC24:** Postgres publishes no port; every container, volume and network carries
  the prefix.
- **AC21:** dumps accrue every interval, and go on with `app` stopped; with `backup`
  stopped a manual export still lands in `exports/`; every file with a final name is
  complete.
- **AC22:** the newest dump restores into a fresh volume with the same order count;
  a truncated dump fails `restore.sh`, the restore sequence leaves `app` down, and
  nothing was dropped.
- **AC23:** "Sluit app" (exit 0) stays down; a terminated lock connection (exit 70)
  is restarted and ready again.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.db.advisory_lock import ADVISORY_LOCK_KEY
from tests.image.conftest import REPO_ROOT, docker, free_port
from tests.integration.realapp.harness import Client, order_until_acked

PROJECT = "borrelbeurs-venue"
PREFIX = f"{PROJECT}-"
LIVE_CONFIG = REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json"
INTERVAL_S = 5


@dataclass
class Bundle:
    path: Path
    app_image: str
    postgres_image: str

    def saved_digests(self) -> set[str]:
        """Every image digest `images.tar` carries: OCI index entries and image configs."""
        with tarfile.open(self.path / "images.tar") as tar:
            index = _tar_json(tar, "index.json")
            manifest = _tar_json(tar, "manifest.json")
        digests = {m["digest"] for m in index.get("manifests", [])}
        digests |= {"sha256:" + m["Config"].rsplit("/", 1)[-1] for m in manifest}
        return digests


def _tar_json(tar: tarfile.TarFile, name: str) -> Any:
    member = tar.extractfile(name)
    return json.load(member) if member else {}


def _sha(image: str) -> str:
    out = docker("image", "inspect", "--format", "{{json .Config.Env}}", image)
    env = dict(str(item).split("=", 1) for item in json.loads(out.stdout))
    sha = env.get("BUILD_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", sha):
        return sha
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return head.stdout.strip()


@pytest.fixture(scope="session")
def bundle(request: pytest.FixtureRequest) -> Bundle:
    image: str = request.config.getoption("--image")
    sha = _sha(image)
    bash = shutil.which("bash")  # not Windows' System32 bash.exe, which is WSL's
    assert bash, "make_bundle.sh needs bash"
    made = subprocess.run(
        [bash, "scripts/make_bundle.sh", sha, "--local", image],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert made.returncode == 0, made.stdout + made.stderr
    path = REPO_ROOT / "bundle" / f"borrelbeurs-{sha}"
    compose = (path / "compose.yml").read_text(encoding="utf-8")
    match = re.search(r"postgres:16-alpine@sha256:[0-9a-f]{64}", compose)
    assert match
    built = Bundle(path, f"ghcr.io/martijnboot/borrelbeurs:{sha}", match.group(0))
    if os.environ.get("CI") == "true":
        # Only what the bundle carries: never locally, where the dev database runs it.
        # Every name of each image goes, `--image` included -- `rmi` of one of several
        # names only untags -- so the stack below can run only what `docker load` adds.
        docker(
            "rmi",
            "--force",
            image,
            built.app_image,
            built.postgres_image,
            "postgres:16-alpine",
            check=False,
        )
        for ref in (built.app_image, built.postgres_image):
            gone = docker("image", "inspect", ref, check=False)
            assert gone.returncode != 0, f"{ref} is still present before the load"
        docker("load", "--input", str(path / "images.tar"), timeout=900)
    return built


@dataclass
class Venue:
    bundle: Bundle
    data: Path
    port: int
    env: dict[str, str]

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.bundle.path / "compose.yml"),
                "--env-file",
                str(self.bundle.path / ".env.example"),
                *args,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if check:
            assert done.returncode == 0, f"compose {args}:\n{done.stdout}{done.stderr}"
        return done

    def cli(self, *args: str, mounts: tuple[str, ...] = ()) -> str:
        """One of the app's CLIs in a one-off `app` container (the app itself stopped)."""
        volumes = [arg for mount in mounts for arg in ("-v", mount)]
        return self.compose("run", "--rm", "--no-deps", *volumes, "app", *args).stdout.strip()

    def psql(self, sql: str) -> str:
        out = self.compose(
            "exec", "-T", "db", "psql", "-U", "borrelbeurs", "-d", "borrelbeurs", "-tAc", sql
        )
        return out.stdout.strip()

    def state(self, service: str) -> dict[str, Any]:
        out = docker("inspect", "--format", "{{json .State}}", f"{PREFIX}{service}")
        result: dict[str, Any] = json.loads(out.stdout)
        return result

    def restarts(self, service: str) -> int:
        out = docker("inspect", "--format", "{{.RestartCount}}", f"{PREFIX}{service}")
        return int(out.stdout.strip())

    def ready(self) -> bool:
        try:
            return Client(self.base).request("GET", "/readyz")[0] == 200
        except OSError:
            return False

    def wait_ready(self, seconds: float = 120) -> None:
        deadline = time.monotonic() + seconds
        while not self.ready():
            if time.monotonic() > deadline:
                logs = self.compose("logs", "--tail", "100", "app", check=False)
                raise AssertionError(f"the venue app never became ready:\n{logs.stdout}")
            time.sleep(1)

    def dumps(self) -> list[Path]:
        return sorted((self.data / "backups").glob("borrelbeurs-*.dump"))

    def orders(self) -> int:
        return int(self.psql('SELECT count(*) FROM "order"'))


def _leftovers() -> list[str]:
    found = docker(
        "ps", "-a", "--filter", f"label=com.docker.compose.project={PROJECT}", "-q"
    ).stdout.split()
    found += docker(
        "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"
    ).stdout.split()
    return found


@pytest.fixture
def venue(bundle: Bundle, tmp_path: Path) -> Iterator[Venue]:
    if leftovers := _leftovers():
        pytest.fail(
            f"a {PROJECT} stack already exists on this machine ({leftovers}); the drill "
            "will not take it down. Remove it by hand if it is not a real venue."
        )
    for sub in ("backups", "exports"):
        (tmp_path / sub).mkdir()
    env = {
        **os.environ,
        "BB_DATA_DIR": tmp_path.as_posix(),
        "BB_HTTP_PORT": str(free_port()),
        "BB_BACKUP_INTERVAL_S": str(INTERVAL_S),
        "JWT_SECRET": secrets.token_hex(32),
    }
    running = Venue(bundle, tmp_path, int(env["BB_HTTP_PORT"]), env)
    try:
        yield running
    finally:
        running.compose("down", "--volumes", "--remove-orphans", "--timeout", "10", check=False)


def _seed(venue: Venue) -> tuple[int, str, str]:
    """A live run and a bar and an admin key, with the database up and the app not yet."""
    venue.compose("up", "--detach", "--pull", "never", "--wait", "db")
    venue.cli("alembic", "-c", "db/alembic.ini", "upgrade", "head")
    run_id = int(
        venue.cli(
            "python",
            "-m",
            "app.cli.import_v1",
            "--config",
            "/seed/exchange_config.json",
            mounts=(f"{LIVE_CONFIG}:/seed/exchange_config.json:ro",),
        )
    )
    venue.cli("python", "-m", "app.cli.runs", "go-live", str(run_id))
    keys = [
        venue.cli("python", "-m", "app.cli.keys", "create", "--role", role, "--label", "venue")
        for role in ("bar", "admin")
    ]
    return run_id, keys[0], keys[1]


def _up(venue: Venue) -> None:
    venue.compose("up", "--detach", "--pull", "never")
    venue.wait_ready()


def _order(venue: Venue, key: str, n: int, label: str) -> None:
    client = Client(venue.base)
    client.login(key)
    for k in range(n):
        assert order_until_acked(client, f"venue-{label}-{k}") is not None


def _wait_until(condition: Any, seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.5)


def test_the_bundle_runs_offline_as_saved(venue: Venue) -> None:
    """AC19, AC20, AC24."""
    _seed(venue)
    _up(venue)

    saved = venue.bundle.saved_digests()
    for service in ("app", "db", "backup"):
        running = docker("inspect", "--format", "{{.Image}}", f"{PREFIX}{service}").stdout.strip()
        assert running in saved, (service, running, saved)

    # `compose port` answers an unpublished port with "invalid IP:0" and exit 0 (Compose
    # v2); `docker port` fails outright. Neither may name a usable host port.
    published = venue.compose("port", "db", "5432", check=False).stdout.strip()
    assert not re.search(r":[1-9]\d*$", published), published
    assert docker("port", f"{PREFIX}db", "5432", check=False).returncode != 0
    names = venue.compose("ps", "--all", "--format", "{{.Name}}").stdout.split()
    assert sorted(names) == [f"{PREFIX}{s}" for s in ("app", "backup", "db")], names
    volumes = docker(
        "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"
    ).stdout.split()
    networks = docker(
        "network",
        "ls",
        "--format",
        "{{.Name}}",
        "--filter",
        f"label=com.docker.compose.project={PROJECT}",
    ).stdout.split()
    assert volumes and networks
    assert all(n.startswith(PREFIX) for n in volumes + networks), (volumes, networks)


def test_dumps_and_exports_land_on_the_host_each_without_the_other(venue: Venue) -> None:
    """AC21: the two paths to the host are independent of each other."""
    run_id, bar, admin = _seed(venue)
    _up(venue)
    _order(venue, bar, 3, "ac21")

    _wait_until(lambda: len(venue.dumps()) >= 2, 4 * INTERVAL_S, "two dumps")
    venue.compose("stop", "app")
    with_app = len(venue.dumps())
    _wait_until(lambda: len(venue.dumps()) > with_app, 3 * INTERVAL_S, "a dump with app stopped")

    venue.compose("start", "app")
    venue.wait_ready()
    venue.compose("stop", "backup")
    client = Client(venue.base)
    client.login(admin)
    status, body = client.request("POST", f"/api/runs/{run_id}/exports")
    assert status == 202, body
    exports = venue.data / "exports"
    _wait_until(lambda: any(exports.glob("borrel-*-manual.xlsx")), 60, "a manual export")

    for dump in venue.dumps():
        listed = venue.compose(
            "exec", "-T", "db", "pg_restore", "--list", f"/backups/{dump.name}", check=False
        )
        assert listed.returncode == 0, (dump.name, listed.stderr)
    for workbook in exports.glob("*.xlsx"):
        assert zipfile.is_zipfile(workbook), workbook.name
    for root in (venue.data / "backups", exports):
        for partial in root.glob("*.partial"):
            assert partial.name.startswith("."), f"a partial file under a final name: {partial}"


def test_the_newest_dump_restores_and_a_bad_one_leaves_the_app_down(venue: Venue) -> None:
    """AC22, both outcomes."""
    _, bar, _ = _seed(venue)
    _up(venue)
    _order(venue, bar, 5, "ac22")
    venue.compose("stop", "app")
    at_dump = venue.orders()
    venue.compose("exec", "-T", "backup", "sh", "/scripts/backup.sh", "once")
    newest = venue.dumps()[-1]

    # A truncated dump: restore.sh refuses it before dropping anything (restore.cmd's
    # sequence: stop app and backup, restore, and only on success start them again).
    bad = venue.data / "backups" / "borrelbeurs-truncated.dump"
    bad.write_bytes(newest.read_bytes()[: newest.stat().st_size // 2])
    venue.compose("stop", "backup")
    failed = venue.compose("exec", "-T", "db", "sh", "/scripts/restore.sh", bad.name, check=False)
    assert failed.returncode != 0, failed.stdout
    assert venue.state("app")["Running"] is False
    assert venue.orders() == at_dump, "a failed restore dropped the database"
    bad.unlink()

    # The newest dump into a fresh volume.
    venue.compose("down", "--volumes", "--timeout", "10")
    venue.compose("up", "--detach", "--pull", "never", "--wait", "db")
    restored = venue.compose("exec", "-T", "db", "sh", "/scripts/restore.sh")
    assert newest.name in restored.stdout, restored.stdout
    _up(venue)
    assert venue.orders() == at_dump


def test_a_shutdown_stays_down_and_a_lost_lock_is_restarted(venue: Venue) -> None:
    """AC23: the restart policy tells "Sluit app" from a lost lock."""
    _, _, admin = _seed(venue)
    _up(venue)

    client = Client(venue.base)
    client.login(admin)
    status, body = client.request("POST", "/api/admin/shutdown")
    assert status == 202, body
    _wait_until(lambda: not venue.state("app")["Running"], 30, "the app to stop")
    restarts = venue.restarts("app")
    time.sleep(20)
    state = venue.state("app")
    assert (state["Status"], state["ExitCode"]) == ("exited", 0), state
    assert venue.restarts("app") == restarts

    venue.compose("start", "app")
    venue.wait_ready()
    restarts = venue.restarts("app")
    terminated = venue.psql(
        "SELECT count(pg_terminate_backend(pid)) FROM pg_locks"
        " WHERE locktype = 'advisory' AND granted"
        f" AND classid = 0 AND objid = {ADVISORY_LOCK_KEY}"
    )
    assert terminated == "1", terminated
    _wait_until(lambda: venue.restarts("app") > restarts, 60, "docker to restart the app")
    venue.wait_ready(60)
