"""Pydantic schemas for Platega payment provider.

NOTE: Platega public docs are scarce — schemas reflect a *generalized* JSON shape
typical for Russian payment gateways: orderId / amount / currency / method /
successUrl / callbackUrl / sign. Adjust field names once the real API spec is
confirmed (TODO: уточнить под реальное API Platega).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PlategaMethod = Literal["sbp", "crypto"]


class PlategaInvoiceRequest(BaseModel):
    """Request body sent to Platega create-invoice endpoint."""

    order_id: str = Field(..., max_length=128)
    amount: int = Field(..., gt=0, description="Amount in kopecks (integer).")
    currency: str = Field(default="RUB", max_length=8)
    method: PlategaMethod
    description: str | None = Field(default=None, max_length=512)
    success_url: str | None = None
    callback_url: str
    shop_id: str
    # Signature is computed and added by the client just before sending.
    sign: str | None = None


class PlategaInvoiceResponse(BaseModel):
    """Response returned by Platega after successful invoice creation."""

    external_id: str = Field(..., description="Provider-side payment id.")
    payment_url: str = Field(..., description="URL the user is redirected to for payment.")
    status: str = Field(default="pending")
    raw: dict[str, Any] = Field(default_factory=dict)


class PlategaWebhookPayload(BaseModel):
    """Generalized webhook payload from Platega."""

    order_id: str | None = None
    external_id: str | None = None
    status: str
    amount: int | None = None
    currency: str | None = None
    method: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class InvoiceResult(BaseModel):
    """Common provider-agnostic invoice creation result."""

    external_id: str
    payment_url: str
    raw: dict[str, Any] = Field(default_factory=dict)
