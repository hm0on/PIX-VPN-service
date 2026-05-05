"""Public /health endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import get_session_factory
from app.deps import RedisDep
from app.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(redis: RedisDep) -> HealthResponse:
    db_ok = "ok"
    redis_ok = "ok"

    factory = get_session_factory()
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = "fail"

    try:
        await redis.ping()
    except Exception:
        redis_ok = "fail"

    status_v = "ok" if db_ok == "ok" and redis_ok == "ok" else "degraded"
    return HealthResponse(status=status_v, db=db_ok, redis=redis_ok)
