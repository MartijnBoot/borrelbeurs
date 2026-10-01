"""Access keys and their secrets (Phase 3 SD5, SD6; plan PD2, PD18).

A key is `bb_<key_id>_<secret>`, with `secret = secrets.token_urlsafe(32)`
(43 characters of `[A-Za-z0-9_-]`). It is parsed by `split("_", 2)` with an
all-digit `key_id`, so an `_` inside the secret is safe. Only the argon2id hash
of the secret is stored (`argon2.PasswordHasher` defaults, RFC 9106); the key
itself is printed once by `app.cli.keys` and never written anywhere.

`dummy_hash()` is what login verifies against when no stored hash exists, so
an unknown `key_id` costs the same argon2 verify as a real one (SD6). It is
built on first use, never at import: hashing at import would slow every
process start, test collection included.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from functools import cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

KEY_PREFIX: Final = "bb"

# token_urlsafe(32) is 43 characters; the bound only stops an absurd input from
# reaching argon2.
_SECRET = re.compile(r"[A-Za-z0-9_-]{1,128}")
_KEY_ID = re.compile(r"[1-9][0-9]{0,18}")

_hasher = PasswordHasher()


@dataclass(frozen=True)
class ParsedKey:
    key_id: int
    secret: str


def mint_secret() -> str:
    return secrets.token_urlsafe(32)


def format_key(key_id: int, secret: str) -> str:
    return f"{KEY_PREFIX}_{key_id}_{secret}"


def parse_key(raw: str) -> ParsedKey | None:
    """`raw` split into `key_id` and secret, or `None` if malformed. Never hashes."""
    parts = raw.split("_", 2)
    if len(parts) != 3:
        return None
    prefix, key_id, secret = parts
    if prefix != KEY_PREFIX or not _KEY_ID.fullmatch(key_id) or not _SECRET.fullmatch(secret):
        return None
    return ParsedKey(key_id=int(key_id), secret=secret)


def hash_secret(secret: str) -> str:
    return _hasher.hash(secret)


def verify_secret(secret_hash: str, secret: str) -> bool:
    """Whether `secret` matches `secret_hash`; any malformed hash is simply no match."""
    try:
        return _hasher.verify(secret_hash, secret)
    except (VerificationError, InvalidHashError):
        return False


@cache
def dummy_hash() -> str:
    """A hash no presented secret matches, built once, on first use."""
    return hash_secret(mint_secret())
