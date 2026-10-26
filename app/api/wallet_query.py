"""A wallet as scanned or typed (B-05 AC14; B-06 SD13): the kassa's lookup, the bar's
lookup and an order's `wallet` all take it, exactly as read. The server resolves it;
the page never sends a wallet id."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WalletQuery(BaseModel):
    """Exactly one of a scanned QR token or a typed short code (AC14)."""

    model_config = ConfigDict(extra="forbid")

    qr_token: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    short_code: Annotated[str, Field(min_length=1, max_length=40)] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.qr_token is None) == (self.short_code is None):
            raise ValueError("give exactly one of qr_token and short_code")
        return self
