"""Subscription service — read paths."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.subscription import Subscription
from app.repositories.subscription_repo import SubscriptionRepository


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SubscriptionRepository(session)

    async def get_user_subscriptions(
        self, *, user_id: int, recently_expired_days: int = 30
    ) -> list[Subscription]:
        return await self.repo.list_for_user(
            user_id=user_id,
            recently_expired_days=recently_expired_days,
        )

    async def get_subscription_detail(
        self, *, subscription_id: int, user_id: int
    ) -> Subscription | None:
        return await self.repo.get_owned(
            subscription_id=subscription_id, user_id=user_id
        )
