"""Tariff repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.tariff import Tariff, TariffDuration


class TariffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Tariff]:
        result = await self.session.execute(
            select(Tariff)
            .where(Tariff.is_active.is_(True))
            .options(selectinload(Tariff.durations))
            .order_by(Tariff.sort_order)
        )
        return list(result.scalars().unique().all())

    async def get_by_code(self, code: str) -> Tariff | None:
        result = await self.session.execute(
            select(Tariff)
            .where(Tariff.code == code)
            .options(selectinload(Tariff.durations))
        )
        return result.scalar_one_or_none()

    async def get_duration(self, tariff_id: int, days: int) -> TariffDuration | None:
        result = await self.session.execute(
            select(TariffDuration).where(
                TariffDuration.tariff_id == tariff_id,
                TariffDuration.days == days,
            )
        )
        return result.scalar_one_or_none()
