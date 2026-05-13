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
from app.db.models.outbox import OUTBOX_MSG_TEXT
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_FAILED,
    SUB_STATUS_PENDING,
    Subscription,
)
from app.db.models.tariff import Tariff
from app.db.models.user import User
from app.repositories.outbox_repo import OutboxRepository
from app.repositories.referral_repo import ReferralRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.user_repo import UserRepository
from app.services import personal_promo_service
from app.services.northline_branding import build_subscription_branding
from app.services.northline_client import NorthLineClient

logger = get_logger("free_trial_service")

# Default trial length in days when ``tariff.free_trial_days`` is unset.
# Bumped 3 → 5 in conversion-pack 2026-05-13 to match the new FREE-tariff
# seed value. Authoritative source is still the DB row; this is only a
# defensive fallback if seeds didn't run.
FREE_TRIAL_DEFAULT_DAYS = 5
# Fallback when ``tariff.devices`` is somehow unset. The FREE tariff seed
# carries the authoritative number (currently 1); historically this was 3
# and the constant was hardcoded above the tariff lookup, ignoring the row.
FREE_TRIAL_DEFAULT_DEVICES = 1


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
        # Take ``devices`` from the FREE tariff row so ops can tune the
        # trial config from the admin panel (or via seeds.py) without a
        # code change. Fallback to the legacy 1-device default if the row
        # is somehow missing the value.
        devices = int(tariff.devices) if tariff.devices else FREE_TRIAL_DEFAULT_DEVICES
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
                # Free trial inherits the LTE bundle from the FREE tariff
                # row (admin can set 0 if the trial should not include LTE).
                lte_gb=getattr(tariff, "lte_gb_per_month", None),
                # Unlimited VPN-traffic (migration 0018 — FREE = TRUE).
                # Без этого NorthLine выдаёт ~334 GB для 2 устр × 5 дн
                # (дефолт 1000 GB/устр/30д масштабируется по days/30).
                unlimited_traffic=(
                    True
                    if getattr(tariff, "is_unlimited_traffic", False)
                    else None
                ),
                # Per-key branding: VPN-клиент покажет "PIX VPN · TRIAL".
                branding=build_subscription_branding(
                    tariff_code=getattr(tariff, "code", None),
                    is_free_trial=True,
                ),
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

        # Conversion-pack 2026-05-13: reward the *referrer* with a personal
        # 15% promo (valid 30 days) when their invitee activates the trial.
        # This is independent of the existing "+70 ₽ when invitee pays
        # first time" bonus (see ``referral_service.apply_referrer_bonus``)
        # — the referrer can collect both.
        #
        # Idempotency is enforced both by the ``trial_bonus_issued_at`` flag
        # on the referral row AND by the deterministic promo code
        # ``REFTRIAL15_<sub.id>`` (UNIQUE in promo_codes; ``issue_personal_
        # discount`` is itself idempotent on conflict).
        #
        # Any failure here MUST NOT propagate — the user already has their
        # trial key persisted and committed above. Worst case the referrer
        # silently misses a promo, which we'll surface via business_log.
        try:
            await self._issue_referrer_trial_bonus(user=user, sub=sub)
        except Exception:
            logger.exception(
                "referrer_trial_bonus_unexpected_error",
                user_id=user.id,
                subscription_id=sub.id,
            )

        return sub

    async def _issue_referrer_trial_bonus(
        self, *, user: User, sub: Subscription
    ) -> None:
        """Mint REFTRIAL15_<sub_id> for the referrer and DM them.

        Separate transaction from the trial activation above. Safe to call
        repeatedly: both the ``trial_bonus_issued_at`` guard and the
        personal-promo factory's ON-CONFLICT path make this no-op on retry.
        """
        referral_repo = ReferralRepository(self.session)
        referral = await referral_repo.get_by_referee(user.id)
        if referral is None:
            return
        if referral.trial_bonus_issued_at is not None:
            return

        code = f"REFTRIAL15_{sub.id}"
        await personal_promo_service.issue_personal_discount(
            self.session,
            user_id=referral.referrer_id,
            code=code,
            percent=15,
            valid_for=timedelta(days=30),
            description=(
                f"Referrer trial bonus: referee_user_id={user.id} "
                f"trial_subscription_id={sub.id}"
            ),
        )

        referral.trial_bonus_issued_at = datetime.now(tz=timezone.utc)
        await self.session.flush()

        # Look up the referrer to get their tg_id for the outbox DM.
        user_repo = UserRepository(self.session)
        referrer = await user_repo.get_by_id(referral.referrer_id)
        if referrer is not None and referrer.tg_id:
            outbox = OutboxRepository(self.session)
            await outbox.enqueue(
                user_id=referrer.id,
                chat_id=referrer.tg_id,
                message_type=OUTBOX_MSG_TEXT,
                payload={
                    "text_key": "referrer_trial_bonus_promo",
                    "format_kwargs": {"promo_code": code},
                    "parse_mode": "HTML",
                    "kind": "referrer_trial_bonus_promo",
                },
            )
        else:
            logger.warning(
                "referrer_trial_bonus_outbox_skipped_no_tg",
                referrer_id=referral.referrer_id,
                referee_id=user.id,
                promo_code=code,
            )

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="referrer_trial_bonus_issued",
            user_id=referral.referrer_id,
            message=(
                f"Referrer received 15% personal promo for referee "
                f"user_id={user.id} trial sub_id={sub.id}"
            ),
            context={
                "referee_id": user.id,
                "referrer_id": referral.referrer_id,
                "promo_code": code,
                "trial_subscription_id": sub.id,
                "valid_for_days": 30,
            },
        )
        await self.session.commit()
