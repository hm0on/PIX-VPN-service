"""Structured logging via structlog with trace_id propagation.

Provides:
- ``configure_logging`` — must be called once at startup.
- ``get_logger`` — module-level logger getter.
- ``trace_id_var`` — ContextVar holding current trace_id (set by middlewares).
- ``bot_log`` — helper that logs locally AND forwards business events to Backend API.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.api_client import BackendClient


# trace_id for the current Update — set by TraceMiddleware, read by structlog processor.
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)


def _add_trace_id(_logger: object, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    trace_id = trace_id_var.get()
    if trace_id is not None:
        event_dict.setdefault("trace_id", trace_id)
    user_id = user_id_var.get()
    if user_id is not None:
        event_dict.setdefault("user_id", user_id)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib + structlog. Idempotent."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]


# Levels for the Backend `logs` table: 0=info, 1=warning, 2=critical.
LOG_LEVEL_INFO = 0
LOG_LEVEL_WARNING = 1
LOG_LEVEL_CRITICAL = 2


async def bot_log(
    api: BackendClient | None,
    *,
    level: int,
    event: str,
    user_id: int | None = None,
    message: str = "",
    context: dict[str, Any] | None = None,
) -> None:
    """Emit a business log: stdout (always) + Backend `/api/bot/logs` (best-effort).

    Failures to deliver to backend never raise — we log a local warning instead.
    """
    log = get_logger("bot.business")
    # `event` is passed positionally to log.<level>(), so it must NOT also live
    # in **payload — otherwise structlog raises
    # "got multiple values for argument 'event'".
    payload: dict[str, Any] = {
        "level": level,
        "user_id": user_id,
        "context": context or {},
    }

    if level >= LOG_LEVEL_CRITICAL:
        log.critical(event, message=message, **payload)
    elif level >= LOG_LEVEL_WARNING:
        log.warning(event, message=message, **payload)
    else:
        log.info(event, message=message, **payload)

    if api is None:
        return

    try:
        await api.log(
            level=level,
            event=event,
            user_id=user_id,
            message=message,
            context=context or {},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, must never raise.
        log.warning("bot_log.backend_delivery_failed", error=str(exc))
