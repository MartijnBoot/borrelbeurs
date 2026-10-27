"""B-11 AC2 — `BB_GATE_WORKERS` is validated before the gate does anything.

A value that is not a positive integer, or is above the cap, fails `check.sh`
before stage 1, naming the variable, and quickly: the script must not start a
nested full gate. Each run has a hard timeout for the same reason, and asserts
that no stage-1 line was printed. `bash` is found as `tests/image/test_venue.py`
does, so WSL's `bash` is never picked up on Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not on PATH (Git Bash needed)")


@pytest.mark.parametrize("value", ["abc", "0", "-1", "9999", "", "2.5", "1e3"])
def test_a_bad_worker_count_fails_before_stage_1_naming_the_variable(value: str) -> None:
    assert BASH is not None
    env = {**os.environ, "BB_GATE_WORKERS": value}
    done = subprocess.run(
        [BASH, "scripts/check.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode != 0
    assert "BB_GATE_WORKERS" in done.stderr
    assert "stage 1" not in done.stdout + done.stderr
    assert "==>" not in done.stdout
