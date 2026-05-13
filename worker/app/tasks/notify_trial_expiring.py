"""Send "your FREE trial expires in 24 hours" reminders.

Conversion-pack 2026-05-13. Distinct from ``notify_expiring`` (which fires
at -3 days for *paid* subscriptions) — trial lifetime is only 5 days, so a
-3d window would land at trial creation time, and the -3d/--1d ladder
mostly delivers value for paid renewals. The trial path needs its own
single-shot reminder at -24h with one of two messages:

- **No prior auto-discount** (user did NOT come via a referral link): we
  mint a personal ``TRIAL15_<sub_id>`` promo-code (15% off, valid 72h) and
  include it in the DM via ``trial_expiring_with_promo`` text key.
- **Has auto-discount** (user IS a referee with the lifetime 15%
  referral discount): they already get -15% by default, so a fresh promo
  would be wasteful (also can't stack). We send the no-promo variant
  ``trial_expiring_no_promo`` so they get the urgency nudge but not a
  duplicate offer.

Idempotency
-----------
- ``notifications_sent (subscription_id, kind='trial_expiring_24h')`` is
  UNIQUE; the ``ON CONFLICT DO NOTHING RETURNING id`` is the atomic guard.
- Promo code ``TRIAL15_<sub_id>`` is deterministic + UNIQUE on
  ``promo_codes.code``; ``ON CONFLICT DO NOTHING`` protects against retries.

The whole task is wrapped in a top-level try/except so a cron-tick failure
does not crash the worker.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging_setup import get_logger
from app.tasks.common import business_log

# --------------------------------------------------------------------- #
# SQL
# --------------------------------------------------------------------- #
_SELECT_EXPIRING_TRIALS_SQL = text(
    """
    SELECT s.id           AS subscription_id,
           s.user_id      AS user_id,
           u.tg_id        AS tg_id
      FROM subscriptions s
      JOIN users u ON u.id = s.user_id
     WHERE s.is_free_trial = TRUE
       AND s.status = 'active'
       AND s.expires_at BETWEEN now() + interval '23 hours'
                            AND now() + interval '25 hours'
       AND NOT EXISTS (
             SELECT 1 FROM notifications_sent ns
              WHERE ns.subscription_id = s.id
                AND ns.kind = 'trial_expiring_24h'
           )
     ORDER BY s.expires_at ASC
     LIMIT 500
    """
)

_INSERT_NOTIFICATION_SQL = text(
    """
    INSERT INTO notifications_sent (user_id, subscription_id, kind, sent_at)
    VALUES (:user_id, :subscription_id, 'trial_expiring_24h', now())
    ON CONFLICT (subscription_id, kind) DO NOTHING
    RETURNING id
    """
)

# True ⇔ user is a referee whose first paid subscription hasn't happened
# yet (i.e. still entitled to the auto-discount via referral_service).
# Mirrors ``auto_discount_for_referee`` in the backend.
_HAS_AUTO_DISCOUNT_SQL = text(
    """
    SELECT EXISTS (
             SELECT 1 FROM referrals r WHERE r.referee_id = :user_id
           )
       AND NOT EXISTS (
             SELECT 1 FROM payments p
              WHERE p.user_id = :user_id
                AND p.status = 'paid'
                AND p.amount_kopecks > 0
           ) AS has_auto_discount
    """
)

# Personal 15% promo for users WITHOUT auto-discount. We use the constants
# from ``app.db.models.promo_code`` implicitly: type='discount_percent',
# max_total_activations=1, max_per_user=1, valid_until=now()+72h.
_INSERT_PROMO_SQL = text(
    """
    INSERT INTO promo_codes (
        code, type, value, max_total_activations, max_per_user,
        current_activations, valid_from, valid_until, is_active,
        description, user_id, created_at
    )
    VALUES (
        :code, 'discount_percent', 15, 1, 1, 0,
        now(), now() + interval '72 hours', TRUE,
        :description, :user_id, now()
    )
    ON CONFLICT (code) DO NOTHING
    RETURNING id
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


async def notify_trial_expiring_subscriptions_task(
    ctx: dict[str, Any],
) -> dict[str, int]:
    """ARQ cron entrypoint — runs hourly at minute 37."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.notify_trial_expiring")

    counters = {
        "candidates": 0,
        "sent_with_promo": 0,
        "sent_no_promo": 0,
        "skipped": 0,
    }

    try:
        async with session_factory() as session, session.begin():
            rows = (await session.execute(_SELECT_EXPIRING_TRIALS_SQL)).all()
            counters["candidates"] = len(rows)
            if not rows:
                log.debug("notify_trial_expiring_no_op")
                return counters

            for row in rows:
                sub_id = int(row.subscription_id)
                user_id = int(row.user_id)
                tg_id = int(row.tg_id)

                # 1. Atomic guard — if another worker already claimed this
                # (subscription_id, kind), the RETURNING is empty and we skip.
                inserted = await session.execute(
                    _INSERT_NOTIFICATION_SQL,
                    {
                        "user_id": user_id,
                        "subscription_id": sub_id,
                    },
                )
                if inserted.scalar() is None:
                    counters["skipped"] += 1
                    continue

                # 2. Determine which message to send.
                has_auto = (
                    await session.execute(
                        _HAS_AUTO_DISCOUNT_SQL, {"user_id": user_id}
                    )
                ).scalar_one()

                if has_auto:
                    # Referral lifetime 15% — no fresh promo.
                    payload = {
                        "text_key": "trial_expiring_no_promo",
                        "format_kwargs": {},
                        "parse_mode": "HTML",
                        "kind": "trial_expiring_24h",
                        "context": {"subscription_id": sub_id},
                    }
                    counter_key = "sent_no_promo"
                else:
                    # Mint TRIAL15_<sub_id>. ON CONFLICT covers replays
                    # (notification row guard above usually short-circuits
                    # this, but keep the safety net).
                    promo_code = f"TRIAL15_{sub_id}"
                    await session.execute(
                        _INSERT_PROMO_SQL,
                        {
                            "code": promo_code,
                            "description": (
                                f"Auto trial-expiring promo for "
                                f"user_id={user_id} sub_id={sub_id}"
                            ),
                            "user_id": user_id,
                        },
                    )
                    payload = {
                        "text_key": "trial_expiring_with_promo",
                        "format_kwargs": {"promo_code": promo_code},
                        "parse_mode": "HTML",
                        "kind": "trial_expiring_24h",
                        "context": {
                            "subscription_id": sub_id,
                            "promo_code": promo_code,
                        },
                    }
                    counter_key = "sent_with_promo"

                # 3. Enqueue the DM. The backend's outbox API renders the
                # ``text_key`` against the ``texts`` table before
                # delivery — see ``app.api.bot.outbox._render_payload``.
                await session.execute(
                    _INSERT_OUTBOX_SQL,
                    {
                        "user_id": user_id,
                        "chat_id": tg_id,
                        "payload": json.dumps(payload, ensure_ascii=False),
                    },
                )
                counters[counter_key] += 1
    except Exception as exc:  # pragma: no cover — defensive guard
        log.warning("notify_trial_expiring_db_error", error=str(exc))
        return counters

    total_sent = counters["sent_with_promo"] + counters["sent_no_promo"]
    if total_sent:
        await business_log(
            api_client,
            level="INFO",
            event="notification_trial_expiring_24h_sent",
            module="worker.notify_trial_expiring",
            message=f"Queued {total_sent} trial-expiring-24h reminder(s)",
            context=counters,
        )
    return counters


__all__ = ["notify_trial_expiring_subscriptions_task"]
