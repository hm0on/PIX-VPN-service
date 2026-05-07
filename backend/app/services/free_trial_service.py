"""FREE-trial activation service."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    FreeTrialAlreadyUsedError,
    NorthLineClientError,
    NorthLineUnavailableError,
    TariffNotFoundError,
)
from app.core.logging import (
    LEVEL_CRITICAL,
    LEVEL_INFO,
    business_log,
    get_logger,
    tech_log,
)
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_FAILED,
    SUB_STATUS_PENDING,
    Subscription,
)
from app.db.models.tariff import Tariff
from app.db.models.user import User
from app.repositories.subscription_repo import SubscriptionRepository
from app.services.northline_client import NorthLineClient

logger = get_logger("free_trial_service")

FREE_TRIAL_DEFAULT_DAYS = 3
FREE_TRIAL_DEFAULT_DEVICES = 3


class FreeTrialService:
    def __init__(
        self,
        session: AsyncSession,
        northline: NorthLineClient,
    ) -> None:
        self.session = session
        self.northline = northline
        self.repo = SubscriptionRepository(session)

    async def is_free_trial_used(self, *, user_id: int) -> bool:
        return await self.repo.has_free_trial(user_id=user_id)

    async def activate_free_trial(self, *, user: User) -> Subscription:
        """Issue a FREE-trial key for `user`.

        Raises:
            FreeTrialAlreadyUsedError, NorthLineUnavailableError, TariffNotFoundError.
        """
        if await self.is_free_trial_used(user_id=user.id):
            raise FreeTrialAlreadyUsedError(
                "Free trial already used",
                details={"user_id": user.id},
            )

        # Find the FREE tariff.
        tariff_result = await self.session.execute(
            select(Tariff).where(
                Tariff.is_free_trial.is_(True),
                Tariff.is_active.is_(True),
            )
        )
        tariff = tariff_result.scalar_one_or_none()
        if tariff is None:
            raise TariffNotFoundError("FREE tariff not configured")

        days = tariff.free_trial_days or FREE_TRIAL_DEFAULT_DAYS
        # Spec: free trial = 3 devices regardless of tariff.devices field.
        devices = FREE_TRIAL_DEFAULT_DEVICES
        idempotency_key = str(uuid.uuid4())

        sub = await self.repo.create(
            user_id=user.id,
            tariff_id=tariff.id,
            tariff_duration_id=None,
            devices=devices,
            days=days,
            status=SUB_STATUS_PENDING,
            is_free_trial=True,
        )

        await tech_log(
            self.session,
            action="free_trial:create_pending",
            user_id=user.id,
            payload={
                "subscription_id": sub.id,
                "days": days,
                "devices": devices,
                "idempotency_key": idempotency_key,
            },
        )
        await self.session.commit()

        # Call NorthLine.
        try:
            key_resp = await self.northline.create_key(
                days=days,
                devices=devices,
                idempotency_key=idempotency_key,
                metadata={
                    "user_tg_id": user.tg_id,
                    "internal_subscription_id": str(sub.id),
                    "free_trial": True,
                },
            )
        except (NorthLineUnavailableError, NorthLineClientError) as e:
            sub.status = SUB_STATUS_FAILED
            await self.session.flush()
            await business_log(
                self.session,
                level=LEVEL_CRITICAL,
                event="free_trial_failed_provider_error",
                user_id=user.id,
                message=f"NorthLine failed for free trial: {e!s}",
                context={
                    "subscription_id": sub.id,
                    "error_code": getattr(e, "error_code", None),
                },
            )
            await self.session.commit()
            raise NorthLineUnavailableError(
                "Could not issue free-trial key",
                details={"subscription_id": sub.id},
            ) from e

        # Persist key and activate.
        now = datetime.now(tz=timezone.utc)
        sub.status = SUB_STATUS_ACTIVE
        sub.provider_subscription_id = key_resp.subscription_id
        sub.key_url = key_resp.key
        sub.started_at = now
        # NB: ``key_resp.expires_at`` is intentionally ignored. NorthLine's
        # test-mode endpoint returns ``expires_at == now`` for fake keys,
        # which would mark the subscription as already expired. The
        # authoritative period is what the user paid for (``days``); we
        # reconcile against the provider periodically via
        # ``app.services.subscription_reconcile`` to catch drift in prod.
        sub.expires_at = now + timedelta(days=days)
        await self.session.flush()

        # No outbox enqueue here. The bot endpoint that calls this service
        # awaits NorthLine synchronously and edits the original chat message
        # to ``key_issued_free_trial`` itself (see
        # ``bot/app/handlers/catalog.py::_handle_free_trial``). Enqueuing an
        # outbox message in addition produced a duplicate delivery — the
        # synchronous edit (with the proper ``key_issued_kb``) followed
        # immediately by the worker's outbox message (which only had a single
        # «Как подключиться» button). Mirrors the same fix applied to the
        # paid-purchase path in ``BalanceService.purchase_with_balance``.

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="free_trial_activated",
            user_id=user.id,
            message=f"Free trial activated for tg_id={user.tg_id}",
            context={
                "subscription_id": sub.id,
                "provider_subscription_id": key_resp.subscription_id,
                "days": days,
                "devices": devices,
            },
        )
        await self.session.commit()
        await self.session.refresh(sub)
        return sub
