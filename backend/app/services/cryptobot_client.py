"""CryptoBot Pay API client.

Docs: https://help.crypt.bot/crypto-pay-api

Webhook signature verification (per docs):
    secret = sha256(api_token).digest()
    expected_hex = hmac_sha256(secret, body_bytes).hexdigest()
    expected_hex == header `crypto-pay-api-signature`
"""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger
from app.schemas.cryptobot import (
    CryptoBotApiResponse,
    CryptoBotInvoice,
)
from app.schemas.platega import InvoiceResult

logger = get_logger("cryptobot")


class CryptoBotError(Exception):
    """Base error for CryptoBot client failures."""


class CryptoBotClientError(CryptoBotError):
    """4xx / API-error response — non-retryable."""


class CryptoBotServerError(CryptoBotError):
    """5xx / network — retryable."""


_RETRY_EXC = (CryptoBotServerError, httpx.TransportError, httpx.TimeoutException)


def _kopecks_to_decimal_str(amount_kopecks: int) -> str:
    """Convert kopecks (int) to a decimal string with 2 decimals (no float)."""
    rubles = Decimal(amount_kopecks) / Decimal(100)
    return f"{rubles:.2f}"


class CryptoBotClient:
    """Async client for CryptoBot Pay API."""

    def __init__(
        self,
        api_token: str,
        api_url: str = "https://pay.crypt.bot/api",
        timeout: float = 15.0,
    ) -> None:
        self.api_token = api_token
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------

    @staticmethod
    def verify_webhook_signature(
        body_bytes: bytes,
        signature_header: str | None,
        api_token: str,
    ) -> bool:
        """Verify HMAC-SHA256 signature.

        Per CryptoBot docs the secret key is `sha256(api_token).digest()`.
        """
        if not signature_header or not api_token:
            return False
        secret = hashlib.sha256(api_token.encode("utf-8")).digest()
        expected = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header.strip().lower())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_invoice(
        self,
        *,
        order_id: str,
        amount_kopecks: int,
        description: str | None = None,
        paid_btn_url: str | None = None,
        paid_btn_name: str | None = None,
        expires_in: int | None = None,
    ) -> InvoiceResult:
        """Create a CryptoBot invoice (fiat=RUB).

        Crypto is auto-converted from RUB by CryptoBot at the payment step.
        """
        if amount_kopecks <= 0:
            raise CryptoBotClientError("amount_kopecks must be positive")

        amount_str = _kopecks_to_decimal_str(amount_kopecks)
        body: dict[str, Any] = {
            "currency_type": "fiat",
            "fiat": "RUB",
            "amount": amount_str,
            "payload": order_id,
        }
        if description:
            body["description"] = description
        if paid_btn_url:
            body["paid_btn_url"] = paid_btn_url
        if paid_btn_name:
            body["paid_btn_name"] = paid_btn_name
        if expires_in:
            body["expires_in"] = expires_in

        url = f"{self.api_url}/createInvoice"
        headers = {
            "Crypto-Pay-API-Token": self.api_token,
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
                    logger.warning("cryptobot_network_error", error=str(e))
                    raise CryptoBotServerError(str(e)) from e

                if last_response.status_code >= 500:
                    logger.warning(
                        "cryptobot_5xx",
                        status_code=last_response.status_code,
                        body=last_response.text[:512],
                    )
                    raise CryptoBotServerError(
                        f"CryptoBot 5xx: {last_response.status_code}"
                    )

        assert last_response is not None  # noqa: S101 — invariant after retry loop
        if last_response.status_code >= 400:
            raise CryptoBotClientError(
                f"CryptoBot {last_response.status_code}: {last_response.text[:256]}"
            )

        try:
            data = last_response.json()
        except ValueError as e:
            raise CryptoBotClientError(f"Invalid JSON response: {e}") from e

        envelope = CryptoBotApiResponse.model_validate(data)
        if not envelope.ok or envelope.result is None:
            raise CryptoBotClientError(
                f"CryptoBot API error: {envelope.error}"
            )

        result = envelope.result
        invoice = CryptoBotInvoice(
            invoice_id=int(result["invoice_id"]),
            status=str(result.get("status", "active")),
            hash=result.get("hash"),
            currency_type=result.get("currency_type"),
            fiat=result.get("fiat"),
            amount=result.get("amount"),
            pay_url=result.get("pay_url") or result.get("bot_invoice_url"),
            bot_invoice_url=result.get("bot_invoice_url"),
            mini_app_invoice_url=result.get("mini_app_invoice_url"),
            web_app_invoice_url=result.get("web_app_invoice_url"),
            description=result.get("description"),
            payload=result.get("payload"),
            raw=result,
        )

        payment_url = (
            invoice.bot_invoice_url
            or invoice.pay_url
            or invoice.mini_app_invoice_url
            or invoice.web_app_invoice_url
        )
        if not payment_url:
            raise CryptoBotClientError(
                "CryptoBot response did not contain a pay URL"
            )

        return InvoiceResult(
            external_id=str(invoice.invoice_id),
            payment_url=payment_url,
            raw=invoice.raw,
        )
