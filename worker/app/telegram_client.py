"""Direct Telegram Bot API client used by the outbox dispatcher.

The worker talks to `https://api.telegram.org/bot{TOKEN}/...` directly so
that outbox delivery is decoupled from the bot process — if the bot is
down, the worker still drains pending messages.

Design notes
------------
- One shared `httpx.AsyncClient` per worker process (HTTP/2 keep-alive).
- All public methods return a dict shaped like the Telegram response
  envelope: `{"ok": bool, "result": ..., "error_code": int|None,
  "description": str|None}`. Network errors are normalised to the same
  envelope with ``ok=False`` and a synthetic ``error_code = -1``.
- On HTTP 429 we honour ``parameters.retry_after`` and retry **once**.
  A second 429 is reported as a regular failure and the dispatcher
  decides whether to fail the message permanently.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Self

import httpx

from app.logging_setup import get_logger

_TELEGRAM_BASE = "https://api.telegram.org"
_DEFAULT_RETRY_AFTER = 1.0
_MAX_RETRY_AFTER = 30.0


class TelegramClient:
    """Minimal Telegram Bot API client (sendMessage / sendPhoto)."""

    def __init__(self, token: str, timeout: float = 15.0) -> None:
        if not token:
            # We accept an empty token at construction time so unit tests
            # can build a client without env wiring; real calls will fail
            # fast with a descriptive 401 from Telegram.
            self._token = ""
        else:
            self._token = token

        self._log = get_logger("worker.telegram")
        self._client = httpx.AsyncClient(
            base_url=f"{_TELEGRAM_BASE}/bot{self._token}",
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=timeout, pool=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            headers={"User-Agent": "vpn-pix-worker/0.1"},
        )

    # --------------------------------------------------------------- #
    # lifecycle
    # --------------------------------------------------------------- #
    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --------------------------------------------------------------- #
    # public API
    # --------------------------------------------------------------- #
    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> dict[str, Any]:
        """POST /sendMessage. Returns the normalised response envelope."""
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            body["parse_mode"] = parse_mode
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        if disable_web_page_preview is not None:
            body["disable_web_page_preview"] = disable_web_page_preview
        return await self._call("sendMessage", body)

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /sendPhoto. ``photo`` may be a file_id or a URL."""
        body: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            body["caption"] = caption
        if parse_mode:
            body["parse_mode"] = parse_mode
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        return await self._call("sendPhoto", body)

    # --------------------------------------------------------------- #
    # internals
    # --------------------------------------------------------------- #
    async def _call(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        """Call Telegram with a single 429-aware retry."""
        for attempt in (1, 2):
            try:
                response = await self._client.post(f"/{method}", json=body)
            except httpx.HTTPError as exc:
                self._log.warning(
                    "telegram_network_error",
                    method=method,
                    attempt=attempt,
                    error=str(exc),
                )
                return {
                    "ok": False,
                    "result": None,
                    "error_code": -1,
                    "description": f"network error: {exc!s}",
                }

            envelope = self._parse_envelope(response)

            if response.status_code == 429 and attempt == 1:
                retry_after = self._extract_retry_after(envelope)
                self._log.warning(
                    "telegram_rate_limited",
                    method=method,
                    retry_after=retry_after,
                )
                await asyncio.sleep(retry_after)
                continue

            return envelope

        # Unreachable — the loop above always returns. Kept for type-checker.
        return {
            "ok": False,
            "result": None,
            "error_code": -1,
            "description": "unreachable",
        }

    @staticmethod
    def _parse_envelope(response: httpx.Response) -> dict[str, Any]:
        """Normalise the Telegram response into a stable shape."""
        try:
            data = response.json()
        except ValueError:
            return {
                "ok": False,
                "result": None,
                "error_code": response.status_code,
                "description": f"non-json response (status={response.status_code})",
            }

        if not isinstance(data, dict):
            return {
                "ok": False,
                "result": None,
                "error_code": response.status_code,
                "description": "unexpected response shape",
            }

        return {
            "ok": bool(data.get("ok", False)),
            "result": data.get("result"),
            "error_code": data.get("error_code", response.status_code)
            if not data.get("ok")
            else None,
            "description": data.get("description"),
            "parameters": data.get("parameters"),
        }

    @staticmethod
    def _extract_retry_after(envelope: dict[str, Any]) -> float:
        """Pull retry_after from Telegram's `parameters.retry_after`."""
        params = envelope.get("parameters")
        if isinstance(params, dict):
            value = params.get("retry_after")
            if isinstance(value, int | float) and value > 0:
                return min(float(value), _MAX_RETRY_AFTER)
        return _DEFAULT_RETRY_AFTER
