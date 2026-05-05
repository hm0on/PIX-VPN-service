"""Custom exceptions for the bot service."""

from __future__ import annotations


class BotServiceError(Exception):
    """Base class for all bot-side service errors."""


class BackendUnavailableError(BotServiceError):
    """Raised when Backend API cannot be reached after retries.

    Caught by middlewares/handlers to show a friendly "service unavailable"
    message to the user without crashing the update.
    """


class BackendClientError(BotServiceError):
    """Raised on 4xx responses from Backend API (bad request, not found).

    The backend returns business errors as JSON ``{"error_code": "...",
    "detail": "..."}``. We expose ``error_code`` so handlers can branch on
    well-known codes (``free_trial_already_used``, ``insufficient_balance``,
    ``payment_provider_unavailable``, ``vpn_provider_unavailable_refunded``,
    ``vpn_provider_unavailable``, ...) without parsing strings.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        error_code: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(f"Backend client error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.payload: dict[str, object] = payload or {}


class BackendConflictError(BackendClientError):
    """Specialised :class:`BackendClientError` for HTTP 409 (Conflict).

    Used by Stage 4 ticket-open flow: backend returns 409 when the user
    already has an open ticket. Handlers branch on the type rather than
    the error_code string.
    """

    def __init__(
        self,
        detail: str,
        *,
        error_code: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(409, detail, error_code=error_code, payload=payload)
