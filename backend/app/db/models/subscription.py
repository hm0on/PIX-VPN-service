"""Subscription ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TimestampMixin

# Status constants
SUB_STATUS_PENDING = "pending"
SUB_STATUS_ACTIVE = "active"
SUB_STATUS_EXPIRED = "expired"
# Necrotic terminal status: NorthLine ``POST /keys/{id}/delete`` отработал,
# ключ необратимо снят у провайдера. Имя «deactivated» оставлено
# для обратной совместимости с админ-фильтрами и существующими записями.
SUB_STATUS_DEACTIVATED = "deactivated"
# Reversible pause: provider ``/stop`` отработал, юзер не может подключиться,
# но подписка ждёт ``/resume``. Срок ``expires_at`` всё ещё тикает.
SUB_STATUS_SUSPENDED = "suspended"
SUB_STATUS_FAILED = "failed"

SUB_STATUSES = frozenset(
    {
        SUB_STATUS_PENDING,
        SUB_STATUS_ACTIVE,
        SUB_STATUS_EXPIRED,
        SUB_STATUS_DEACTIVATED,
        SUB_STATUS_SUSPENDED,
        SUB_STATUS_FAILED,
    }
)


class Subscription(BigIntPK, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tariff_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tariffs.id", ondelete="RESTRICT"), nullable=False
    )
    tariff_duration_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tariff_durations.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    key_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    devices: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=SUB_STATUS_PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deactivation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_free_trial: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )

    __table_args__ = (
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_status", "status"),
        Index("ix_subscriptions_expires_at", "expires_at"),
        Index(
            "ix_subscriptions_user_free_trial",
            "user_id",
            "is_free_trial",
        ),
    )
