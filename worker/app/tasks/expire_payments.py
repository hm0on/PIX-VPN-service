"""Mark stale ``pending`` payments as expired (and cascade to subscription).

Runs every 5 minutes. Operates directly against Postgres via the worker's
SQLAlchemy session factory — this is pure maintenance with no business
logic that needs to live in Backend.

SQL plan
--------
1. ``UPDATE payments SET status='expired', updated_at=now()
    WHERE status='pending' AND created_at < now() - INTERVAL ':ttl minutes'
    RETURNING id, subscription_id``
2. For each row that has a ``subscription_id`` we flip the matching
   ``subscriptions`` row from ``pending`` to ``failed`` (only if it's
   still pending — never overwrite an already active/failed sub).
3. Emit a ``business_log`` entry with the expired count and ids.

The whole thing runs in a single transaction so that a partial crash
doesn't leave subscriptions in an inconsistent state.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import BigInteger, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.logging_setup import get_logger
from app.tasks.common import business_log

_EXPIRE_PAYMENTS_SQL = text(
    """
    UPDATE payments
       SET status = 'expired',
           updated_at = now()
     WHERE status = 'pending'
       AND created_at < now() - make_interval(mins => :ttl_minutes)
    RETURNING id, subscription_id
    """
)

_FAIL_SUBSCRIPTIONS_SQL = text(
    """
    UPDATE subscriptions
       SET status = 'failed',
           updated_at = now()
     WHERE status = 'pending'
       AND id = ANY(:subscription_ids)
    RETURNING id
    """
).bindparams(bindparam("subscription_ids", type_=ARRAY(BigInteger)))


async def expire_pending_payments_task(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ cron entrypoint."""
    settings: Settings = ctx["settings"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.expire_payments")

    counters = {"payments_expired": 0, "subscriptions_failed": 0}

    try:
        async with session_factory() as session, session.begin():
            payment_ids, subscription_ids = await _expire_payments(
                session, settings.payment_pending_ttl_minutes
            )
            counters["payments_expired"] = len(payment_ids)

            failed_sub_ids: list[int] = []
            if subscription_ids:
                failed_sub_ids = await _fail_subscriptions(session, subscription_ids)
                counters["subscriptions_failed"] = len(failed_sub_ids)
    except Exception as exc:  # pragma: no cover — defensive guard
        log.error("expire_pending_payments_db_error", error=str(exc))
        return counters

    if counters["payments_expired"] == 0:
        log.debug("expire_pending_payments_no_op")
        return counters

    await business_log(
        api_client,
        level="INFO",
        event="pending_payment_expired",
        module="worker.expire_payments",
        message=f"Expired {counters['payments_expired']} pending payment(s)",
        context={
            "count": counters["payments_expired"],
            "payment_ids": payment_ids,
            "subscriptions_failed": counters["subscriptions_failed"],
            "ttl_minutes": settings.payment_pending_ttl_minutes,
        },
    )
    return counters


async def _expire_payments(
    session: AsyncSession, ttl_minutes: int
) -> tuple[list[int], list[int]]:
    """Run the UPDATE...RETURNING and split the result into two lists."""
    result = await session.execute(
        _EXPIRE_PAYMENTS_SQL, {"ttl_minutes": ttl_minutes}
    )
    rows = result.all()
    payment_ids = [int(row.id) for row in rows]
    subscription_ids = [
        int(row.subscription_id) for row in rows if row.subscription_id is not None
    ]
    return payment_ids, subscription_ids


async def _fail_subscriptions(
    session: AsyncSession, subscription_ids: list[int]
) -> list[int]:
    """Cascade-fail any still-pending subscriptions tied to expired payments."""
    if not subscription_ids:
        return []
    result = await session.execute(
        _FAIL_SUBSCRIPTIONS_SQL, {"subscription_ids": subscription_ids}
    )
    return [int(row.id) for row in result.all()]


__all__ = ["expire_pending_payments_task"]
