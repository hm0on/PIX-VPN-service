"""User ORM model."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    # SQLite tests need plain INTEGER for autoincrement (BIGINT doesn't work).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    balance_kopecks: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    is_banned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    banned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_users_tg_id", "tg_id"),
        Index("ix_users_ref_id", "ref_id"),
        Index("ix_users_created_at", "created_at"),
    )
