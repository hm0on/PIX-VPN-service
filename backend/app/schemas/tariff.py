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
    # Conversion-pack 2026-05-13: marketing field — отображается в карточке
    # тарифа (NULL = безлимит). Не enforce'ится NorthLine'ом, только UI.
    traffic_gb_per_month: int | None = None
    lte_gb_per_month: int | None = None
    # 2026-05-13 (post-conversion-pack): передаётся в NorthLine при
    # выпуске ключа. TRUE — безлимит, FALSE — провайдерский дефолт
    # (1000 GB / устройство / 30 дней). Бот не использует это поле для
    # рендера — копия в ``description_html``.
    is_unlimited_traffic: bool = False
    durations: list[TariffDurationSchema]
