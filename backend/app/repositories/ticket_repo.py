"""Ticket repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ticket import (
    TICKET_STATUS_CLOSED,
    TICKET_STATUS_OPEN,
    Ticket,
)


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **fields: Any) -> Ticket:
        ticket = Ticket(**fields)
        self.session.add(ticket)
        await self.session.flush()
        await self.session.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: int) -> Ticket | None:
        result = await self.session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(self, user_id: int) -> Ticket | None:
        result = await self.session.execute(
            select(Ticket)
            .where(
                Ticket.user_id == user_id,
                Ticket.status == TICKET_STATUS_OPEN,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_thread(self, thread_id: int) -> Ticket | None:
        """Return the most recent ticket bound to the given topic thread.

        A topic is reused across tickets, so we order by id desc and take the
        first match.
        """
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.topic_thread_id == thread_id)
            .order_by(Ticket.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_closed(
        self, ticket_id: int, by: str, when: datetime
    ) -> Ticket | None:
        await self.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(
                status=TICKET_STATUS_CLOSED,
                closed_by=by,
                closed_at=when,
                updated_at=when,
            )
        )
        await self.session.flush()
        return await self.get_by_id(ticket_id)

    async def set_topic_thread_id(
        self, ticket_id: int, thread_id: int
    ) -> Ticket | None:
        await self.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(topic_thread_id=thread_id)
        )
        await self.session.flush()
        return await self.get_by_id(ticket_id)

    async def touch(self, ticket_id: int, when: datetime) -> None:
        """Bump updated_at on the ticket row (used after a new message)."""
        await self.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(updated_at=when)
        )
        await self.session.flush()
