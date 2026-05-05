"""Text repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.text import Text


class TextRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> Text | None:
        result = await self.session.execute(select(Text).where(Text.key == key))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Text]:
        result = await self.session.execute(select(Text).order_by(Text.key))
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        key: str,
        value_html: str,
        description: str | None = None,
        updated_by: str | None = None,
    ) -> Text:
        existing = await self.get_by_key(key)
        if existing is None:
            existing = Text(
                key=key,
                value_html=value_html,
                description=description,
                updated_by=updated_by,
            )
            self.session.add(existing)
        else:
            existing.value_html = value_html
            if description is not None:
                existing.description = description
            if updated_by is not None:
                existing.updated_by = updated_by
        await self.session.flush()
        return existing
