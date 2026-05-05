"""Subscription-extension tests.

Covers:
  - happy extend via balance: NL extend called, expires_at += days, outbox row;
  - cannot extend deactivated/expired subscriptions;
  - NL failure on extend → refund on balance + outbox notification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.exceptions import NorthLineUnavailableError
from app.db.models.balance_transaction import BalanceTransaction
from app.db.models.outbox import Outbox
from app.db.models.payment import (
    PAYMENT_PROVIDER_BALANCE,
    PAYMENT_STATUS_PAID,
    Payment,
)
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_DEACTIVATED,
    SUB_STATUS_EXPIRED,
    Subscription,
)
from app.db.models.tariff import Tariff, TariffDuration
from app.db.models.user import User
from app.db.session import get_session_factory
from app.schemas.northline import ExtendResponse
from app.services import extension_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(_engine_setup):  # noqa: ANN001
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _make_extend_mock(*, fail: bool = False) -> AsyncMock:
    mock = AsyncMock()
    if fail:
        mock.extend_key = AsyncMock(
            side_effect=NorthLineUnavailableError("provider down")
        )
    else:
        mock.extend_key = AsyncMock(
            return_value=ExtendResponse(
                ok=True,
                subscription_id="ext_sub_1",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=33),
                added_days=30,
            )
        )
    mock.aclose = AsyncMock(return_value=None)
    return mock


async def _fixture_world(session, *, balance: int = 0):  # noqa: ANN001
    """Create a user, tariff, duration, and one ACTIVE subscription."""
    user = User(tg_id=20100, username="extuser", balance_kopecks=balance)
    session.add(user)
    await session.flush()
    await session.refresh(user)

    tariff = Tariff(
        code="ext_basic",
        name="Ext Basic",
        devices=3,
        sort_order=1,
        is_active=True,
        is_free_trial=False,
    )
    session.add(tariff)
    await session.flush()
    duration = TariffDuration(
        tariff_id=tariff.id,
        days=30,
        price_kopecks=18900,
        is_hot=False,
        is_active=True,
    )
    session.add(duration)
    await session.flush()

    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=10)
    sub = Subscription(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_duration_id=duration.id,
        provider_subscription_id="ext_provider_sub_1",
        key_url="https://sub.pixio.icu/k1",
        devices=tariff.devices,
        days=duration.days,
        status=SUB_STATUS_ACTIVE,
        started_at=datetime.now(tz=timezone.utc) - timedelta(days=20),
        expires_at=expires_at,
        is_free_trial=False,
    )
    session.add(sub)
    await session.flush()
    await session.refresh(sub)

    return user, tariff, duration, sub, expires_at


# ---------------------------------------------------------------------------
# Happy path: extend via balance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extend_via_balance_success(db_session):  # noqa: ANN001
    user, _tariff, duration, sub, original_expires = await _fixture_world(
        db_session, balance=50000
    )
    nl_mock = _make_extend_mock()

    result = await extension_service.create_extension_payment(
        db_session,
        subscription_id=sub.id,
        duration_id=duration.id,
        user=user,
        payment_provider=PAYMENT_PROVIDER_BALANCE,
        promo_code=None,
        northline_client=nl_mock,
    )

    assert result.payment_id > 0
    assert result.amount_kopecks == 18900
    assert result.payment_url is None
    assert result.key_url == sub.key_url

    # NL was called with the right args.
    nl_mock.extend_key.assert_awaited_once()
    call_kwargs = nl_mock.extend_key.await_args.kwargs
    assert call_kwargs["subscription_id"] == sub.provider_subscription_id
    assert call_kwargs["days"] == duration.days
    assert call_kwargs["idempotency_key"].startswith("payment-")
    assert call_kwargs["idempotency_key"].endswith("-extend")

    # expires_at was bumped by `duration.days`.
    await db_session.refresh(sub)
    expected_min = original_expires + timedelta(days=duration.days - 1)
    assert sub.expires_at > expected_min
    assert sub.status == SUB_STATUS_ACTIVE

    # Balance was debited.
    await db_session.refresh(user)
    assert user.balance_kopecks == 50000 - 18900

    # Payment row recorded.
    payment = await db_session.get(Payment, result.payment_id)
    assert payment is not None
    assert payment.status == PAYMENT_STATUS_PAID
    assert payment.purpose == "extend_subscription"
    assert payment.amount_kopecks == 18900
    assert (payment.meta or {}).get("subscription_id") == sub.id

    # Outbox: subscription_extended
    rows = (
        await db_session.execute(
            select(Outbox).where(Outbox.user_id == user.id)
        )
    ).scalars().all()
    assert any(
        r.payload.get("text_key") == "subscription_extended" for r in rows
    )


# ---------------------------------------------------------------------------
# Cannot extend non-active subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extend_deactivated_rejected(db_session):  # noqa: ANN001
    user, _tariff, duration, sub, _ = await _fixture_world(
        db_session, balance=50000
    )
    sub.status = SUB_STATUS_DEACTIVATED
    await db_session.flush()

    from app.core.exceptions import SubscriptionNotExtendableError

    with pytest.raises(SubscriptionNotExtendableError):
        await extension_service.create_extension_payment(
            db_session,
            subscription_id=sub.id,
            duration_id=duration.id,
            user=user,
            payment_provider=PAYMENT_PROVIDER_BALANCE,
            promo_code=None,
        )


@pytest.mark.asyncio
async def test_extend_expired_rejected(db_session):  # noqa: ANN001
    user, _tariff, duration, sub, _ = await _fixture_world(
        db_session, balance=50000
    )
    sub.status = SUB_STATUS_EXPIRED
    await db_session.flush()

    from app.core.exceptions import SubscriptionNotExtendableError

    with pytest.raises(SubscriptionNotExtendableError):
        await extension_service.create_extension_payment(
            db_session,
            subscription_id=sub.id,
            duration_id=duration.id,
            user=user,
            payment_provider=PAYMENT_PROVIDER_BALANCE,
            promo_code=None,
        )


@pytest.mark.asyncio
async def test_extend_other_user_rejected(db_session):  # noqa: ANN001
    """Subscription owned by a different user must be 404."""
    user, _tariff, duration, sub, _ = await _fixture_world(
        db_session, balance=50000
    )
    other = User(tg_id=99999, balance_kopecks=50000)
    db_session.add(other)
    await db_session.flush()

    from app.core.exceptions import SubscriptionNotFoundError

    with pytest.raises(SubscriptionNotFoundError):
        await extension_service.create_extension_payment(
            db_session,
            subscription_id=sub.id,
            duration_id=duration.id,
            user=other,
            payment_provider=PAYMENT_PROVIDER_BALANCE,
            promo_code=None,
        )


# ---------------------------------------------------------------------------
# Cross-tariff duration rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extend_with_foreign_tariff_duration_rejected(  # noqa: ANN001
    db_session,
):
    user, _tariff, _duration, sub, _ = await _fixture_world(
        db_session, balance=50000
    )

    other_tariff = Tariff(
        code="ext_other",
        name="Other",
        devices=5,
        sort_order=2,
        is_active=True,
        is_free_trial=False,
    )
    db_session.add(other_tariff)
    await db_session.flush()
    other_dur = TariffDuration(
        tariff_id=other_tariff.id,
        days=90,
        price_kopecks=45000,
        is_hot=False,
        is_active=True,
    )
    db_session.add(other_dur)
    await db_session.flush()

    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await extension_service.create_extension_payment(
            db_session,
            subscription_id=sub.id,
            duration_id=other_dur.id,
            user=user,
            payment_provider=PAYMENT_PROVIDER_BALANCE,
            promo_code=None,
        )


# ---------------------------------------------------------------------------
# NL failure → refund on balance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extend_via_balance_nl_failure_refunds(db_session):  # noqa: ANN001
    user, _tariff, duration, sub, _ = await _fixture_world(
        db_session, balance=50000
    )
    nl_mock = _make_extend_mock(fail=True)

    with pytest.raises(NorthLineUnavailableError):
        await extension_service.create_extension_payment(
            db_session,
            subscription_id=sub.id,
            duration_id=duration.id,
            user=user,
            payment_provider=PAYMENT_PROVIDER_BALANCE,
            promo_code=None,
            northline_client=nl_mock,
        )

    # Balance restored.
    await db_session.refresh(user)
    assert user.balance_kopecks == 50000

    # Refund balance_transaction recorded.
    refunds = (
        await db_session.execute(
            select(BalanceTransaction).where(
                BalanceTransaction.user_id == user.id,
                BalanceTransaction.reason == "refund",
            )
        )
    ).scalars().all()
    assert len(refunds) == 1
    assert refunds[0].amount_kopecks == 18900

    # Outbox: extension_failed_refund text was enqueued.
    rows = (
        await db_session.execute(
            select(Outbox).where(Outbox.user_id == user.id)
        )
    ).scalars().all()
    assert any(
        r.payload.get("text_key") == "extension_failed_refund" for r in rows
    )


# ---------------------------------------------------------------------------
# apply_extension_after_payment (webhook path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_extension_after_payment_bumps_expires_at(  # noqa: ANN001
    db_session,
):
    user, _tariff, duration, sub, original_expires = await _fixture_world(
        db_session, balance=0
    )

    payment = Payment(
        user_id=user.id,
        subscription_id=sub.id,
        purpose="extend_subscription",
        provider="platega_sbp",
        amount_kopecks=18900,
        currency="RUB",
        status=PAYMENT_STATUS_PAID,
        meta={
            "subscription_id": sub.id,
            "duration_id": duration.id,
            "days": duration.days,
            "is_extension": True,
        },
    )
    db_session.add(payment)
    await db_session.flush()
    await db_session.refresh(payment)

    nl_mock = _make_extend_mock()

    await extension_service.apply_extension_after_payment(
        db_session, payment, nl_mock
    )

    nl_mock.extend_key.assert_awaited_once()
    await db_session.refresh(sub)
    assert sub.expires_at > original_expires
    assert sub.status == SUB_STATUS_ACTIVE
