"""Outbox dispatcher — drains pending messages and pushes them to Telegram.

Flow per tick (cron every 5 seconds, see ``app.main.WorkerSettings``):

1. ``GET /api/bot/outbox/pending?limit=N`` — Backend atomically marks the
   selected rows as ``dispatching`` and increments ``attempts`` (so two
   workers can never claim the same row).
2. For each message we call the matching Telegram method directly via
   :class:`app.telegram_client.TelegramClient`.
3. Outcome is reported back to Backend:
   - success                 → ``POST /api/bot/outbox/{id}/sent``
   - permanent TG error (4xx) → ``POST /api/bot/outbox/{id}/failed``
   - 5xx / network / 429×2   → ``POST /api/bot/outbox/{id}/failed``
     (Backend decides whether to retry based on attempts vs MAX.)
4. Concurrency is bounded by ``Settings.outbox_concurrency`` so we don't
   open hundreds of sockets to Telegram from a single worker.

If the Backend API is unreachable, the task logs and exits cleanly
instead of raising — ARQ would otherwise crash-loop the cron.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.logging_setup import get_logger
from app.telegram_client import TelegramClient

_OUTBOX_PENDING_PATH = "/api/bot/outbox/pending"
_OUTBOX_SENT_PATH = "/api/bot/outbox/{id}/sent"
_OUTBOX_FAILED_PATH = "/api/bot/outbox/{id}/failed"

# Telegram error codes that are pointless to retry (user blocked the bot,
# chat not found, banned, etc.). Anything else 4xx is also non-retryable.
_PERMANENT_ERROR_CODES = frozenset({400, 401, 403, 404})


async def outbox_dispatcher_task(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ cron entrypoint. Returns counts for observability/tests."""
    settings: Settings = ctx["settings"]
    api_client: httpx.AsyncClient = ctx["api_client"]
    tg_client: TelegramClient = ctx["telegram_client"]
    log = get_logger("worker.outbox")

    counters = {"fetched": 0, "sent": 0, "failed": 0, "skipped": 0}

    messages = await _fetch_pending(api_client, settings.outbox_batch_size, log)
    if messages is None:
        # Backend unreachable — already logged. Skip this tick.
        return counters

    counters["fetched"] = len(messages)
    if not messages:
        return counters

    sem = asyncio.Semaphore(settings.outbox_concurrency)

    async def _bounded(msg: dict[str, Any]) -> str:
        async with sem:
            return await _process_one(msg, api_client, tg_client, log)

    results = await asyncio.gather(
        *(_bounded(m) for m in messages),
        return_exceptions=True,
    )

    for outcome in results:
        if isinstance(outcome, BaseException):
            counters["skipped"] += 1
            log.error("outbox_message_unexpected_exception", error=str(outcome))
            continue
        counters[outcome] = counters.get(outcome, 0) + 1

    log.info("outbox_tick_done", **counters)
    return counters


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #
async def _fetch_pending(
    api_client: httpx.AsyncClient,
    limit: int,
    log: Any,
) -> list[dict[str, Any]] | None:
    """Return the pending batch or ``None`` if Backend is unreachable."""
    try:
        response = await api_client.get(
            _OUTBOX_PENDING_PATH,
            params={"limit": limit},
        )
    except httpx.HTTPError as exc:
        log.warning("outbox_fetch_network_error", error=str(exc))
        return None

    if response.status_code >= 500:
        log.warning("outbox_fetch_backend_5xx", status=response.status_code)
        return None
    if response.status_code >= 400:
        log.error(
            "outbox_fetch_backend_4xx",
            status=response.status_code,
            body=response.text[:500],
        )
        return None

    try:
        data = response.json()
    except ValueError:
        log.error("outbox_fetch_bad_json")
        return None

    if not isinstance(data, list):
        log.error("outbox_fetch_unexpected_shape", type=type(data).__name__)
        return None

    return [m for m in data if isinstance(m, dict)]


