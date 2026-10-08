"""Image sniffing and the bounded reader, pure (Phase 6 T18: SD29; AC31, AC33)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.runtime.images import TooLarge, read_limited, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF87 = b"GIF87a" + b"\x00" * 16
GIF89 = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 8
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF87, "image/gif"),
        (GIF89, "image/gif"),
        (WEBP, "image/webp"),
    ],
)
def test_sniff_knows_the_four_types_by_magic_bytes(data: bytes, content_type: str) -> None:
    assert sniff(data) == content_type


@pytest.mark.parametrize(
    "data",
    [SVG, b"", b"\x89PN", b"RIFF\x24\x00\x00\x00WAVEfmt ", b"GIF88a", b"<html>"],
    ids=["svg", "empty", "short-png", "riff-wave", "gif88", "html"],
)
def test_sniff_refuses_everything_else(data: bytes) -> None:
    assert sniff(data) is None


class Counting:
    """An async chunk source that records how much was consumed."""

    def __init__(self, chunk: int, total: int) -> None:
        self.chunk = chunk
        self.total = total
        self.consumed = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while self.consumed < self.total:
            size = min(self.chunk, self.total - self.consumed)
            self.consumed += size
            yield b"x" * size


async def _drain(source: AsyncIterator[bytes]) -> int:
    got = 0
    async for part in source:
        got += len(part)
    return got


def test_read_limited_passes_a_body_within_the_limit_through() -> None:
    source = Counting(chunk=1000, total=5_000)

    assert asyncio.run(_drain(read_limited(source.__aiter__(), 5_000))) == 5_000


def test_read_limited_stops_within_one_chunk_of_the_limit() -> None:
    """AC33: at most `limit + chunk` is ever consumed."""
    source = Counting(chunk=64 * 1024, total=6 * 1024 * 1024)
    limit = 5 * 1024 * 1024

    with pytest.raises(TooLarge):
        asyncio.run(_drain(read_limited(source.__aiter__(), limit)))

    assert source.consumed <= limit + source.chunk
