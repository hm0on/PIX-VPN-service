"""Async HTTP client for the NorthLine Reseller API.

Spec: https://northline-vpn.xyz/reseller-api-docs

- httpx.AsyncClient under the hood.
- Retries on 5xx and transport errors (3 attempts, exponential 1s/2s/4s) via tenacity.
- 4xx → no retries, raise NorthLineClientError.
- All calls are tech-logged with trace_id (best-effort: caller may pass a session).
- Optional ``test_mode``: when enabled, ``create_key`` includes ``"test": true``
  in the request body. The provider returns a fake ``subscription_id`` and key
  URL, never debits the reseller balance and does not provision a real VLESS
  key. Toggle through the ``NORTHLINE_TEST_MODE`` env var. Other endpoints
  (``extend_key``, ``get_key``) do not support a sandbox flag — calls against
  fake test subscriptions will simply fail with NOT_FOUND.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import NorthLineClientError, NorthLineUnavailableError
from app.core.logging import get_logger, get_trace_id
from app.schemas.northline import (
    DeactivateResponse,
    ExtendResponse,
    KeyInfo,
    KeyResponse,
)

logger = get_logger("northline_client")


class _RetryableHTTPError(Exception):
    """Internal marker to drive tenacity on 5xx responses."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"NorthLine 5xx: {response.status_code}")
        self.response = response


