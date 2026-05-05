"""Admin health endpoint (JWT-protected)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import require_admin_jwt
from app.schemas.common import OkResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=OkResponse,
    dependencies=[Depends(require_admin_jwt)],
)
async def admin_health() -> OkResponse:
    return OkResponse(ok=True)
