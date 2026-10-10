"""Export file names (Phase 7 PD10; Phase 8 PD7): one slug rule for the download and the host.

`borrel-<slug>-<yyyymmdd-hhmm>.xlsx` is the download's name. The copy on the host
(`app/hostdir.py`) adds its kind -- `manual`, `final` or `auto` -- so the three sit
side by side in one folder: `borrel-<slug>-<yyyymmdd-hhmm>-<kind>.xlsx`. ASCII
only, stamped in UTC; a run whose name folds to nothing is `run-<id>`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Final, Literal

SLUG_MAX: Final = 40

HostKind = Literal["manual", "final", "auto"]


def slug(run_name: str, run_id: int) -> str:
    folded = unicodedata.normalize("NFKD", run_name).encode("ascii", "ignore").decode()
    slugged = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:SLUG_MAX].strip("-")
    return slugged or f"run-{run_id}"


def stamp(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms // 1000, tz=UTC).strftime("%Y%m%d-%H%M")


def filename(run_name: str, run_id: int, created_at_ms: int) -> str:
    """PD10: `borrel-<slug>-<yyyymmdd-hhmm>.xlsx`, the download's name."""
    return f"borrel-{slug(run_name, run_id)}-{stamp(created_at_ms)}.xlsx"


def host_filename(run_name: str, run_id: int, at_ms: int, kind: HostKind) -> str:
    """PD7: the host copy's name, the download's with its kind."""
    return f"borrel-{slug(run_name, run_id)}-{stamp(at_ms)}-{kind}.xlsx"


def auto_pattern(run_name: str, run_id: int) -> str:
    """The glob of one slug's auto exports, for pruning (runs sharing a slug share them)."""
    return f"borrel-{slug(run_name, run_id)}-*-auto.xlsx"
