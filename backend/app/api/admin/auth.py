"""Admin authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.config import get_settings
from app.core.exceptions import ForbiddenError
from app.deps import AdminDep, DBSession
from app.schemas.admin import (
    AdminLoginRequest,
    AdminMeResponse,
    AdminRotateRequest,
    AdminRotateResponse,
    AdminTokenResponse,
)
from app.schemas.admin_panel.auth import (
    AdminKeyListItem,
    AdminKeyRotateRequest,
    AdminKeyRotateResponse,
)
from app.schemas.common import OkResponse
from app.services.admin_auth_service import AdminAuthService

router = APIRouter()


@router.post("/login", response_model=AdminTokenResponse)
async def login(payload: AdminLoginRequest, session: DBSession) -> AdminTokenResponse:
    service = AdminAuthService(session)
    result = await service.login(key_plaintext=payload.key)
    return AdminTokenResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
        label=result.label,
        kid=result.kid,
    )


@router.post("/refresh", response_model=AdminRotateResponse)
async def rotate(
    payload: AdminRotateRequest,
    session: DBSession,
    principal: AdminDep,
) -> AdminRotateResponse:
    """Legacy/backwards-compatible: rotates by replacing the CURRENT key.

    Returns a fresh JWT issued for the new key. The previous key keeps a grace
    window (``settings.admin_key_grace_hours``).
    """
    service = AdminAuthService(session)
    rot = await service.rotate_key(
        current_kid=principal.kid,
        new_label=payload.new_label,
    )
    return AdminRotateResponse(
        new_plaintext_key=rot.new_plaintext_key,
        new_key_id=rot.new_key_id,
        new_label=rot.new_label,
        previous_key_id=rot.previous_key_id,
        previous_valid_until=rot.previous_valid_until,
        access_token=rot.access_token,
        expires_at=rot.expires_at,
    )


@router.post("/keys/rotate", response_model=AdminKeyRotateResponse)
async def rotate_key_with_grace(
    payload: AdminKeyRotateRequest,
    session: DBSession,
    principal: AdminDep,
) -> AdminKeyRotateResponse:
    """Stage 5 rotation: creates a new key, retires every OTHER active key with grace.

    Plaintext is returned ONCE.
    """
    service = AdminAuthService(session)
    settings = get_settings()
    grace_hours = (
        payload.grace_hours
        if payload.grace_hours is not None
        else settings.admin_key_grace_hours_default
    )
    plaintext, new_row = await service.rotate_with_grace(
        new_label=payload.label,
        grace_hours=grace_hours,
        current_kid=principal.kid,
    )
    return AdminKeyRotateResponse(
        key=plaintext,
        label=new_row.label,
        valid_until=new_row.valid_until,
        id=new_row.id,
    )


@router.get("/me", response_model=AdminMeResponse)
async def me(principal: AdminDep) -> AdminMeResponse:
    return AdminMeResponse(
        label=principal.label,
        kid=principal.kid,
        issued_at=datetime.fromtimestamp(principal.iat, tz=UTC),
        expires_at=datetime.fromtimestamp(principal.exp, tz=UTC),
    )


@router.get("/keys", response_model=list[AdminKeyListItem])
async def list_keys(
    session: DBSession,
    principal: AdminDep,
) -> list[AdminKeyListItem]:
    """List every admin key with `is_current` set for the JWT's own key."""
    service = AdminAuthService(session)
    rows = await service.list_keys()
    return [
        AdminKeyListItem(
            id=r.id,
            label=r.label,
            created_at=r.created_at,
            valid_until=r.valid_until,
            revoked_at=r.revoked_at,
            is_current=(r.id == principal.kid),
        )
        for r in rows
    ]


@router.delete("/keys/{key_id}", response_model=OkResponse, status_code=status.HTTP_200_OK)
async def revoke_key(
    key_id: int,
    session: DBSession,
    principal: AdminDep,
) -> OkResponse:
    """Hard-revoke a key. Forbids self-revocation (rotate first)."""
    if key_id == principal.kid:
        raise ForbiddenError(
            "Cannot revoke the key currently in use; rotate first.",
            error_code="cannot_revoke_current_key",
        )
    service = AdminAuthService(session)
    await service.revoke_key(key_id)
    return OkResponse(ok=True)
