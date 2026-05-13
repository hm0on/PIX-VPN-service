"""Referral ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK


class Referral(BigIntPK, Base):
    __tablename__ = "referrals"

    referrer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    referee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    bonus_paid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    bonus_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    referee_first_purchase_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Момент, когда рефереру выдали персональный промокод 15% за то,
    # что приглашённый юзер взял free trial. NULL = ещё не выдавали;
    # non-NULL = идемпотентность (повторный trial у того же referee
    # больше не триггерит выдачу). Независимо от ``bonus_paid_at``
    # (paid-бонус) — реферер может получить и trial-промо, и +70₽.
    trial_bonus_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("referee_id", name="uq_referrals_referee_id"),
        Index("ix_referrals_referrer_id", "referrer_id"),
        Index("ix_referrals_referee_id", "referee_id"),
    )