class NorthLineClient:
    """Async client for the NorthLine reseller API.

    The base URL must already include the ``/api/v1`` prefix
    (the provider's docs publish endpoints relative to that prefix).
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        provider_key: str,
        *,
        timeout: float = 15.0,
        connect_timeout: float = 5.0,
        test_mode: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.provider_key = provider_key
        self.test_mode = test_mode
        self._timeout = httpx.Timeout(timeout, connect=connect_timeout)
        self._client: httpx.AsyncClient | None = None

    # ----- Lifecycle -----

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self.bearer_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ----- Internal request engine -----

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a request with retry on 5xx/network. Return parsed JSON."""
        client = await self._get_client()

        async def _do_call() -> dict[str, Any]:
            try:
                resp = await client.request(
                    method, path, json=json_body, params=params
                )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                logger.warning(
                    "northline_transport_error",
                    method=method,
                    path=path,
                    error=str(e),
                )
                raise

            if 500 <= resp.status_code < 600:
                logger.warning(
                    "northline_server_error",
                    method=method,
                    path=path,
                    status_code=resp.status_code,
                )
                raise _RetryableHTTPError(resp)

            if 400 <= resp.status_code < 500:
                self._raise_client_error(resp)

            try:
                return resp.json()
            except ValueError as e:
                raise NorthLineUnavailableError(
                    "Invalid JSON in NorthLine response",
                    details={"status_code": resp.status_code},
                ) from e

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception_type(
                    (
                        _RetryableHTTPError,
                        httpx.TimeoutException,
                        httpx.TransportError,
                    )
                ),
                reraise=True,
            ):
                with attempt:
                    return await _do_call()
        except RetryError as e:  # pragma: no cover (reraise=True)
            raise NorthLineUnavailableError("NorthLine retries exhausted") from e
        except _RetryableHTTPError as e:
            raise NorthLineUnavailableError(
                "NorthLine server error",
                details={"status_code": e.response.status_code},
            ) from e
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise NorthLineUnavailableError(
                "NorthLine network error", details={"error": str(e)}
            ) from e

        # Unreachable, but keeps type-checker happy.
        raise NorthLineUnavailableError("NorthLine unknown error")  # pragma: no cover

    @staticmethod
    def _raise_client_error(resp: httpx.Response) -> None:
        """Translate 4xx into NorthLineClientError."""
        try:
            body = resp.json()
        except ValueError:
            body = {}

        error_code = (body.get("error_code") or "client_error").lower()
        error_message = body.get("error_message") or f"NorthLine 4xx ({resp.status_code})"
        logger.warning(
            "northline_client_error",
            status_code=resp.status_code,
            error_code=error_code,
            error_message=error_message,
        )
        raise NorthLineClientError(
            error_code=error_code,
            error_message=error_message,
            http_status=resp.status_code,
            details={"status_code": resp.status_code, "raw": body},
        )

    # ----- Public methods -----

    async def create_key(
        self,
        *,
        days: int,
        devices: int,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> KeyResponse:
        """POST /keys — create a new VPN subscription.

        When ``self.test_mode`` is ``True`` the request includes ``"test": true``
        and the provider returns a fake ``subscription_id`` + key URL without
        debiting the reseller balance.
        """
        body: dict[str, Any] = {
            "provider_key": self.provider_key,
            "days": days,
            "devices": devices,
            "idempotency_key": idempotency_key,
            "metadata": metadata or {},
        }
        if self.test_mode:
            body["test"] = True
        started = time.perf_counter()
        data = await self._request("POST", "/keys", json_body=body)
        await self._tech_log(
            "northline:create_key",
            started=started,
            payload={
                "days": days,
                "devices": devices,
                "idempotency_key": idempotency_key,
                "test_mode": self.test_mode,
            },
        )
        return KeyResponse.model_validate(data)

    async def extend_key(
        self,
        *,
        subscription_id: str,
        days: int,
        idempotency_key: str,
    ) -> ExtendResponse:
        """POST /keys/{id}/extend — extend an existing subscription by N days."""
        body = {
            "provider_key": self.provider_key,
            "days": days,
            "idempotency_key": idempotency_key,
        }
        started = time.perf_counter()
        data = await self._request(
            "POST", f"/keys/{subscription_id}/extend", json_body=body
        )
        await self._tech_log(
            "northline:extend_key",
            started=started,
            payload={"subscription_id": subscription_id, "days": days},
        )
        return ExtendResponse.model_validate(data)

    async def deactivate_key(
        self,
        *,
        subscription_id: str,
        reason: str,
    ) -> DeactivateResponse:
        """Soft no-op: the reseller API has no deactivate endpoint.

        Subscriptions auto-expire on ``expires_at`` and the reseller side has
        no way to forcibly retire one early. We keep this method on the client
        so the admin "deactivate" action still works (it flips the local DB
        status and notifies the user) — we just don't make an HTTP call to the
        provider.
        """
        from datetime import UTC, datetime

        logger.info(
            "northline_deactivate_local_only",
            subscription_id=subscription_id,
            reason=reason,
            note="provider has no deactivate endpoint; DB-only change",
        )
        return DeactivateResponse(
            ok=True,
            subscription_id=subscription_id,
            deactivated_at=datetime.now(tz=UTC),
        )

    async def get_key(self, *, subscription_id: str) -> KeyInfo:
        """GET /keys/{id} — fetch subscription state.

        Note: ``provider_key`` is not required as a query parameter on this
        endpoint per current docs (auth is via the Bearer token alone).
        """
        started = time.perf_counter()
        data = await self._request("GET", f"/keys/{subscription_id}")
        await self._tech_log(
            "northline:get_key",
            started=started,
            payload={"subscription_id": subscription_id},
        )
        return KeyInfo.model_validate(data)

    async def remove_device(
        self, *, subscription_id: str, device_id: str
    ) -> None:
        """Soft no-op: per-device removal is not exposed by the reseller API.

        Kept for compatibility with the admin endpoint
        ``DELETE /api/admin/subscriptions/{id}/devices/{device_id}``;
        we just record a tech log and return. If the provider adds this in
        a future revision this method should be wired up to the real call.
        """
        logger.info(
            "northline_remove_device_unsupported",
            subscription_id=subscription_id,
            device_id=device_id,
            note="provider has no per-device removal endpoint",
        )

    async def ping(self) -> bool:
        """GET /ping — public healthcheck (no auth required)."""
        try:
            data = await self._request("GET", "/ping")
        except (NorthLineClientError, NorthLineUnavailableError):
            return False
        return bool(data.get("ok"))

    # ----- Logging helpers -----

    async def _tech_log(
        self,
        action: str,
        *,
        started: float,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort tech_log: opens its own session so it can't break the caller flow."""
        from app.core.logging import tech_log
        from app.db.session import get_session_factory

        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            factory = get_session_factory()
            async with factory() as session:
                await tech_log(
                    session,
                    service="backend",
                    action=action,
                    payload=payload,
                    duration_ms=duration_ms,
                    trace_id=get_trace_id(),
                )
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("northline_tech_log_failed", error=str(e))
