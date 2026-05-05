"""Tiny helper to send single messages from the admin panel (e.g. /test
broadcast). Talks to the Telegram Bot API directly so the backend doesn't
have to wait on the worker.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.core.logging import get_logger

_TELEGRAM_BASE = "https://api.telegram.org"

logger = get_logger("telegram_admin_client")


async def _post(
    method: str,
    body: dict[str, Any],
    *,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    token = settings.bot_token or ""
    if not token:
        return {
            "ok": False,
            "error_code": -1,
            "description": "BOT_TOKEN not configured",
        }
    url = f"{_TELEGRAM_BASE}/bot{token}/{method}"
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if files:
                response = await client.post(url, data=body, files=files)
            else:
                response = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        logger.warning("telegram_admin_network_error", method=method, error=str(exc))
        return {
            "ok": False,
            "error_code": -1,
            "description": f"network error: {exc!s}",
        }

    try:
        return response.json()  # type: ignore[no-any-return]
    except ValueError:
        return {
            "ok": False,
            "error_code": response.status_code,
            "description": f"non-json (status={response.status_code})",
        }


async def send_message(
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    reply_markup: dict[str, Any] | None = None,
    disable_web_page_preview: bool | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        body["parse_mode"] = parse_mode
    if reply_markup is not None:
        body["reply_markup"] = reply_markup
    if disable_web_page_preview is not None:
        body["disable_web_page_preview"] = disable_web_page_preview
    return await _post("sendMessage", body)


async def send_photo_path(
    chat_id: int,
    photo_path: str,
    *,
    caption: str | None = None,
    parse_mode: str | None = "HTML",
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upload a photo from a local path; suitable for the test endpoint.

    The worker handles `file_id` reuse during real broadcasts; here we only
    care that a single test message arrives.
    """
    body: dict[str, Any] = {"chat_id": chat_id}
    if caption is not None:
        body["caption"] = caption
    if parse_mode:
        body["parse_mode"] = parse_mode
    if reply_markup is not None:
        import json as _json

        body["reply_markup"] = _json.dumps(reply_markup)

    with open(photo_path, "rb") as fp:  # noqa: ASYNC230 — small one-shot upload
        return await _post(
            "sendPhoto",
            body,
            files={"photo": (photo_path.split("/")[-1], fp.read())},
        )
