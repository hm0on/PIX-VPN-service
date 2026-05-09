"""Promo-code schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PromoApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tg_id: int
    code: str = Field(min_length=1, max_length=64)


class PromoApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["balance", "discount_percent"]
    amount_kopecks: int | None = None
    percent: int | None = None
    promo_id: int | None = None
    message: str | None = None
    # The user's *post-credit* balance in kopecks (only set for ``balance``
    # type promos). The bot renders this directly to the user as
    # «Текущий баланс: X ₽» — so the value is computed server-side after
    # the credit so we don't have to fetch the balance again client-side.
    balance_kopecks: int | None = None


@dataclass
class PromoApplyResult:
    """Internal result returned by PromoService.validate_and_apply."""

    type: str  # "balance" | "discount_percent"
    amount_kopecks: int | None = None
    percent: int | None = None
    promo_id: int | None = None
    message_text: str | None = None
    # Post-credit balance for ``balance`` promos. ``None`` for discount promos
    # (no balance change at apply time).
    balance_kopecks: int | None = None
