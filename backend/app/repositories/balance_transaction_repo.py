"""BalanceTransaction repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.balance_transaction import BalanceTransaction


class BalanceTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **fields: Any) -> BalanceTransaction:
        row = BalanceTransaction(**fields)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row
