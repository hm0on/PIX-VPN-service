"""Send "your subscription expires in 3 days" reminders.

Runs hourly (Stage 3 §7). The cron schedule is offset by 23 minutes in
``app.main.WorkerSettings`` so all hourly jobs don't fire at minute 0.

Algorithm
---------
1. ``SELECT`` active subscriptions whose ``expires_at`` falls inside the
   ``[now() + 2d23h, now() + 3d1h]`` window and that don't already have
   a ``notifications_sent(kind='expiry_3d')`` row.
2. For each row:
   a. ``INSERT INTO notifications_sent ... ON CONFLICT (subscription_id, kind)
      DO NOTHING RETURNING id`` — atomic one-shot guard. If RETURNING is
      empty another worker beat us to it: skip.
   b. Resolve the message text from the ``texts`` table
      (key ``subscription_expiring_3d``) with a hard-coded fallback if
      the row is missing.
   c. Insert an ``outbox`` row in the exact shape that
      :func:`app.tasks.outbox_dispatcher.outbox_dispatcher_task`
      expects (``message_type='text'``, ``payload`` with
      ``text``/``parse_mode``/``reply_markup``).
3. Emit a ``business_log`` line per sent notification so operators can
   audit.

The whole task is wrapped in a top-level try/except: a failed cron tick
must NEVER crash the worker (ARQ would crash-loop it).
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
_SELECT_EXPIRING_SQL = text(
    """
    SELECT s.id           AS subscription_id,
           s.user_id      AS user_id,
           u.tg_id        AS tg_id
      FROM subscriptions s
      JOIN users u ON u.id = s.user_id
     WHERE s.status = 'active'
       AND s.expires_at BETWEEN now() + interval '2 days 23 hours'
                            AND now() + interval '3 days 1 hour'
       AND NOT EXISTS (
             SELECT 1 FROM notifications_sent ns
              WHERE ns.subscription_id = s.id
                AND ns.kind = 'expiry_3d'
           )
     ORDER BY s.expires_at ASC
     LIMIT 500
    """
)

# Atomic one-shot guard: only one worker wins the row, the rest get NULL.
_INSERT_NOTIFICATION_SQL = text(
    """
    INSERT INTO notifications_sent (user_id, subscription_id, kind, sent_at)
    VALUES (:user_id, :subscription_id, 'expiry_3d', now())
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

_TEXT_KEY = "subscription_expiring_3d"


def _fallback_text(subscription_id: int) -> str:
    return (
        f"⚠️ Ваша подписка <b>#{subscription_id}</b> "
        f"закончится через <b>3 дня</b>."
    )


def _build_reply_markup(subscription_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Продлить", "callback_data": f"extend:{subscription_id}"}]
        ]
    }


async def notify_expiring_subscriptions_task(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ cron entrypoint."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.notify_expiring")

    counters = {"candidates": 0, "sent": 0, "skipped": 0}

    try:
        async with session_factory() as session, session.begin():
            rows = (await session.execute(_SELECT_EXPIRING_SQL)).all()
            counters["candidates"] = len(rows)
            if not rows:
                log.debug("notify_expiring_no_op")
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
                    # Another worker raced us — skip silently.
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
        log.warning("notify_expiring_db_error", error=str(exc))
        return counters

    if counters["sent"]:
        await business_log(
            api_client,
            level="INFO",
            event="notification_expiry_3d_sent",
            module="worker.notify_expiring",
            message=f"Queued {counters['sent']} expiry-3d reminder(s)",
            context=counters,
        )
    return counters


async def _resolve_template(session: AsyncSession) -> str | None:
    """Fetch ``texts.value_html`` for ``subscription_expiring_3d`` (or None)."""
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
        # texts table missing or other DB hiccup — let caller fall back.
        return None


def _json_dumps(value: Any) -> str:
    """Serialise to JSON for the asyncpg ``jsonb`` cast."""
    import json

    return json.dumps(value, ensure_ascii=False)


__all__ = ["notify_expiring_subscriptions_task"]
