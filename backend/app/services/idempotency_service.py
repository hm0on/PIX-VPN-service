"""Idempotency-key persistence service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.idempotency_repo import IdempotencyKeyRepository


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = IdempotencyKeyRepository(session)

    async def get_or_set(
        self,
        *,
        key: str,
        operation: str,
        generator: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Return cached response for `key` or run `generator` and cache its result."""
        existing = await self.repo.get(key)
        if existing is not None and existing.response is not None:
            return existing.response

        # Reserve via INSERT ... ON CONFLICT DO NOTHING (or fallback for SQLite).
        if existing is None:
            inserted = await self.repo.reserve(key=key, operation=operation)
            if not inserted:
                # Lost a race; another worker is computing — re-fetch.
                row = await self.repo.get(key)
                if row is not None and row.response is not None:
                    return row.response
                # If still no response, fall through and recompute (caller's choice).

        response = await generator()
        await self.repo.store_response(key=key, response=response)
        return response
