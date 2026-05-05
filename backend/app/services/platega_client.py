"""Platega payment provider HTTP client.

NOTE: Platega public docs are scarce. The implementation below uses a
*generalized* request/response shape typical for Russian payment gateways
(orderId / amount / currency / method / callbackUrl / successUrl / sign).

TODO: уточнить под реальное API Platega — в первую очередь:
  - точный путь create-invoice (/create_invoice vs /api/v1/invoices vs ...);
  - точные имена полей (snake_case vs camelCase);
  - набор полей, входящих в HMAC-подпись, и порядок их сортировки.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger
from app.schemas.platega import (
    InvoiceResult,
    PlategaInvoiceResponse,
    PlategaMethod,
)

logger = get_logger("platega")


class PlategaError(Exception):
    """Base error for Platega client failures."""


class PlategaClientError(PlategaError):
    """4xx — non-retryable client error."""


class PlategaServerError(PlategaError):
    """5xx / network — retryable."""


_RETRY_EXC = (PlategaServerError, httpx.TransportError, httpx.TimeoutException)


class PlategaClient:
    """Async client for Platega payment gateway.

    Parameters
    ----------
    api_key:
        API key issued by Platega (sent in `Authorization` header — TODO confirm).
    shop_id:
        Shop / merchant identifier.
    secret:
        HMAC-SHA256 secret for signing requests and verifying webhooks.
    base_url:
        Base API URL (default https://api.platega.io).
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        shop_id: str,
        secret: str,
        base_url: str = "https://api.platega.io",
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.shop_id = shop_id
        self.secret = secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Signing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_string(payload: dict[str, Any]) -> str:
        """Build a canonical string for signing.

        Convention: sort keys alphabetically, join `key=value` pairs with `&`,
        skip None and the `sign` field itself. This is a *generic* approach —
        TODO: align with real Platega spec.
        """
        parts: list[str] = []
        for key in sorted(payload.keys()):
            if key == "sign":
                continue
            value = payload[key]
            if value is None:
                continue
            parts.append(f"{key}={value}")
        return "&".join(parts)

    def _sign_payload(self, payload: dict[str, Any]) -> str:
        canonical = self._canonical_string(payload)
        return hmac.new(
            self.secret.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_webhook_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        """Verify HMAC-SHA256 signature of incoming webhook body."""
        if not signature_header or not self.secret:
            return False
        expected = hmac.new(
            self.secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        # Constant-time comparison.
        return hmac.compare_digest(expected, signature_header.strip().lower())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_invoice(
        self,
        *,
        order_id: str,
        amount_kopecks: int,
        currency: str = "RUB",
        payment_method: PlategaMethod,
        description: str | None,
        callback_url: str,
        success_url: str | None = None,
    ) -> InvoiceResult:
        """Create a new invoice and return the URL the user must visit to pay.

        Raises
        ------
        PlategaClientError
            On 4xx (no retry).
        PlategaServerError
            On 5xx after exhausted retries.
        """
        if amount_kopecks <= 0:
            raise PlategaClientError("amount_kopecks must be positive")

        # TODO: уточнить под реальное API Platega — формат может потребовать
        # `amount` в рублях с двумя знаками после запятой, а не копейки.
        body: dict[str, Any] = {
            "orderId": order_id,
            "shopId": self.shop_id,
            "amount": amount_kopecks,
            "currency": currency,
            "method": payment_method,
            "description": description,
            "successUrl": success_url,
            "callbackUrl": callback_url,
        }
        body["sign"] = self._sign_payload(body)

        url = f"{self.base_url}/create_invoice"  # TODO: confirm real path
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as cli:
                return await cli.post(url, json=body, headers=headers)

        last_response: httpx.Response | None = None
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type(_RETRY_EXC),
        ):
            with attempt:
                try:
                    last_response = await _do_request()
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    logger.warning("platega_network_error", error=str(e))
                    raise PlategaServerError(str(e)) from e

                if last_response.status_code >= 500:
                    logger.warning(
                        "platega_5xx",
                        status_code=last_response.status_code,
                        body=last_response.text[:512],
                    )
                    raise PlategaServerError(
                        f"Platega 5xx: {last_response.status_code}"
                    )

        assert last_response is not None  # noqa: S101 — invariant after retry loop
        if last_response.status_code >= 400:
            logger.warning(
                "platega_4xx",
                status_code=last_response.status_code,
                body=last_response.text[:512],
            )
            raise PlategaClientError(
                f"Platega {last_response.status_code}: {last_response.text[:256]}"
            )

        try:
            data = last_response.json()
        except ValueError as e:
            raise PlategaClientError(f"Invalid JSON response: {e}") from e

        # TODO: уточнить структуру ответа. Ниже — обобщённое сопоставление полей.
        external_id = (
            data.get("payment_id")
            or data.get("invoice_id")
            or data.get("id")
            or data.get("orderId")
            or order_id
        )
        payment_url = (
            data.get("payment_url")
            or data.get("url")
            or data.get("redirect_url")
            or ""
        )
        if not payment_url:
            raise PlategaClientError(
                "Platega response did not contain a payment URL"
            )

        parsed = PlategaInvoiceResponse(
            external_id=str(external_id),
            payment_url=str(payment_url),
            status=str(data.get("status") or "pending"),
            raw=data,
        )
        return InvoiceResult(
            external_id=parsed.external_id,
            payment_url=parsed.payment_url,
            raw=parsed.raw,
        )
