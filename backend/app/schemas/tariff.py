"""Tariff schemas."""

from __future__ import annotations

from app.schemas.common import ORMModel


class TariffDurationSchema(ORMModel):
    id: int
    days: int
    price_kopecks: int
    is_hot: bool
    is_active: bool


class TariffWithDurationsSchema(ORMModel):
    id: int
    code: str
    name: str
    description_html: str | None = None
    devices: int
    sort_order: int
    is_active: bool
    is_free_trial: bool
    free_trial_days: int | None = None
    durations: list[TariffDurationSchema]
