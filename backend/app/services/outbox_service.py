"""Outbox service: enqueue messages, fetch pending with row-level locking,
mark sent / failed. Used by payment_service and consumed by the worker.

The Outbox model is provided by the Backend Core agent in `app.db.models.outbox`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("outbox")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _exponential_backoff_minutes(attempts: int) -> int:
    """2^attempts capped at 60 min."""
    if attempts <= 0:
        return 1
    return min(2**attempts, 60)


def _get_outbox_model() -> Any:
    """Lazy import to avoid a hard dependency at import-time
    (Backend Core agent owns this model).
    """
    from app.db.models.outbox import Outbox

    return Outbox


async def enqueue_message(
    session: AsyncSession,
    *,
    user_id: int,
    chat_id: int,
    message_type: str,
    payload: dict[str, Any],
    send_after: datetime | None = None,
) -> Any:
    """Insert a new outbox message in `pending` state."""
    OutboxMessage = _get_outbox_model()
    msg = OutboxMessage(
        user_id=user_id,
        chat_id=chat_id,
        message_type=message_type,
        payload=payload,
        status="pending",
        attempts=0,
        send_after=send_after or _now(),
    )
    session.add(msg)
    await session.flush()
    return msg


async def fetch_pending(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> list[Any]:
    """Atomically claim up to `limit` pending messages.

    Uses `FOR UPDATE SKIP LOCKED` so multiple workers don't pick the same row.
    Marks claimed rows as `dispatching` and increments attempts before
    returning them.
    """
    OutboxMessage = _get_outbox_model()
    now = _now()

    stmt = (
        select(OutboxMessage)
        .where(
            OutboxMessage.status == "pending",
            OutboxMessage.send_after <= now,
        )
        .order_by(OutboxMessage.send_after.asc(), OutboxMessage.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    # SQLite (used in tests) doesn't support FOR UPDATE — fall back gracefully.
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        stmt = (
            select(OutboxMessage)
            .where(
                OutboxMessage.status == "pending",
                OutboxMessage.send_after <= now,
            )
            .order_by(OutboxMessage.send_after.asc(), OutboxMessage.id.asc())
            .limit(limit)
        )

    result = await session.execute(stmt)
    rows: list[Any] = list(result.scalars().all())
    if not rows:
        return []

    ids = [r.id for r in rows]
    await session.execute(
        update(OutboxMessage)
        .where(OutboxMessage.id.in_(ids))
        .values(status="dispatching", attempts=OutboxMessage.attempts + 1)
    )
    await session.flush()
    # Refresh the in-memory rows so callers see the updated status / attempts.
    for r in rows:
        await session.refresh(r)
    return rows


async def mark_sent(
    session: AsyncSession,
    *,
    message_id: int,
    tg_message_id: int | None = None,
) -> Any:
    """Mark message as sent."""
    OutboxMessage = _get_outbox_model()
    result = await session.execute(
        select(OutboxMessage).where(OutboxMessage.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if msg is None:
        raise NoResultFound(f"OutboxMessage id={message_id} not found")

    msg.status = "sent"
    msg.sent_at = _now()
    if tg_message_id is not None:
        payload = dict(msg.payload or {})
        payload["tg_message_id"] = tg_message_id
        msg.payload = payload
    await session.flush()
    return msg


async def mark_failed(
    session: AsyncSession,
    *,
    message_id: int,
    error: str,
    max_attempts: int = 5,
) -> Any:
    """Mark a delivery attempt as failed.

    If attempts >= max_attempts → status='failed' (no further retries).
    Otherwise, status returns to 'pending' with exponential backoff.
    """
    OutboxMessage = _get_outbox_model()
    result = await session.execute(
        select(OutboxMessage).where(OutboxMessage.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if msg is None:
        raise NoResultFound(f"OutboxMessage id={message_id} not found")

    msg.last_error = error
    if msg.attempts >= max_attempts:
        msg.status = "failed"
    else:
        msg.status = "pending"
        msg.send_after = _now() + timedelta(
            minutes=_exponential_backoff_minutes(msg.attempts)
        )
    await session.flush()
    return msg
