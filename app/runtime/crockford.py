"""Crockford's base32 symbols, drawn and read back forgivingly (B-05 SD14, B-08 SD1-SD2).

A leaf with two callers: a wallet's 8-symbol short code (`app.runtime.wallet_codes`)
and a 9-symbol access key (`app.api.security`). Each symbol is drawn from
`secrets`, never `random`. Reading forgives what a person typing from a screen or
from someone's voice gets wrong: surrounding whitespace, case, every `-` and
space, `O` for `0`, and `I` or `L` for `1`.
"""

from __future__ import annotations

import secrets
from typing import Final

ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_READ_AS: Final = str.maketrans({"O": "0", "I": "1", "L": "1"})


def draw(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def read(text: str, length: int) -> str | None:
    """The stored form of typed `text`: exactly `length` symbols of `ALPHABET`, or `None`."""
    symbols = text.strip().upper().replace("-", "").replace(" ", "").translate(_READ_AS)
    if len(symbols) != length or any(symbol not in ALPHABET for symbol in symbols):
        return None
    return symbols
