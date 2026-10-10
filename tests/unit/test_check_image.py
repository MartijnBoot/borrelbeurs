"""`scripts/ci/check_image.py`'s matcher (Phase 8 T11; AC2, D-43; plan PD9)."""

from __future__ import annotations

import pytest

from scripts.ci.check_image import forbidden, violations


@pytest.mark.parametrize(
    ("path", "is_dir"),
    [
        pytest.param("app/bierbeurs-image.tar", False, id="tar"),
        pytest.param("tmp/backup.tar.gz", False, id="tar-gz"),
        pytest.param("app/.git/HEAD", False, id="git"),
        pytest.param("app/.env", False, id="env"),
        pytest.param("app/.env.local", False, id="env-local"),
        pytest.param("app/config/keys.json", False, id="keys"),
        pytest.param("app/.jwt_secret", False, id="jwt-secret"),
        pytest.param("app/tests/test_x.py", False, id="tests-file"),
        pytest.param("app/.venv/lib/python3.11/site-packages/greenlet/tests", True, id="tests-dir"),
        pytest.param("app/legacy/v1/run.bat", False, id="legacy"),
        pytest.param("web/node_modules/react/index.js", False, id="node-modules"),
        pytest.param("usr/local/lib/python3.11/site-packages/pip/__init__.py", False, id="pip"),
        pytest.param("usr/local/lib/python3.11/site-packages/setuptools", True, id="setuptools"),
        pytest.param(
            "usr/local/lib/python3.11/site-packages/pip-24.0.dist-info", True, id="pip-di"
        ),
        pytest.param("app/.venv/lib/python3.11/site-packages/uv/__init__.py", False, id="uv"),
        pytest.param("usr/local/bin/pip3.11", False, id="bin-pip"),
        pytest.param("usr/local/bin/uv", False, id="bin-uv"),
    ],
)
def test_forbidden_paths_are_found(path: str, is_dir: bool) -> None:
    assert forbidden(path, is_dir=is_dir) is not None


@pytest.mark.parametrize(
    ("path", "is_dir"),
    [
        pytest.param("usr/local/lib/python3.11/pipes.py", False, id="pipes-is-not-pip"),
        pytest.param("usr/local/lib/python3.11/site-packages/pydantic", True, id="pydantic"),
        pytest.param("app/app/api/tests_helper.py", False, id="tests-prefix"),
        pytest.param("usr/share/doc/tar/copyright", False, id="tar-dir-name"),
        pytest.param("app/web/dist/assets/index-abc.js", False, id="asset"),
        pytest.param("usr/local/bin/python3.11", False, id="python"),
        pytest.param("app/.venv/lib/python3.11/site-packages/uvicorn", True, id="uvicorn-not-uv"),
        pytest.param("app/.venv/lib/python3.11/site-packages/uvloop", True, id="uvloop-not-uv"),
        pytest.param("etc/environment", False, id="environment-not-env"),
        pytest.param("", True, id="root"),
    ],
)
def test_allowed_paths_pass(path: str, is_dir: bool) -> None:
    assert forbidden(path, is_dir=is_dir) is None


def test_violations_lists_each_forbidden_entry_with_its_reason() -> None:
    found = violations([("app/main.py", False), ("app/.git", True), ("x/keys.json", False)])

    assert found == ["app/.git: a git repository", "x/keys.json: a secret file"]
