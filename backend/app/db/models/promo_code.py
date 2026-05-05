"""PromoCode ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK

# Type constants
PROMO_TYPE_BALANCE = "balance"
PROMO_TYPE_DISCOUNT_PERCENT = "discount_percent"

PROMO_TYPES = frozenset({PROMO_TYPE_BALANCE, PROMO_TYPE_DISCOUNT_PERCENT})


class PromoCode(BigIntPK, Base):
    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total_activations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_per_user: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", default=1
    )
    current_activations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by_admin_key_label: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_promo_codes_code", "code"),
        Index("ix_promo_codes_is_active", "is_active"),
        Index("ix_promo_codes_valid_until", "valid_until"),
    )
