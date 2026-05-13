"""Telegram admin alerts via the existing outbox pipeline.

What this is
------------
A thin helper that enqueues a raw-text outbox row addressed to the admin's
Telegram chat (``settings.admin_tg_id``). The outbox worker picks it up
within ~5 seconds and delivers it like any other bot message — no new
infrastructure, no separate bot, no extra deploys.

Three levels — ``ALERT`` (yellow), ``WARN`` (orange), ``CRIT`` (red) —
get emoji-prefixed so the chat history is glance-scannable when something
is on fire at 3am.

Why it lives in its own module
------------------------------
``business_log`` calls this helper for every ``LEVEL_CRITICAL`` event, so
*every* existing money-side critical (``vpn_provider_failed_after_payment``,
``free_trial_failed_provider_error``, balance refund, etc.) becomes a
Telegram alert for free, with **no edits to the 7 critical call sites**.
Reconcile and similar non-business flows call ``send_admin_alert`` directly.

Dedup
-----
``dedup_key`` (optional) suppresses repeated alerts inside a 10-minute
window. Designed for the failure mode that prompted this feature: when
NorthLine ratates the bearer and reconcile sees ``invalid_provider_key``
on 30 subs in a row, we want **one** TG ping per outage, not 30.

The dedup check is a single ``SELECT EXISTS`` against the outbox; same
session as the caller, so it costs ~1 ms.

Silent no-op when disabled
--------------------------
If ``settings.admin_tg_id`` is unset (``None``) — e.g. local dev, CI,
fresh staging without the env populated — the helper returns immediately
without raising. The rest of the business logic stays portable.
"""

from __future__ import annotations

import html as _html
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import get_logger, get_trace_id
from app.db.models.outbox import OUTBOX_MSG_TEXT, Outbox
from app.db.models.user import User

log = get_logger("admin_alert")

AlertLevel = Literal["ALERT", "WARN", "CRIT"]

_LEVEL_EMOJI: dict[str, str] = {
    "ALERT": "🟡",
    "WARN": "🟠",
    "CRIT": "🔴",
}

# How long a dedup_key suppresses a repeat. 10 min is the sweet spot: long
# enough to absorb a reconcile-batch storm, short enough that two distinct
# incidents of the same class within an hour still both notify.
DEDUP_WINDOW = timedelta(minutes=10)

# Marker we stash in the outbox payload so dedup queries don't need their
# own column or index. The existing ``ix_outbox_status_send_after`` already
# narrows the scan to recent rows.
_PAYLOAD_KIND = "admin_alert"


def _format_text(
    *,
    level: AlertLevel,
    summary: str,
    details: dict[str, Any] | None,
) -> str:
    """Build the actual Telegram-HTML body.

    Format:
        🔴 <b>[АУД] CRIT</b>: {summary}
        <code>k=v k=v ...</code>
        <i>trace: {trace_id}</i>

    Everything user-controlled (summary text, dict values) is
    html-escaped because the worker sends with ``parse_mode=HTML`` and a
    stray ``<`` in an error message would break rendering.
    """
    emoji = _LEVEL_EMOJI.get(level, "⚪")
    safe_summary = _html.escape(summary)
    lines = [f"{emoji} <b>[АУД] {level}</b>: {safe_summary}"]

    if details:
        # Render as ``key=value`` pairs on one line — compact and readable
        # on mobile. Long values are truncated; full payload is still in
        # tech_logs/business_log for forensics.
        pairs: list[str] = []
        for k, v in details.items():
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:77] + "..."
            pairs.append(f"{_html.escape(str(k))}={_html.escape(v_str)}")
        if pairs:
            lines.append(f"<code>{' '.join(pairs)}</code>")

    trace = get_trace_id()
    if trace:
        lines.append(f"<i>trace: {_html.escape(trace)}</i>")

    return "\n".join(lines)


