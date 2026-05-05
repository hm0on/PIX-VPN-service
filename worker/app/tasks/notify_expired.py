"""Send "your subscription has expired" notifications.

Runs hourly (Stage 3 §7) at minute 53 — 10 minutes after
``mark_expired_subscriptions_task`` so we always notify on the same
hour the rows flipped to ``expired``.

Algorithm mirrors :mod:`app.tasks.notify_expiring`:

1. ``SELECT`` recently-expired subscriptions (``status='expired'`` and
   ``expires_at >= now() - interval '2 hours'``) that don't yet have an
   ``expired`` notification recorded.
2. Insert a guard row in ``notifications_sent`` with
   ``ON CONFLICT DO NOTHING RETURNING id`` for atomic one-shot.
3. Insert an ``outbox`` row in the dispatcher's expected payload
   shape with two inline buttons: "Продлить" (extend the expired sub)
   and "Купить новую" (back to catalog).
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging_setup import get_logger
from app.tasks.common import business_log

# --------------------------------------------------------------------- #
# SQL
# --------------------------------------------------------------------- #
_SELECT_EXPIRED_SQL = text(
    """
    SELECT s.id           AS subscription_id,
           s.user_id      AS user_id,
           u.tg_id        AS tg_id
      FROM subscriptions s
      JOIN users u ON u.id = s.user_id
     WHERE s.status = 'expired'
       AND s.expires_at >= now() - interval '2 hours'
       AND NOT EXISTS (
             SELECT 1 FROM notifications_sent ns
              WHERE ns.subscription_id = s.id
                AND ns.kind = 'expired'
           )
     ORDER BY s.expires_at ASC
     LIMIT 500
    """
)

_INSERT_NOTIFICATION_SQL = text(
    """
    INSERT INTO notifications_sent (user_id, subscription_id, kind, sent_at)
    VALUES (:user_id, :subscription_id, 'expired', now())
    ON CONFLICT (subscription_id, kind) DO NOTHING
    RETURNING id
    """
)

_SELECT_TEXT_SQL = text(
    """
    SELECT value_html FROM texts WHERE key = :key LIMIT 1
    """
)

_INSERT_OUTBOX_SQL = text(
    """
    INSERT INTO outbox (
        user_id, chat_id, message_type, payload, status, attempts,
        send_after, created_at
    )
    VALUES (
        :user_id, :chat_id, 'text', CAST(:payload AS jsonb), 'pending', 0,
        now(), now()
    )
    RETURNING id
    """
)

_TEXT_KEY = "subscription_expired"


def _fallback_text(subscription_id: int) -> str:
    return (
        f"❌ Ваша подписка <b>#{subscription_id}</b> истекла. "
        f"Продлите её или оформите новую."
    )


def _build_reply_markup(subscription_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Продлить", "callback_data": f"extend:{subscription_id}"}],
            [{"text": "Купить новую", "callback_data": "catalog"}],
        ]
    }


async def notify_expired_subscriptions_task(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ cron entrypoint."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.notify_expired")

    counters = {"candidates": 0, "sent": 0, "skipped": 0}

    try:
        async with session_factory() as session, session.begin():
            rows = (await session.execute(_SELECT_EXPIRED_SQL)).all()
            counters["candidates"] = len(rows)
            if not rows:
                log.debug("notify_expired_no_op")
                return counters

            template = await _resolve_template(session)

            for row in rows:
                inserted = await session.execute(
                    _INSERT_NOTIFICATION_SQL,
                    {
                        "user_id": int(row.user_id),
                        "subscription_id": int(row.subscription_id),
                    },
                )
                if inserted.scalar() is None:
                    counters["skipped"] += 1
                    continue

                msg_text = (
                    template if template else _fallback_text(int(row.subscription_id))
                )
                payload = {
                    "text": msg_text,
                    "parse_mode": "HTML",
                    "reply_markup": _build_reply_markup(int(row.subscription_id)),
                    "context": {"subscription_id": int(row.subscription_id)},
                }
                await session.execute(
                    _INSERT_OUTBOX_SQL,
                    {
                        "user_id": int(row.user_id),
                        "chat_id": int(row.tg_id),
                        "payload": _json_dumps(payload),
                    },
                )
                counters["sent"] += 1
    except Exception as exc:  # pragma: no cover — defensive guard
        log.warning("notify_expired_db_error", error=str(exc))
        return counters

    if counters["sent"]:
        await business_log(
            api_client,
            level="INFO",
            event="notification_expired_sent",
            module="worker.notify_expired",
            message=f"Queued {counters['sent']} expired-subscription notice(s)",
            context=counters,
        )
    return counters


async def _resolve_template(session: AsyncSession) -> str | None:
    try:
        result = await session.execute(_SELECT_TEXT_SQL, {"key": _TEXT_KEY})
        row = result.first()
        if row is None:
            return None
        value = row.value_html
        if isinstance(value, str) and value.strip():
            return value
        return None
    except Exception:
        return None


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


__all__ = ["notify_expired_subscriptions_task"]
