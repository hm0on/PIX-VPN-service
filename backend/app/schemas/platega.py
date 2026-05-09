"""Pydantic schemas for Platega payment provider.

API spec source: https://docs.platega.io/

Платёжные методы передаются как INTEGER:
    2  — СБП (QR-код)
    3  — ЕРИП
    11 — Карточный эквайринг
    12 — Международная оплата
    13 — Криптовалюта

Сумма в API передаётся в РУБЛЯХ (float), не в копейках.

В ответе и webhook поле статуса — строка верхним регистром:
    PENDING | CONFIRMED | CANCELED | CHARGEBACKED
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# Семантические алиасы, которые используются в payment_service для маршрутизации.
# Маппятся в integer Platega-кода в platega_client.
PlategaMethod = Literal["sbp", "crypto", "card", "erip", "international"]


# Числовые коды Platega для поля paymentMethod в /transaction/process.
PLATEGA_METHOD_CODES: dict[str, int] = {
    "sbp": 2,
    "erip": 3,
    "card": 11,
    "international": 12,
    "crypto": 13,
}


class PlategaPaymentDetails(BaseModel):
    """Сумма + валюта для запроса /transaction/process."""

    amount: float = Field(..., gt=0)
    currency: str = Field(default="RUB", max_length=8)


class PlategaInvoiceRequest(BaseModel):
    """Запрос к POST /transaction/process."""

    paymentMethod: int  # noqa: N815 — точный JSON-ключ Platega
    paymentDetails: PlategaPaymentDetails  # noqa: N815
    description: str = Field(..., max_length=512)
    return_: str | None = Field(default=None, alias="return")  # успешный возврат
    failedUrl: str | None = None  # noqa: N815
    payload: str | None = Field(default=None, max_length=512)

    model_config = {"populate_by_name": True}


class PlategaInvoiceResponse(BaseModel):
    """Ответ на POST /transaction/process."""

    transactionId: str  # noqa: N815
    redirect: str | None = None
    status: str = "PENDING"
    raw: dict[str, Any] = Field(default_factory=dict)


class PlategaWebhookPayload(BaseModel):
    """Payload входящего callback'а от Platega."""

    id: str
    amount: float
    currency: str = "RUB"
    status: str  # CONFIRMED | CANCELED | CHARGEBACKED
    paymentMethod: int | None = None  # noqa: N815
    payload: str | None = None


class InvoiceResult(BaseModel):
    """Provider-agnostic результат создания инвойса."""

    external_id: str
    payment_url: str
    raw: dict[str, Any] = Field(default_factory=dict)
