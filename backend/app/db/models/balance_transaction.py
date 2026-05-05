"""BalanceTransaction ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK

# Reasons
BT_REASON_TOPUP = "topup"
BT_REASON_PURCHASE = "purchase"
BT_REASON_REFERRAL_BONUS = "referral_bonus"
BT_REASON_PROMO_BONUS = "promo_bonus"
BT_REASON_REFUND = "refund"
BT_REASON_ADMIN_ADJUST = "admin_adjust"


class BalanceTransaction(BigIntPK, Base):
    __tablename__ = "balance_transactions"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_payment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    ref_subscription_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance_after_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_balance_transactions_user_id", "user_id"),
        Index("ix_balance_transactions_reason", "reason"),
        Index("ix_balance_transactions_created_at_desc", "created_at"),
    )
