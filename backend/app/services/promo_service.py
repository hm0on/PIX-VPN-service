"""Promo-code service: validate, apply (balance / discount), record activations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PromoCodeNotFoundError,
    PromoCodeUnavailableError,
)
from app.core.logging import LEVEL_INFO, business_log, get_logger
from app.db.models.balance_transaction import (
    BT_REASON_PROMO_BONUS,
    BalanceTransaction,
)
from app.db.models.promo_activation import PromoActivation
from app.db.models.promo_code import (
    PROMO_TYPE_BALANCE,
    PROMO_TYPE_DISCOUNT_PERCENT,
    PromoCode,
)
from app.db.models.user import User
from app.repositories.promo_activation_repo import PromoActivationRepository
from app.repositories.promo_code_repo import PromoCodeRepository
from app.schemas.promo import PromoApplyResult

logger = get_logger("promo_service")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Coerce a possibly-naive datetime (e.g. from SQLite) to UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def compute_discounted_price(price_kopecks: int, percent: int) -> int:
    """price * (100 - percent) // 100 (round down to kopecks)."""
    if percent <= 0:
        return int(price_kopecks)
    if percent >= 100:
        return 0
    return int(price_kopecks) * (100 - int(percent)) // 100


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PromoCodeRepository(session)
        self.activations_repo = PromoActivationRepository(session)

    # ---------- public API ----------

    async def validate_and_apply(
        self, *, code: str, user: User
    ) -> PromoApplyResult:
        """Validate a promo code, apply the side-effects, and return a result.

        - Balance promos: credit user balance, create PromoActivation,
          increment current_activations. The "promo applied" notification
          is rendered to the user *synchronously* by the bot from the HTTP
          response — we deliberately do NOT enqueue an outbox text here,
          since that would deliver a second copy.
        - Discount promos: only return promo metadata. The activation row
          and current_activations bump happen later in
          `record_discount_activation` after the corresponding payment is paid.
        """
        normalized_code = code.strip()
        if not normalized_code:
            raise PromoCodeNotFoundError(
                "Promo code not found",
                details={"code": code},
            )

        # 1. Lookup (case-insensitive via CITEXT / lower()).
        existing = await self.repo.get_by_code(normalized_code)
        if existing is None:
            raise PromoCodeNotFoundError(
                "Promo code not found",
                details={"code": normalized_code},
            )

        # 2. SELECT ... FOR UPDATE on the promo row.
        promo = await self.repo.lock_for_update(existing.id)
        if promo is None:
            raise PromoCodeNotFoundError(
                "Promo code not found",
                details={"code": normalized_code},
            )

        # 3. Validate.
        self._ensure_active_and_in_window(promo)
        self._ensure_total_capacity(promo)
        await self._ensure_per_user_capacity(promo, user)

        # 4. Apply.
        if promo.type == PROMO_TYPE_BALANCE:
            return await self._apply_balance(promo, user)
        if promo.type == PROMO_TYPE_DISCOUNT_PERCENT:
            return await self._apply_discount(promo, user)

        # Unknown type — treat as unavailable.
        raise PromoCodeUnavailableError(
            "Promo code is not available",
            reason="invalid_type",
        )

    async def record_discount_activation(
        self,
        *,
        promo_id: int,
        user_id: int,
        payment_id: int,
        discount_kopecks: int,
    ) -> PromoActivation | None:
        """Persist a discount-promo activation after a successful payment.

        Called from payment_service.process_webhook_payment when a payment
        with an attached promo_id transitions to `paid`.

        On race-condition exhaustion: log a warning and return None — the
        user has already paid, we must not raise.
        """
        promo = await self.repo.lock_for_update(promo_id)
        if promo is None:
            logger.warning(
                "promo_record_discount_missing",
                promo_id=promo_id,
                user_id=user_id,
                payment_id=payment_id,
            )
            return None

        # Best-effort visibility: if the promo's validity window passed
        # between FSM-time validation and the payment-paid webhook, log it
        # but still record the activation — the user already paid the
        # discounted price, refusing to record would only hide the fact
        # that we charged them with an expired promo.
        now = _now()
        if promo.valid_until is not None and now > _aware(promo.valid_until):
            logger.warning(
                "promo_record_discount_after_expiry",
                promo_id=promo_id,
                user_id=user_id,
                payment_id=payment_id,
                valid_until=_aware(promo.valid_until).isoformat(),
                now=now.isoformat(),
            )
        if not promo.is_active:
            logger.warning(
                "promo_record_discount_inactive",
                promo_id=promo_id,
                user_id=user_id,
                payment_id=payment_id,
            )

        # Re-check limits at apply time (race protection).
        if promo.max_total_activations is not None and (
            promo.current_activations >= promo.max_total_activations
        ):
            logger.warning(
                "promo_record_discount_exhausted",
                promo_id=promo_id,
                user_id=user_id,
                payment_id=payment_id,
                current_activations=promo.current_activations,
                max_total_activations=promo.max_total_activations,
            )
            return None

        per_user = await self.activations_repo.count_user_activations(
            promo_id=promo_id, user_id=user_id
        )
        if per_user >= promo.max_per_user:
            logger.warning(
                "promo_record_discount_per_user_exceeded",
                promo_id=promo_id,
                user_id=user_id,
                payment_id=payment_id,
                per_user=per_user,
                max_per_user=promo.max_per_user,
            )
            return None

        activation = await self.activations_repo.create(
            promo_id=promo.id,
            user_id=user_id,
            payment_id=payment_id,
            amount_applied_kopecks=int(discount_kopecks),
        )
        await self.repo.increment_activations(promo.id)

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="promo_discount_recorded",
            user_id=user_id,
            message=f"Discount promo '{promo.code}' applied to payment",
            context={
                "code": promo.code,
                "promo_id": promo.id,
                "payment_id": payment_id,
                "discount_kopecks": int(discount_kopecks),
            },
        )
        return activation

    # ---------- internals ----------

    def _ensure_active_and_in_window(self, promo: PromoCode) -> None:
        if not promo.is_active:
            raise PromoCodeUnavailableError(
                "Promo code is not available",
                reason="inactive",
            )
        now = _now()
        if promo.valid_from is not None and now < _aware(promo.valid_from):
            raise PromoCodeUnavailableError(
                "Promo code is not available",
                reason="not_started",
            )
        if promo.valid_until is not None and now > _aware(promo.valid_until):
            raise PromoCodeUnavailableError(
                "Promo code is not available",
                reason="expired",
            )

    def _ensure_total_capacity(self, promo: PromoCode) -> None:
        if promo.max_total_activations is None:
            return
        if promo.current_activations >= promo.max_total_activations:
            raise PromoCodeUnavailableError(
                "Promo code is not available",
                reason="max_total_activations_exceeded",
            )

    async def _ensure_per_user_capacity(
        self, promo: PromoCode, user: User
    ) -> None:
        per_user = await self.activations_repo.count_user_activations(
            promo_id=promo.id, user_id=user.id
        )
        if per_user >= promo.max_per_user:
            raise PromoCodeUnavailableError(
                "Promo code is not available",
                reason="max_per_user_exceeded",
            )

    async def _apply_balance(
        self, promo: PromoCode, user: User
    ) -> PromoApplyResult:
        amount = int(promo.value)

        # Lock user row, credit balance.
        locked_user = await self._lock_user(user.id)
        new_balance = int(locked_user.balance_kopecks) + amount
        locked_user.balance_kopecks = new_balance

        # Balance transaction.
        bt = BalanceTransaction(
            user_id=locked_user.id,
            amount_kopecks=amount,
            reason=BT_REASON_PROMO_BONUS,
            description=f"Promo code '{promo.code}' applied",
            balance_after_kopecks=new_balance,
        )
        self.session.add(bt)
        await self.session.flush()

        # Activation row.
        activation = PromoActivation(
            promo_id=promo.id,
            user_id=locked_user.id,
            payment_id=None,
            amount_applied_kopecks=amount,
        )
        self.session.add(activation)
        await self.session.flush()

        # Increment current_activations on the locked promo row.
        await self.repo.increment_activations(promo.id)

        # NOTE: we deliberately do NOT enqueue an outbox notification here.
        # The bot's promo handlers (see ``bot/app/handlers/{promo,catalog,
        # profile}.py``) already render ``promo_balance_applied`` to the
        # user synchronously after this endpoint returns. Re-sending it via
        # the outbox would deliver a second, identical message a second or
        # two later, which is exactly the bug users were reporting.

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="promo_balance_applied",
            user_id=locked_user.id,
            message=f"Balance promo '{promo.code}' applied (+{amount} kopecks)",
            context={
                "code": promo.code,
                "promo_id": promo.id,
                "value_kopecks": amount,
                "balance_after_kopecks": new_balance,
            },
        )

        message_text = (
            f"Промокод применён: на баланс зачислено {amount // 100} ₽."
        )
        return PromoApplyResult(
            type=PROMO_TYPE_BALANCE,
            amount_kopecks=amount,
            promo_id=promo.id,
            message_text=message_text,
            balance_kopecks=new_balance,
        )

    async def _apply_discount(
        self, promo: PromoCode, user: User
    ) -> PromoApplyResult:
        # Discount: just return the metadata. Bot stores promo_id in FSM
        # and passes it back when creating a payment. The activation row
        # is created later via record_discount_activation after `paid`.
        percent = int(promo.value)
        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="promo_discount_validated",
            user_id=user.id,
            message=f"Discount promo '{promo.code}' validated ({percent}%)",
            context={
                "code": promo.code,
                "promo_id": promo.id,
                "percent": percent,
            },
        )
        return PromoApplyResult(
            type=PROMO_TYPE_DISCOUNT_PERCENT,
            percent=percent,
            promo_id=promo.id,
            message_text=f"Промокод применён: скидка {percent}%.",
        )

    async def _lock_user(self, user_id: int) -> User:
        bind = self.session.get_bind()
        stmt = select(User).where(User.id == user_id)
        if bind is None or bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one()