async def _process_one(
    msg: dict[str, Any],
    api_client: httpx.AsyncClient,
    tg_client: TelegramClient,
    log: Any,
) -> str:
    """Send a single message and report the outcome to Backend.

    Returns one of: ``"sent"``, ``"failed"``, ``"skipped"``.
    """
    msg_id = msg.get("id")
    chat_id = msg.get("chat_id")
    message_type = (msg.get("message_type") or "text").lower()
    payload = msg.get("payload") or {}

    if msg_id is None or chat_id is None:
        log.error("outbox_message_invalid", msg=msg)
        return "skipped"

    try:
        envelope = await _dispatch_to_telegram(
            tg_client, int(chat_id), message_type, payload
        )
    except ValueError as exc:
        # Unknown message_type or malformed payload — permanent failure.
        await _mark_failed(api_client, msg_id, f"invalid payload: {exc!s}", log)
        return "failed"

    if envelope.get("ok"):
        result = envelope.get("result") or {}
        tg_message_id = result.get("message_id") if isinstance(result, dict) else None
        await _mark_sent(api_client, msg_id, tg_message_id, log)
        return "sent"

    error_code = envelope.get("error_code")
    description = envelope.get("description") or "unknown error"
    error_text = f"{error_code}: {description}"

    if isinstance(error_code, int) and error_code in _PERMANENT_ERROR_CODES:
        # No point retrying — user blocked bot, chat doesn't exist, etc.
        log.info(
            "outbox_message_permanent_failure",
            id=msg_id,
            chat_id=chat_id,
            error=error_text,
        )
    else:
        log.warning(
            "outbox_message_transient_failure",
            id=msg_id,
            chat_id=chat_id,
            error=error_text,
        )

    await _mark_failed(api_client, msg_id, error_text, log)
    return "failed"


async def _dispatch_to_telegram(
    tg_client: TelegramClient,
    chat_id: int,
    message_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Route the outbox payload to the right Telegram method."""
    parse_mode = payload.get("parse_mode", "HTML")
    reply_markup = payload.get("reply_markup")

    if message_type == "text":
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("text payload requires non-empty 'text'")
        return await tg_client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=payload.get("disable_web_page_preview"),
        )

    if message_type == "photo":
        photo = payload.get("photo") or payload.get("file_id")
        if not isinstance(photo, str) or not photo:
            raise ValueError("photo payload requires 'photo' or 'file_id'")
        return await tg_client.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=payload.get("caption"),
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    raise ValueError(f"unsupported message_type: {message_type!r}")


async def _mark_sent(
    api_client: httpx.AsyncClient,
    msg_id: int,
    tg_message_id: int | None,
    log: Any,
) -> None:
    body: dict[str, Any] = {"tg_message_id": tg_message_id}
    try:
        response = await api_client.post(
            _OUTBOX_SENT_PATH.format(id=msg_id), json=body
        )
    except httpx.HTTPError as exc:
        log.warning("outbox_mark_sent_failed", id=msg_id, error=str(exc))
        return
    if response.status_code >= 400:
        log.warning(
            "outbox_mark_sent_rejected",
            id=msg_id,
            status=response.status_code,
            body=response.text[:200],
        )


async def _mark_failed(
    api_client: httpx.AsyncClient,
    msg_id: int,
    error: str,
    log: Any,
) -> None:
    body = {"error": error}
    try:
        response = await api_client.post(
            _OUTBOX_FAILED_PATH.format(id=msg_id), json=body
        )
    except httpx.HTTPError as exc:
        log.warning("outbox_mark_failed_failed", id=msg_id, error=str(exc))
        return
    if response.status_code >= 400:
        log.warning(
            "outbox_mark_failed_rejected",
            id=msg_id,
            status=response.status_code,
            body=response.text[:200],
        )


__all__ = ["outbox_dispatcher_task"]
