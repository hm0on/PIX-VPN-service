"""Idempotency key repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.idempotency_key import IdempotencyKey


class IdempotencyKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> IdempotencyKey | None:
        result = await self.session.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == key)
        )
        return result.scalar_one_or_none()

    async def reserve(self, *, key: str, operation: str) -> bool:
        """Insert a placeholder row. Returns True if inserted, False on conflict."""
        dialect = self.session.bind.dialect.name if self.session.bind else "postgresql"

        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = (
                pg_insert(IdempotencyKey)
                .values(key=key, operation=operation, response=None)
                .on_conflict_do_nothing(index_elements=["key"])
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return bool(result.rowcount)

        # SQLite / fallback: pre-check + insert (best-effort, no race protection).
        existing = await self.get(key)
        if existing is not None:
            return False
        await self.session.execute(
            insert(IdempotencyKey).values(
                key=key, operation=operation, response=None
            )
        )
        await self.session.flush()
        return True

    async def store_response(
        self, *, key: str, response: dict[str, Any]
    ) -> None:
        existing = await self.get(key)
        if existing is not None:
            existing.response = response
            await self.session.flush()
