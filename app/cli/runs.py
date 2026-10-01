"""Make a draft run live (Phase 3 SD16).

    uv run python -m app.cli.runs go-live <run_id>

Takes the advisory lock first (`app/db/advisory_lock.py`): while the app is
running it holds the lock, and this refuses, so a run going live takes effect at
the app's next boot. Otherwise it wraps Phase 2's `go_live` and releases the
lock. Exit status: 0 on success, 2 if the app holds the lock, 1 if the run
cannot go live or the database fails; on 1 and 2 nothing is written.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import ConfigError, get_settings
from app.db.advisory_lock import acquire, release
from app.db.runs import LiveRunExists, RunNotDraft, RunNotReady, go_live
from app.db.session import create_engine
from app.runtime.clock import RealClock


class LockHeld(Exception):
    """The app is running: it holds the single-writer lock."""


async def make_live(run_id: int) -> int:
    """Go live under the advisory lock; the new run's version."""
    engine = create_engine(get_settings())
    try:
        conn = await acquire(engine)
        if conn is None:
            raise LockHeld
        try:
            state = await go_live(engine, run_id, now_ms=RealClock().wall_ms())
        finally:
            await release(conn)
        return state.version
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.runs", description="Manage runs.")
    commands = parser.add_subparsers(dest="command", required=True)
    go = commands.add_parser("go-live", help="make a draft run live (the app must be stopped)")
    go.add_argument("run_id", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        version = asyncio.run(make_live(args.run_id))
    except LockHeld:
        print("runs: the app is running; stop it first", file=sys.stderr)
        return 2
    except (RunNotDraft, RunNotReady, LiveRunExists, LookupError) as error:
        print(f"runs: run {args.run_id} cannot go live: {error}", file=sys.stderr)
        return 1
    except (ConfigError, SQLAlchemyError, OSError) as error:
        print(f"runs: database error, nothing written: {error}", file=sys.stderr)
        return 1

    print(f"run {args.run_id} is live at version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
