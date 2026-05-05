"""Referral repository.

Models (`Referral`) live in `app.db.models.referral` — owned by the Backend Promo
agent. We import lazily to keep this module importable even if the migration
hasn't been applied yet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.balance_transaction import (
    BT_REASON_REFERRAL_BONUS,
    BalanceTransaction,
)


def _get_referral_model() -> Any:
    from app.db.models.referral import Referral

    return Referral


class ReferralRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, referrer_id: int, referee_id: int) -> Any:
        Referral = _get_referral_model()
        row = Referral(
            referrer_id=referrer_id,
            referee_id=referee_id,
            bonus_paid=False,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_by_referee(self, referee_id: int) -> Any | None:
        Referral = _get_referral_model()
        result = await self.session.execute(
            select(Referral).where(Referral.referee_id == referee_id)
        )
        return result.scalar_one_or_none()

    async def mark_bonus_paid(
        self, *, referral_id: int, payment_id: int
    ) -> Any | None:
        Referral = _get_referral_model()
        result = await self.session.execute(
            select(Referral).where(Referral.id == referral_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.bonus_paid = True
        row.bonus_paid_at = datetime.now(tz=timezone.utc)
        row.referee_first_purchase_id = payment_id
        await self.session.flush()
        return row

    async def count_referrals(self, referrer_id: int) -> int:
        Referral = _get_referral_model()
        result = await self.session.execute(
            select(func.count(Referral.id)).where(
                Referral.referrer_id == referrer_id
            )
        )
        return int(result.scalar_one() or 0)

    async def sum_earned(self, referrer_id: int) -> int:
        """Sum of BalanceTransaction(reason='referral_bonus') for the referrer."""
        result = await self.session.execute(
            select(func.coalesce(func.sum(BalanceTransaction.amount_kopecks), 0))
            .where(
                BalanceTransaction.user_id == referrer_id,
                BalanceTransaction.reason == BT_REASON_REFERRAL_BONUS,
            )
        )
        return int(result.scalar_one() or 0)
