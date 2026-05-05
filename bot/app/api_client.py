"""Async HTTP client for Backend API.

The bot NEVER touches the database directly. All persistence happens through
``http://backend:8000/api/bot/*`` with ``Authorization: Bearer <service-token>``.

Single ``httpx.AsyncClient`` instance per bot process (lifespan-managed in
``app.main``). All mutating/reading methods retry on 5xx with exponential
backoff via ``tenacity``. Each request carries a fresh ``X-Trace-ID`` header
unless one is already set in the ``trace_id_var`` ContextVar (then we reuse
it for correlation).
"""

from __future__ import annotations

import uuid
from types import TracebackType
from typing import Any, Self

import httpx
from aiogram.types import User as TgUser
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings
from app.utils.errors import (
    BackendClientError,
    BackendConflictError,
    BackendUnavailableError,
)
from app.utils.logging import get_logger, trace_id_var

log = get_logger("bot.api_client")


def _is_retryable(exc: BaseException) -> bool:
    """Retry on connection errors and 5xx responses."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return False


class BackendClient:
    """Thin async wrapper around the Backend bot-API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.BACKEND_API_URL.rstrip("/"),
            timeout=settings.BACKEND_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {settings.BACKEND_SERVICE_TOKEN}",
                "User-Agent": "vpn-pix-bot/0.1",
                "Accept": "application/json",
            },
        )

    # ---- lifecycle ----------------------------------------------------------

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

    # ---- core request -------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Issue an HTTP request with retries and structured error handling."""
        trace_id = trace_id_var.get() or str(uuid.uuid4())
        headers = {"X-Trace-ID": trace_id}
        response: httpx.Response | None = None

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.3, min=0.3, max=2.0),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.request(
                        method,
                        path,
                        json=json,
                        params=params,
                        headers=headers,
                    )
                    response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # 4xx — non-retryable client error. Surface error_code from the
            # JSON body (if any) so handlers can branch on it.
            error_code: str | None = None
            payload: dict[str, Any] = {}
            try:
                parsed = e.response.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                payload = parsed
                code = parsed.get("error_code") or parsed.get("code")
                if isinstance(code, str):
                    error_code = code
            log.warning(
                "api_client.client_error",
                method=method,
                path=path,
                status=e.response.status_code,
                error_code=error_code,
                body=e.response.text[:500],
            )
            if e.response.status_code == 409:
                raise BackendConflictError(
                    e.response.text,
                    error_code=error_code,
                    payload=payload,
                ) from e
            raise BackendClientError(
                e.response.status_code,
                e.response.text,
                error_code=error_code,
                payload=payload,
            ) from e
        except (httpx.HTTPError, RetryError) as e:
            log.error(
                "api_client.unavailable",
                method=method,
                path=path,
                error=str(e),
            )
            raise BackendUnavailableError(f"{method} {path}: {e}") from e

        # Either a successful response or a ``BackendUnavailableError`` raised
        # above. The ``None`` branch is impossible in practice but kept for
        # mypy strict-mode soundness.
        if response is None:
            raise BackendUnavailableError(f"{method} {path}: no response")
        return response

    # ---- users --------------------------------------------------------------

    async def upsert_user(
        self,
        tg_user: TgUser,
        *,
        start_payload: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/bot/users — register or update a Telegram user.

        ``start_payload`` is the raw text after ``/start`` (e.g. ``ref_42``).
        Backend decides whether it's a valid referral payload — the bot only
        forwards it. Sent as ``null`` when absent so the backend treats the
        upsert as a normal one (no referral attribution).
        """
        body: dict[str, Any] = {
            "tg_id": tg_user.id,
            "username": tg_user.username,
            "first_name": tg_user.first_name,
            "last_name": tg_user.last_name,
            "language_code": tg_user.language_code,
        }
        if start_payload is not None:
            body["start_payload"] = start_payload
        response = await self._request("POST", "/api/bot/users", json=body)
        return response.json()  # type: ignore[no-any-return]

    async def get_user(self, tg_id: int) -> dict[str, Any] | None:
        """GET /api/bot/users/{tg_id} — returns ``None`` if 404."""
        try:
            response = await self._request("GET", f"/api/bot/users/{tg_id}")
        except BackendClientError as e:
            if e.status_code == 404:
                return None
            raise
        return response.json()  # type: ignore[no-any-return]

    # ---- texts --------------------------------------------------------------

    async def get_text(self, key: str) -> dict[str, Any] | None:
        """GET /api/bot/texts/{key} — returns the full record or ``None``.

        Shape: ``{"key", "value_html", "media_file_id"|None, "media_kind"|None}``.
        """
        try:
            response = await self._request("GET", f"/api/bot/texts/{key}")
        except BackendClientError as e:
            if e.status_code == 404:
                return None
            raise
        data = response.json()
        if not isinstance(data, dict):
            return None
        return data

    async def get_all_texts(self) -> dict[str, dict[str, Any]]:
        """GET /api/bot/texts — returns ``{key: {value_html, media_file_id, media_kind}}``."""
        response = await self._request("GET", "/api/bot/texts")
        data = response.json()
        out: dict[str, dict[str, Any]] = {}
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                value_html = item.get("value_html")
                if not isinstance(key, str) or not isinstance(value_html, str):
                    continue
                out[key] = {
                    "value_html": value_html,
                    "media_file_id": item.get("media_file_id"),
                    "media_kind": item.get("media_kind"),
                }
        return out

    # ---- catalog / tariffs --------------------------------------------------

    async def get_tariffs(self) -> list[dict[str, Any]]:
        """GET /api/bot/tariffs — list of tariffs with embedded durations.

        Backend returns roughly::

            [
              {"id": 1, "code": "free", "name": "FREE", "description": "...",
               "is_free_trial": true, "is_active": true, "sort_order": 0,
               "devices": 3, "days": 3, "durations": []},
              {"id": 2, "code": "basic", "name": "Basic", "description": "...",
               "is_free_trial": false, "is_active": true, "sort_order": 10,
               "devices": 3,
               "durations": [
                 {"id": 11, "months": 1, "price_kopecks": 18900, "is_hot": false},
                 {"id": 12, "months": 3, "price_kopecks": 45900, "is_hot": true},
                 ...
               ]},
              ...
            ]
        """
        response = await self._request("GET", "/api/bot/tariffs")
        data = response.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    # ---- free trial ---------------------------------------------------------

    async def activate_free_trial(self, tg_id: int) -> dict[str, Any]:
        """POST /api/bot/free-trial — issue 3-day FREE key for the user.

        On success returns ``{"subscription_id": ..., "key_url": "...",
        "days": 3, "devices": 3}``. On error raises ``BackendClientError``
        with ``error_code`` ∈ {``free_trial_already_used``,
        ``vpn_provider_unavailable``}.
        """
        response = await self._request(
            "POST", "/api/bot/free-trial", json={"tg_id": tg_id}
        )
        return response.json()  # type: ignore[no-any-return]

    # ---- purchase -----------------------------------------------------------

    async def start_purchase(
        self,
        tg_id: int,
        tariff_id: int,
        duration_id: int,
        provider: str,
        *,
        promo_id: int | None = None,
    ) -> dict[str, Any]:
        """POST /api/bot/purchase/start — create Payment+Subscription, return invoice.

        ``provider`` ∈ {``platega_sbp``, ``platega_crypto``, ``cryptobot``}.
        ``promo_id`` is the id of a successfully validated discount promo
        (returned by :meth:`apply_promo`); backend uses it to recompute the
        final amount and record a ``promo_activation`` once the payment is
        captured.

        Returns ``{"payment_id": ..., "payment_url": "https://...",
        "amount_kopecks": ...}``.
        """
        body: dict[str, Any] = {
            "tg_id": tg_id,
            "tariff_id": tariff_id,
            "duration_id": duration_id,
            "provider": provider,
        }
        if promo_id is not None:
            body["promo_id"] = promo_id
        response = await self._request("POST", "/api/bot/purchase/start", json=body)
        return response.json()  # type: ignore[no-any-return]

    async def purchase_with_balance(
        self,
        tg_id: int,
        tariff_id: int,
        duration_id: int,
        *,
        promo_id: int | None = None,
    ) -> dict[str, Any]:
        """POST /api/bot/purchase/balance — synchronous balance-paid purchase.

        On success returns ``{"subscription_id": ..., "key_url": "...",
        "payment_id": ..., "amount_kopecks": ...}``. On error raises
        ``BackendClientError`` with ``error_code`` ∈ {``insufficient_balance``,
        ``vpn_provider_unavailable``, ``vpn_provider_unavailable_refunded``}.
        """
        body: dict[str, Any] = {
            "tg_id": tg_id,
            "tariff_id": tariff_id,
            "duration_id": duration_id,
        }
        if promo_id is not None:
            body["promo_id"] = promo_id
        response = await self._request("POST", "/api/bot/purchase/balance", json=body)
        return response.json()  # type: ignore[no-any-return]

    # ---- balance / topup ----------------------------------------------------

    async def create_topup(
        self,
        tg_id: int,
        amount_kopecks: int,
        provider: str,
    ) -> dict[str, Any]:
        """POST /api/bot/topup/create — create a balance top-up invoice.

        Returns ``{"payment_id": ..., "payment_url": "...",
        "amount_kopecks": ...}``.
        """
        body = {
            "tg_id": tg_id,
            "amount_kopecks": amount_kopecks,
            "provider": provider,
        }
        response = await self._request("POST", "/api/bot/topup/create", json=body)
        return response.json()  # type: ignore[no-any-return]

    async def get_user_balance(self, tg_id: int) -> int:
        """GET /api/bot/users/{tg_id}/balance — return balance in kopecks."""
        response = await self._request(
            "GET", f"/api/bot/users/{tg_id}/balance"
        )
        data = response.json()
        if isinstance(data, dict):
            value = data.get("balance_kopecks")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return 0

    # ---- subscriptions ------------------------------------------------------

    async def get_user_subscriptions(self, tg_id: int) -> list[dict[str, Any]]:
        """GET /api/bot/users/{tg_id}/subscriptions — list of subs (any status).

        Each item: ``{"id": ..., "tariff_name": "...", "devices": ...,
        "days": ..., "status": "active|expired|...", "started_at": ...,
        "expires_at": ..., "key_url": "...", "is_free_trial": ...}``.
        """
        try:
            response = await self._request(
                "GET", f"/api/bot/users/{tg_id}/subscriptions"
            )
        except BackendClientError as e:
            if e.status_code == 404:
                return []
            raise
        data = response.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    async def get_subscription_detail(
        self, subscription_id: int, tg_id: int
    ) -> dict[str, Any]:
        """GET /api/bot/subscriptions/{id}?tg_id=... — single subscription view.

        ``tg_id`` is sent as a query param so the backend can authorize that
        the requesting user owns this subscription.
        """
        response = await self._request(
            "GET",
            f"/api/bot/subscriptions/{subscription_id}",
            params={"tg_id": tg_id},
        )
        return response.json()  # type: ignore[no-any-return]

    # ---- promo / referral / extension (Stage 3) -----------------------------

    async def apply_promo(self, *, tg_id: int, code: str) -> dict[str, Any]:
        """POST /api/bot/promo/apply — validate and (for balance-type) credit.

        Body: ``{"tg_id", "code"}``.

        On success returns one of two shapes:

        - balance-type::

            {"type": "balance", "amount_kopecks": 5000,
             "balance_kopecks": 12300, "promo_id": 7}

          backend has already credited the balance; the bot just shows the
          confirmation and clears the purchase FSM.

        - discount-type::

            {"type": "discount_percent", "percent": 10, "promo_id": 8,
             "final_amount_kopecks": 17010}  # final price may be omitted

          the bot stores ``promo_id`` in FSM and proceeds to payment-method
          selection with the discounted amount.

        On 4xx raises :class:`BackendClientError` with ``error_code`` in
        ``{"promo_not_found", "promo_unavailable",
        "promo_max_per_user_reached", "promo_max_total_reached"}``.
        """
        body = {"tg_id": tg_id, "code": code}
        response = await self._request("POST", "/api/bot/promo/apply", json=body)
        return response.json()  # type: ignore[no-any-return]

    async def get_referral_stats(self, tg_id: int) -> dict[str, Any]:
        """GET /api/bot/users/{tg_id}/referral-stats.

        Returns ``{"invited": int, "earned_kopecks": int, "ref_link": str}``.
        ``ref_link`` is the full ``https://t.me/<bot>?start=ref_<id>`` URL
        (backend knows the bot username, the bot does not).
        """
        response = await self._request(
            "GET", f"/api/bot/users/{tg_id}/referral-stats"
        )
        data = response.json()
        if not isinstance(data, dict):
            return {"invited": 0, "earned_kopecks": 0, "ref_link": ""}
        return data

    async def start_extension(
        self,
        subscription_id: int,
        duration_id: int,
        provider: str,
        *,
        tg_id: int,
        promo_id: int | None = None,
    ) -> dict[str, Any]:
        """POST /api/bot/subscriptions/{id}/extend — create extension invoice.

        Body: ``{"tg_id", "duration_id", "payment_provider", "promo_id"}``.
        ``provider`` mirrors the purchase flow:
        ``platega_sbp`` / ``platega_crypto`` / ``cryptobot`` / ``balance``.

        Returns ``{"payment_id", "payment_url", "amount_kopecks", "key_url"}``
        — for ``provider="balance"`` the key URL is delivered synchronously
        and ``payment_url`` is empty; otherwise the bot shows the invoice and
        the outbox worker delivers the "extended" notification after the
        webhook fires.
        """
        body: dict[str, Any] = {
            "tg_id": tg_id,
            "duration_id": duration_id,
            "payment_provider": provider,
            "promo_id": promo_id,
        }
        response = await self._request(
            "POST", f"/api/bot/subscriptions/{subscription_id}/extend", json=body
        )
        return response.json()  # type: ignore[no-any-return]

    # ---- tickets / support (Stage 4) ----------------------------------------

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        """GET /api/bot/users/by-id/{user_id} — internal lookup by PK.

        TODO(backend): Stage 4 needs this route to resolve a ticket's
        ``user_id`` (FK) → Telegram ``tg_id`` for outgoing replies. If the
        backend hasn't shipped it yet, callers should fall back to the
        ``user_tg_id`` field embedded in the ticket payload (preferred path).
        """
        try:
            response = await self._request(
                "GET", f"/api/bot/users/by-id/{user_id}"
            )
        except BackendClientError as e:
            if e.status_code in (404, 405):
                return None
            raise
        data = response.json()
        if not isinstance(data, dict) or not data:
            return None
        return data

    async def get_active_ticket(self, tg_id: int) -> dict[str, Any] | None:
        """GET /api/bot/users/{tg_id}/active-ticket.

        Backend response: ``{"ticket": {...} | null}``. We return the inner
        ``ticket`` dict, or ``None`` if there is no open ticket. A 404 from
        the backend is also treated as ``None`` (defensive — newer backend
        deployments return ``{"ticket": null}`` instead).
        """
        try:
            response = await self._request(
                "GET", f"/api/bot/users/{tg_id}/active-ticket"
            )
        except BackendClientError as e:
            if e.status_code == 404:
                return None
            raise
        data = response.json()
        if not isinstance(data, dict):
            return None
        ticket = data.get("ticket")
        if isinstance(ticket, dict):
            return ticket
        return None

    async def open_ticket(self, tg_id: int, kind: str) -> dict[str, Any]:
        """POST /api/bot/tickets/open — create a new ticket for the user.

        Body: ``{"tg_id", "kind"}``. ``kind`` ∈ ``{"support", "idea"}``.
        Returns the created ticket dict (id, code, status, kind, ...).

        On 409 raises :class:`BackendConflictError` — the user already has
        an open ticket; handlers translate that into a friendly message.
        """
        body = {"tg_id": tg_id, "kind": kind}
        response = await self._request("POST", "/api/bot/tickets/open", json=body)
        return response.json()  # type: ignore[no-any-return]

    async def close_ticket(
        self,
        ticket_id: int,
        *,
        by: str,
        tg_user_id: int | None = None,
    ) -> dict[str, Any]:
        """POST /api/bot/tickets/{id}/close — mark a ticket as closed.

        ``by`` ∈ ``{"user", "admin"}``. ``tg_user_id`` identifies the actor
        for audit purposes (the user themselves, or the admin in the topic).
        Returns the updated ticket dict.
        """
        body: dict[str, Any] = {"by": by}
        if tg_user_id is not None:
            body["tg_user_id"] = tg_user_id
        response = await self._request(
            "POST", f"/api/bot/tickets/{ticket_id}/close", json=body
        )
        return response.json()  # type: ignore[no-any-return]

    async def record_ticket_message(
        self,
        ticket_id: int,
        *,
        direction: str,
        message_type: str,
        text: str | None = None,
        photo_file_id: str | None = None,
        sticker_file_id: str | None = None,
        tg_message_id: int | None = None,
    ) -> None:
        """POST /api/bot/tickets/{id}/messages — append one message to ticket log.

        ``direction`` ∈ ``{"from_user", "from_admin"}``.
        ``message_type`` ∈ ``{"text", "photo", "sticker"}``.
        Backend stores the row and returns it; we discard the response.
        """
        body: dict[str, Any] = {
            "direction": direction,
            "message_type": message_type,
        }
        if text is not None:
            body["text"] = text
        if photo_file_id is not None:
            body["photo_file_id"] = photo_file_id
        if sticker_file_id is not None:
            body["sticker_file_id"] = sticker_file_id
        if tg_message_id is not None:
            body["tg_message_id"] = tg_message_id
        await self._request(
            "POST", f"/api/bot/tickets/{ticket_id}/messages", json=body
        )

    async def get_ticket_by_thread(
        self, thread_id: int
    ) -> dict[str, Any] | None:
        """GET /api/bot/tickets/by-thread/{thread_id}.

        Backend response is the same envelope as ``/active-ticket``:
        ``{"ticket": {...} | null}``. Returns the inner ticket dict (so
        callers can read ``ticket["id"]``, ``ticket["status"]`` directly),
        or ``None`` if the thread has no bound ticket. A 404 is also treated
        as ``None``.
        """
        try:
            response = await self._request(
                "GET", f"/api/bot/tickets/by-thread/{thread_id}"
            )
        except BackendClientError as e:
            if e.status_code == 404:
                return None
            raise
        data = response.json()
        if not isinstance(data, dict):
            return None
        ticket = data.get("ticket")
        if isinstance(ticket, dict):
            return ticket
        return None

    async def get_support_topic(self, user_id: int) -> dict[str, Any]:
        """GET /api/bot/support-topic/{user_id}.

        Returns ``{"topic_thread_id": int|null, "topic_name": str|null}``.
        On 404 returns the same shape with both nulls so callers don't
        special-case a missing record.
        """
        try:
            response = await self._request(
                "GET", f"/api/bot/support-topic/{user_id}"
            )
        except BackendClientError as e:
            if e.status_code == 404:
                return {"topic_thread_id": None, "topic_name": None}
            raise
        data = response.json()
        if not isinstance(data, dict):
            return {"topic_thread_id": None, "topic_name": None}
        return data

    async def save_support_topic(
        self,
        user_id: int,
        topic_thread_id: int,
        topic_name: str,
    ) -> None:
        """POST /api/bot/support-topic — upsert the user→topic binding."""
        body = {
            "user_id": user_id,
            "topic_thread_id": topic_thread_id,
            "topic_name": topic_name,
        }
        await self._request("POST", "/api/bot/support-topic", json=body)

    async def attach_topic_to_ticket(
        self,
        ticket_id: int,
        topic_thread_id: int,
    ) -> None:
        """POST /api/bot/tickets/{id}/topic — bind a topic thread to a ticket."""
        body = {"topic_thread_id": topic_thread_id}
        await self._request(
            "POST", f"/api/bot/tickets/{ticket_id}/topic", json=body
        )

    async def ban_user_by_tg(self, tg_id: int, reason: str) -> None:
        """POST /api/bot/users/{tg_id}/ban — flag the user as banned."""
        body = {"reason": reason}
        await self._request("POST", f"/api/bot/users/{tg_id}/ban", json=body)

    async def unban_user_by_tg(self, tg_id: int) -> None:
        """POST /api/bot/users/{tg_id}/unban — clear the user's banned state."""
        await self._request("POST", f"/api/bot/users/{tg_id}/unban", json={})

    # ---- logs ---------------------------------------------------------------

    async def log(
        self,
        *,
        level: int,
        event: str,
        user_id: int | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """POST /api/bot/logs — best-effort; raises on failure (caller decides)."""
        body = {
            "level": level,
            "event": event,
            "module": "bot",
            "user_id": user_id,
            "message": message,
            "context": context or {},
        }
        await self._request("POST", "/api/bot/logs", json=body)
