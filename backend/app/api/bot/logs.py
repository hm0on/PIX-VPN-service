"""Bot log ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.logging import business_log
from app.deps import DBSession
from app.schemas.common import OkResponse
from app.schemas.log import BotLogCreate

router = APIRouter()


@router.post("/logs", response_model=OkResponse)
async def submit_bot_log(payload: BotLogCreate, session: DBSession) -> OkResponse:
    await business_log(
        session,
        level=payload.level,
        event=payload.event,
        module=payload.module or "bot",
        user_id=payload.user_id,
        message=payload.message,
        context=payload.context,
    )
    await session.commit()
    return OkResponse(ok=True)