async def _recent_dedup_hit(
    session: AsyncSession, *, dedup_key: str
) -> bool:
    """Return True if an alert with the same ``dedup_key`` was enqueued
    within ``DEDUP_WINDOW``.

    Uses raw SQL with Postgres ``->>`` because ``Outbox.payload`` is
    declared as the generic ``JSON`` type with a ``JSONB`` variant — on
    the ORM column descriptor the ``.astext`` accessor isn't available
    (it lives on the dialect-specific ``JSONB`` type only). At our
    outbox volume the ``send_after`` btree narrows the scan to a few
    dozen recent rows before the JSON match runs.
    """
    from sqlalchemy import text

    stmt = text(
        """
        SELECT 1
          FROM outbox
         WHERE send_after >= NOW() - :window
           AND payload->>'dedup_key' = :dedup_key
           AND payload->>'kind' = :kind
         LIMIT 1
        """
    )
    found = (
        await session.execute(
            stmt,
            {
                "window": DEDUP_WINDOW,
                "dedup_key": dedup_key,
                "kind": _PAYLOAD_KIND,
            },
        )
    ).scalar_one_or_none()
    return found is not None


async def send_admin_alert(
    session: AsyncSession,
    *,
    level: AlertLevel,
    summary: str,
    details: dict[str, Any] | None = None,
    dedup_key: str | None = None,
) -> None:
    """Enqueue a Telegram alert for the admin.

    Args:
        session: Caller's session. The outbox row goes into the caller's
            transaction — if the caller rolls back, the alert is rolled
            back too (correct: don't alert on a logical no-op).
        level: ``ALERT`` / ``WARN`` / ``CRIT``.
        summary: Short, human-readable headline.
        details: Optional key→value context shown as ``k=v`` line.
        dedup_key: If set, suppresses repeats inside ``DEDUP_WINDOW``.

    Non-raising: anything that fails inside the helper is logged but
    re-raised only as a stdlib ``log.warning`` — we never let alert
    plumbing take down a business operation.
    """
    settings = get_settings()
    admin_tg_id = settings.admin_tg_id
    if not admin_tg_id:
        # No admin configured (local dev / staging without ADMIN_TG_ID).
        return

    try:
        if dedup_key and await _recent_dedup_hit(session, dedup_key=dedup_key):
            log.debug(
                "admin_alert_deduped",
                dedup_key=dedup_key,
                summary=summary,
                level=level,
            )
            return

        # Resolve admin's internal user.id — outbox.user_id is a NOT NULL
        # FK to users.id with ON DELETE CASCADE, so we can't pass tg_id
        # directly. The admin already exists in the users table (anyone
        # who has ever interacted with the bot does); if for some reason
        # they don't, we log and bail rather than crash.
        admin_user_id = (
            await session.execute(
                select(User.id).where(User.tg_id == admin_tg_id)
            )
        ).scalar_one_or_none()
        if admin_user_id is None:
            log.warning(
                "admin_alert_user_not_found",
                admin_tg_id=admin_tg_id,
                summary=summary,
            )
            return

        text = _format_text(level=level, summary=summary, details=details)

        # ``kind=admin_alert`` lets the outbox worker / admin panel grep
        # for these later without scanning every text message.
        payload: dict[str, Any] = {
            "text": text,
            "parse_mode": "HTML",
            "kind": _PAYLOAD_KIND,
            "level": level,
        }
        if dedup_key:
            payload["dedup_key"] = dedup_key

        row = Outbox(
            user_id=admin_user_id,
            chat_id=admin_tg_id,
            message_type=OUTBOX_MSG_TEXT,
            payload=payload,
        )
        session.add(row)
        await session.flush()

        log.info(
            "admin_alert_enqueued",
            level=level,
            summary=summary,
            dedup_key=dedup_key,
        )
    except Exception as exc:  # noqa: BLE001
        # Never let alert plumbing crash a business call. The original
        # error path (business_log + raise to caller) is still intact.
        log.warning(
            "admin_alert_failed",
            error=repr(exc),
            level=level,
            summary=summary,
        )


__all__ = ["send_admin_alert", "AlertLevel"]
