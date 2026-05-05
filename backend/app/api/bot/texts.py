"""Bot text endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import DBSession
from app.schemas.text import TextResponse
from app.services.text_service import TextService

router = APIRouter()


@router.get("/texts", response_model=list[TextResponse])
async def list_texts(session: DBSession) -> list[TextResponse]:
    service = TextService(session)
    rows = await service.get_all_texts()
    return [TextResponse.model_validate(r) for r in rows]


@router.get("/texts/{key}", response_model=TextResponse)
async def get_text(key: str, session: DBSession) -> TextResponse:
    service = TextService(session)
    row = await service.get_text(key)
    return TextResponse.model_validate(row)
