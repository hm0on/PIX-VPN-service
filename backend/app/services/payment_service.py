"""Payment service.

Orchestrates:
  - subscription purchase via external provider (Platega SBP / Crypto, CryptoBot);
  - balance top-up via the same providers;
  - webhook processing (idempotent), including key issuance via NorthLine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AppError, NotFoundError, ValidationError
from app.core.logging import (
    LEVEL_CRITICAL,
    LEVEL_INFO,
    LEVEL_WARNING,
    business_log,
    get_logger,
    tech_log,
)
from app.services import outbox_service, referral_service
from app.services.cryptobot_client import CryptoBotClient, CryptoBotError
from app.services.platega_client import PlategaClient, PlategaError

# Optional Stage-3 modules — graceful skip if Promo agent hasn't merged yet.
try:
    from app.services import promo_service  # type: ignore
except ImportError:  # pragma: no cover
    promo_service = None  # type: ignore

logger = get_logger("payment_service")

MIN_TOPUP_KOPECKS = 1000  # 10 RUB


class PaymentProviderUnavailableError(AppError):
    error_code = "payment_provider_unavailable"
    status_code = 503
    message = "Payment provider is temporarily unavailable"


class MinimumTopupError(ValidationError):
    error_code = "topup_amount_too_small"
    message = "Top-up amount is below the minimum"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _format_rub(amount_kopecks: int) -> str:
    """Format kopecks (int) as a human-readable RUB string with 2 decimals.

    Avoids float by doing integer division.
    """
    sign = "-" if amount_kopecks < 0 else ""
    abs_kopecks = abs(int(amount_kopecks))
    rubles, kop = divmod(abs_kopecks, 100)
    return f"{sign}{rubles}.{kop:02d}"


# ---------------------------------------------------------------------------
# Lazy model resolution (Backend Core owns the models).
# ---------------------------------------------------------------------------


def _models() -> dict[str, Any]:
    from app.db import models as m  # type: ignore[attr-defined]

    return {
        "User": m.User,
        "Tariff": m.Tariff,
        "TariffDuration": m.TariffDuration,
        "Subscription": getattr(m, "Subscription", None),
        "Payment": getattr(m, "Payment", None),
        "BalanceTransaction": getattr(m, "BalanceTransaction", None),
    }


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------


def _build_platega() -> PlategaClient:
    s = get_settings()
    return PlategaClient(
        api_key=s.platega_api_key,
        shop_id=s.platega_shop_id,
        secret=s.platega_secret,
        base_url=s.platega_api_url,
    )


def _build_cryptobot() -> CryptoBotClient:
    s = get_settings()
    return CryptoBotClient(
        api_token=s.cryptobot_api_token,
        api_url=s.cryptobot_api_url,
    )


def _provider_callback_url(provider: str) -> str:
    s = get_settings()
    base = s.public_webhook_base_url.rstrip("/") if s.public_webhook_base_url else ""
    if provider.startswith("platega"):
        return f"{base}/webhook/platega"
    if provider == "cryptobot":
        return f"{base}/webhook/cryptobot"
    return f"{base}/webhook/{provider}"


def _success_url() -> str | None:
    s = get_settings()
    if s.public_bot_username:
        return f"https://t.me/{s.public_bot_username.lstrip('@')}"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -------------------- Subscription purchase --------------------

    async def create_subscription_payment(
        self,
        *,
        user_id: int,
        tariff_id: int,
        duration_id: int,
        provider: str,
        promo_id: int | None = None,
    ) -> dict[str, Any]:
        models = _models()
        Tariff = models["Tariff"]
        TariffDuration = models["TariffDuration"]
        Subscription = models["Subscription"]
        Payment = models["Payment"]
        if Subscription is None or Payment is None:
            raise RuntimeError(
                "Subscription/Payment models not available — Backend Core hasn't "
                "merged Stage 2 models yet."
            )

        # Load tariff + duration.
        tariff = (
            await self.session.execute(select(Tariff).where(Tariff.id == tariff_id))
        ).scalar_one_or_none()
        duration = (
            await self.session.execute(
                select(TariffDuration).where(TariffDuration.id == duration_id)
            )
        ).scalar_one_or_none()
        if tariff is None:
            raise NotFoundError(
                f"Tariff id={tariff_id} not found", error_code="tariff_not_found"
            )
        if duration is None or duration.tariff_id != tariff_id:
            raise NotFoundError(
                f"TariffDuration id={duration_id} not found",
                error_code="duration_not_found",
            )

        original_amount_kopecks = int(duration.price_kopecks)
        amount_kopecks = original_amount_kopecks

        # ----- Discount promo (optional) -----
        # The bot validates the code via /promo/apply, gets back ``promo_id``,
        # then passes it here. We re-lookup the promo so we never trust an
        # arbitrary percent from the client. We do NOT bump
        # ``current_activations`` here — that happens in
        # ``_record_promo_activation_safe`` once the webhook flips us to paid.
        promo_meta: dict[str, Any] = {}
        if promo_id is not None and promo_service is not None:
            try:
                from app.db.models.promo_code import (  # noqa: WPS433
                    PROMO_TYPE_DISCOUNT_PERCENT,
                    PromoCode,
                )

                promo_row = (
                    await self.session.execute(
                        select(PromoCode).where(PromoCode.id == int(promo_id))
                    )
                ).scalar_one_or_none()
                if promo_row is not None and promo_row.type == PROMO_TYPE_DISCOUNT_PERCENT:
                    percent = int(promo_row.value)
                    amount_kopecks = promo_service.compute_discounted_price(
                        original_amount_kopecks, percent
                    )
                    promo_meta = {
                        "promo_id": int(promo_row.id),
                        "promo_type": "discount_percent",
                        "discount_percent": percent,
                        "original_amount_kopecks": original_amount_kopecks,
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "promo_discount_lookup_failed",
                    promo_id=promo_id,
                    user_id=user_id,
                    error=str(e),
                )

        # Create Subscription(pending).
        sub = Subscription(
            user_id=user_id,
            tariff_id=tariff_id,
            tariff_duration_id=duration_id,
            devices=tariff.devices,
            days=duration.days,
            status="pending",
            is_free_trial=False,
        )
        self.session.add(sub)
        await self.session.flush()

        # Create Payment(pending).
        payment = Payment(
            user_id=user_id,
            subscription_id=sub.id,
            purpose="subscription",
            provider=provider,
            amount_kopecks=amount_kopecks,
            currency="RUB",
            status="pending",
            meta=dict(promo_meta),
        )
        self.session.add(payment)
        await self.session.flush()

        order_id = f"payment-{payment.id}"
        try:
            invoice = await self._create_invoice_for_provider(
                provider=provider,
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                description=f"VPN_PIX subscription #{payment.id} ({tariff.code}, {duration.days}d)",
            )
        except (PlategaError, CryptoBotError) as e:
            await tech_log(
                self.session,
                action=f"payment_provider_create_invoice_failed:{provider}",
                payload={"order_id": order_id, "error": str(e)},
            )
            await business_log(
                self.session,
                level=LEVEL_WARNING,
                event="payment_provider_unavailable",
                user_id=user_id,
                message=f"Failed to create invoice via {provider}",
                context={"order_id": order_id, "error": str(e)},
            )
            raise PaymentProviderUnavailableError() from e

        payment.external_id = invoice.external_id
        payment.meta = {
            **promo_meta,
            "payment_url": invoice.payment_url,
            "provider_response": invoice.raw,
        }
        await self.session.flush()

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="subscription_payment_created",
            user_id=user_id,
            message=f"Created subscription payment id={payment.id} via {provider}",
            context={
                "payment_id": payment.id,
                "subscription_id": sub.id,
                "provider": provider,
                "amount_kopecks": amount_kopecks,
            },
        )

        return {
            "payment_id": payment.id,
            "subscription_id": sub.id,
            "payment_url": invoice.payment_url,
            "expires_at": _payment_expires_at(),
            "amount_kopecks": amount_kopecks,
        }

    # -------------------- Top-up --------------------

    async def create_topup_payment(
        self,
        *,
        user_id: int,
        amount_kopecks: int,
        provider: str,
    ) -> dict[str, Any]:
        if amount_kopecks < MIN_TOPUP_KOPECKS:
            raise MinimumTopupError(
                f"Top-up amount must be at least {MIN_TOPUP_KOPECKS // 100} RUB",
                details={"min_kopecks": MIN_TOPUP_KOPECKS},
            )

        models = _models()
        Payment = models["Payment"]
        if Payment is None:
            raise RuntimeError(
                "Payment model not available — Backend Core hasn't merged Stage 2 yet."
            )

        payment = Payment(
            user_id=user_id,
            subscription_id=None,
            purpose="topup",
            provider=provider,
            amount_kopecks=amount_kopecks,
            currency="RUB",
            status="pending",
            meta={},
        )
        self.session.add(payment)
        await self.session.flush()

        order_id = f"payment-{payment.id}"
        try:
            invoice = await self._create_invoice_for_provider(
                provider=provider,
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                description=f"VPN_PIX top-up #{payment.id}",
            )
        except (PlategaError, CryptoBotError) as e:
            await tech_log(
                self.session,
                action=f"payment_provider_create_invoice_failed:{provider}",
                payload={"order_id": order_id, "error": str(e)},
            )
            raise PaymentProviderUnavailableError() from e

        payment.external_id = invoice.external_id
        payment.meta = {
            "payment_url": invoice.payment_url,
            "provider_response": invoice.raw,
        }
        await self.session.flush()

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="topup_payment_created",
            user_id=user_id,
            message=f"Created top-up payment id={payment.id} via {provider}",
            context={
                "payment_id": payment.id,
                "provider": provider,
                "amount_kopecks": amount_kopecks,
            },
        )

        return {
            "payment_id": payment.id,
            "payment_url": invoice.payment_url,
            "expires_at": _payment_expires_at(),
            "amount_kopecks": amount_kopecks,
        }

    # -------------------- Webhook processing --------------------

    async def process_webhook_payment(
        self,
        *,
        provider: str,
        external_id: str,
        status_value: str,
        raw_meta: dict[str, Any],
        trace_id: str | None = None,
        northline_client: Any | None = None,
    ) -> dict[str, Any]:
        """Idempotent webhook handler.

        - If payment already in terminal state — silently return.
        - On `paid`:
            * for subscription → call NorthLine, activate, outbox the key;
            * for topup → bump balance, balance_transactions row, outbox.
        - On `failed`/`expired` → mark, outbox notification.
        """
        models = _models()
        Payment = models["Payment"]
        if Payment is None:
            raise RuntimeError("Payment model not available")

        result = await self.session.execute(
            select(Payment).where(Payment.external_id == external_id)
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            await tech_log(
                self.session,
                action=f"webhook_payment_unknown:{provider}",
                payload={"external_id": external_id, "status": status_value},
                trace_id=trace_id,
            )
            return {"ok": True, "ignored": "unknown_payment"}

        # Idempotency: terminal payments aren't re-processed.
        if payment.status in {"paid", "refunded"}:
            await tech_log(
                self.session,
                action=f"webhook_payment_duplicate:{provider}",
                payload={
                    "external_id": external_id,
                    "payment_id": payment.id,
                    "current_status": payment.status,
                },
                trace_id=trace_id,
            )
            return {"ok": True, "ignored": "already_terminal"}

        normalized = status_value.lower()
        if normalized in {"paid", "success", "succeeded", "completed"}:
            return await self._handle_paid(
                payment, raw_meta, trace_id=trace_id, northline_client=northline_client
            )
        if normalized in {"failed", "fail", "error"}:
            return await self._handle_failed(payment, raw_meta, trace_id=trace_id)
        if normalized in {"expired", "cancelled", "canceled"}:
            return await self._handle_expired(payment, raw_meta, trace_id=trace_id)

        # Unknown status — log and ignore.
        await tech_log(
            self.session,
            action=f"webhook_payment_unknown_status:{provider}",
            payload={
                "external_id": external_id,
                "payment_id": payment.id,
                "status": status_value,
            },
            trace_id=trace_id,
        )
        return {"ok": True, "ignored": "unknown_status"}

    # -------------------- Internal: paid flow --------------------

    async def _handle_paid(
        self,
        payment: Any,
        raw_meta: dict[str, Any],
        *,
        trace_id: str | None,
        northline_client: Any | None = None,
    ) -> dict[str, Any]:
        payment.status = "paid"
        payment.paid_at = _now()
        meta = dict(payment.meta or {})
        meta["webhook_raw"] = raw_meta
        payment.meta = meta
        await self.session.flush()

        # Branch by purpose. The presence of `meta.subscription_id` together
        # with a non-topup purpose signals an extension — route those to
        # extension_service so we do NOT create a brand-new subscription.
        is_extension = (
            payment.purpose != "topup"
            and bool((payment.meta or {}).get("subscription_id"))
            and (
                payment.purpose == "extend_subscription"
                or (payment.meta or {}).get("is_extension")
            )
        )

        if is_extension:
            try:
                from app.services import extension_service  # type: ignore
            except ImportError:  # pragma: no cover
                extension_service = None  # type: ignore
            if extension_service is not None:
                await extension_service.apply_extension_after_payment(
                    self.session, payment, northline_client
                )
        elif payment.purpose == "subscription":
            await self._provision_subscription_key(
                payment, trace_id=trace_id, northline_client=northline_client
            )
        elif payment.purpose == "topup":
            await self._credit_topup(payment, trace_id=trace_id)
        else:
            await tech_log(
                self.session,
                action=f"webhook_payment_unknown_purpose:{payment.purpose}",
                payload={"payment_id": payment.id},
                trace_id=trace_id,
            )

        # ---- Post-paid hooks (referral bonus + promo activation) ----
        # Only for real paid orders (not topups, not zero-amount).
        if payment.purpose != "topup" and int(payment.amount_kopecks or 0) > 0:
            await self._apply_referral_bonus_safe(payment)
            await self._record_promo_activation_safe(payment)

        return {"ok": True, "payment_id": payment.id, "status": "paid"}

    async def _apply_referral_bonus_safe(self, payment: Any) -> None:
        """Best-effort referral bonus credit. Never crashes the webhook."""
        try:
            from app.services import referral_service  # type: ignore
        except ImportError:  # pragma: no cover
            return
        try:
            models = _models()
            User = models["User"]
            res = await self.session.execute(
                select(User).where(User.id == payment.user_id)
            )
            user = res.scalar_one_or_none()
            if user is None:
                return
            await referral_service.apply_referrer_bonus(
                self.session,
                referee_user=user,
                referee_payment=payment,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "referral_bonus_failed",
                payment_id=payment.id,
                error=str(e),
            )

    async def _record_promo_activation_safe(self, payment: Any) -> None:
        """Best-effort promo activation recording. Never crashes the webhook."""
        meta = payment.meta or {}
        promo_id = meta.get("promo_id")
        promo_type = meta.get("promo_type") or (
            "discount_percent" if meta.get("discount_percent") is not None else None
        )
        if not promo_id or promo_type != "discount_percent":
            return
        try:
            from app.services import promo_service  # type: ignore
        except ImportError:  # pragma: no cover
            return
        try:
            original = int(meta.get("original_amount_kopecks") or 0)
            paid = int(payment.amount_kopecks or 0)
            discount_kopecks = max(0, original - paid)
            service = promo_service.PromoService(self.session)
            await service.record_discount_activation(
                promo_id=int(promo_id),
                user_id=payment.user_id,
                payment_id=payment.id,
                discount_kopecks=discount_kopecks,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "promo_record_discount_failed",
                payment_id=payment.id,
                promo_id=promo_id,
                error=str(e),
            )

    async def _provision_subscription_key(
        self,
        payment: Any,
        *,
        trace_id: str | None,
        northline_client: Any | None = None,
    ) -> None:
        """Call NorthLine and activate the subscription. On failure — mark and notify user."""
        models = _models()
        Subscription = models["Subscription"]
        if Subscription is None:
            raise RuntimeError("Subscription model not available")

        sub_result = await self.session.execute(
            select(Subscription).where(Subscription.id == payment.subscription_id)
        )
        sub = sub_result.scalar_one_or_none()
        if sub is None:
            await business_log(
                self.session,
                level=LEVEL_CRITICAL,
                event="vpn_provider_failed_after_payment",
                user_id=payment.user_id,
                message=(
                    "Subscription record missing for paid payment — manual intervention"
                ),
                context={"payment_id": payment.id},
            )
            return

        idempotency_key = f"payment-{payment.id}"
        try:
            if northline_client is None:
                from app.services.northline_client import NorthLineClient

                settings = get_settings()
                northline_client = NorthLineClient(
                    base_url=(
                        settings.northline_api_url
                        or "https://northline-vpn.xyz/api/v1"
                    ),
                    bearer_token=settings.northline_bearer_token or "",
                    provider_key=settings.northline_provider_key or "",
                    test_mode=bool(settings.northline_test_mode),
                )
            # Pull LTE add-on size from the tariff row. New tariffs (and
            # all the legacy ones backfilled by migration 0012) carry 35GB
            # by default; custom tariffs may store their own value.
            tariff_lte_gb: int | None = None
            try:
                Tariff = models["Tariff"]
                if Tariff is not None and sub.tariff_id:
                    tariff_row = (
                        await self.session.execute(
                            select(Tariff).where(Tariff.id == sub.tariff_id)
                        )
                    ).scalar_one_or_none()
                    if tariff_row is not None:
                        tariff_lte_gb = getattr(
                            tariff_row, "lte_gb_per_month", None
                        )
            except Exception:  # noqa: BLE001
                # Don't block key issuing on a tariff lookup hiccup — worst
                # case we issue without LTE, which is recoverable.
                tariff_lte_gb = None

            key_response = await northline_client.create_key(
                days=sub.days,
                devices=sub.devices,
                idempotency_key=idempotency_key,
                lte_gb=tariff_lte_gb,
                metadata={
                    "user_id": payment.user_id,
                    "subscription_id": sub.id,
                    "payment_id": payment.id,
                },
            )
        except Exception as e:  # noqa: BLE001
            sub.status = "failed_provider"
            await self.session.flush()
            await business_log(
                self.session,
                level=LEVEL_CRITICAL,
                event="vpn_provider_failed_after_payment",
                user_id=payment.user_id,
                message=(
                    "NorthLine failed to issue key after successful payment"
                ),
                context={
                    "payment_id": payment.id,
                    "subscription_id": sub.id,
                    "error": str(e),
                },
            )
            await tech_log(
                self.session,
                action="northline_create_key_failed",
                user_id=payment.user_id,
                payload={
                    "payment_id": payment.id,
                    "subscription_id": sub.id,
                    "error": str(e),
                },
                trace_id=trace_id,
            )
            await self._enqueue_provider_failed_outbox(payment.user_id)
            return

        # Successful provisioning.
        provider_subscription_id = (
            getattr(key_response, "subscription_id", None)
            or getattr(key_response, "id", None)
        )
        key_url = (
            getattr(key_response, "key", None)
            or getattr(key_response, "key_url", None)
            or getattr(key_response, "url", None)
        )
        sub.provider_subscription_id = (
            str(provider_subscription_id) if provider_subscription_id else None
        )
        sub.key_url = key_url
        sub.status = "active"
        sub.started_at = _now()
        sub.expires_at = _now() + timedelta(days=sub.days)
        await self.session.flush()

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="subscription_activated",
            user_id=payment.user_id,
            message=f"Subscription id={sub.id} activated after payment id={payment.id}",
            context={
                "subscription_id": sub.id,
                "payment_id": payment.id,
                "key_url": key_url,
            },
        )

        await self._enqueue_subscription_key_outbox(
            user_id=payment.user_id,
            payment_id=payment.id,
            key_url=key_url or "",
        )

    async def _credit_topup(self, payment: Any, *, trace_id: str | None) -> None:
        models = _models()
        User = models["User"]
        BalanceTransaction = models["BalanceTransaction"]
        if BalanceTransaction is None:
            raise RuntimeError("BalanceTransaction model not available")

        # Lock the user row.
        bind = self.session.get_bind()
        if bind.dialect.name == "sqlite":
            user_stmt = select(User).where(User.id == payment.user_id)
        else:
            user_stmt = (
                select(User).where(User.id == payment.user_id).with_for_update()
            )
        user_result = await self.session.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if user is None:
            await tech_log(
                self.session,
                action="topup_user_not_found",
                payload={"payment_id": payment.id, "user_id": payment.user_id},
                trace_id=trace_id,
            )
            return

        amount = int(payment.amount_kopecks)
        new_balance = int(user.balance_kopecks) + amount
        user.balance_kopecks = new_balance

        tx = BalanceTransaction(
            user_id=user.id,
            amount_kopecks=amount,
            reason="topup",
            ref_payment_id=payment.id,
            ref_subscription_id=None,
            description=f"Top-up via {payment.provider}",
            balance_after_kopecks=new_balance,
        )
        self.session.add(tx)
        await self.session.flush()

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="balance_topped_up",
            user_id=user.id,
            message=f"Top-up payment id={payment.id} credited {amount} kopecks",
            context={
                "payment_id": payment.id,
                "amount_kopecks": amount,
                "balance_after": new_balance,
            },
        )

        await outbox_service.enqueue_message(
            self.session,
            user_id=user.id,
            chat_id=user.tg_id,
            message_type="text",
            payload={
                "text": (
                    f"💰 Баланс пополнен на <b>{_format_rub(amount)} ₽</b>.\n"
                    f"Текущий баланс: <b>{_format_rub(new_balance)} ₽</b>."
                ),
                "parse_mode": "HTML",
                "kind": "topup_succeeded",
                "payment_id": payment.id,
            },
        )

    async def _handle_failed(
        self,
        payment: Any,
        raw_meta: dict[str, Any],
        *,
        trace_id: str | None,
    ) -> dict[str, Any]:
        payment.status = "failed"
        meta = dict(payment.meta or {})
        meta["webhook_raw"] = raw_meta
        payment.meta = meta

        if payment.subscription_id is not None:
            models = _models()
            Subscription = models["Subscription"]
            sub_res = await self.session.execute(
                select(Subscription).where(Subscription.id == payment.subscription_id)
            )
            sub = sub_res.scalar_one_or_none()
            if sub is not None and sub.status == "pending":
                sub.status = "failed"
        await self.session.flush()

        await business_log(
            self.session,
            level=LEVEL_WARNING,
            event="payment_failed",
            user_id=payment.user_id,
            message=f"Payment id={payment.id} marked as failed",
            context={"payment_id": payment.id, "raw": raw_meta},
        )

        # Notify user.
        try:
            chat_id = await self._user_chat_id(payment.user_id)
        except NotFoundError:
            chat_id = None
        if chat_id is not None:
            await outbox_service.enqueue_message(
                self.session,
                user_id=payment.user_id,
                chat_id=chat_id,
                message_type="text",
                payload={
                    "text": (
                        "❌ Оплата не прошла. Попробуйте ещё раз или обратитесь "
                        "в поддержку."
                    ),
                    "parse_mode": "HTML",
                    "kind": "payment_failed",
                    "payment_id": payment.id,
                },
            )

        await tech_log(
            self.session,
            action="payment_failed",
            payload={"payment_id": payment.id, "raw": raw_meta},
            trace_id=trace_id,
        )
        return {"ok": True, "payment_id": payment.id, "status": "failed"}

    async def _handle_expired(
        self,
        payment: Any,
        raw_meta: dict[str, Any],
        *,
        trace_id: str | None,
    ) -> dict[str, Any]:
        payment.status = "expired"
        meta = dict(payment.meta or {})
        meta["webhook_raw"] = raw_meta
        payment.meta = meta
        await self.session.flush()
        await tech_log(
            self.session,
            action="payment_expired",
            payload={"payment_id": payment.id, "raw": raw_meta},
            trace_id=trace_id,
        )
        return {"ok": True, "payment_id": payment.id, "status": "expired"}

    # -------------------- Helpers --------------------

    async def _create_invoice_for_provider(
        self,
        *,
        provider: str,
        order_id: str,
        amount_kopecks: int,
        description: str,
    ) -> Any:
        callback_url = _provider_callback_url(provider)
        success_url = _success_url()

        if provider == "platega_sbp":
            client = _build_platega()
            return await client.create_invoice(
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                payment_method="sbp",
                description=description,
                callback_url=callback_url,
                success_url=success_url,
            )
        if provider == "platega_crypto":
            client = _build_platega()
            return await client.create_invoice(
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                payment_method="crypto",
                description=description,
                callback_url=callback_url,
                success_url=success_url,
            )
        if provider == "cryptobot":
            cb = _build_cryptobot()
            return await cb.create_invoice(
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                description=description,
                paid_btn_url=success_url,
                paid_btn_name="openBot" if success_url else None,
            )

        raise ValidationError(
            f"Unknown payment provider: {provider}",
            error_code="unknown_provider",
        )

    async def _user_chat_id(self, user_id: int) -> int:
        models = _models()
        User = models["User"]
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError(f"User id={user_id} not found")
        return user.tg_id

    async def _enqueue_subscription_key_outbox(
        self,
        *,
        user_id: int,
        payment_id: int,
        key_url: str,
    ) -> None:
        chat_id = await self._user_chat_id(user_id)
        settings = get_settings()
        text = (
            f"✅ Вы успешно оплатили заказ <b>#{payment_id}</b>\n\n"
            f"Ваш ключ:\n<code>{key_url}</code>"
        )
        payload: dict[str, Any] = {
            "text": text,
            "parse_mode": "HTML",
            "kind": "subscription_key",
            "payment_id": payment_id,
            "key_url": key_url,
        }
        if settings.howto_connect_url:
            payload["inline_keyboard"] = [
                [
                    {
                        "text": "Как подключиться",
                        "url": settings.howto_connect_url,
                    }
                ]
            ]
        await outbox_service.enqueue_message(
            self.session,
            user_id=user_id,
            chat_id=chat_id,
            message_type="text",
            payload=payload,
        )

    async def _enqueue_provider_failed_outbox(self, user_id: int) -> None:
        try:
            chat_id = await self._user_chat_id(user_id)
        except NotFoundError:
            return
        await outbox_service.enqueue_message(
            self.session,
            user_id=user_id,
            chat_id=chat_id,
            message_type="text",
            payload={
                "text": (
                    "Оплата прошла, но возникла техническая ошибка с выдачей ключа. "
                    "Обратитесь в поддержку — мы всё решим."
                ),
                "parse_mode": "HTML",
                "kind": "vpn_provider_failed_after_payment",
            },
        )


def _payment_expires_at() -> datetime:
    settings = get_settings()
    return _now() + timedelta(minutes=settings.payment_pending_ttl_minutes)
