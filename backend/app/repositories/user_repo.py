"""User repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.tg_id == tg_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create(self, **fields: Any) -> User:
        user = User(**fields)
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update_fields(self, user: User, **fields: Any) -> User:
        for k, v in fields.items():
            setattr(user, k, v)
        await self.session.flush()
        return user
