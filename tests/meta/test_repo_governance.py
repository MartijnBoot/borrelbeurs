"""AC5 / AC7 — the repository-governance files T12 commits must stay in place.

Most of T12 is GitHub settings — branch protection, secret scanning, push
protection — and no test in this repo can see those; the plan verifies them
with `gh api` and a rejected push. What *is* in the tree is the half that
drifts silently: Dependabot losing an ecosystem, CODEOWNERS losing
`db/migrations/`, the PR template losing its new-dependency block (CLAUDE.md
makes that block the place a dependency gets justified), or the R5 review
waiver losing the compensating controls that make it acceptable. This guard
pins those down.

**Why this reads the YAML as text.** Same trade as
`test_compose_matches_env_example.py`: parsing it properly would need PyYAML,
and a new dependency is a hard stop. Dependabot's file is split on its
`- package-ecosystem:` entries and each entry checked as a block, which catches
a dropped ecosystem, schedule or group and would miss a sufficiently creative
reformatting. GitHub validates the real file on push.

**Why `uv`, not the plan's `pip`.** Dependabot's `pip` ecosystem edits
`pyproject.toml` and leaves `uv.lock` behind, so its PRs would arrive with a
stale lockfile. The `uv` ecosystem updates both. Same intent — weekly grouped
Python updates — on the package manager this repo actually uses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB = REPO_ROOT / ".github"
DEPENDABOT = GITHUB / "dependabot.yml"
CODEOWNERS = GITHUB / "CODEOWNERS"
PR_TEMPLATE = GITHUB / "PULL_REQUEST_TEMPLATE.md"
ISSUE_TEMPLATES = [
    GITHUB / "ISSUE_TEMPLATE" / "bug.yml",
    GITHUB / "ISSUE_TEMPLATE" / "feedback.yml",
]
REVIEW_WAIVER_ADR = REPO_ROOT / "docs" / "adr" / "0012-single-operator-review-waiver.md"

# ecosystem -> directory holding its manifest.
DEPENDABOT_ECOSYSTEMS = {"uv": "/", "npm": "/web", "github-actions": "/"}

# Appendix F's sections, in its order (way-of-working:2091).
PR_TEMPLATE_HEADINGS = [
    "## What and why",
    "## Section",
    "## How it was verified",
    "## Screenshots / recordings",
    "## Data changes",
    "## Rollback",
    "## New dependencies",
    "## Checklist",
]


def _dependabot_entries(text: str) -> dict[str, str]:
    """Each `- package-ecosystem:` block, keyed by its ecosystem."""
    blocks = re.split(r"^\s*-\s+package-ecosystem:", text, flags=re.M)[1:]
    entries: dict[str, str] = {}
    for block in blocks:
        ecosystem = block.split("\n", 1)[0].strip().strip("\"'")
        entries[ecosystem] = block
    return entries


def _codeowners_rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            pattern, *owners = line.split()
            rules[pattern] = owners
    return rules


@pytest.mark.parametrize(
    "path", [DEPENDABOT, CODEOWNERS, PR_TEMPLATE, *ISSUE_TEMPLATES, REVIEW_WAIVER_ADR]
)
def test_the_guard_is_reading_a_real_file(path: Path) -> None:
    """Every file must exist, or the assertions below pass vacuously."""
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing (plan T12)"


@pytest.mark.parametrize(("ecosystem", "directory"), DEPENDABOT_ECOSYSTEMS.items())
def test_dependabot_updates_each_ecosystem_weekly_and_grouped(
    ecosystem: str, directory: str
) -> None:
    entries = _dependabot_entries(DEPENDABOT.read_text(encoding="utf-8"))
    assert ecosystem in entries, f"dependabot.yml has no `{ecosystem}` entry (plan T12)"
    block = entries[ecosystem]
    assert re.search(rf"^\s*directory:\s*[\"']?{re.escape(directory)}[\"']?\s*$", block, re.M), (
        f"dependabot `{ecosystem}` must point at {directory!r}, where its manifest lives"
    )
    assert re.search(r"^\s*interval:\s*[\"']?weekly[\"']?\s*$", block, re.M), (
        f"dependabot `{ecosystem}` must run weekly (way-of-working 7.1)"
    )
    assert re.search(r"^\s*groups:\s*$", block, re.M), (
        f"dependabot `{ecosystem}` must group its updates into one PR (way-of-working 7.1)"
    )


def test_dependabot_entry_detector_notices_a_dropped_ecosystem() -> None:
    """The guard's own regression test: a file without `npm` must not yield one."""
    text = "updates:\n  - package-ecosystem: uv\n    directory: /\n"
    assert "npm" not in _dependabot_entries(text)
    assert "uv" in _dependabot_entries(text)


@pytest.mark.parametrize("pattern", ["/db/migrations/", "/docker/"])
def test_codeowners_covers_the_sensitive_paths(pattern: str) -> None:
    owners = _codeowners_rules().get(pattern)
    assert owners, f"CODEOWNERS must assign an owner to {pattern} (plan T12, way-of-working 7.1)"
    assert all(owner.startswith("@") for owner in owners), owners


def test_pr_template_keeps_appendix_f_sections_in_order() -> None:
    text = PR_TEMPLATE.read_text(encoding="utf-8")
    positions = [text.find(heading) for heading in PR_TEMPLATE_HEADINGS]
    missing = [h for h, pos in zip(PR_TEMPLATE_HEADINGS, positions, strict=True) if pos < 0]
    assert not missing, f"PR template is missing Appendix F sections: {missing}"
    assert positions == sorted(positions), "PR template sections are out of Appendix F's order"


def test_pr_template_names_this_repos_gate() -> None:
    """Appendix F says `pnpm check`; this repo's one gate is `./scripts/check.sh`."""
    assert "./scripts/check.sh" in PR_TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ISSUE_TEMPLATES, ids=lambda p: p.name)
def test_issue_template_is_a_github_issue_form(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for key in ("name", "description", "body"):
        assert re.search(rf"^{key}:", text, re.M), f"{path.name} has no top-level `{key}:`"


def test_review_waiver_names_its_controls_and_its_trigger() -> None:
    """R5: the waiver is only acceptable alongside what compensates for it."""
    text = REVIEW_WAIVER_ADR.read_text(encoding="utf-8")
    for required in ("check", "secret-scan", "docker", "fresh-eyes-reviewer", "second contributor"):
        assert required in text, f"ADR 0012 no longer mentions {required!r} (plan R5, T12)"
