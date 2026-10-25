"""A wallet's credentials and codes, and the names offered for a taken one (B-05 SD3, SD14, SD19).

Pure: random values come from `secrets`, never `random`, and none is derived from
a wallet's id or name (plan PD5).

- The **QR token** is 128 random bits; the scanner treats it as opaque.
- The **cookie value** is 256 random bits. Only its SHA-256 is stored, and it is
  found by that hash, so a slow hash (argon2, as for access keys) cannot be used:
  a key carries its `key_id` to look it up by, the cookie carries nothing (PD5).
- The **short code** is 8 symbols of Crockford's base32 (no I, L, O, U), stored
  uppercase without the hyphen and shown as `K7Q4-M2XD` (SD14, PD6). Reading one
  back forgives case, hyphens, spaces, `O` for `0` and `I`/`L` for `1`.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SHORT_CODE_LENGTH: Final = 8
NAME_MAX: Final = 40

_READ_AS: Final = str.maketrans({"O": "0", "I": "1", "L": "1"})


def new_qr_token() -> str:
    return secrets.token_urlsafe(16)


def new_cookie_value() -> str:
    return secrets.token_urlsafe(32)


def cookie_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_short_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(SHORT_CODE_LENGTH))


def normalise_short_code(text: str) -> str | None:
    """The stored form of a typed short code, or `None` if it cannot be one (AC14)."""
    code = text.strip().upper().replace("-", "").replace(" ", "").translate(_READ_AS)
    if len(code) != SHORT_CODE_LENGTH or any(symbol not in ALPHABET for symbol in code):
        return None
    return code


def display_short_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def suggestions(base: str, taken_keys: set[str], *, limit: int = 3) -> list[str]:
    """The `limit` free names "<base> 2", "<base> 3", … with the lowest numbers (SD3, PD7).

    `taken_keys` holds the taken names' keys (`name.strip().casefold()`, as
    `app.db.products.name_key`). A candidate over `NAME_MAX` characters keeps its
    number and loses characters from the end of the base.
    """
    base = base.strip()
    found: list[str] = []
    number = 2
    while len(found) < limit:
        suffix = f" {number}"
        candidate = base[: NAME_MAX - len(suffix)].rstrip() + suffix
        if candidate.strip().casefold() not in taken_keys:
            found.append(candidate)
        number += 1
    return found
