"""IdempotencyKey ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


# Operation constants
IDEMPOTENCY_OP_NORTHLINE_CREATE = "northline_create"
IDEMPOTENCY_OP_NORTHLINE_EXTEND = "northline_extend"
IDEMPOTENCY_OP_NORTHLINE_DEACTIVATE = "northline_deactivate"
IDEMPOTENCY_OP_PAYMENT_WEBHOOK = "payment_webhook"


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(_json_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
