"""Log and TechLog ORM models."""

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
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Portable JSON: JSONB on PostgreSQL, JSON elsewhere (used in tests on SQLite).
def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


class Log(Base):
    __tablename__ = "logs"

    # Use BigInteger on PostgreSQL but Integer on SQLite (autoincrement only
    # works on the latter when the column is plain INTEGER).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    event: Mapped[str] = mapped_column(String(128), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(
        _json_type(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_logs_level", "level"),
        Index("ix_logs_module", "module"),
        Index("ix_logs_user_id", "user_id"),
        Index("ix_logs_created_at_desc", "created_at"),
        # GIN index on `context` is created via Alembic migration only (Postgres-specific).
    )


class TechLog(Base):
    __tablename__ = "tech_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(_json_type(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_tech_logs_trace_id", "trace_id"),
        Index("ix_tech_logs_created_at_desc", "created_at"),
        Index("ix_tech_logs_service", "service"),
        Index("ix_tech_logs_action", "action"),
    )
