"""Text service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.text import Text
from app.repositories.text_repo import TextRepository


class TextService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TextRepository(session)

    async def get_text(self, key: str) -> Text:
        text = await self.repo.get_by_key(key)
        if text is None:
            raise NotFoundError(f"Text '{key}' not found", error_code="text_not_found")
        return text

    async def get_all_texts(self) -> list[Text]:
        return await self.repo.list_all()
