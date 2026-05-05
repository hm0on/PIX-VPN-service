"""Subscription extension service.

Flow:
    bot → POST /api/bot/subscriptions/{id}/extend → create_extension_payment
    payment provider → webhook → payment_service.process_webhook_payment
        → apply_extension_after_payment (this module)

`payment.meta.subscription_id` is the marker that distinguishes an extend from
a fresh purchase: the webhook handler routes those payments here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import (
    InsufficientBalanceError,
    NorthLineClientError,
    NorthLineUnavailableError,
    NotFoundError,
    SubscriptionNotExtendableError,
    SubscriptionNotFoundError,
    ValidationError,
)
from app.core.logging import (
    LEVEL_CRITICAL,
    LEVEL_INFO,
    business_log,
    get_logger,
    tech_log,
)
from app.db.models.balance_transaction import (
    BT_REASON_PURCHASE,
    BT_REASON_REFUND,
    BalanceTransaction,
)
from app.db.models.outbox import OUTBOX_MSG_TEXT
from app.db.models.payment import (
    PAYMENT_PROVIDER_BALANCE,
    PAYMENT_STATUS_PAID,
    Payment,
)
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    Subscription,
)
from app.db.models.tariff import Tariff, TariffDuration
from app.db.models.user import User
from app.repositories.outbox_repo import OutboxRepository

logger = get_logger("extension_service")

PAYMENT_PURPOSE_EXTEND = "extend_subscription"


@dataclass
class ExtensionPaymentResult:
    payment_id: int
    amount_kopecks: int
    payment_url: str | None
    key_url: str | None  # populated only for balance-paid extensions


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _compute_discounted_price(
    *, base_kopecks: int, discount_percent: int | None
) -> int:
    """Floor-rounded percentage discount; never goes below 0."""
    if not discount_percent:
        return int(base_kopecks)
    pct = max(0, min(100, int(discount_percent)))
    discounted = (int(base_kopecks) * (100 - pct)) // 100
    return max(0, discounted)


async def _lock_user(session: AsyncSession, user_id: int) -> User | None:
    bind = session.get_bind()
    stmt = select(User).where(User.id == user_id)
    if bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Step 1: create the extension payment (called from API endpoint)
# ---------------------------------------------------------------------------


async def create_extension_payment(
    session: AsyncSession,
    *,
    subscription_id: int,
    duration_id: int,
    user: User,
    payment_provider: str,
    promo_code: str | None,
    northline_client: Any | None = None,
) -> ExtensionPaymentResult:
    """Create or fulfil an extension payment.

    For external providers (platega/cryptobot) — creates a pending Payment with
    `meta.subscription_id` set, then asks the provider to issue an invoice
    (delegating to `PaymentService._create_invoice_for_provider`).

    For `balance` — debits the user's wallet immediately and calls NorthLine
    to extend the key right away. Returns key_url in that case.
    """
    # ---- Validate subscription ownership and state ----
    sub_res = await session.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    sub: Subscription | None = sub_res.scalar_one_or_none()
    if sub is None or sub.user_id != user.id:
        raise SubscriptionNotFoundError(
            f"Subscription id={subscription_id} not found"
        )
    if sub.status != SUB_STATUS_ACTIVE:
        raise SubscriptionNotExtendableError(
            "Subscription is not in active state",
            details={
                "subscription_id": sub.id,
                "current_status": sub.status,
            },
        )
    if not sub.provider_subscription_id:
        # Defensive: an active sub without a provider id can't be extended.
        raise SubscriptionNotExtendableError(
            "Subscription has no provider id",
            details={"subscription_id": sub.id},
        )

    # ---- Validate duration belongs to the subscription's tariff ----
    duration_res = await session.execute(
        select(TariffDuration).where(TariffDuration.id == duration_id)
    )
    duration: TariffDuration | None = duration_res.scalar_one_or_none()
    if duration is None or duration.tariff_id != sub.tariff_id:
        raise NotFoundError(
            f"TariffDuration id={duration_id} not found for tariff_id={sub.tariff_id}",
            error_code="duration_not_found",
        )

    # Tariff (used for description text only).
    tariff_res = await session.execute(
        select(Tariff).where(Tariff.id == sub.tariff_id)
    )
    tariff: Tariff | None = tariff_res.scalar_one_or_none()
    tariff_code = tariff.code if tariff is not None else f"tariff_{sub.tariff_id}"

    base_price = int(duration.price_kopecks)

    # ---- Resolve promo (graceful: promo_service may be absent during dev) ----
    promo_id: int | None = None
    promo_type: str | None = None
    discount_percent: int | None = None
    promo_balance_kopecks: int | None = None  # only for balance-type promos

    if promo_code:
        try:
            from app.services import promo_service  # type: ignore
        except ImportError:
            promo_service = None  # type: ignore

        if promo_service is not None:
            try:
                svc = promo_service.PromoService(session)
                promo_result = await svc.validate_and_apply(
                    code=promo_code, user=user
                )
            except Exception as e:  # noqa: BLE001 — surface as validation
                raise ValidationError(
                    "Promo code invalid",
                    error_code="promo_invalid",
                    details={"error": str(e)},
                ) from e

            if promo_result is not None:
                promo_id = getattr(promo_result, "promo_id", None)
                promo_type = getattr(promo_result, "type", None)
                if promo_type == "discount_percent":
                    discount_percent = int(
                        getattr(promo_result, "discount_percent", 0)
                        or getattr(promo_result, "value", 0)
                        or 0
                    ) or None
                elif promo_type == "balance":
                    # Balance promo was already applied to the user; the
                    # extension uses the (now larger) balance — no price
                    # adjustment here.
                    promo_balance_kopecks = int(
                        getattr(promo_result, "balance_kopecks", 0)
                        or getattr(promo_result, "value", 0)
                        or 0
                    ) or None

    final_amount = _compute_discounted_price(
        base_kopecks=base_price, discount_percent=discount_percent
    )

    # ---- Create the Payment row (pending) ----
    payment_meta: dict[str, Any] = {
        "subscription_id": sub.id,
        "duration_id": duration.id,
        "days": duration.days,
        "is_extension": True,
    }
    if promo_id is not None:
        payment_meta["promo_id"] = promo_id
        if promo_type:
            payment_meta["promo_type"] = promo_type
        if discount_percent is not None:
            payment_meta["discount_percent"] = discount_percent
            payment_meta["original_amount_kopecks"] = base_price
        if promo_balance_kopecks is not None:
            payment_meta["promo_balance_kopecks"] = promo_balance_kopecks

    if payment_provider == PAYMENT_PROVIDER_BALANCE:
        return await _extend_via_balance(
            session,
            user=user,
            sub=sub,
            duration=duration,
            tariff_code=tariff_code,
            amount_kopecks=final_amount,
            payment_meta=payment_meta,
            northline_client=northline_client,
        )

    # External-provider path: defer invoice creation to PaymentService helpers.
    payment = Payment(
        user_id=user.id,
        subscription_id=sub.id,
        purpose=PAYMENT_PURPOSE_EXTEND,
        provider=payment_provider,
        amount_kopecks=final_amount,
        currency="RUB",
        status="pending",
        meta=payment_meta,
    )
    session.add(payment)
    await session.flush()

    from app.services import payment_service as _ps
    from app.services.cryptobot_client import CryptoBotError
    from app.services.platega_client import PlategaError

    ps = _ps.PaymentService(session)
    order_id = f"payment-{payment.id}"
    try:
        invoice = await ps._create_invoice_for_provider(  # noqa: SLF001
            provider=payment_provider,
            order_id=order_id,
            amount_kopecks=final_amount,
            description=(
                f"VPN_PIX extend #{payment.id} ({tariff_code}, +{duration.days}d)"
            ),
        )
    except (PlategaError, CryptoBotError) as e:
        await tech_log(
            session,
            action=f"payment_provider_create_invoice_failed:{payment_provider}",
            payload={"order_id": order_id, "error": str(e)},
        )
        raise _ps.PaymentProviderUnavailableError() from e

    payment.external_id = invoice.external_id
    new_meta = dict(payment.meta or {})
    new_meta.update(
        {
            "payment_url": invoice.payment_url,
            "provider_response": invoice.raw,
        }
    )
    payment.meta = new_meta
    await session.flush()

    await business_log(
        session,
        level=LEVEL_INFO,
        event="extension_payment_created",
        user_id=user.id,
        message=f"Created extension payment id={payment.id} via {payment_provider}",
        context={
            "payment_id": payment.id,
            "subscription_id": sub.id,
            "duration_id": duration.id,
            "amount_kopecks": final_amount,
            "provider": payment_provider,
        },
    )

    return ExtensionPaymentResult(
        payment_id=payment.id,
        amount_kopecks=final_amount,
        payment_url=invoice.payment_url,
        key_url=None,
    )


# ---------------------------------------------------------------------------
# Balance-paid extension (synchronous)
# ---------------------------------------------------------------------------


async def _extend_via_balance(
    session: AsyncSession,
    *,
    user: User,
    sub: Subscription,
    duration: TariffDuration,
    tariff_code: str,
    amount_kopecks: int,
    payment_meta: dict[str, Any],
    northline_client: Any | None,
) -> ExtensionPaymentResult:
    locked_user = await _lock_user(session, user.id)
    if locked_user is None:
        raise NotFoundError(
            f"User id={user.id} not found", error_code="user_not_found"
        )

    if int(locked_user.balance_kopecks) < amount_kopecks:
        raise InsufficientBalanceError(
            "Insufficient balance",
            details={
                "current_balance_kopecks": int(locked_user.balance_kopecks),
                "required_kopecks": amount_kopecks,
            },
        )

    new_balance = int(locked_user.balance_kopecks) - amount_kopecks
    locked_user.balance_kopecks = new_balance

    payment = Payment(
        user_id=locked_user.id,
        subscription_id=sub.id,
        purpose=PAYMENT_PURPOSE_EXTEND,
        provider=PAYMENT_PROVIDER_BALANCE,
        external_id=None,
        amount_kopecks=amount_kopecks,
        currency="RUB",
        status=PAYMENT_STATUS_PAID,
        paid_at=_now(),
        meta=payment_meta,
    )
    session.add(payment)
    await session.flush()

    bt = BalanceTransaction(
        user_id=locked_user.id,
        amount_kopecks=-amount_kopecks,
        reason=BT_REASON_PURCHASE,
        ref_payment_id=payment.id,
        ref_subscription_id=sub.id,
        description=(
            f"Extend subscription #{sub.id} ({tariff_code}, +{duration.days}d)"
        ),
        balance_after_kopecks=new_balance,
    )
    session.add(bt)
    await session.flush()

    # Now perform the NL extend; on failure — refund.
    try:
        await _call_northline_extend(
            session,
            payment=payment,
            sub=sub,
            northline_client=northline_client,
        )
    except (NorthLineUnavailableError, NorthLineClientError) as e:
        await _refund_extension(
            session,
            user_id=locked_user.id,
            payment=payment,
            sub_id=sub.id,
            amount_kopecks=amount_kopecks,
            error=e,
        )
        raise NorthLineUnavailableError(
            "Could not extend key after balance debit; refunded",
            details={
                "subscription_id": sub.id,
                "refund_kopecks": amount_kopecks,
            },
        ) from e

    return ExtensionPaymentResult(
        payment_id=payment.id,
        amount_kopecks=amount_kopecks,
        payment_url=None,
        key_url=sub.key_url,
    )


# ---------------------------------------------------------------------------
# Step 2: applied after webhook → paid (or inline for balance flow)
# ---------------------------------------------------------------------------


async def apply_extension_after_payment(
    session: AsyncSession,
    payment: Payment,
    northline_client: Any | None = None,
) -> None:
    """Extend the key + bump expires_at, idempotent via NL idempotency_key.

    Should only be called for payments whose `meta.subscription_id` is set.
    """
    sub_id = (payment.meta or {}).get("subscription_id")
    if sub_id is None:
        return

    sub_res = await session.execute(
        select(Subscription).where(Subscription.id == int(sub_id))
    )
    sub: Subscription | None = sub_res.scalar_one_or_none()
    if sub is None:
        await business_log(
            session,
            level=LEVEL_CRITICAL,
            event="vpn_provider_failed_after_payment_extend",
            user_id=payment.user_id,
            message="Subscription record missing for paid extension payment",
            context={"payment_id": payment.id},
        )
        return

    try:
        await _call_northline_extend(
            session,
            payment=payment,
            sub=sub,
            northline_client=northline_client,
        )
    except (NorthLineUnavailableError, NorthLineClientError) as e:
        # Refund to balance + notify user.
        await _refund_extension(
            session,
            user_id=payment.user_id,
            payment=payment,
            sub_id=sub.id,
            amount_kopecks=int(payment.amount_kopecks),
            error=e,
        )
        return


async def _call_northline_extend(
    session: AsyncSession,
    *,
    payment: Payment,
    sub: Subscription,
    northline_client: Any | None,
) -> None:
    days = int((payment.meta or {}).get("days") or sub.days)
    idempotency_key = f"payment-{payment.id}-extend"

    if northline_client is None:
        from app.services.northline_client import NorthLineClient

        settings = get_settings()
        northline_client = NorthLineClient(
            base_url=settings.northline_api_url or "https://api.northline.vpn",
            bearer_token=settings.northline_bearer_token or "",
            provider_key=settings.northline_provider_key or "",
        )

    await northline_client.extend_key(
        subscription_id=str(sub.provider_subscription_id),
        days=days,
        idempotency_key=idempotency_key,
    )

    # max(now, expires_at) + days
    now = _now()
    base = sub.expires_at if sub.expires_at and sub.expires_at > now else now
    new_expires = base + timedelta(days=days)
    sub.expires_at = new_expires
    sub.status = SUB_STATUS_ACTIVE
    await session.flush()

    await business_log(
        session,
        level=LEVEL_INFO,
        event="subscription_extended",
        user_id=payment.user_id,
        message=(
            f"Subscription id={sub.id} extended by {days} days; "
            f"new expires_at={new_expires.isoformat()}"
        ),
        context={
            "subscription_id": sub.id,
            "payment_id": payment.id,
            "days_added": days,
            "new_expires_at": new_expires.isoformat(),
        },
    )

    # Outbox: notify user.
    user = await session.get(User, payment.user_id)
    if user is not None:
        new_expires_str = new_expires.strftime("%d.%m.%Y %H:%M UTC")
        outbox = OutboxRepository(session)
        await outbox.enqueue(
            user_id=user.id,
            chat_id=user.tg_id,
            message_type=OUTBOX_MSG_TEXT,
            payload={
                "text_key": "subscription_extended",
                "format_kwargs": {"new_expires_at": new_expires_str},
                "parse_mode": "HTML",
                "kind": "subscription_extended",
                "subscription_id": sub.id,
            },
        )


async def _refund_extension(
    session: AsyncSession,
    *,
    user_id: int,
    payment: Payment,
    sub_id: int,
    amount_kopecks: int,
    error: Exception,
) -> None:
    """Refund the user's balance and notify them after an NL failure."""
    locked_user = await _lock_user(session, user_id)
    if locked_user is None:
        await business_log(
            session,
            level=LEVEL_CRITICAL,
            event="vpn_provider_failed_after_payment_extend",
            user_id=user_id,
            message="User missing during extension refund",
            context={"payment_id": payment.id},
        )
        return

    new_balance = int(locked_user.balance_kopecks) + amount_kopecks
    locked_user.balance_kopecks = new_balance

    payment.status = "refunded"
    bt = BalanceTransaction(
        user_id=locked_user.id,
        amount_kopecks=amount_kopecks,
        reason=BT_REASON_REFUND,
        ref_payment_id=payment.id,
        ref_subscription_id=sub_id,
        description="Refund after VPN provider failure on extension",
        balance_after_kopecks=new_balance,
    )
    session.add(bt)
    await session.flush()

    await business_log(
        session,
        level=LEVEL_CRITICAL,
        event="vpn_provider_failed_after_payment_extend",
        user_id=locked_user.id,
        message="NorthLine failed to extend key after payment; refunded",
        context={
            "payment_id": payment.id,
            "subscription_id": sub_id,
            "refund_kopecks": amount_kopecks,
            "balance_after_kopecks": new_balance,
            "error": str(error),
            "error_code": getattr(error, "error_code", None),
        },
    )

    outbox = OutboxRepository(session)
    await outbox.enqueue(
        user_id=locked_user.id,
        chat_id=locked_user.tg_id,
        message_type=OUTBOX_MSG_TEXT,
        payload={
            "text_key": "extension_failed_refund",
            "format_kwargs": {},
            "parse_mode": "HTML",
            "kind": "extension_failed_refund",
            "payment_id": payment.id,
        },
    )

    # Commit the refund so it survives the upcoming exception bubbling up to
    # the endpoint (FastAPI will not call session.commit() for a failed call).
    await session.commit()
