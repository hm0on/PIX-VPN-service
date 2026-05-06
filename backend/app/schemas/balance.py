"""Balance / purchase schemas."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.subscription import SubscriptionResponse


class BalanceResponse(BaseModel):
    balance_kopecks: int


class PurchaseWithBalanceRequest(BaseModel):
    tg_id: int
    tariff_id: int
    duration_id: int


class PurchaseWithBalanceResponse(BaseModel):
    subscription: SubscriptionResponse
    balance_after_kopecks: int
    # ``payment_id`` is the row id of the internal Payment created by this
    # balance-paid purchase. The bot uses it to render the order number in
    # the success message ("✅ Вы успешно оплатили заказ #{payment_id}").
    payment_id: int
