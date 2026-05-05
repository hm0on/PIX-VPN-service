"""Schemas for subscription extension endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


ExtensionPaymentProvider = Literal[
    "platega_sbp",
    "platega_crypto",
    "cryptobot",
    "balance",
]


class ExtensionStartRequest(BaseModel):
    tg_id: int
    duration_id: int
    payment_provider: ExtensionPaymentProvider
    promo_code: str | None = None


class ExtensionStartResponse(BaseModel):
    payment_id: int
    payment_url: str | None = None
    amount_kopecks: int
    key_url: str | None = None
