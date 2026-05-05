"""NotificationSent repository.

Model (`NotificationSent`) lives in `app.db.models.notification_sent` — owned by
the Backend Promo agent. Lazy import to survive an in-flight migration.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _get_notification_sent_model() -> Any:
    from app.db.models.notification_sent import NotificationSent

    return NotificationSent


class NotificationSentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, user_id: int, subscription_id: int, kind: str
    ) -> Any | None:
        """Insert with `ON CONFLICT DO NOTHING` semantics on (subscription_id, kind).

        Returns the new row, or None if a duplicate already exists.
        """
        NotificationSent = _get_notification_sent_model()

        bind = self.session.get_bind()
        if bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = (
                pg_insert(NotificationSent.__table__)
                .values(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    kind=kind,
                )
                .on_conflict_do_nothing(
                    index_elements=["subscription_id", "kind"]
                )
                .returning(NotificationSent.__table__.c.id)
            )
            res = await self.session.execute(stmt)
            inserted_id = res.scalar()
            await self.session.flush()
            if inserted_id is None:
                return None
            row_res = await self.session.execute(
                select(NotificationSent).where(
                    NotificationSent.id == inserted_id
                )
            )
            return row_res.scalar_one_or_none()

        # SQLite (tests): try insert; on integrity error → already exists.
        row = NotificationSent(
            user_id=user_id,
            subscription_id=subscription_id,
            kind=kind,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return None
        return row

    async def exists(self, *, subscription_id: int, kind: str) -> bool:
        NotificationSent = _get_notification_sent_model()
        result = await self.session.execute(
            select(NotificationSent.id)
            .where(
                NotificationSent.subscription_id == subscription_id,
                NotificationSent.kind == kind,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
