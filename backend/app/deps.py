"""FastAPI dependencies: DB session, Redis, auth guards."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import jwt
import redis.asyncio as redis_asyncio
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import constant_time_compare, verify_admin_jwt
from app.db.session import get_session
from app.services.northline_client import NorthLineClient

# ---------- DB ----------

async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


DBSession = Annotated[AsyncSession, Depends(get_db)]


# ---------- Redis ----------

async def get_redis(request: Request) -> redis_asyncio.Redis:
    """Return the redis client stored on the FastAPI app state."""
    client: redis_asyncio.Redis | None = getattr(request.app.state, "redis", None)
    if client is None:
        # Build on demand (e.g. during tests)
        settings = get_settings()
        client = redis_asyncio.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        request.app.state.redis = client
    return client


RedisDep = Annotated[redis_asyncio.Redis, Depends(get_redis)]


# ---------- Bot service token ----------

def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def require_service_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Guard for /api/bot/*. Compares Bearer token to BACKEND_SERVICE_TOKEN."""
    settings = get_settings()
    token = _extract_bearer(authorization)
    if not token or not constant_time_compare(token, settings.backend_service_token):
        raise UnauthorizedError("Invalid service token", error_code="invalid_service_token")


# ---------- Admin JWT ----------

class AdminPrincipal:
    """Decoded admin JWT principal."""

    __slots__ = ("kid", "label", "iat", "exp")

    def __init__(self, *, kid: int, label: str, iat: int, exp: int) -> None:
        self.kid = kid
        self.label = label
        self.iat = iat
        self.exp = exp


async def require_admin_jwt(
    authorization: Annotated[str | None, Header()] = None,
) -> AdminPrincipal:
    token = _extract_bearer(authorization)
    if not token:
        raise UnauthorizedError("Missing admin token", error_code="missing_admin_token")
    try:
        payload = verify_admin_jwt(token)
    except jwt.ExpiredSignatureError as e:
        raise UnauthorizedError("Token expired", error_code="token_expired") from e
    except jwt.InvalidTokenError as e:
        raise UnauthorizedError("Invalid admin token", error_code="invalid_admin_token") from e

    try:
        kid = int(payload["kid"])
        label = str(payload["sub"])
        iat = int(payload["iat"])
        exp = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as e:
        raise UnauthorizedError("Malformed token", error_code="malformed_token") from e

    return AdminPrincipal(kid=kid, label=label, iat=iat, exp=exp)


AdminDep = Annotated[AdminPrincipal, Depends(require_admin_jwt)]
ServiceTokenDep = Annotated[None, Depends(require_service_token)]


# ---------- NorthLine client ----------

def get_northline_client(request: Request) -> NorthLineClient:
    """Return (and cache) a NorthLine client on the FastAPI app state.

    Closed during lifespan shutdown.
    """
    client: NorthLineClient | None = getattr(
        request.app.state, "northline_client", None
    )
    if client is None:
        settings = get_settings()
        client = NorthLineClient(
            base_url=(
                settings.northline_api_url or "https://northline-vpn.xyz/api/v1"
            ),
            bearer_token=settings.northline_bearer_token or "",
            provider_key=settings.northline_provider_key or "",
            test_mode=bool(settings.northline_test_mode),
        )
        request.app.state.northline_client = client
    return client


NorthLineClientDep = Annotated[NorthLineClient, Depends(get_northline_client)]
