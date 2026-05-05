"""User service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LEVEL_INFO, business_log
from app.db.models.user import User
from app.repositories.user_repo import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserRepository(session)

    async def upsert_user(
        self,
        *,
        tg_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
        ref_id: int | None = None,
    ) -> tuple[User, bool]:
        """Upsert a user by tg_id.

        Returns (user, created).
        """
        existing = await self.repo.get_by_tg_id(tg_id)
        if existing is None:
            user = await self.repo.create(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                ref_id=ref_id,
            )
            await business_log(
                self.session,
                level=LEVEL_INFO,
                event="user_registered",
                module="backend",
                user_id=user.id,
                message=f"User registered tg_id={tg_id}",
                context={"tg_id": tg_id, "username": username, "ref_id": ref_id},
            )
            return user, True

        # update mutable fields if changed
        changed = False
        for attr, value in (
            ("username", username),
            ("first_name", first_name),
            ("last_name", last_name),
            ("language_code", language_code),
        ):
            if value is not None and getattr(existing, attr) != value:
                setattr(existing, attr, value)
                changed = True
        if changed:
            await self.session.flush()
        return existing, False

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        return await self.repo.get_by_tg_id(tg_id)
