"""Platega payment provider HTTP client.

Spec: https://docs.platega.io/

Ключевое:
- Base URL: https://app.platega.io
- Авторизация: заголовки X-MerchantId + X-Secret
- Создание транзакции: POST /transaction/process
- Сумма в рублях (float), НЕ в копейках
- Метод оплаты — целое число (2 = СБП)
- Webhook: те же два заголовка X-MerchantId/X-Secret;
  отдельной HMAC-подписи нет, проверяем равенство этих заголовков нашим credentials.
- Статусы: PENDING | CONFIRMED | CANCELED | CHARGEBACKED
"""

from __future__ import annotations

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
    PLATEGA_METHOD_CODES,
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
        X-Secret из личного кабинета Platega → Настройки.
    shop_id:
        X-MerchantId (UUID) из личного кабинета Platega → Настройки.
    secret:
        Совпадает с api_key. Оставлено для обратной совместимости со старым
        конструктором; webhook авторизуется тем же X-Secret.
    base_url:
        Базовый URL API (по умолчанию https://app.platega.io).
    timeout:
        Таймаут запроса в секундах.
    """

    def __init__(
        self,
        api_key: str,
        shop_id: str,
        secret: str | None = None,
        base_url: str = "https://app.platega.io",
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.shop_id = shop_id
        # X-Secret = api_key. Поле secret оставлено только для совместимости
        # со старой сигнатурой, реально не используется в подписи.
        self.secret = secret or api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-MerchantId": self.shop_id,
            "X-Secret": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def verify_webhook_credentials(
        self,
        merchant_id_header: str | None,
        secret_header: str | None,
    ) -> bool:
        """Проверка авторизации callback'а.

        Platega не использует HMAC-подпись — приходящие заголовки
        X-MerchantId / X-Secret должны буквально совпадать с нашими.
        """
        if not merchant_id_header or not secret_header:
            return False
        ok_merchant = hmac.compare_digest(
            merchant_id_header.strip(), self.shop_id.strip()
        )
        ok_secret = hmac.compare_digest(
            secret_header.strip(), self.api_key.strip()
        )
        return ok_merchant and ok_secret

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _kopecks_to_rubles(amount_kopecks: int) -> float:
        """Целые копейки → рубли с двумя знаками после запятой.

        Возвращаем float, т.к. OpenAPI схема Platega объявляет number/float.
        Точность копеек сохраняется (round до 2 знаков).
        """
        return round(amount_kopecks / 100, 2)

    async def create_invoice(
        self,
        *,
        order_id: str,
        amount_kopecks: int,
        currency: str = "RUB",
        payment_method: PlategaMethod,
        description: str | None,
        callback_url: str,  # сохранён в сигнатуре для совместимости
        success_url: str | None = None,
    ) -> InvoiceResult:
        """Создать транзакцию через POST /transaction/process.

        ``callback_url`` Platega'й конфигурируется в личном кабинете → Настройки →
        Callback URLs, в API его не передают. Параметр сохранён в сигнатуре,
        чтобы не ломать payment_service.
        """
        if amount_kopecks <= 0:
            raise PlategaClientError("amount_kopecks must be positive")

        method_code = PLATEGA_METHOD_CODES.get(payment_method)
        if method_code is None:
            raise PlategaClientError(
                f"Unsupported Platega payment method: {payment_method}"
            )

        body: dict[str, Any] = {
            "paymentMethod": method_code,
            "paymentDetails": {
                "amount": self._kopecks_to_rubles(amount_kopecks),
                "currency": currency,
            },
            "description": description or f"Order {order_id}",
            "payload": order_id,
        }
        if success_url:
            body["return"] = success_url
            body["failedUrl"] = success_url

        # callback_url доступен только если хотим логировать; в API не уходит.
        _ = callback_url

        url = f"{self.base_url}/transaction/process"
        headers = self._auth_headers()

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

        # /transaction/process возвращает: transactionId, redirect, status, ...
        # /v2/transaction/process возвращает: transactionId, url, status, ...
        external_id = data.get("transactionId") or data.get("id")
        payment_url = data.get("redirect") or data.get("url")
        if not external_id:
            raise PlategaClientError(
                "Platega response did not contain transactionId"
            )
        if not payment_url:
            raise PlategaClientError(
                "Platega response did not contain a payment URL"
            )

        parsed = PlategaInvoiceResponse(
            transactionId=str(external_id),
            redirect=str(payment_url),
            status=str(data.get("status") or "PENDING"),
            raw=data,
        )
        return InvoiceResult(
            external_id=parsed.transactionId,
            payment_url=parsed.redirect or "",
            raw=parsed.raw,
        )

    async def get_transaction_status(self, transaction_id: str) -> dict[str, Any]:
        """GET /transaction/{id} — проверить статус транзакции.

        Используется для ручной сверки или fallback'а при потере webhook'а.
        """
        url = f"{self.base_url}/transaction/{transaction_id}"
        headers = self._auth_headers()
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            resp = await cli.get(url, headers=headers)
        if resp.status_code == 404:
            raise PlategaClientError(f"transaction {transaction_id} not found")
        if resp.status_code >= 400:
            raise PlategaClientError(
                f"Platega {resp.status_code}: {resp.text[:256]}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise PlategaClientError(f"Invalid JSON response: {e}") from e
