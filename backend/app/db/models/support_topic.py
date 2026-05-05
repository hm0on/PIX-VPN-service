"""SupportTopic ORM model (Stage 4): cache user_id → forum topic thread."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SupportTopic(TimestampMixin, Base):
    __tablename__ = "support_topics"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    topic_thread_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False
    )
    topic_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
