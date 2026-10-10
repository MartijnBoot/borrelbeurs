"""Files the app writes on the host, beside Postgres rather than instead of it (Phase 8 PD5).

At the venue the export worker copies every finished export, and every 15 minutes a
row-less `auto` export, into `EXPORT_DIR` -- a folder on the laptop, so the takings
survive even if the database does not (SD14). Postgres stays the system of record
(ADR 0004): nothing here is ever read back.

This is the only file-writing code in `app/`, kept outside the roots
`tests/meta/test_no_file_io.py` scans so `app/jobs` still opens no file: deliberate
I/O in one small, named module rather than a loophole in a guarded one.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def write_atomic(directory: Path, name: str, data: bytes) -> Path:
    """Write `data` as `directory/name`, never visible half-written.

    The bytes go to `.<name>.partial` first and are renamed into place, so a reader
    sees the old file or the new one; a failure removes the partial and raises.
    """
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / name
    partial = directory / f".{name}.partial"
    try:
        partial.write_bytes(data)
        os.replace(partial, final)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    return final


def prune(directory: Path, pattern: str, keep: int) -> list[Path]:
    """Delete all but the newest `keep` files matching `pattern`; the deleted paths.

    Newest by name: the names this app writes carry a `yyyymmdd-hhmm` stamp, so for
    one pattern the name order is the time order. Partial files never match.
    """
    matches = sorted(
        (path for path in directory.glob(pattern) if not path.name.startswith(".")),
        key=lambda path: path.name,
    )
    doomed = matches[: max(0, len(matches) - keep)]
    for path in doomed:
        path.unlink()
    return doomed
