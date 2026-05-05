"""Outbox ORM model — reliable async messaging out to Telegram."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK


def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


# Status constants
OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_FAILED = "failed"

# Message types
OUTBOX_MSG_TEXT = "text"
OUTBOX_MSG_PHOTO = "photo"
OUTBOX_MSG_DOCUMENT = "document"


class Outbox(BigIntPK, Base):
    __tablename__ = "outbox"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=OUTBOX_MSG_TEXT
    )
    payload: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=OUTBOX_STATUS_PENDING
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_outbox_status", "status"),
        Index("ix_outbox_send_after", "send_after"),
        Index("ix_outbox_status_send_after", "status", "send_after"),
    )
