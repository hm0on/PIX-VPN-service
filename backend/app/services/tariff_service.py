"""Tariff service with Redis caching."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    TariffDurationNotFoundError,
    TariffNotFoundError,
)
from app.core.logging import get_logger
from app.db.models.tariff import Tariff, TariffDuration
from app.repositories.tariff_repo import TariffRepository
from app.schemas.tariff import TariffDurationSchema, TariffWithDurationsSchema

logger = get_logger("tariff_service")

_CACHE_KEY = "tariffs:active"
_CACHE_TTL_SECONDS = 60


class TariffService:
    def __init__(
        self,
        session: AsyncSession,
        redis: redis_asyncio.Redis | None = None,
    ) -> None:
        self.session = session
        self.repo = TariffRepository(session)
        self.redis = redis

    async def get_active_tariffs_with_durations(
        self,
    ) -> list[TariffWithDurationsSchema]:
        # Redis cache first
        if self.redis is not None:
            try:
                cached = await self.redis.get(_CACHE_KEY)
                if isinstance(cached, (str, bytes)) and cached:
                    raw = json.loads(cached)
                    return [TariffWithDurationsSchema.model_validate(r) for r in raw]
            except Exception as e:  # noqa: BLE001
                logger.warning("tariffs_cache_read_failed", error=str(e))

        tariffs = await self.repo.list_active()
        result = [self._serialize_tariff(t) for t in tariffs]

        if self.redis is not None:
            try:
                payload = json.dumps([r.model_dump(mode="json") for r in result])
                await self.redis.set(_CACHE_KEY, payload, ex=_CACHE_TTL_SECONDS)
            except Exception as e:  # noqa: BLE001
                logger.warning("tariffs_cache_write_failed", error=str(e))

        return result

    async def get_tariff_or_raise(self, tariff_id: int) -> Tariff:
        result = await self.session.get(Tariff, tariff_id)
        if result is None or not result.is_active:
            raise TariffNotFoundError(f"Tariff id={tariff_id} not found")
        return result

    async def get_duration_or_raise(
        self, *, tariff_id: int, duration_id: int
    ) -> TariffDuration:
        result = await self.session.get(TariffDuration, duration_id)
        if (
            result is None
            or not result.is_active
            or result.tariff_id != tariff_id
        ):
            raise TariffDurationNotFoundError(
                f"Duration id={duration_id} not found for tariff_id={tariff_id}"
            )
        return result

    @staticmethod
    def _serialize_tariff(t: Tariff) -> TariffWithDurationsSchema:
        durations: list[TariffDurationSchema] = [
            TariffDurationSchema.model_validate(d)
            for d in t.durations
            if d.is_active
        ]
        # Stable order
        durations.sort(key=lambda d: d.days)
        data: dict[str, Any] = {
            "id": t.id,
            "code": t.code,
            "name": t.name,
            "description_html": t.description_html,
            "devices": t.devices,
            "sort_order": t.sort_order,
            "is_active": t.is_active,
            "is_free_trial": t.is_free_trial,
            "free_trial_days": t.free_trial_days,
            "durations": durations,
        }
        return TariffWithDurationsSchema.model_validate(data)

    @staticmethod
    async def invalidate_cache(redis: redis_asyncio.Redis | None) -> None:
        if redis is None:
            return
        try:
            await redis.delete(_CACHE_KEY)
        except Exception as e:  # noqa: BLE001
            logger.warning("tariffs_cache_invalidate_failed", error=str(e))
