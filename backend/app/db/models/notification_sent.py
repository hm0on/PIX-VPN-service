"""NotificationSent ORM model — guards against duplicate expiry notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK

# Kind constants
NOTIFICATION_EXPIRY_3D = "expiry_3d"
NOTIFICATION_EXPIRY_1D = "expiry_1d"
NOTIFICATION_EXPIRED = "expired"
# Trial-only напоминание за 24ч до конца — отдельный kind, потому что
# trial живёт 5 дней и попадал бы в окно "expiry_3d" одновременно с
# выдачей. Не пересекаем с обычной expiry-логикой.
NOTIFICATION_TRIAL_EXPIRING_24H = "trial_expiring_24h"

NOTIFICATION_KINDS = frozenset(
    {
        NOTIFICATION_EXPIRY_3D,
        NOTIFICATION_EXPIRY_1D,
        NOTIFICATION_EXPIRED,
        NOTIFICATION_TRIAL_EXPIRING_24H,
    }
)


class NotificationSent(BigIntPK, Base):
    __tablename__ = "notifications_sent"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "kind", name="uq_notifications_sent_sub_kind"
        ),
        Index("ix_notifications_sent_user_id", "user_id"),
        Index("ix_notifications_sent_subscription_id", "subscription_id"),
    )
