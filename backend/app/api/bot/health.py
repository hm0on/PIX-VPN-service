"""Bot health endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import OkResponse

router = APIRouter()


@router.get("/health", response_model=OkResponse)
async def bot_health() -> OkResponse:
    return OkResponse(ok=True)
