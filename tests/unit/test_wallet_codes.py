"""A wallet's codes and the names offered for a taken one (B-05 T4: SD3, SD14, SD19; PD5-PD7)."""

from __future__ import annotations

import base64

import pytest

from app.runtime.wallet_codes import (
    ALPHABET,
    cookie_hash,
    display_short_code,
    new_cookie_value,
    new_qr_token,
    new_short_code,
    normalise_short_code,
    suggestions,
)


def test_the_alphabet_is_crockfords_base32() -> None:
    """SD14: no I, L, O, U."""
    assert len(ALPHABET) == 32
    assert set(ALPHABET).isdisjoint("ILOU")
    assert set(ALPHABET) == set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") - set("ILOU")


def test_a_short_code_is_eight_symbols_of_the_alphabet() -> None:
    codes = {new_short_code() for _ in range(200)}

    assert all(len(code) == 8 and set(code) <= set(ALPHABET) for code in codes)
    assert len(codes) > 190, "random, not derived from anything"


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("K7Q4-M2XD", "K7Q4M2XD"),
        ("k7q4-m2xd", "K7Q4M2XD"),
        ("K7Q4M2XD", "K7Q4M2XD"),
        (" k7q4 m2xd ", "K7Q4M2XD"),
        ("O0O0-0000", "00000000"),
        ("I1L1-il11", "11111111"),
    ],
)
def test_a_typed_short_code_is_read_forgivingly(typed: str, stored: str) -> None:
    """AC14: any case, with or without the hyphen, `O` as `0`, `I` and `L` as `1`."""
    assert normalise_short_code(typed) == stored


@pytest.mark.parametrize("typed", ["K7Q4-M2XU", "K7Q4-M2X", "K7Q4-M2XDD", "", "K7Q4_M2XD"])
def test_anything_else_is_no_short_code(typed: str) -> None:
    assert normalise_short_code(typed) is None


def test_the_display_form_has_a_hyphen_in_the_middle() -> None:
    assert display_short_code("K7Q4M2XD") == "K7Q4-M2XD"


def _bits(token: str) -> int:
    return len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) * 8


def test_the_token_and_the_cookie_value_carry_at_least_128_random_bits() -> None:
    """SD14, SD19."""
    tokens = {new_qr_token() for _ in range(50)}
    cookies = {new_cookie_value() for _ in range(50)}

    assert len(tokens) == len(cookies) == 50
    assert min(_bits(token) for token in tokens) >= 128
    assert min(_bits(cookie) for cookie in cookies) >= 128


def test_the_stored_hash_is_not_the_cookie_value() -> None:
    """SD19, AC12: SHA-256, hex."""
    value = new_cookie_value()
    digest = cookie_hash(value)

    assert digest != value
    assert value not in digest
    assert len(digest) == 64
    assert cookie_hash(value) == digest


def test_suggestions_are_the_lowest_free_numbers() -> None:
    """AC4: "Jan 2" is taken, so "Jan 3", "Jan 4", "Jan 5"."""
    assert suggestions("Jan", {"jan", "jan 2"}) == ["Jan 3", "Jan 4", "Jan 5"]


def test_suggestions_are_built_from_the_name_as_typed_and_compared_folded() -> None:
    assert suggestions("  JAN  ", {"jan", "jan 3"}) == ["JAN 2", "JAN 4", "JAN 5"]


def test_suggestions_stay_within_forty_characters() -> None:
    """SD3: the number stays; the base loses characters from its end."""
    base = "x" * 39 + "y"
    found = suggestions(base, {base}, limit=12)

    assert len(found) == 12
    assert all(len(name) <= 40 for name in found)
    assert found[0] == "x" * 38 + " 2"
    assert found[-1] == "x" * 37 + " 13"


def test_a_cut_base_drops_its_trailing_spaces() -> None:
    base = "x" * 37 + " " + "yy"
    assert suggestions(base, set(), limit=1) == ["x" * 37 + " 2"]
