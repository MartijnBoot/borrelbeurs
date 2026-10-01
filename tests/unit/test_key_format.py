"""Access-key format and hashing (Phase 3 T10: SD5, SD6; PD18)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.api.security import (
    ParsedKey,
    format_key,
    hash_secret,
    mint_secret,
    parse_key,
    verify_secret,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a_minted_secret_is_43_url_safe_characters() -> None:
    secrets = {mint_secret() for _ in range(50)}

    assert len(secrets) == 50
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", s) for s in secrets)


def test_format_and_parse_round_trip() -> None:
    for _ in range(50):  # some secrets contain `_`; split("_", 2) must keep them whole
        secret = mint_secret()
        assert parse_key(format_key(42, secret)) == ParsedKey(key_id=42, secret=secret)


def test_an_underscore_inside_the_secret_is_part_of_the_secret() -> None:
    assert parse_key("bb_7_ab_cd-ef") == ParsedKey(key_id=7, secret="ab_cd-ef")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("", id="empty"),
        pytest.param("bb", id="prefix-only"),
        pytest.param("bb_12", id="no-secret-part"),
        pytest.param("bb_12_", id="empty-secret"),
        pytest.param("xx_12_secret", id="wrong-prefix"),
        pytest.param("BB_12_secret", id="upper-case-prefix"),
        pytest.param(" bb_12_secret", id="leading-space"),
        pytest.param("bb_ab_secret", id="non-digit-id"),
        pytest.param("bb_-1_secret", id="negative-id"),
        pytest.param("bb__secret", id="empty-id"),
        pytest.param("bb_0_secret", id="zero-id"),
        pytest.param("bb_012_secret", id="leading-zero-id"),
        pytest.param("bb_١٢_secret", id="non-ascii-digits"),
        pytest.param("bb_12_sec ret", id="space-in-secret"),
        pytest.param("bb_12_sécret", id="non-ascii-secret"),
        pytest.param("bb_12_" + "a" * 129, id="absurdly-long-secret"),
    ],
)
def test_malformed_keys_are_rejected(raw: str) -> None:
    assert parse_key(raw) is None


def test_a_hash_is_argon2id_and_verifies_only_its_secret() -> None:
    secret = mint_secret()

    stored = hash_secret(secret)

    assert stored.startswith("$argon2id$")
    assert secret not in stored
    assert verify_secret(stored, secret) is True
    assert verify_secret(stored, secret + "x") is False


@pytest.mark.parametrize("stored", ["", "pending", "$argon2id$garbage", "$2b$12$bcrypt"])
def test_a_malformed_stored_hash_is_no_match_not_an_error(stored: str) -> None:
    assert verify_secret(stored, "anything") is False


def test_the_dummy_hash_is_not_computed_at_import() -> None:
    """SD6's dummy hash costs an argon2 hash; importing the module must not pay it."""
    probe = (
        "import app.api.security as s\n"
        "print(s.dummy_hash.cache_info().currsize)\n"
        "s.dummy_hash()\n"
        "print(s.dummy_hash.cache_info().currsize)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout

    assert out.split() == ["0", "1"]
