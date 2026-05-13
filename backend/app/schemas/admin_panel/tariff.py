"""Admin Tariffs schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdminTariffDuration(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    days: int
    price_kopecks: int
    is_hot: bool
    is_active: bool


class AdminTariff(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description_html: str | None = None
    devices: int
    sort_order: int
    is_active: bool
    is_free_trial: bool
    free_trial_days: int | None = None
    # Conversion-pack 2026-05-13: маркетинговое поле «трафик GB/мес».
    # NorthLine не умеет хард-кап обычного трафика, поэтому это значение
    # отображается только в карточке тарифа (бот + админка). LTE-трафик
    # лежит в отдельном поле ``lte_gb_per_month``.
    traffic_gb_per_month: int | None = None
    lte_gb_per_month: int | None = None
    durations: list[AdminTariffDuration]


class AdminTariffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    description_html: str | None = None
    devices: int = Field(ge=1, le=100)
    sort_order: int = 0
    is_active: bool = True
    is_free_trial: bool = False
    free_trial_days: int | None = None
    traffic_gb_per_month: int | None = Field(default=None, ge=0)
    lte_gb_per_month: int | None = Field(default=None, ge=0)


class AdminTariffPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description_html: str | None = None
    devices: int | None = Field(default=None, ge=1, le=100)
    sort_order: int | None = None
    is_active: bool | None = None
    is_free_trial: bool | None = None
    free_trial_days: int | None = None
    traffic_gb_per_month: int | None = Field(default=None, ge=0)
    lte_gb_per_month: int | None = Field(default=None, ge=0)


class AdminTariffDurationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=3650)
    price_kopecks: int = Field(ge=0)
    is_hot: bool = False
    is_active: bool = True


class AdminTariffDurationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_kopecks: int | None = Field(default=None, ge=0)
    is_hot: bool | None = None
    is_active: bool | None = None
