"""Structlog configuration and helpers for business / technical logging."""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

# Context for trace_id (propagated through requests / async tasks).
_trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id", default=None)


def get_trace_id() -> str:
    """Return current trace id, generating a new one if missing."""
    value = _trace_id_ctx.get()
    if value is None:
        value = str(uuid.uuid4())
        _trace_id_ctx.set(value)
    return value


def set_trace_id(value: str | None) -> None:
    _trace_id_ctx.set(value)


def new_trace_id() -> str:
    value = str(uuid.uuid4())
    _trace_id_ctx.set(value)
    return value


def _add_trace_id(_logger: object, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    tid = _trace_id_ctx.get()
    if tid is not None and "trace_id" not in event_dict:
        event_dict["trace_id"] = tid
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog and stdlib logging to emit JSON to stdout."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# DB log helpers — synchronous on Stage 1 (same transaction).
# Imports are local to avoid circular imports with models.
# ---------------------------------------------------------------------------

LEVEL_INFO = 0
LEVEL_WARNING = 1
LEVEL_CRITICAL = 2


async def business_log(
    session: AsyncSession,
    *,
    level: int = LEVEL_INFO,
    event: str,
    module: str = "backend",
    user_id: int | None = None,
    message: str = "",
    context: dict[str, Any] | None = None,
) -> None:
    """Persist a business log row to `logs` table.

    LEVEL_CRITICAL events additionally trigger a Telegram alert to the
    admin (``settings.admin_tg_id``) via the existing outbox pipeline.
    Wiring this into ``business_log`` itself means every current and
    future critical site — payment failures, free-trial failures, balance
    refund inconsistencies, etc. — gets an admin ping for free, without
    touching the 7+ existing call sites. See
    ``app.services.admin_alert_service`` for the alert plumbing.
    """
    from app.db.models.log import Log

    row = Log(
        level=level,
        event=event,
        module=module,
        user_id=user_id,
        message=message,
        context=context,
    )
    session.add(row)
    await session.flush()
    get_logger("business").info(
        event,
        module=module,
        level=level,
        user_id=user_id,
        message=message,
        context=context,
    )

    if level >= LEVEL_CRITICAL:
        # Local import to avoid an import cycle: admin_alert_service
        # imports config + outbox model, both of which transitively
        # depend on this module at startup. Lazy import keeps the
        # dependency graph one-way.
        from app.services.admin_alert_service import send_admin_alert

        # Dedup by event name so a storm of identical criticals
        # (e.g. 30 ``vpn_provider_failed_after_payment`` during a
        # provider outage) collapses into a single Telegram ping per
        # 10-minute window. Distinct event types still alert independently.
        details: dict[str, Any] = {"event": event}
        if user_id is not None:
            details["user_id"] = user_id
        if context:
            # Promote a few interesting keys to the summary line; the
            # full context is in the logs table for forensics anyway.
            for key in (
                "subscription_id",
                "payment_id",
                "provider_subscription_id",
                "error_code",
                "amount_kopecks",
            ):
                if key in context and context[key] is not None:
                    details[key] = context[key]
        await send_admin_alert(
            session,
            level="CRIT",
            summary=message or event,
            details=details,
            dedup_key=f"business:{event}",
        )


async def tech_log(
    session: AsyncSession,
    *,
    service: str = "backend",
    action: str,
    user_id: int | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    trace_id: str | None = None,
) -> None:
    """Persist a technical log row to `tech_logs` table."""
    from app.db.models.log import TechLog

    row = TechLog(
        trace_id=trace_id or get_trace_id(),
        service=service,
        action=action,
        user_id=user_id,
        payload=payload,
        duration_ms=duration_ms,
    )
    session.add(row)
    await session.flush()
