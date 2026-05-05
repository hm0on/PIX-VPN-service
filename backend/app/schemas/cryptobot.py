"""Pydantic schemas for CryptoBot Pay API.

Docs: https://help.crypt.bot/crypto-pay-api
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CryptoBotInvoiceStatus = Literal["active", "paid", "expired"]


class CryptoBotCreateInvoiceRequest(BaseModel):
    """Body for POST {api_url}/createInvoice."""

    currency_type: Literal["fiat", "crypto"] = "fiat"
    fiat: str = "RUB"
    amount: str = Field(..., description="Decimal string, e.g. '189.00'.")
    description: str | None = Field(default=None, max_length=1024)
    payload: str | None = Field(default=None, max_length=4096)
    paid_btn_name: str | None = None
    paid_btn_url: str | None = None
    expires_in: int | None = None
    allow_comments: bool | None = None
    allow_anonymous: bool | None = None


class CryptoBotInvoice(BaseModel):
    """A subset of CryptoBot Invoice fields used by us."""

    invoice_id: int
    status: str
    hash: str | None = None
    currency_type: str | None = None
    fiat: str | None = None
    amount: str | None = None
    pay_url: str | None = None
    bot_invoice_url: str | None = None
    mini_app_invoice_url: str | None = None
    web_app_invoice_url: str | None = None
    description: str | None = None
    payload: str | None = None
    created_at: datetime | None = None
    paid_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CryptoBotApiResponse(BaseModel):
    """Top-level Crypto-Pay API response envelope."""

    ok: bool
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class CryptoBotWebhookUpdate(BaseModel):
    """Incoming webhook update body.

    Real shape (per docs):
      {
        "update_id": 1,
        "update_type": "invoice_paid",
        "request_date": "2024-01-01T00:00:00Z",
        "payload": { ...invoice fields... }
      }
    """

    update_id: int | None = None
    update_type: str
    request_date: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
