"""Subscription repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_EXPIRED,
    Subscription,
)


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **fields: Any) -> Subscription:
        sub = Subscription(**fields)
        self.session.add(sub)
        await self.session.flush()
        await self.session.refresh(sub)
        return sub

    async def get_by_id(self, subscription_id: int) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        return result.scalar_one_or_none()

    async def get_owned(
        self, *, subscription_id: int, user_id: int
    ) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: int,
        recently_expired_days: int = 30,
    ) -> list[Subscription]:
        """Active + recently expired/deactivated subscriptions for the user."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=recently_expired_days)
        result = await self.session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                (
                    (Subscription.status == SUB_STATUS_ACTIVE)
                    | (
                        (Subscription.status == SUB_STATUS_EXPIRED)
                        & (Subscription.updated_at >= cutoff)
                    )
                ),
            )
            .order_by(Subscription.created_at.desc())
        )
        return list(result.scalars().all())

    async def has_free_trial(self, *, user_id: int) -> bool:
        result = await self.session.execute(
            select(Subscription.id)
            .where(
                Subscription.user_id == user_id,
                Subscription.is_free_trial.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def update_fields(
        self, sub: Subscription, **fields: Any
    ) -> Subscription:
        for k, v in fields.items():
            setattr(sub, k, v)
        await self.session.flush()
        return sub
