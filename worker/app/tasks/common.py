"""Shared helpers for worker tasks.

Currently only contains :func:`business_log`, a fire-and-forget helper that
mirrors a structured business event into the backend's ``logs`` table via
``POST /api/bot/logs``. It also emits the same payload to structlog so we
keep useful information in stdout even if the backend is down.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.logging_setup import get_logger

_LOG_ENDPOINT = "/api/bot/logs"

_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


async def business_log(
    api_client: httpx.AsyncClient,
    *,
    level: str,
    event: str,
    module: str,
    message: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Post a structured log entry to Backend, never raising on failure.

    The worker is also expected to log via structlog at the same level so
    that operators can debug from stdout when the backend is unreachable.
    """
    log_level = level.upper() if level.upper() in _VALID_LEVELS else "INFO"
    payload: dict[str, Any] = {
        "level": log_level,
        "event": event,
        "module": module,
        "message": message or event,
        "context": context or {},
    }

    log = get_logger(module)
    log_method = getattr(log, log_level.lower(), log.info)
    log_method(event, **(context or {}))

    try:
        response = await api_client.post(_LOG_ENDPOINT, json=payload)
    except httpx.HTTPError as exc:
        log.warning("business_log_post_failed", event=event, error=str(exc))
        return

    if response.status_code >= 400:
        # 404 is expected if the backend doesn't expose /logs yet — degrade
        # gracefully and keep the structlog record as the source of truth.
        log.debug(
            "business_log_endpoint_rejected",
            event=event,
            status=response.status_code,
        )
