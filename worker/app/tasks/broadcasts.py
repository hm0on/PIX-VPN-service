"""Broadcast worker tasks (Stage 5 §10).

Two ARQ entrypoints:

* :func:`run_broadcast` — on-demand job kicked off by ``POST
  /api/admin/broadcasts/{id}/send`` (or by :func:`pick_scheduled_broadcasts`
  when a schedule comes due). Snapshots the recipient list, then drains it
  through the Telegram Bot API ~25 msg/sec, honouring the Redis stop-flag
  ``broadcast:cancel:{id}`` between batches.

* :func:`pick_scheduled_broadcasts` — minute cron that promotes due
  ``scheduled`` broadcasts to ``sending`` and enqueues ``run_broadcast``.

Plus :func:`cleanup_logs` — daily retention worker (logs 365d, tech_logs
30d, broadcast_recipients of done broadcasts 90d).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import redis.asyncio as redis_asyncio
from sqlalchemy import text

from app.logging_setup import get_logger
from app.tg_html import to_telegram_html

if TYPE_CHECKING:
    from arq import ArqRedis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import Settings
    from app.telegram_client import TelegramClient

# Constants kept in sync with backend/app/db/models/broadcast*.py
_STATUS_DRAFT = "draft"
_STATUS_SCHEDULED = "scheduled"
_STATUS_SENDING = "sending"
_STATUS_DONE = "done"
_STATUS_CANCELLED = "cancelled"

_TARGET_ALL = "all"
_TARGET_SUBSCRIBERS = "subscribers"

_BATCH = 25
_INTER_MSG_DELAY = 0.04  # ~25 msg/sec — Telegram limit is 30/s for bots


_TELEGRAM_BASE = "https://api.telegram.org"


# --------------------------------------------------------------------- #
# Shared Redis pool helper
# --------------------------------------------------------------------- #
def _build_redis(settings: Settings) -> redis_asyncio.Redis[Any]:
    password = (
        settings.redis_password.get_secret_value()
        if settings.redis_password
        else None
    )
    if password:
        url = (
            f"redis://:{password}@{settings.redis_host}:"
            f"{settings.redis_port}/{settings.redis_database}"
        )
    else:
        url = (
            f"redis://{settings.redis_host}:"
            f"{settings.redis_port}/{settings.redis_database}"
        )
    return redis_asyncio.from_url(url, encoding="utf-8", decode_responses=True)


# --------------------------------------------------------------------- #
# run_broadcast
# --------------------------------------------------------------------- #
async def run_broadcast(ctx: dict[str, Any], broadcast_id: int) -> dict[str, int]:
    """Snapshot recipients then send the broadcast batch by batch."""
    settings: Settings = ctx["settings"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    tg_client: TelegramClient = ctx["telegram_client"]
    log = get_logger("worker.broadcasts").bind(broadcast_id=broadcast_id)

    redis = _build_redis(settings)
    counters = {"recipients_total": 0, "sent": 0, "failed": 0}

    try:
        # 1. Load broadcast — abort if not 'sending'.
        async with session_factory() as session, session.begin():
            row = await session.execute(
                text("SELECT * FROM broadcasts WHERE id = :id FOR UPDATE"),
                {"id": broadcast_id},
            )
            bc_row = row.mappings().first()
            if bc_row is None:
                log.warning("run_broadcast_not_found")
                return counters
            if bc_row["status"] != _STATUS_SENDING:
                log.warning(
                    "run_broadcast_wrong_status", status=bc_row["status"]
                )
                return counters

            # 2. Snapshot recipients (only on the first run — i.e. when no
            #    rows exist yet for this broadcast).
            existing = await session.execute(
                text(
                    "SELECT count(*) FROM broadcast_recipients "
                    "WHERE broadcast_id = :id"
                ),
                {"id": broadcast_id},
            )
            already = int(existing.scalar() or 0)

            if already == 0:
                target = bc_row["target"]
                if target == _TARGET_SUBSCRIBERS:
                    snapshot_sql = text(
                        """
                        INSERT INTO broadcast_recipients
                            (broadcast_id, user_id, status, created_at)
                        SELECT :bid, u.id, 'pending', now()
                          FROM users u
                         WHERE u.is_banned = false
                           AND EXISTS (
                                 SELECT 1 FROM subscriptions s
                                  WHERE s.user_id = u.id
                                    AND s.status = 'active'
                                    AND (s.expires_at IS NULL
                                         OR s.expires_at > now())
                               )
                        """
                    )
                else:  # target == 'all'
                    snapshot_sql = text(
                        """
                        INSERT INTO broadcast_recipients
                            (broadcast_id, user_id, status, created_at)
                        SELECT :bid, u.id, 'pending', now()
                          FROM users u
                         WHERE u.is_banned = false
                        """
                    )

                await session.execute(snapshot_sql, {"bid": broadcast_id})
                count_res = await session.execute(
                    text(
                        "SELECT count(*) FROM broadcast_recipients "
                        "WHERE broadcast_id = :id"
                    ),
                    {"id": broadcast_id},
                )
                total = int(count_res.scalar() or 0)
                await session.execute(
                    text(
                        "UPDATE broadcasts SET recipients_total = :n, "
                        "started_at = COALESCE(started_at, now()) "
                        "WHERE id = :id"
                    ),
                    {"n": total, "id": broadcast_id},
                )
                counters["recipients_total"] = total
            else:
                counters["recipients_total"] = already

        # 3. Drain pending recipients in batches.
        while True:
            # Cancel flag check.
            try:
                if await redis.get(f"broadcast:cancel:{broadcast_id}"):
                    await _finalize(session_factory, broadcast_id, _STATUS_CANCELLED)
                    log.info("run_broadcast_cancelled")
                    return counters
            except Exception as e:
                log.warning("redis_cancel_check_failed", error=str(e))

            async with session_factory() as session, session.begin():
                rows_res = await session.execute(
                    text(
                        """
                        SELECT br.id, br.user_id, u.tg_id
                          FROM broadcast_recipients br
                          JOIN users u ON u.id = br.user_id
                         WHERE br.broadcast_id = :id
                           AND br.status = 'pending'
                         ORDER BY br.id ASC
                         LIMIT :limit
                        """
                    ),
                    {"id": broadcast_id, "limit": _BATCH},
                )
                batch = list(rows_res.mappings().all())

                bc_res = await session.execute(
                    text(
                        "SELECT html_text, photo_file_id, photo_path, buttons, "
                        "buttons_per_row, status FROM broadcasts "
                        "WHERE id = :id"
                    ),
                    {"id": broadcast_id},
                )
                bc_curr = bc_res.mappings().first()

            if bc_curr is None or bc_curr["status"] != _STATUS_SENDING:
                cur_status = bc_curr["status"] if bc_curr is not None else None
                log.info(
                    "run_broadcast_status_changed",
                    status=cur_status,
                )
                return counters

            if not batch:
                # All done.
                await _finalize(session_factory, broadcast_id, _STATUS_DONE)
                log.info("run_broadcast_done", **counters)
                return counters

            buttons = bc_curr["buttons"]
            if isinstance(buttons, str):
                try:
                    buttons = json.loads(buttons)
                except ValueError:
                    buttons = None
            per_row_raw = bc_curr.get("buttons_per_row") or 1
            try:
                per_row = max(1, min(int(per_row_raw), 4))
            except (TypeError, ValueError):
                per_row = 1
            reply_markup = _build_reply_markup(buttons, per_row=per_row)

            # The editor (TipTap) emits full HTML — <p>, class=, target=,
            # and HTML-escaped <tg-emoji>/<tg-spoiler>. Telegram's HTML
            # parser is strict (rejects <p>), so sanitize once per batch.
            tg_html_text = to_telegram_html(bc_curr["html_text"])

            # Send each recipient in this batch sequentially so we keep
            # to ~25 msg/sec.
            for rec in batch:
                tg_id = int(rec["tg_id"])
                try:
                    envelope = await _send_one(
                        tg_client,
                        chat_id=tg_id,
                        html_text=tg_html_text,
                        photo_file_id=bc_curr["photo_file_id"],
                        photo_path=bc_curr["photo_path"],
                        reply_markup=reply_markup,
                        token=settings.bot_token.get_secret_value(),
                    )
                except Exception as exc:
                    envelope = {
                        "ok": False,
                        "error_code": -1,
                        "description": f"unhandled: {exc!s}",
                    }

                if envelope.get("ok"):
                    # If we just uploaded a photo, persist its file_id to
                    # avoid re-uploading on every recipient.
                    new_file_id = _maybe_extract_photo_file_id(envelope)
                    async with session_factory() as session, session.begin():
                        await session.execute(
                            text(
                                "UPDATE broadcast_recipients "
                                "SET status='sent', sent_at=now() WHERE id = :rid"
                            ),
                            {"rid": rec["id"]},
                        )
                        await session.execute(
                            text(
                                "UPDATE broadcasts SET sent = sent + 1 "
                                "WHERE id = :id"
                            ),
                            {"id": broadcast_id},
                        )
                        if new_file_id and not bc_curr["photo_file_id"]:
                            await session.execute(
                                text(
                                    "UPDATE broadcasts SET photo_file_id = :fid "
                                    "WHERE id = :id AND photo_file_id IS NULL"
                                ),
                                {"fid": new_file_id, "id": broadcast_id},
                            )
                            # Update local copy so subsequent loop iterations
                            # in this batch use the file_id.
                            mutable_bc: dict[str, Any] = dict(bc_curr)
                            mutable_bc["photo_file_id"] = new_file_id
                            bc_curr = mutable_bc  # type: ignore[assignment]
                    counters["sent"] += 1
                else:
                    err = (
                        f"{envelope.get('error_code')}: "
                        f"{envelope.get('description') or 'unknown'}"
                    )
                    async with session_factory() as session, session.begin():
                        await session.execute(
                            text(
                                "UPDATE broadcast_recipients "
                                "SET status='failed', error=:err WHERE id=:rid"
                            ),
                            {"err": err[:1000], "rid": rec["id"]},
                        )
                        await session.execute(
                            text(
                                "UPDATE broadcasts SET failed = failed + 1 "
                                "WHERE id = :id"
                            ),
                            {"id": broadcast_id},
                        )
                    counters["failed"] += 1

                await asyncio.sleep(_INTER_MSG_DELAY)

    finally:
        with contextlib.suppress(Exception):
            await redis.aclose()  # type: ignore[attr-defined]


async def _finalize(
    session_factory: async_sessionmaker[AsyncSession],
    broadcast_id: int,
    new_status: str,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE broadcasts SET status = :s, finished_at = now() "
                "WHERE id = :id"
            ),
            {"s": new_status, "id": broadcast_id},
        )


def _build_reply_markup(
    buttons: Any, *, per_row: int = 1
) -> dict[str, Any] | None:
    if not isinstance(buttons, list) or not buttons:
        return None
    per_row = max(1, min(int(per_row or 1), 4))
    flat: list[dict[str, str]] = []
    for btn in buttons:
        if not isinstance(btn, dict):
            continue
        text_v = btn.get("text")
        url = btn.get("url")
        if isinstance(text_v, str) and isinstance(url, str):
            flat.append({"text": text_v, "url": url})
    if not flat:
        return None
    rows = [flat[i : i + per_row] for i in range(0, len(flat), per_row)]
    return {"inline_keyboard": rows}


def _maybe_extract_photo_file_id(envelope: dict[str, Any]) -> str | None:
    result = envelope.get("result")
    if not isinstance(result, dict):
        return None
    photos = result.get("photo")
    if isinstance(photos, list) and photos:
        # Telegram returns multiple thumbs; take the largest by file_size.
        sorted_photos = sorted(
            (p for p in photos if isinstance(p, dict)),
            key=lambda p: p.get("file_size") or 0,
            reverse=True,
        )
        if sorted_photos:
            fid = sorted_photos[0].get("file_id")
            if isinstance(fid, str):
                return fid
    return None


async def _send_one(
    tg_client: TelegramClient,
    *,
    chat_id: int,
    html_text: str,
    photo_file_id: str | None,
    photo_path: str | None,
    reply_markup: dict[str, Any] | None,
    token: str,
) -> dict[str, Any]:
    """Send a single broadcast message; uploads from path if no file_id yet."""
    if photo_file_id:
        return await tg_client.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=html_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    if photo_path and Path(photo_path).exists():  # noqa: ASYNC240 — local stat is cheap
        # First time we send this broadcast's photo — upload via multipart so
        # Telegram returns a file_id we can cache for subsequent recipients.
        return await _send_photo_multipart(
            chat_id=chat_id,
            photo_path=photo_path,
            caption=html_text,
            reply_markup=reply_markup,
            token=token,
        )
    return await tg_client.send_message(
        chat_id=chat_id,
        text=html_text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def _send_photo_multipart(
    *,
    chat_id: int,
    photo_path: str,
    caption: str | None,
    reply_markup: dict[str, Any] | None,
    token: str,
) -> dict[str, Any]:
    """One-shot multipart upload of a photo (used the first time only)."""
    if not token:
        return {
            "ok": False,
            "error_code": -1,
            "description": "BOT_TOKEN not configured",
        }
    url = f"{_TELEGRAM_BASE}/bot{token}/sendPhoto"
    data: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption is not None:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            with open(photo_path, "rb") as fp:  # noqa: ASYNC230 — small one-shot read
                content = fp.read()
            response = await client.post(
                url,
                data=data,
                files={
                    "photo": (Path(photo_path).name, content),
                },
            )
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "error_code": -1,
                "description": f"network: {exc!s}",
            }

    try:
        return response.json()  # type: ignore[no-any-return]
    except ValueError:
        return {
            "ok": False,
            "error_code": response.status_code,
            "description": "non-json",
        }


# --------------------------------------------------------------------- #
# pick_scheduled_broadcasts (cron, every minute)
# --------------------------------------------------------------------- #
async def pick_scheduled_broadcasts(ctx: dict[str, Any]) -> dict[str, int]:
    """Promote due `scheduled` broadcasts to `sending` and enqueue them."""
    settings: Settings = ctx["settings"]  # noqa: F841
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    redis: ArqRedis | None = ctx.get("redis")  # arq injects its own pool
    log = get_logger("worker.broadcasts.pick")

    promoted: list[int] = []
    async with session_factory() as session, session.begin():
        # FOR UPDATE SKIP LOCKED to support multiple workers.
        rows = await session.execute(
            text(
                """
                SELECT id FROM broadcasts
                 WHERE status = 'scheduled'
                   AND scheduled_at IS NOT NULL
                   AND scheduled_at <= now()
                 ORDER BY scheduled_at ASC
                 LIMIT 100
                 FOR UPDATE SKIP LOCKED
                """
            )
        )
        ids = [int(r[0]) for r in rows.all()]
        for bid in ids:
            await session.execute(
                text(
                    "UPDATE broadcasts SET status = 'sending', "
                    "started_at = COALESCE(started_at, now()) "
                    "WHERE id = :id"
                ),
                {"id": bid},
            )
            promoted.append(bid)

    if redis is not None:
        for bid in promoted:
            try:
                await redis.enqueue_job("run_broadcast", bid)
            except Exception as e:
                log.warning("enqueue_run_broadcast_failed", id=bid, error=str(e))

    if promoted:
        log.info("scheduled_broadcasts_promoted", ids=promoted)
    return {"promoted": len(promoted)}


# --------------------------------------------------------------------- #
# cleanup_logs (daily)
# --------------------------------------------------------------------- #
_CLEANUP_LOGS_SQL = text(
    "DELETE FROM logs WHERE created_at < now() - interval '365 days'"
)
_CLEANUP_TECH_LOGS_SQL = text(
    "DELETE FROM tech_logs WHERE created_at < now() - interval '30 days'"
)
_CLEANUP_RECIPIENTS_SQL = text(
    """
    DELETE FROM broadcast_recipients br
     USING broadcasts b
     WHERE br.broadcast_id = b.id
       AND b.status = 'done'
       AND br.created_at < now() - interval '90 days'
    """
)


async def cleanup_logs(ctx: dict[str, Any]) -> dict[str, int]:
    """Daily retention sweep — drops old logs to keep DB compact."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]
    api_client: httpx.AsyncClient = ctx["api_client"]  # noqa: F841
    log = get_logger("worker.cleanup_logs")

    counts = {"logs": 0, "tech_logs": 0, "recipients": 0}
    try:
        async with session_factory() as session, session.begin():
            r1 = await session.execute(_CLEANUP_LOGS_SQL)
            counts["logs"] = max(int(getattr(r1, "rowcount", 0) or 0), 0)
            r2 = await session.execute(_CLEANUP_TECH_LOGS_SQL)
            counts["tech_logs"] = max(
                int(getattr(r2, "rowcount", 0) or 0), 0
            )
            r3 = await session.execute(_CLEANUP_RECIPIENTS_SQL)
            counts["recipients"] = max(
                int(getattr(r3, "rowcount", 0) or 0), 0
            )
    except Exception as exc:
        log.error("cleanup_logs_db_error", error=str(exc))
        return counts

    log.info("cleanup_logs_done", **counts)
    return counts


__all__ = [
    "cleanup_logs",
    "pick_scheduled_broadcasts",
    "run_broadcast",
]


# Suppress unused imports for the type-checker (some only used in __future__).
_ = datetime, timezone
