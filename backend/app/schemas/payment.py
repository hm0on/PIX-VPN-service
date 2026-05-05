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


class PurchaseStartResponse(BaseModel):
    payment_id: int
    subscription_id: int
    payment_url: str
    expires_at: datetime


class TopupCreateRequest(BaseModel):
    tg_id: int
    amount_kopecks: int = Field(..., ge=1)
    provider: PaymentProvider


class TopupCreateResponse(BaseModel):
    payment_id: int
    payment_url: str
    expires_at: datetime
