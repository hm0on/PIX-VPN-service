"""TicketMessage repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ticket_message import TicketMessage


class TicketMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        ticket_id: int,
        direction: str,
        message_type: str,
        text: str | None = None,
        photo_file_id: str | None = None,
        sticker_file_id: str | None = None,
        tg_message_id: int | None = None,
    ) -> TicketMessage:
        row = TicketMessage(
            ticket_id=ticket_id,
            direction=direction,
            message_type=message_type,
            text=text,
            photo_file_id=photo_file_id,
            sticker_file_id=sticker_file_id,
            tg_message_id=tg_message_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def list_for_ticket(self, ticket_id: int) -> list[TicketMessage]:
        result = await self.session.execute(
            select(TicketMessage)
            .where(TicketMessage.ticket_id == ticket_id)
            .order_by(TicketMessage.created_at.asc(), TicketMessage.id.asc())
        )
        return list(result.scalars().all())
