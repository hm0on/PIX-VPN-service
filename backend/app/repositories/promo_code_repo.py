"""PromoCode repository."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.promo_code import PromoCode


class PromoCodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_code(self, code: str) -> PromoCode | None:
        """Look up a promo code (case-insensitive).

        On Postgres `code` is CITEXT so the comparison is already
        case-insensitive. On SQLite (tests) we lower() both sides.
        """
        bind = self.session.get_bind()
        if bind is not None and bind.dialect.name == "sqlite":
            stmt = select(PromoCode).where(
                func.lower(PromoCode.code) == code.lower()
            )
        else:
            stmt = select(PromoCode).where(PromoCode.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, promo_id: int) -> PromoCode | None:
        result = await self.session.execute(
            select(PromoCode).where(PromoCode.id == promo_id)
        )
        return result.scalar_one_or_none()

    async def lock_for_update(self, promo_id: int) -> PromoCode | None:
        """SELECT ... FOR UPDATE on a promo_codes row (no-op on SQLite)."""
        bind = self.session.get_bind()
        stmt = select(PromoCode).where(PromoCode.id == promo_id)
        if bind is None or bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_activations(self, promo_id: int) -> None:
        """Atomically bump current_activations by 1."""
        await self.session.execute(
            update(PromoCode)
            .where(PromoCode.id == promo_id)
            .values(current_activations=PromoCode.current_activations + 1)
        )
        await self.session.flush()
