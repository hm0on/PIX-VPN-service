"""TicketMessage ORM model (Stage 4)."""

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

# Direction constants
TICKET_MSG_FROM_USER = "from_user"
TICKET_MSG_FROM_ADMIN = "from_admin"

TICKET_MSG_DIRECTIONS = frozenset({TICKET_MSG_FROM_USER, TICKET_MSG_FROM_ADMIN})

# Message-type constants
TICKET_MSG_TYPE_TEXT = "text"
TICKET_MSG_TYPE_PHOTO = "photo"
TICKET_MSG_TYPE_STICKER = "sticker"

TICKET_MSG_TYPES = frozenset(
    {TICKET_MSG_TYPE_TEXT, TICKET_MSG_TYPE_PHOTO, TICKET_MSG_TYPE_STICKER}
)


class TicketMessage(BigIntPK, Base):
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sticker_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_ticket_messages_ticket_id", "ticket_id"),
        Index("ix_ticket_messages_created_at", "created_at"),
    )
