"""Tariff and TariffDuration ORM models."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPK


class Tariff(IntPK, Base):
    __tablename__ = "tariffs"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    devices: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    is_free_trial: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    free_trial_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # LTE add-on выдаваемый вместе с ключом NorthLine. Передаётся как
    # ``lte_gb`` в ``POST /keys`` (см. NorthLineClient.create_key). 35GB —
    # дефолт для всех текущих тарифов; кастомные тарифы (безлимит и т.п.)
    # позже смогут хранить своё значение в этой же колонке.
    lte_gb_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="35", default=35
    )
    # «Обычный» трафик, GB/мес. NorthLine не принимает hard-cap для
    # non-LTE (только ``unlimited_traffic`` boolean — см. поле ниже),
    # поэтому это поле рендерится только в UI/seeds-текстах, на
    # провайдер не передаётся. Для FREE-trial — 50 (декларируемый),
    # для paid тарифов сейчас NULL.
    traffic_gb_per_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # Передаётся в ``POST /keys`` как ``unlimited_traffic`` (см.
    # NorthLineClient.create_key). Если False — провайдер выдаст
    # дефолтные 1000 GB / устройство / 30 дней (масштабируется).
    # На стороне провайдера TRUE даёт +50% к базовой цене ключа.
    # Backfill 0018: все 4 публичных тарифа = TRUE (мы маркетим
    # безлимит в карточках). Кастомные тарифы могут выставить FALSE,
    # если хочется явный лимит — но тогда квота назначается
    # провайдером, наш UI её не контролирует.
    is_unlimited_traffic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )

    durations: Mapped[list["TariffDuration"]] = relationship(
        back_populates="tariff",
        cascade="all, delete-orphan",
        order_by="TariffDuration.days",
    )


class TariffDuration(IntPK, Base):
    __tablename__ = "tariff_durations"

    tariff_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tariffs.id", ondelete="CASCADE"), nullable=False
    )
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_hot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )

    tariff: Mapped[Tariff] = relationship(back_populates="durations")

    __table_args__ = (
        UniqueConstraint("tariff_id", "days", name="uq_tariff_durations_tariff_days"),
    )
