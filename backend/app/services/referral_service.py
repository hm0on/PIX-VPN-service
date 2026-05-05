"""Referral service.

- `register_referral`: bind a brand-new referee to a referrer (called from the
  bot's /start handler / users/upsert payload parsing).
- `has_paid_history`: helper to decide whether the referee already paid.
- `auto_discount_for_referee`: returns 10 (%) for first-purchase auto-discount.
- `apply_referrer_bonus`: triggered after a referee's PAID payment — credits
  100 RUB to the referrer's balance, idempotent per referral.
- `get_stats`: invited count + earned kopecks for the referral profile screen.

Models `Referral` are owned by the Backend Promo agent — imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    RefereeAlreadyHasPurchaseError,
    ReferralAlreadyExistsError,
    ReferralSelfReferralError,
)
from app.core.logging import LEVEL_INFO, business_log, get_logger
from app.db.models.balance_transaction import (
    BT_REASON_REFERRAL_BONUS,
    BalanceTransaction,
)
from app.db.models.outbox import OUTBOX_MSG_TEXT
from app.db.models.payment import (
    PAYMENT_PURPOSE_TOPUP,
    PAYMENT_STATUS_PAID,
    Payment,
)
from app.db.models.user import User
from app.repositories.outbox_repo import OutboxRepository
from app.repositories.referral_repo import ReferralRepository

logger = get_logger("referral_service")

REFERRAL_BONUS_KOPECKS = 10000  # 100 RUB
REFERRAL_AUTO_DISCOUNT_PERCENT = 10


@dataclass
class ReferralStats:
    invited: int
    earned_kopecks: int


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def register_referral(
    session: AsyncSession,
    *,
    referrer_user: User,
    referee_user: User,
    is_new: bool,
) -> Any | None:
    """Create a Referral row if all preconditions are met.

    Preconditions:
        - referee was created in this same /start handling (`is_new=True`);
        - referrer != referee;
        - no existing Referral row for the referee;
        - referee has no `paid` payment history (defensive: deep-link came late).

    Returns the created Referral, or None if skipped.
    Raises domain errors only for callers who care; the API layer logs+ignores.
    """
    if not is_new:
        logger.info(
            "referral_skip_not_new",
            referrer_id=referrer_user.id,
            referee_id=referee_user.id,
        )
        return None

    if referrer_user.id == referee_user.id:
        raise ReferralSelfReferralError()

    repo = ReferralRepository(session)
    existing = await repo.get_by_referee(referee_user.id)
    if existing is not None:
        raise ReferralAlreadyExistsError()

    if await has_paid_history(session, referee_user.id):
        raise RefereeAlreadyHasPurchaseError()

    row = await repo.create(
        referrer_id=referrer_user.id, referee_id=referee_user.id
    )
    await business_log(
        session,
        level=LEVEL_INFO,
        event="referral_registered",
        user_id=referee_user.id,
        message=(
            f"Referee user_id={referee_user.id} registered for "
            f"referrer user_id={referrer_user.id}"
        ),
        context={
            "referrer_id": referrer_user.id,
            "referee_id": referee_user.id,
        },
    )
    return row


# ---------------------------------------------------------------------------
# Helpers used by purchase flow
# ---------------------------------------------------------------------------


async def has_paid_history(session: AsyncSession, user_id: int) -> bool:
    """True if the user already has at least one paid payment with amount > 0."""
    result = await session.execute(
        select(Payment.id)
        .where(
            Payment.user_id == user_id,
            Payment.status == PAYMENT_STATUS_PAID,
            Payment.amount_kopecks > 0,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def auto_discount_for_referee(
    session: AsyncSession, user: User
) -> int | None:
    """Return REFERRAL_AUTO_DISCOUNT_PERCENT if the user is an unpaid referee."""
    repo = ReferralRepository(session)
    referral = await repo.get_by_referee(user.id)
    if referral is None:
        return None
    if await has_paid_history(session, user.id):
        return None
    return REFERRAL_AUTO_DISCOUNT_PERCENT


# ---------------------------------------------------------------------------
# Bonus payout (called from payment webhook)
# ---------------------------------------------------------------------------


async def apply_referrer_bonus(
    session: AsyncSession,
    *,
    referee_user: User,
    referee_payment: Payment,
) -> None:
    """Pay out the +100 ₽ referrer bonus on the referee's first paid payment.

    Idempotent: if `bonus_paid` is already True, returns immediately.
    Skips topups and zero-amount payments (caller is expected to filter, but we
    double-check to be defensive against future code paths).
    """
    if referee_payment.purpose == PAYMENT_PURPOSE_TOPUP:
        return
    if int(referee_payment.amount_kopecks or 0) <= 0:
        return

    repo = ReferralRepository(session)
    referral = await repo.get_by_referee(referee_user.id)
    if referral is None:
        return
    if referral.bonus_paid:
        return

    # Lock the referrer row to safely bump the balance.
    bind = session.get_bind()
    stmt = select(User).where(User.id == referral.referrer_id)
    if bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    referrer = result.scalar_one_or_none()
    if referrer is None:
        logger.warning(
            "referral_bonus_skip_referrer_missing",
            referral_id=referral.id,
            referrer_id=referral.referrer_id,
        )
        return

    new_balance = int(referrer.balance_kopecks) + REFERRAL_BONUS_KOPECKS
    referrer.balance_kopecks = new_balance

    tx = BalanceTransaction(
        user_id=referrer.id,
        amount_kopecks=REFERRAL_BONUS_KOPECKS,
        reason=BT_REASON_REFERRAL_BONUS,
        ref_payment_id=referee_payment.id,
        ref_subscription_id=None,
        description=(
            f"Referral bonus for referee user_id={referee_user.id} "
            f"payment_id={referee_payment.id}"
        ),
        balance_after_kopecks=new_balance,
    )
    session.add(tx)

    referral.bonus_paid = True
    referral.bonus_paid_at = _now()
    referral.referee_first_purchase_id = referee_payment.id
    await session.flush()

    # Outbox: notify the referrer.
    username = referee_user.username or "друг"
    outbox = OutboxRepository(session)
    await outbox.enqueue(
        user_id=referrer.id,
        chat_id=referrer.tg_id,
        message_type=OUTBOX_MSG_TEXT,
        payload={
            "text_key": "referral_bonus_credited",
            "format_kwargs": {"username": username},
            "parse_mode": "HTML",
            "kind": "referral_bonus_credited",
        },
    )

    await business_log(
        session,
        level=LEVEL_INFO,
        event="referral_bonus_credited",
        user_id=referrer.id,
        message=(
            f"Referral bonus +{REFERRAL_BONUS_KOPECKS} kopecks credited to "
            f"referrer user_id={referrer.id} for referee user_id={referee_user.id}"
        ),
        context={
            "referee_id": referee_user.id,
            "payment_id": referee_payment.id,
            "amount_kopecks": REFERRAL_BONUS_KOPECKS,
            "balance_after": new_balance,
            "referral_id": referral.id,
        },
    )


# ---------------------------------------------------------------------------
# Stats for the profile screen
# ---------------------------------------------------------------------------


async def get_stats(session: AsyncSession, user_id: int) -> ReferralStats:
    repo = ReferralRepository(session)
    invited = await repo.count_referrals(user_id)
    earned = await repo.sum_earned(user_id)
    return ReferralStats(invited=invited, earned_kopecks=earned)
