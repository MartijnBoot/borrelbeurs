"""Import v1's files as a new draft run (SD15).

    uv run python -m app.cli.import_v1 --config <path> [--news <path>] [--bar-prices <path>]

Everything is validated into an `ImportPlan` (`app/cli/v1_files.py`) before the
database is opened. Then one transaction creates the draft run, its drinks, its
news and config revision 1, and the new `run_id` is printed. Exit status:
0 on success, 2 on bad input, 1 on a database (or configuration) error; on 1
and 2 nothing is written. The import never touches an existing run and never
goes live (SD6).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.cli.v1_files import ImportPlan, load_plan
from app.core.config import ConfigError, get_settings
from app.db.mapping import params_to_json
from app.db.news import create_news
from app.db.runs import DuplicateDrinkName, add_drink, append_config_revision, create_draft_run
from app.db.session import create_engine

AUTHOR = "import_v1"


def revision_config(plan: ImportPlan) -> dict[str, Any]:
    """Revision 1: the params and every drink field, bar price included, as validated."""
    return {
        "params": params_to_json(plan.params),
        "drinks": [dataclasses.asdict(drink) for drink in plan.drinks],
    }


async def write_plan(plan: ImportPlan, *, name: str) -> int:
    """Store `plan` as a new draft run named `name`, in one transaction; return its `run_id`."""
    engine = create_engine(get_settings())
    try:
        async with engine.begin() as conn:
            run_id = await create_draft_run(
                conn, name=name, params=plan.params, run_seed=secrets.randbits(63)
            )
            for drink in plan.drinks:
                await add_drink(conn, run_id, **dataclasses.asdict(drink))
            for item in plan.news:
                await create_news(conn, run_id, ts_ms=item.ts_ms, level=item.level, text=item.text)
            await append_config_revision(conn, run_id, config=revision_config(plan), author=AUTHOR)
        return run_id
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.import_v1", description="Import v1's files as a new draft run."
    )
    parser.add_argument("--config", type=Path, required=True, help="exchange_config.json")
    parser.add_argument("--news", type=Path, help="news.json")
    parser.add_argument("--bar-prices", type=Path, help="the bar_prices.json sidecar")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = load_plan(args.config, news_path=args.news, bar_prices_path=args.bar_prices)
    except (OSError, ValueError) as error:
        print(f"import_v1: invalid input: {error}", file=sys.stderr)
        return 2

    try:
        # Phase 6 SD2: a run is named; an import takes its config file's stem.
        run_id = asyncio.run(write_plan(plan, name=args.config.stem[:100]))
    except DuplicateDrinkName as error:
        print(f"import_v1: invalid input: {error}", file=sys.stderr)
        return 2
    except (ConfigError, SQLAlchemyError, OSError) as error:
        print(f"import_v1: database error, nothing written: {error}", file=sys.stderr)
        return 1

    print(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
