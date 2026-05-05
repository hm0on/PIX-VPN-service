"""Best-effort ARQ enqueue helper used by admin endpoints.

The backend uses arq's ``ArqRedis`` to push jobs onto the worker's queue.
Failures (arq missing, redis unreachable) are logged and returned as
``False`` — the caller decides whether to abort the request. In tests we
simply skip enqueueing entirely.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger("arq_client")

_pool: Any | None = None


async def _get_pool() -> Any | None:
    global _pool
    if _pool is not None:
        return _pool
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
    except ImportError:  # pragma: no cover — arq optional in some envs
        logger.warning("arq_not_installed")
        return None

    settings = get_settings()
    redis_settings = RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        database=0,
    )
    try:
        _pool = await create_pool(redis_settings)
    except Exception as e:  # noqa: BLE001
        logger.warning("arq_pool_create_failed", error=str(e))
        return None
    return _pool


async def enqueue(function_name: str, *args: Any, **kwargs: Any) -> bool:
    """Push a job onto the default ARQ queue. Returns True on success."""
    pool = await _get_pool()
    if pool is None:
        return False
    try:
        await pool.enqueue_job(function_name, *args, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "arq_enqueue_failed", function=function_name, error=str(e)
        )
        return False


async def close_pool() -> None:
    global _pool
    if _pool is None:
        return
    try:
        await _pool.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("arq_pool_aclose_failed", error=str(exc))
    _pool = None
