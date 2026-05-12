"""Schemas for payment endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


PaymentProvider = Literal["platega_sbp", "platega_crypto", "cryptobot"]


class PurchaseStartRequest(BaseModel):
    tg_id: int
    tariff_id: int
    duration_id: int
    provider: PaymentProvider
    # Validated discount promo id (from POST /promo/apply). When present,
    # backend recomputes the final amount with ``promo.value`` percent
    # discount and stamps the promo meta into the Payment row so the
    # webhook can record a ``promo_activation``.
    promo_id: int | None = None


class PurchaseStartResponse(BaseModel):
    payment_id: int
    subscription_id: int
    payment_url: str
    expires_at: datetime
    # Echoed back so the bot can render the «Сумма: X ₽» line on the
    # invoice card without a second round-trip. Without this the bot
    # falls back to ``0`` and shows "Сумма: 0 ₽" — see the regression
    # test in ``tests/test_purchase_endpoint.py``.
    amount_kopecks: int


class TopupCreateRequest(BaseModel):
    tg_id: int
    amount_kopecks: int = Field(..., ge=1)
    provider: PaymentProvider


class TopupCreateResponse(BaseModel):
    payment_id: int
    payment_url: str
    expires_at: datetime
    # Same rationale as ``PurchaseStartResponse.amount_kopecks``: the bot's
    # invoice template needs the amount, and the source of truth is the
    # backend (after any provider-side rounding / currency conversion).
    amount_kopecks: int
