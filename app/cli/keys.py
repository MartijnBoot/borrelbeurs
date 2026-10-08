"""Mint, list and revoke access keys (Phase 3 SD5).

    uv run python -m app.cli.keys create --role <display|bar|admin> --label <label>
    uv run python -m app.cli.keys list
    uv run python -m app.cli.keys revoke <key_id>

`create` prints `bb_<key_id>_<secret>` **once**: only the argon2id hash is
stored, so a lost key is revoked and replaced, never recovered
(`app.api.security.issue_key`, shared with `POST /api/keys`). `list` shows id,
label, role and status, never a secret or a hash. `revoke` takes effect on the
key's next request (SD8). Exit status: 0 on success, 2 on bad input, 1 on an
unknown key or a database error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import cast

from sqlalchemy.exc import SQLAlchemyError

from app.api.security import issue_key
from app.core.config import ConfigError, get_settings
from app.db.keys import ROLES, AuthKeyRow, Role, list_keys, revoke_key
from app.db.session import create_engine

_MAX_LABEL = 100


async def create(role: Role, label: str) -> str:
    engine = create_engine(get_settings())
    try:
        async with engine.begin() as conn:
            return await issue_key(conn, role=role, label=label)
    finally:
        await engine.dispose()


async def listing() -> list[AuthKeyRow]:
    engine = create_engine(get_settings())
    try:
        async with engine.connect() as conn:
            return await list_keys(conn)
    finally:
        await engine.dispose()


async def revoke(key_id: int) -> None:
    engine = create_engine(get_settings())
    try:
        async with engine.begin() as conn:
            await revoke_key(conn, key_id)
    finally:
        await engine.dispose()


def format_table(keys: Sequence[AuthKeyRow]) -> str:
    """id, label, role, status: nothing secret-derived."""
    rows = [("id", "label", "role", "status")] + [
        (str(k.key_id), k.label, k.role, "revoked" if k.revoked else "active") for k in keys
    ]
    widths = [max(len(row[column]) for row in rows) for column in range(4)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.keys", description="Access keys.")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("create", help="mint a key; it is printed once")
    make.add_argument("--role", required=True, choices=ROLES)
    make.add_argument("--label", required=True)
    commands.add_parser("list", help="every key, without secrets")
    gone = commands.add_parser("revoke", help="revoke a key")
    gone.add_argument("key_id", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            label = args.label.strip()
            if not 1 <= len(label) <= _MAX_LABEL:
                print(
                    f"keys: invalid input: --label must be 1-{_MAX_LABEL} characters",
                    file=sys.stderr,
                )
                return 2
            print(asyncio.run(create(cast(Role, args.role), label)))
        elif args.command == "list":
            print(format_table(asyncio.run(listing())))
        else:
            asyncio.run(revoke(args.key_id))
            print(f"key {args.key_id} revoked")
    except LookupError as error:
        print(f"keys: {error}", file=sys.stderr)
        return 1
    except (ConfigError, SQLAlchemyError, OSError) as error:
        print(f"keys: database error, nothing written: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
