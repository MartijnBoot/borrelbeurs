"""SD6-SD10 and AC28 -- the Render Blueprint and the deploy workflow say what the plan says
(Phase 8 T17; PD11, PD12).

Neither file runs anywhere a test can reach: the Blueprint is applied by hand (H1), and
the workflow is dispatched by hand. A wrong field is found at the first deploy, mid-way
through a live setup. So each property the plan fixes is one line asserted here, read
as text like `test_venue_stack.py` and for the same reason (no YAML parser without a
new dependency).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = REPO_ROOT / "render.yaml"
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
PLACEHOLDER = "REPLACE_WITH_FIRST_DEPLOY_SHA"


def _blueprint() -> str:
    return BLUEPRINT.read_text(encoding="utf-8")


def _deploy() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _section(text: str, top: str) -> str:
    """The lines under a top-level key, up to the next top-level key."""
    match = re.search(rf"^{top}:\n((?:(?:[ #].*)?\n)*)", text, re.M)
    assert match, f"render.yaml has no `{top}:`"
    return match.group(1)


def _env_vars(web: str) -> dict[str, str]:
    """`envVars` entries: key -> the rest of the entry (value, sync or generateValue)."""
    entries = re.findall(r"^\s*- key: (\S+)\n((?:\s+(?!- key:)\w+: .*\n)*)", web, re.M)
    return {key: body for key, body in entries}


@pytest.mark.parametrize(
    "line",
    [
        "type: web",
        "name: borrelbeurs-web",
        "runtime: image",
        "region: frankfurt",
        "numInstances: 1",
        "healthCheckPath: /healthz",
        "plan: starter",
    ],
)
def test_the_web_service(line: str) -> None:
    assert re.search(rf"^\s*-?\s*{re.escape(line)}\s*$", _section(_blueprint(), "services"), re.M)


def _tag_allowed(tag: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", tag)) or tag == PLACEHOLDER


def test_the_image_is_a_sha_or_the_first_deploy_placeholder() -> None:
    """PD12: never `latest`, never a floating tag."""
    match = re.search(r"^\s*url:\s*ghcr\.io/martijnboot/borrelbeurs:(\S+)\s*$", _blueprint(), re.M)
    assert match, "no ghcr.io/martijnboot/borrelbeurs image in render.yaml"
    assert _tag_allowed(match.group(1)), match.group(1)


@pytest.mark.parametrize(
    "tag", ["latest", "main", "1cb111f", "1CB111F89AD6A926A47B97A2253F766F9D838DC8"]
)
def test_the_tag_rule_refuses_a_floating_or_short_tag(tag: str) -> None:
    assert not _tag_allowed(tag)


def test_the_environment() -> None:
    """SD8, SD9: a hand-pasted DSN, a generated secret, production, Render's proxy trusted."""
    env = _env_vars(_section(_blueprint(), "services"))
    assert "sync: false" in env["DATABASE_URL"]
    assert "generateValue: true" in env["JWT_SECRET"]
    assert re.search(r"value: \"?production\"?", env["APP_ENV"])
    assert re.search(r"value: \"\*\"", env["TRUSTED_PROXY_IPS"])
    assert re.search(r"value: \"?INFO\"?", env["LOG_LEVEL"])
    # Render's filesystem is ephemeral (SD14), and the app binds Render's own PORT.
    assert "EXPORT_DIR" not in env and "PORT" not in env


@pytest.mark.parametrize(
    "line",
    [
        "name: borrelbeurs-db",
        "region: frankfurt",
        'postgresMajorVersion: "16"',
        "plan: basic-256mb",
    ],
)
def test_the_database(line: str) -> None:
    assert re.search(rf"^\s*-?\s*{re.escape(line)}\s*$", _section(_blueprint(), "databases"), re.M)


def test_deploy_is_manual_with_a_validated_sha() -> None:
    """PD11: dispatch only; the input is checked before anything else uses it."""
    text = _deploy()
    on = _section(text, "on")
    assert "workflow_dispatch:" in on
    assert not re.search(r"^\s+(push|pull_request|schedule|workflow_run):", on, re.M), on
    assert "^[0-9a-f]{40}$" in text


def test_deploy_takes_no_more_than_it_needs() -> None:
    text = _deploy()
    permissions = _section(text, "permissions")
    assert re.findall(r"^\s+(\S+): (\S+)", permissions, re.M) == [
        ("contents", "read"),
        ("packages", "read"),
    ]
    concurrency = _section(text, "concurrency")
    assert re.search(r"group: deploy\s*$", concurrency, re.M)
    assert re.search(r"cancel-in-progress: false\s*$", concurrency, re.M)
    # The input reaches a shell only through `env:`, never spliced into a script: the
    # only line naming it is the env entry.
    uses = [line.strip() for line in text.splitlines() if "inputs.sha" in line]
    assert uses == ["SHA: ${{ inputs.sha }}"], uses


def test_deploy_runs_the_smoke_of_its_own_commit() -> None:
    """A3 (T24): checkout takes the workflow's own commit, not the deployed SHA, so a
    rollback to an old SHA still runs `main`'s smoke; `--expect-sha` pins the image."""
    text = _deploy()
    checkout = re.search(r"- uses: actions/checkout@\S+\n((?:[ ]{8,}.*\n)*)", text)
    assert checkout, "deploy.yml has no checkout step"
    assert not re.search(r"^\s+ref:.*inputs\.sha", checkout.group(1), re.M), checkout.group(1)
    assert not re.search(r"^\s+ref:.*inputs\.sha", text, re.M)


def test_deploy_checks_ghcr_then_triggers_then_smoke_tests() -> None:
    """AC28's three steps, in order."""
    text = _deploy()
    manifest = text.find('docker manifest inspect "$IMAGE"')
    hook = text.find("secrets.RENDER_DEPLOY_HOOK_URL")
    smoke = text.find('scripts/smoke.py "$RENDER_URL" --expect-sha "$SHA" --wait-seconds 600')
    assert -1 < manifest < hook < smoke, (manifest, hook, smoke)
    assert "secrets.BB_SMOKE_KEY" in text and "vars.RENDER_URL" in text


def test_the_guard_is_reading_real_files() -> None:
    for path in (BLUEPRINT, DEPLOY):
        assert path.is_file(), f"{path} is missing; this guard is checking nothing"
