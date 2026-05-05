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


@dataclass
class PromoApplyResult:
    """Internal result returned by PromoService.validate_and_apply."""

    type: str  # "balance" | "discount_percent"
    amount_kopecks: int | None = None
    percent: int | None = None
    promo_id: int | None = None
    message_text: str | None = None
