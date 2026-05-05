"""SQLAlchemy declarative base + common mixins."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base for all ORM models."""


class IntPK:
    """Integer auto-increment primary key."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class BigIntPK:
    """BigInteger auto-increment primary key.

    On SQLite (used in tests) `BIGINT` columns do not support implicit
    autoincrement, so we fall back to `INTEGER` for that dialect — the
    surrogate key range is still way more than tests need.
    """

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


class TimestampMixin:
    """created_at / updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
