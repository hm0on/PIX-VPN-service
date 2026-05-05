"""Ticket ORM model (Stage 4)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TimestampMixin

# Kind constants
TICKET_KIND_SUPPORT = "support"
TICKET_KIND_IDEA = "idea"

TICKET_KINDS = frozenset({TICKET_KIND_SUPPORT, TICKET_KIND_IDEA})

# Status constants
TICKET_STATUS_OPEN = "open"
TICKET_STATUS_CLOSED = "closed"

TICKET_STATUSES = frozenset({TICKET_STATUS_OPEN, TICKET_STATUS_CLOSED})

# Closed-by constants
TICKET_CLOSED_BY_USER = "user"
TICKET_CLOSED_BY_ADMIN = "admin"

TICKET_CLOSED_BY = frozenset({TICKET_CLOSED_BY_USER, TICKET_CLOSED_BY_ADMIN})


class Ticket(BigIntPK, TimestampMixin, Base):
    __tablename__ = "tickets"

    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=TICKET_STATUS_OPEN
    )
    closed_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    topic_thread_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_tickets_code", "code", unique=True),
        Index("ix_tickets_topic_thread_id", "topic_thread_id"),
        Index("ix_tickets_user_id", "user_id"),
        # Partial UNIQUE: 1 open ticket per user.
        Index(
            "uq_tickets_user_open",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )
