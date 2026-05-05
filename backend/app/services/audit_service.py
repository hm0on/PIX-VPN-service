"""Admin audit helper.

Writes a `Log(event='admin_action', module='admin', ...)` row capturing who did what.
Caller is responsible for the surrounding transaction (commit/rollback).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LEVEL_INFO, business_log
from app.deps import AdminPrincipal


async def record_admin_action(
    session: AsyncSession,
    admin: AdminPrincipal,
    action: str,
    *,
    target_user_id: int | None = None,
    target_subscription_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist an `admin_action` business-log row.

    Args:
        session: active AsyncSession
        admin: decoded JWT principal (kid + label)
        action: short slug, e.g. ``user.ban`` / ``subscription.deactivate``
        target_user_id: user_id the action targets (also written to logs.user_id)
        target_subscription_id: subscription_id the action targets (in context)
        extra: additional context fields
    """
    context: dict[str, Any] = {
        "admin_key_id": admin.kid,
        "admin_key_label": admin.label,
        "action": action,
    }
    if target_subscription_id is not None:
        context["target_subscription_id"] = target_subscription_id
    if target_user_id is not None:
        context["target_user_id"] = target_user_id
    if extra:
        context.update(extra)

    await business_log(
        session,
        level=LEVEL_INFO,
        event="admin_action",
        module="admin",
        user_id=target_user_id,
        message=action,
        context=context,
    )
