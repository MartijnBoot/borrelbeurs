"""B-11 AC16 — a run that selects no database test opens no Postgres connection.

`tests/conftest.py` takes the run lock only for a session that selects something
under `tests/integration` or `tests/api` (SD13). Here a child pytest runs a unit
file with a plugin that makes `MaintenanceConnection` raise on construction and
the gate's own variable cleared: if any hook reached for the server, the child
fails. A control run on a database directory proves the plugin does bite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PLUGIN = """
from tests.support import pg_gate


def _refuse(self, base_url):
    raise AssertionError("a Postgres connection was opened")


pg_gate.MaintenanceConnection.__init__ = _refuse
"""


def _pytest(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "no_connection_plugin.py").write_text(PLUGIN, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "BB_GATE_LOCK_HELD"}
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(REPO_ROOT)])
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no_connection_plugin", "-q", "-p",
         "no:cacheprovider", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip


def test_a_unit_run_opens_no_connection(tmp_path: Path) -> None:
    done = _pytest(tmp_path, "tests/unit/test_fake_clock.py")
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_plugin_bites_on_a_database_test(tmp_path: Path) -> None:
    """The control: a database test's session does reach for the server."""
    done = _pytest(tmp_path, "tests/integration/test_advisory_lock.py", "-x")
    assert done.returncode != 0
    assert "a Postgres connection was opened" in done.stdout + done.stderr
