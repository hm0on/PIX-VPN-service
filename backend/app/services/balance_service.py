"""Balance service: read balance + atomic purchase-with-balance flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
from app.db.models.outbox import OUTBOX_MSG_TEXT
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
from app.repositories.outbox_repo import OutboxRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.subscription_repo import SubscriptionRepository
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
        self.outbox_repo = OutboxRepository(session)

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
    ) -> tuple[Subscription, int]:
        """Atomic purchase-with-balance flow.

        Returns (subscription, balance_after_kopecks).

        Raises InsufficientBalanceError, TariffNotFoundError, TariffDurationNotFoundError,
        NorthLineUnavailableError.
        """
        tariff = await self.tariffs.get_tariff_or_raise(tariff_id)
        duration = await self.tariffs.get_duration_or_raise(
            tariff_id=tariff_id, duration_id=duration_id
        )

        price = int(duration.price_kopecks)

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
        sub_db.expires_at = key_resp.expires_at or (
            now + timedelta(days=duration.days)
        )
        await self.session.flush()

        # Outbox: send the key.
        settings = get_settings()
        howto_url = settings.howto_connect_url or ""
        await self.outbox_repo.enqueue(
            user_id=locked_user.id,
            chat_id=locked_user.tg_id,
            message_type=OUTBOX_MSG_TEXT,
            payload={
                "text_key": "key_issued",
                "format_kwargs": {
                    "payment_id": payment.id,
                    "key_url": sub_db.key_url,
                },
                "parse_mode": "HTML",
                "buttons": (
                    [{"text": "Как подключиться", "url": howto_url}]
                    if howto_url
                    else []
                ),
            },
        )

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
        return sub_db, balance_after

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
