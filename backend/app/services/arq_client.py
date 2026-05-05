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
        database=settings.redis_database,
    )
    try:
        _pool = await create_pool(redis_settings)
    except Exception as e:  # noqa: BLE001
        logger.warning("arq_pool_create_failed", error=str(e))
        return None
    return _pool


async def enqueue(function_name: str, *args: Any, **kwargs: Any) -> bool:
    """Push a job onto the worker's ARQ queue. Returns True on success.

    We explicitly pin ``_queue_name`` to ``settings.arq_queue_name`` so the
    job lands on the same queue the worker actually polls. ARQ defaults to
    ``arq:queue`` when ``_queue_name`` is omitted, which silently swallows
    jobs whenever the worker is configured with a non-default queue
    (``WorkerSettings.queue_name``). The caller can still override by
    passing ``_queue_name`` explicitly via ``kwargs``.
    """
    pool = await _get_pool()
    if pool is None:
        return False
    settings = get_settings()
    kwargs.setdefault("_queue_name", settings.arq_queue_name)
    try:
        await pool.enqueue_job(function_name, *args, **kwargs)
        logger.info(
            "arq_enqueued",
            function=function_name,
            queue=kwargs["_queue_name"],
        )
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
