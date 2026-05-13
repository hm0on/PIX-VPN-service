"""Balance service: read balance + atomic purchase-with-balance flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InsufficientBalanceError,
    NorthLineClientError,
    NorthLineUnavailableError,
)
from app.core.logging import (
    LEVEL_CRITICAL,
    LEVEL_INFO,
    business_log,
    get_logger,
)
from app.db.models.balance_transaction import (
    BT_REASON_ADMIN_ADJUST,
    BT_REASON_PURCHASE,
    BT_REASON_REFUND,
)
from app.db.models.payment import (
    PAYMENT_PROVIDER_BALANCE,
    PAYMENT_PURPOSE_SUBSCRIPTION,
    PAYMENT_STATUS_PAID,
    Payment,
)
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_FAILED,
    SUB_STATUS_PENDING,
    Subscription,
)
from app.db.models.user import User
from app.repositories.balance_transaction_repo import BalanceTransactionRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.services.northline_branding import build_subscription_branding
from app.services.northline_client import NorthLineClient
from app.services.tariff_service import TariffService

logger = get_logger("balance_service")


class BalanceService:
    def __init__(
        self,
        session: AsyncSession,
        northline: NorthLineClient,
    ) -> None:
        self.session = session
        self.northline = northline
        self.tariffs = TariffService(session)
        self.subs_repo = SubscriptionRepository(session)
        self.payments_repo = PaymentRepository(session)
        self.bt_repo = BalanceTransactionRepository(session)

    async def get_balance_kopecks(self, *, user: User) -> int:
        return int(user.balance_kopecks)

    async def add_admin_adjust(
        self,
        *,
        user_id: int,
        amount_kopecks: int,
        reason: str,
        admin_key_id: int,
        admin_key_label: str | None = None,
    ) -> int:
        """Apply a signed admin balance adjustment.

        Locks the user row, updates balance, and writes a BalanceTransaction
        with reason='admin_adjust'. Caller (admin endpoint) is responsible for
        the audit log + outbox notification + commit.

        Returns the new balance in kopecks.
        """
        if amount_kopecks == 0:
            return int((await self._lock_user(user_id)).balance_kopecks)

        locked_user = await self._lock_user(user_id)
        new_balance = int(locked_user.balance_kopecks) + int(amount_kopecks)
        if new_balance < 0:
            # Forbid negative balance via admin adjust.
            raise InsufficientBalanceError(
                "Adjustment would result in negative balance",
                details={
                    "current_balance_kopecks": int(locked_user.balance_kopecks),
                    "delta_kopecks": int(amount_kopecks),
                },
            )
        locked_user.balance_kopecks = new_balance

        await self.bt_repo.create(
            user_id=user_id,
            amount_kopecks=int(amount_kopecks),
            reason=BT_REASON_ADMIN_ADJUST,
            ref_payment_id=None,
            ref_subscription_id=None,
            description=reason,
            balance_after_kopecks=new_balance,
        )

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="balance_admin_adjusted",
            user_id=user_id,
            message=(
                f"Admin '{admin_key_label or admin_key_id}' adjusted balance "
                f"by {amount_kopecks} kopecks"
            ),
            context={
                "admin_key_id": admin_key_id,
                "admin_key_label": admin_key_label,
                "amount_kopecks": int(amount_kopecks),
                "balance_after_kopecks": new_balance,
                "reason": reason,
            },
        )
        await self.session.flush()
        return new_balance

    async def purchase_with_balance(
        self,
        *,
        user: User,
        tariff_id: int,
        duration_id: int,
        promo_id: int | None = None,
    ) -> tuple[Subscription, int, int]:
        """Atomic purchase-with-balance flow.

        Returns (subscription, balance_after_kopecks, payment_id).

        ``payment_id`` is the row id of the internal Payment created by this
        flow; the bot uses it to render ``"#{payment_id}"`` in the success
        message it edits in-place after this call returns. We deliberately
        do NOT enqueue an outbox row for the success message here — the bot
        owns that UX (one edited message, not a fresh sendMessage on top of
        it). See `bot/app/handlers/purchase.py:_pay_with_balance`.

        Raises InsufficientBalanceError, TariffNotFoundError, TariffDurationNotFoundError,
        NorthLineUnavailableError.
        """
        tariff = await self.tariffs.get_tariff_or_raise(tariff_id)
        duration = await self.tariffs.get_duration_or_raise(
            tariff_id=tariff_id, duration_id=duration_id
        )

        original_price = int(duration.price_kopecks)
        price = original_price

        # ----- Discount promo (optional) -----
        # Same shape as in payment_service.create_subscription_payment.
        # Balance-paid purchases settle synchronously here, so we also
        # record the activation in-flight (no webhook later).
        promo_meta: dict[str, object] = {}
        applied_promo_id: int | None = None
        applied_percent: int | None = None
        if promo_id is not None:
            try:
                from app.db.models.promo_code import (  # noqa: WPS433
                    PROMO_TYPE_DISCOUNT_PERCENT,
                    PromoCode,
                )
                from app.services import promo_service as _promo_svc  # noqa: WPS433

                promo_row = (
                    await self.session.execute(
                        select(PromoCode).where(PromoCode.id == int(promo_id))
                    )
                ).scalar_one_or_none()
                if promo_row is not None and promo_row.type == PROMO_TYPE_DISCOUNT_PERCENT:
                    applied_percent = int(promo_row.value)
                    price = _promo_svc.compute_discounted_price(
                        original_price, applied_percent
                    )
                    applied_promo_id = int(promo_row.id)
                    promo_meta = {
                        "promo_id": applied_promo_id,
                        "promo_type": "discount_percent",
                        "discount_percent": applied_percent,
                        "original_amount_kopecks": original_price,
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "balance_promo_discount_lookup_failed",
                    promo_id=promo_id,
                    user_id=user.id,
                    error=str(e),
                )

        # ----- Atomic block: lock user, debit, create payment + pending subscription -----
        locked_user = await self._lock_user(user.id)

        if locked_user.balance_kopecks < price:
            raise InsufficientBalanceError(
                "Insufficient balance",
                details={
                    "current_balance_kopecks": int(locked_user.balance_kopecks),
                    "required_kopecks": price,
                },
            )

        balance_after = int(locked_user.balance_kopecks) - price
        locked_user.balance_kopecks = balance_after

        sub = await self.subs_repo.create(
            user_id=locked_user.id,
            tariff_id=tariff.id,
            tariff_duration_id=duration.id,
            devices=tariff.devices,
            days=duration.days,
            status=SUB_STATUS_PENDING,
            is_free_trial=False,
        )

        payment = await self.payments_repo.create(
            user_id=locked_user.id,
            subscription_id=sub.id,
            purpose=PAYMENT_PURPOSE_SUBSCRIPTION,
            provider=PAYMENT_PROVIDER_BALANCE,
            external_id=None,
            amount_kopecks=price,
            currency="RUB",
            status=PAYMENT_STATUS_PAID,
            paid_at=datetime.now(tz=timezone.utc),
            meta=dict(promo_meta) if promo_meta else {},
        )

        # Balance-paid → settle promo activation synchronously (no webhook).
        if applied_promo_id is not None and applied_percent is not None:
            try:
                from app.services.promo_service import PromoService  # noqa: WPS433

                discount_kopecks = max(0, original_price - price)
                await PromoService(self.session).record_discount_activation(
                    promo_id=applied_promo_id,
                    user_id=locked_user.id,
                    payment_id=payment.id,
                    discount_kopecks=discount_kopecks,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "balance_promo_activation_failed",
                    promo_id=applied_promo_id,
                    payment_id=payment.id,
                    error=str(e),
                )

        await self.bt_repo.create(
            user_id=locked_user.id,
            amount_kopecks=-price,
            reason=BT_REASON_PURCHASE,
            ref_payment_id=payment.id,
            ref_subscription_id=sub.id,
            description=f"Purchase tariff '{tariff.code}' for {duration.days} days",
            balance_after_kopecks=balance_after,
        )

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="balance_purchase_pending",
            user_id=locked_user.id,
            message=f"Balance debited {price} kopecks for tariff {tariff.code}",
            context={
                "subscription_id": sub.id,
                "payment_id": payment.id,
                "tariff_id": tariff.id,
                "duration_id": duration.id,
                "price_kopecks": price,
                "balance_after_kopecks": balance_after,
            },
        )
        await self.session.commit()

        # ----- Out-of-transaction: call NorthLine -----
        idempotency_key = str(uuid.uuid4())
        try:
            key_resp = await self.northline.create_key(
                days=duration.days,
                devices=tariff.devices,
                idempotency_key=idempotency_key,
                # LTE add-on size from the tariff (default 35GB for all
                # public tariffs, set per-row via migration 0012).
                lte_gb=getattr(tariff, "lte_gb_per_month", None),
                # Unlimited VPN-traffic flag (migration 0018 — все
                # публичные тарифы TRUE; без этого провайдер выдаёт
                # дефолтные 1000 GB / устройство / 30 дней, а мы
                # маркетим безлимит). ``None`` опускает поле в запросе,
                # чтобы для legacy тарифов с FALSE не отправлять явный
                # негатив (получают провайдерский дефолт).
                unlimited_traffic=(
                    True
                    if getattr(tariff, "is_unlimited_traffic", False)
                    else None
                ),
                # Per-key branding override: VPN-клиент покажет
                # "PIX VPN · BASIC/PLUS/MAX" вместо общего "PIX VPN".
                branding=build_subscription_branding(
                    tariff_code=getattr(tariff, "code", None),
                    is_free_trial=False,
                ),
                metadata={
                    "user_tg_id": locked_user.tg_id,
                    "internal_subscription_id": str(sub.id),
                    "payment_id": payment.id,
                },
            )
        except (NorthLineUnavailableError, NorthLineClientError) as e:
            await self._refund_after_failure(
                user_id=locked_user.id,
                sub_id=sub.id,
                payment_id=payment.id,
                price_kopecks=price,
                error=e,
            )
            raise NorthLineUnavailableError(
                "Could not issue key after balance debit; refunded",
                details={
                    "subscription_id": sub.id,
                    "refund_kopecks": price,
                },
            ) from e

        # ----- Activate subscription -----
        now = datetime.now(tz=timezone.utc)
        sub_db = await self.subs_repo.get_by_id(sub.id)
        assert sub_db is not None  # noqa: S101
        sub_db.status = SUB_STATUS_ACTIVE
        sub_db.provider_subscription_id = key_resp.subscription_id
        sub_db.key_url = key_resp.key
        sub_db.started_at = now
        # NB: ``key_resp.expires_at`` is intentionally ignored. NorthLine's
        # test-mode endpoint returns ``expires_at == now`` for fake keys,
        # which would mark the subscription as already expired. The
        # authoritative period is what the user paid for (``duration.days``);
        # we reconcile against the provider periodically via
        # ``app.services.subscription_reconcile`` to catch drift in prod.
        sub_db.expires_at = now + timedelta(days=duration.days)
        await self.session.flush()

        # NB: no outbox row for the success message — the bot edits the
        # original payment-method message in-place once this method returns
        # (see ``bot/app/handlers/purchase.py:_pay_with_balance``). Enqueueing
        # here would produce a duplicate sendMessage on top of the edit.

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="balance_purchase_completed",
            user_id=locked_user.id,
            message=f"Subscription {sub_db.id} activated via balance",
            context={
                "subscription_id": sub_db.id,
                "payment_id": payment.id,
                "provider_subscription_id": key_resp.subscription_id,
            },
        )
        await self.session.commit()
        await self.session.refresh(sub_db)
        return sub_db, balance_after, payment.id

    # ---------- internals ----------

    async def _lock_user(self, user_id: int) -> User:
        """SELECT ... FOR UPDATE on the user row (no-op on SQLite)."""
        dialect = (
            self.session.bind.dialect.name if self.session.bind else "postgresql"
        )
        stmt = select(User).where(User.id == user_id)
        if dialect != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        user = result.scalar_one()
        return user

    async def _refund_after_failure(
        self,
        *,
        user_id: int,
        sub_id: int,
        payment_id: int,
        price_kopecks: int,
        error: Exception,
    ) -> None:
        """Compensating action: re-credit the balance and mark subscription as failed."""
        locked_user = await self._lock_user(user_id)
        new_balance = int(locked_user.balance_kopecks) + price_kopecks
        locked_user.balance_kopecks = new_balance

        sub_db = await self.subs_repo.get_by_id(sub_id)
        if sub_db is not None:
            sub_db.status = SUB_STATUS_FAILED
            sub_db.deactivation_reason = (
                f"NorthLine failure: {getattr(error, 'error_code', '')} "
                f"{getattr(error, 'message', '')}"
            ).strip()

        payment = await self.session.get(Payment, payment_id)
        if payment is not None:
            payment.status = "refunded"

        await self.bt_repo.create(
            user_id=user_id,
            amount_kopecks=price_kopecks,
            reason=BT_REASON_REFUND,
            ref_payment_id=payment_id,
            ref_subscription_id=sub_id,
            description="Refund after VPN provider failure",
            balance_after_kopecks=new_balance,
        )

        # NOTE: We deliberately do NOT enqueue an outbox notification here.
        # The bot's purchase handler already raises ``BackendClientError`` on
        # the 502 response and edits the user's original message to the
        # ``vpn_provider_unavailable`` text ("Похоже, что-то пошло не так..."),
        # which is enough. Adding an outbox message on top means the user
        # sees N+1 notifications (where N was up to the bot's HTTP retry
        # count) — the original complaint that surfaced this whole change.

        await business_log(
            self.session,
            level=LEVEL_CRITICAL,
            event="balance_purchase_refunded",
            user_id=user_id,
            message="VPN provider failed; balance refunded",
            context={
                "subscription_id": sub_id,
                "payment_id": payment_id,
                "refund_kopecks": price_kopecks,
                "balance_after_kopecks": new_balance,
                "error_code": getattr(error, "error_code", None),
            },
        )
        await self.session.commit()
