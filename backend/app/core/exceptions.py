"""Application-level exceptions and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, get_trace_id

logger = get_logger("exceptions")


class AppError(Exception):
    """Base application error returned as a structured JSON response."""

    error_code: str = "internal_error"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        self.details = details or {}


class NotFoundError(AppError):
    error_code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Resource not found"


class UnauthorizedError(AppError):
    error_code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Unauthorized"


class ForbiddenError(AppError):
    error_code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Forbidden"


class ValidationError(AppError):
    error_code = "validation_error"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "Validation error"


class ConflictError(AppError):
    error_code = "conflict"
    status_code = status.HTTP_409_CONFLICT
    message = "Conflict"


# ---------- Domain (Stage 2) ----------


class FreeTrialAlreadyUsedError(AppError):
    error_code = "free_trial_already_used"
    status_code = status.HTTP_409_CONFLICT
    message = "Free trial has already been used for this account"


class InsufficientBalanceError(AppError):
    error_code = "insufficient_balance"
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    message = "Insufficient balance"


class TariffNotFoundError(AppError):
    error_code = "tariff_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Tariff not found"


class TariffDurationNotFoundError(AppError):
    error_code = "tariff_duration_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Tariff duration not found"


class SubscriptionNotFoundError(AppError):
    error_code = "subscription_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Subscription not found"


# ---------- Domain (Stage 3) ----------


class SubscriptionNotExtendableError(AppError):
    """Subscription is not in an extendable state (expired/deactivated/failed/pending)."""

    error_code = "subscription_not_extendable"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Subscription cannot be extended"


class ReferralSelfReferralError(AppError):
    """Internal: referrer == referee. Not surfaced to bot."""

    error_code = "referral_self"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Cannot refer yourself"


class ReferralAlreadyExistsError(AppError):
    """Internal: referee already has a Referral row."""

    error_code = "referral_already_exists"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Referral already registered"


class RefereeAlreadyHasPurchaseError(AppError):
    """Internal: cannot register referral after referee already paid."""

    error_code = "referee_already_has_purchase"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Referee already has paid history"


# ---------- NorthLine ----------


class NorthLineClientError(AppError):
    """4xx error from the NorthLine API."""

    error_code = "northline_client_error"
    status_code = status.HTTP_502_BAD_GATEWAY
    message = "NorthLine client error"

    def __init__(
        self,
        error_code: str,
        error_message: str,
        http_status: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_message,
            error_code=error_code or "northline_client_error",
            details=details,
        )
        self.http_status = http_status


class NorthLineUnavailableError(AppError):
    """5xx, network, or retries-exhausted error from NorthLine."""

    error_code = "vpn_provider_unavailable"
    status_code = status.HTTP_502_BAD_GATEWAY
    message = "VPN provider is temporarily unavailable"


def _error_payload(
    *,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": error_code,
            "message": message,
            "details": details or {},
            "trace_id": get_trace_id(),
        }
    }


async def _app_error_handler(_request: Request, exc: AppError) -> ORJSONResponse:
    logger.warning(
        "app_error",
        error_code=exc.error_code,
        status_code=exc.status_code,
        message=exc.message,
    )
    return ORJSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details,
        ),
    )


async def _http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> ORJSONResponse:
    code_map = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
    }
    error_code = code_map.get(exc.status_code, "http_error")
    return ORJSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            error_code=error_code,
            message=str(exc.detail) if exc.detail else error_code,
        ),
    )


async def _validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_payload(
            error_code="validation_error",
            message="Request validation failed",
            details={"errors": exc.errors()},
        ),
    )


async def _unhandled_exception_handler(_request: Request, exc: Exception) -> ORJSONResponse:
    logger.exception("unhandled_exception", error=str(exc))
    return ORJSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload(
            error_code="internal_error",
            message="Internal server error",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)


# ---------- Domain (Stage 3 — Promo) ----------


class PromoCodeNotFoundError(AppError):
    error_code = "promo_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Promo code not found"


# ---------- Domain (Stage 4 — Tickets) ----------


class TicketAlreadyOpenError(AppError):
    error_code = "ticket_already_open"
    status_code = status.HTTP_409_CONFLICT
    message = "User already has an open ticket"


class TicketNotFoundError(AppError):
    error_code = "ticket_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Ticket not found"


class TicketAlreadyClosedError(AppError):
    error_code = "ticket_already_closed"
    status_code = status.HTTP_409_CONFLICT
    message = "Ticket is already closed"


class PromoCodeUnavailableError(AppError):
    error_code = "promo_unavailable"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Promo code is not available"

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = dict(details or {})
        if reason is not None:
            merged_details.setdefault("reason", reason)
        super().__init__(message, details=merged_details)
        self.reason = reason
