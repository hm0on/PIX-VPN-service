"""PromoActivation repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.promo_activation import PromoActivation


class PromoActivationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **fields: Any) -> PromoActivation:
        row = PromoActivation(**fields)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def count_user_activations(
        self, *, promo_id: int, user_id: int
    ) -> int:
        stmt = select(func.count(PromoActivation.id)).where(
            PromoActivation.promo_id == promo_id,
            PromoActivation.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def list_for_promo(self, promo_id: int) -> list[PromoActivation]:
        stmt = (
            select(PromoActivation)
            .where(PromoActivation.promo_id == promo_id)
            .order_by(PromoActivation.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
