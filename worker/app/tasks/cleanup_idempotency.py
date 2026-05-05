"""Drop expired ``idempotency_keys`` rows.

Runs hourly. The TTL is configurable via ``IDEMPOTENCY_KEYS_TTL_HOURS``
(default 24h, matching the Stage 2 spec).
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.logging_setup import get_logger
from app.tasks.common import business_log

_DELETE_SQL = text(
    """
    DELETE FROM idempotency_keys
     WHERE created_at < now() - make_interval(hours => :ttl_hours)
    """
)


async def cleanup_idempotency_keys_task(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ cron entrypoint."""
    settings: Settings = ctx["settings"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.cleanup_idempotency")

    deleted = 0
    try:
        async with session_factory() as session, session.begin():
            result = await session.execute(
                _DELETE_SQL, {"ttl_hours": settings.idempotency_keys_ttl_hours}
            )
            # ``rowcount`` is -1 if the driver can't report it; clamp to 0.
            deleted = max(int(result.rowcount or 0), 0)
    except Exception as exc:  # pragma: no cover — defensive guard
        log.error("cleanup_idempotency_db_error", error=str(exc))
        return {"deleted": 0}

    if deleted == 0:
        log.debug("cleanup_idempotency_no_op")
        return {"deleted": 0}

    await business_log(
        api_client,
        level="INFO",
        event="idempotency_keys_cleaned",
        module="worker.cleanup_idempotency",
        message=f"Deleted {deleted} stale idempotency key(s)",
        context={
            "deleted": deleted,
            "ttl_hours": settings.idempotency_keys_ttl_hours,
        },
    )
    return {"deleted": deleted}


__all__ = ["cleanup_idempotency_keys_task"]
