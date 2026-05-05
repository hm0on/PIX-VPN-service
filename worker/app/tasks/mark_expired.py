"""Flip ``active`` subscriptions whose ``expires_at`` is in the past.

Runs hourly (Stage 3 §7) at minute 43 to spread cron load.

We do NOT call ``northline.deactivate_key`` — per the project spec the
provider deactivates expired keys on its own. This task only updates
local state so admins/users see the correct status. The follow-up
``notify_expired_subscriptions_task`` runs at minute 53 and picks up
the freshly-expired rows.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging_setup import get_logger
from app.tasks.common import business_log

_MARK_EXPIRED_SQL = text(
    """
    WITH updated AS (
      UPDATE subscriptions
         SET status = 'expired',
             updated_at = now()
       WHERE status = 'active'
         AND expires_at < now()
       RETURNING id, user_id
    )
    SELECT id, user_id FROM updated
    """
)


async def mark_expired_subscriptions_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ cron entrypoint."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.mark_expired")

    expired_ids: list[int] = []
    user_ids: list[int] = []

    try:
        async with session_factory() as session, session.begin():
            rows = (await session.execute(_MARK_EXPIRED_SQL)).all()
            expired_ids = [int(r.id) for r in rows]
            user_ids = [int(r.user_id) for r in rows]
    except Exception as exc:  # pragma: no cover — defensive guard
        log.warning("mark_expired_db_error", error=str(exc))
        return {"expired": 0}

    if not expired_ids:
        log.debug("mark_expired_no_op")
        return {"expired": 0}

    await business_log(
        api_client,
        level="INFO",
        event="subscriptions_marked_expired",
        module="worker.mark_expired",
        message=f"Marked {len(expired_ids)} subscription(s) as expired",
        context={
            "count": len(expired_ids),
            "subscription_ids": expired_ids,
            "user_ids": user_ids,
        },
    )

    # We deliberately do NOT enqueue notifications here — the dedicated
    # ``notify_expired_subscriptions_task`` runs 10 minutes later and
    # picks them up via ``notifications_sent`` UNIQUE guard. This keeps
    # responsibilities separated and tasks individually testable.
    return {"expired": len(expired_ids)}


__all__ = ["mark_expired_subscriptions_task"]
