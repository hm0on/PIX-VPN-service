"""Personal promo-code factory.

Mints a ``PromoCode`` row scoped to one specific user (``user_id`` is
non-NULL — see ``promo_codes.user_id`` added in migration 0016). The
existing ``PromoService.validate_and_apply`` rejects a personal code if
the applying user doesn't match (``not_for_this_user`` reason).

Two current callers:

1. **Trial-expiring -24h** (worker): when a user's free-trial is about
   to expire and they did NOT come through a referral link (no
   pre-existing 15% auto-discount), we mint ``TRIAL15_<sub_id>`` valid
   for 72 hours and DM them the code. Worker writes directly to SQL —
   the service call below is the canonical path used from the backend
   (e.g. ``free_trial_service`` for the referrer bonus).

2. **Referrer bonus on referee's trial** (free_trial_service): when an
   invited user activates the free trial, we mint
   ``REFTRIAL15_<referee_sub_id>`` valid for 30 days for the *referrer*
   and DM them. The referrer's "+70 ₽ when referee pays" bonus remains
   untouched and independent (see ``Referral.bonus_paid`` vs
   ``trial_bonus_issued_at``).

Idempotency: code is unique in ``promo_codes`` (existing unique
constraint on ``code``). If the requested code already exists we
return the existing row instead of raising — callers can safely retry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.promo_code import PROMO_TYPE_DISCOUNT_PERCENT, PromoCode

log = get_logger("personal_promo")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def issue_personal_discount(
    session: AsyncSession,
    *,
    user_id: int,
    code: str,
    percent: int,
    valid_for: timedelta,
    description: str,
) -> PromoCode:
    """Create (or fetch existing) personal discount-percent promo code.

    Args:
        session: Caller's AsyncSession. Insert is staged via
            ``session.add`` + ``session.flush``; commit is the caller's
            responsibility so we participate in their transaction.
        user_id: Internal ``users.id`` of the recipient. The promo is
            unusable by anyone else (see ``promo_service`` user_id check).
        code: Stable string used as the promo code. Should be
            deterministic for idempotency (e.g. ``TRIAL15_<sub_id>``).
        percent: Integer discount percent (1..100).
        valid_for: ``timedelta`` from now → ``valid_until``.
        description: Free-form admin-facing description (shown in
            promo-codes admin list).

    Returns:
        Either the newly-created or the previously-existing ``PromoCode``.
    """
    existing = (
        await session.execute(select(PromoCode).where(PromoCode.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        log.info(
            "personal_promo_already_exists",
            code=code,
            user_id=user_id,
            promo_id=existing.id,
        )
        return existing

    promo = PromoCode(
        code=code,
        type=PROMO_TYPE_DISCOUNT_PERCENT,
        value=percent,
        max_total_activations=1,
        max_per_user=1,
        current_activations=0,
        valid_from=_now(),
        valid_until=_now() + valid_for,
        is_active=True,
        description=description,
        user_id=user_id,
    )
    session.add(promo)
    try:
        await session.flush()
    except IntegrityError:
        # Кто-то другой создал ту же строку между нашим SELECT и INSERT.
        # SAVEPOINT-семантика SQLAlchemy откатит вставку; перечитываем.
        await session.rollback()
        existing = (
            await session.execute(
                select(PromoCode).where(PromoCode.code == code)
            )
        ).scalar_one()
        log.info(
            "personal_promo_race_lost",
            code=code,
            user_id=user_id,
            promo_id=existing.id,
        )
        return existing

    log.info(
        "personal_promo_issued",
        code=code,
        user_id=user_id,
        promo_id=promo.id,
        percent=percent,
        valid_for_seconds=int(valid_for.total_seconds()),
    )
    return promo


__all__ = ["issue_personal_discount"]
