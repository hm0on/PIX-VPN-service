"""BroadcastRecipient ORM model."""

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

# Recipient status constants
BROADCAST_RECIPIENT_PENDING = "pending"
BROADCAST_RECIPIENT_SENT = "sent"
BROADCAST_RECIPIENT_FAILED = "failed"

BROADCAST_RECIPIENT_STATUSES = frozenset(
    {
        BROADCAST_RECIPIENT_PENDING,
        BROADCAST_RECIPIENT_SENT,
        BROADCAST_RECIPIENT_FAILED,
    }
)


class BroadcastRecipient(BigIntPK, Base):
    __tablename__ = "broadcast_recipients"

    broadcast_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("broadcasts.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=BROADCAST_RECIPIENT_PENDING
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_broadcast_recipients_broadcast_status",
            "broadcast_id",
            "status",
        ),
        Index("ix_broadcast_recipients_user_id", "user_id"),
    )
