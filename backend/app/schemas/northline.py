"""Pydantic schemas for NorthLine reseller API requests and responses.

Spec: NorthLine Reseller API (https://northline-vpn.xyz/api/v1).

Конвенции:
- Все ответы содержат ``ok: bool`` (для успеха ``true``).
- Ошибки возвращаются как ``{"ok": false, "error_code": "...", "error_message": "..."}``.
- Datetime'ы — ISO-8601 UTC.
- Цены — RUB (number, может быть с дробной).
- Статусы подписки — enum: ``active | suspended | expired``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# Enum статусов подписки на стороне NorthLine.
# ``deleted`` появилось вместе с реальным ``POST /keys/{id}/delete`` —
# раньше провайдер не отдавал такой статус, потому что endpoint'а не было.
NorthLineSubStatus = Literal["active", "suspended", "expired", "deleted"]


class KeyResponse(BaseModel):
    """Response of ``POST /keys``."""

    ok: bool = True
    subscription_id: str
    key: str
    expires_at: datetime
    devices: int
    days: int


class ExtendResponse(BaseModel):
    """Response of ``POST /keys/{id}/extend``.

    Provider возвращает ``new_expires_at``, ``days_added`` и ``charged_rub``.
    Мы экспонируем ``expires_at`` / ``added_days`` через alias'ы,
    чтобы legacy-callers продолжали работать.
    """

    model_config = ConfigDict(populate_by_name=True)

    ok: bool = True
    subscription_id: str
    expires_at: datetime = Field(validation_alias="new_expires_at")
    added_days: int = Field(validation_alias="days_added")
    # spec: number → допускаем float; integer тоже валидно.
    charged_rub: float | None = None


class DeleteResponse(BaseModel):
    """Response of ``POST /keys/{id}/delete`` (alias ``/remove``).

    Подписка переходит в терминальный статус ``deleted`` — продлить или
    возобновить её уже нельзя. Провайдер возвращает ``refund_rub``
    (остаток списанных средств). Сейчас мы его только логируем; учётом
    реселлер-баланса займёмся отдельно.
    """

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    subscription_id: str
    status: Literal["deleted"]
    expires_at: datetime | None = None
    refund_rub: float | None = None


class StopResponse(BaseModel):
    """Response of ``POST /keys/{id}/stop`` (alias ``/suspend``).

    Подписка переходит в ``suspended`` — обратимая блокировка, доступ
    отключается немедленно, но подписку можно возобновить через
    ``/resume``. Срок ``expires_at`` не двигается.
    """

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    subscription_id: str
    status: Literal["suspended"]
    expires_at: datetime | None = None


class ResumeResponse(BaseModel):
    """Response of ``POST /keys/{id}/resume`` (alias ``/activate``).

    Возобновляет ранее приостановленную подписку, возвращает её в
    ``active``. Срок ``expires_at`` не двигается.
    """

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    subscription_id: str
    status: Literal["active"]
    expires_at: datetime | None = None


# Back-compat алиас для legacy callers, мигрирующих с no-op deactivate_key.
# Новый код должен использовать ``DeleteResponse``.
DeactivateResponse = DeleteResponse


class KeyDevice(BaseModel):
    """Per-device row. Reseller API сейчас НЕ возвращает список устройств,
    но схема оставлена для forward-совместимости — admin UI терпит пустой
    список."""

    device_id: str
    name: str | None = None
    platform: str | None = None
    last_seen: datetime | None = None
    traffic_bytes: int | None = None


class KeyInfo(BaseModel):
    """Response of ``GET /keys/{id}``.

    По спеке провайдер возвращает:
    ``subscription_id, key, status, expires_at, devices (int — total slots),
    traffic_used_bytes, traffic_quota_gb`` (``-1`` для безлимита).

    Для backward-совместимости с admin UI мы оставляем легаси-алиасы
    ``devices_total`` / ``traffic_bytes`` и (всегда пустой) ``device_list``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ok: bool = True
    subscription_id: str
    key: str
    status: NorthLineSubStatus
    # По спеке required, но оставляем optional для тестов и forward-совместимости.
    expires_at: datetime | None = None
    devices_total: int | None = Field(default=None, validation_alias="devices")
    devices_used: int | None = None
    traffic_bytes: int | None = Field(
        default=None, validation_alias="traffic_used_bytes"
    )
    # ``-1`` означает безлимит; integer допускает.
    traffic_quota_gb: int | None = None
    lte_traffic_bytes: int | None = None
    device_list: list[KeyDevice] = Field(default_factory=list)

    # Back-compat shim: callers used to do ``info.devices`` (the list).
    @property
    def devices(self) -> list[KeyDevice]:
        return self.device_list


# ---------------------------------------------------------------------------
# Reseller endpoints
# ---------------------------------------------------------------------------


class ResellerProfile(BaseModel):
    """Response of ``GET /reseller/profile``."""

    ok: bool = True
    provider_key: str
    label: str | None = None
    balance_rub: float
    active: bool = True
    issued_total: int = 0
    active_total: int = 0
    spent_rub: float = 0.0


class PriceQuote(BaseModel):
    """Response of ``GET /reseller/price-quote``.

    Публичный эндпоинт — без авторизации.
    """

    model_config = ConfigDict(extra="ignore")

    days: int
    devices: int
    tariff_code: str | None = None
    total_price_rub: float
    regular_price_rub: float | None = None
    savings_rub: float | None = None
    discount_pct: int | None = None
    device_discount_pct: int | None = None
    term_discount_pct: int | None = None
    price_per_device_per_day: float | None = None
    # ``-1`` если безлимит, иначе квота в GB.
    traffic_quota_gb: int | None = None
    unlimited_traffic: bool = False
    lte_gb: int | None = None
    lte_addon_rub: float | None = None
    lte_rate_per_gb: float | None = None


class PriceMatrixRow(BaseModel):
    """Строка матрицы цен партнёра."""

    days: int
    devices: int
    total_price_rub: float
    override_key: str | None = None


class ResellerPrices(BaseModel):
    """Response of ``GET /reseller/prices``."""

    ok: bool = True
    provider_key: str
    price_matrix: list[PriceMatrixRow] = Field(default_factory=list)


class LtePackage(BaseModel):
    """Один LTE-пакет из справочника."""

    gb: int
    price_rub: float
    label: str | None = None
    rate: float | None = None


class LtePackagesResponse(BaseModel):
    """Response of ``GET /reseller/lte-packages``."""

    ok: bool = True
    packages: list[LtePackage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------


class BrandingResponse(BaseModel):
    """Response of ``GET /reseller/branding``."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    branding: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    ok: bool = False
    error_code: str = "INTERNAL_ERROR"
    error_message: str = "Internal error"
