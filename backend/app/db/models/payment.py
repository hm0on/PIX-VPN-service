"""Payment ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TimestampMixin


def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


# Status constants
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_EXPIRED = "expired"
PAYMENT_STATUS_REFUNDED = "refunded"

PAYMENT_PURPOSE_SUBSCRIPTION = "subscription"
PAYMENT_PURPOSE_TOPUP = "topup"

PAYMENT_PROVIDER_PLATEGA_SBP = "platega_sbp"
PAYMENT_PROVIDER_PLATEGA_CRYPTO = "platega_crypto"
PAYMENT_PROVIDER_CRYPTOBOT = "cryptobot"
PAYMENT_PROVIDER_BALANCE = "balance"


class Payment(BigIntPK, TimestampMixin, Base):
    __tablename__ = "payments"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="RUB"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=PAYMENT_STATUS_PENDING
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(_json_type(), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_payments_user_id", "user_id"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_external_id", "external_id"),
        Index("ix_payments_created_at_desc", "created_at"),
    )
