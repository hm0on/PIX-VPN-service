"""Bot endpoint: list active tariffs (with durations)."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import DBSession, RedisDep
from app.schemas.tariff import TariffWithDurationsSchema
from app.services.tariff_service import TariffService

router = APIRouter()


@router.get("/tariffs", response_model=list[TariffWithDurationsSchema])
async def list_tariffs(
    session: DBSession, redis: RedisDep
) -> list[TariffWithDurationsSchema]:
    service = TariffService(session, redis=redis)
    return await service.get_active_tariffs_with_durations()
