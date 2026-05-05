"""Broadcast ORM model — admin-managed mass messages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
BROADCAST_STATUS_DRAFT = "draft"
BROADCAST_STATUS_SCHEDULED = "scheduled"
BROADCAST_STATUS_SENDING = "sending"
BROADCAST_STATUS_DONE = "done"
BROADCAST_STATUS_CANCELLED = "cancelled"

BROADCAST_STATUSES = frozenset(
    {
        BROADCAST_STATUS_DRAFT,
        BROADCAST_STATUS_SCHEDULED,
        BROADCAST_STATUS_SENDING,
        BROADCAST_STATUS_DONE,
        BROADCAST_STATUS_CANCELLED,
    }
)

# Targets
BROADCAST_TARGET_ALL = "all"
BROADCAST_TARGET_SUBSCRIBERS = "subscribers"

BROADCAST_TARGETS = frozenset({BROADCAST_TARGET_ALL, BROADCAST_TARGET_SUBSCRIBERS})


class Broadcast(BigIntPK, Base):
    __tablename__ = "broadcasts"

    html_text: Mapped[str] = mapped_column(Text, nullable=False)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    buttons: Mapped[list[dict[str, Any]] | None] = mapped_column(
        _json_type(), nullable=True
    )
    target: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=BROADCAST_TARGET_ALL
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=BROADCAST_STATUS_DRAFT
    )
    recipients_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    sent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by_admin_key_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("admin_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_admin_key_label: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_broadcasts_status", "status"),
        Index("ix_broadcasts_scheduled_at", "scheduled_at"),
        Index("ix_broadcasts_created_at_desc", "created_at"),
    )
