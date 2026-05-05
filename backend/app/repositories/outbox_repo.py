"""Outbox repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.outbox import OUTBOX_MSG_TEXT, Outbox


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        user_id: int,
        chat_id: int,
        payload: dict[str, Any],
        message_type: str = OUTBOX_MSG_TEXT,
    ) -> Outbox:
        row = Outbox(
            user_id=user_id,
            chat_id=chat_id,
            payload=payload,
            message_type=message_type,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row
