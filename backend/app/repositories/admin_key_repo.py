"""AdminKey repository."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.admin_key import AdminKey


class AdminKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[AdminKey]:
        result = await self.session.execute(
            select(AdminKey).order_by(AdminKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_usable(self, *, now: datetime | None = None) -> list[AdminKey]:
        """Return keys that can still be used to authenticate.

        Conditions: revoked_at IS NULL OR valid_until > now.
        """
        now = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            select(AdminKey).where(
                or_(
                    AdminKey.revoked_at.is_(None),
                    AdminKey.valid_until > now,
                )
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, key_id: int) -> AdminKey | None:
        result = await self.session.execute(select(AdminKey).where(AdminKey.id == key_id))
        return result.scalar_one_or_none()

    async def add(self, *, key_hash: str, label: str) -> AdminKey:
        row = AdminKey(key_hash=key_hash, label=label)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def revoke(
        self,
        key: AdminKey,
        *,
        valid_until: datetime | None,
        now: datetime | None = None,
    ) -> AdminKey:
        key.revoked_at = now or datetime.now(timezone.utc)
        key.valid_until = valid_until
        await self.session.flush()
        return key

    async def count_usable(self) -> int:
        keys = await self.list_usable()
        return len(keys)
