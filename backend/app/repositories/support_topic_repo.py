"""SupportTopic repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.support_topic import SupportTopic


class SupportTopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: int) -> SupportTopic | None:
        result = await self.session.execute(
            select(SupportTopic).where(SupportTopic.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        user_id: int,
        topic_thread_id: int,
        topic_name: str | None,
    ) -> SupportTopic:
        existing = await self.get_by_user_id(user_id)
        if existing is None:
            row = SupportTopic(
                user_id=user_id,
                topic_thread_id=topic_thread_id,
                topic_name=topic_name,
            )
            self.session.add(row)
            await self.session.flush()
            await self.session.refresh(row)
            return row

        changed = False
        if existing.topic_thread_id != topic_thread_id:
            existing.topic_thread_id = topic_thread_id
            changed = True
        if existing.topic_name != topic_name:
            existing.topic_name = topic_name
            changed = True
        if changed:
            await self.session.flush()
        return existing
