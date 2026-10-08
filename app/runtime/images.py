"""Uploaded images, pure (Phase 6 SD29; AC31, AC33).

`sniff` types an upload by its first bytes only -- never its name or the
client's content type -- as one of the four types the `asset` table accepts,
so an SVG (script in an image) named `.png` is nothing (AC31).

`read_limited` passes a body's chunks through until their running total passes
`limit`, then raises `TooLarge`. It never asks for another chunk after that,
so at most `limit` plus the one chunk that crossed it is ever read (AC33).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Final, Literal

from app.core.errors import AppError

ContentType = Literal["image/png", "image/jpeg", "image/webp", "image/gif"]

MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024


class TooLarge(AppError):
    status_code = 413
    code = "too_large"


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "unsupported_media_type"


def sniff(prefix: bytes) -> ContentType | None:
    """The image type `prefix` starts with, or `None`."""
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_limited(chunks: AsyncIterator[bytes], limit: int) -> AsyncGenerator[bytes, None]:
    """`chunks`, unless they add up to more than `limit`: then `TooLarge`."""
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise TooLarge(f"the upload is larger than {limit} bytes")
        yield chunk
