"""Tests for the periodic subscription reconciliation service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import NorthLineClientError, NorthLineUnavailableError
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_DEACTIVATED,
    SUB_STATUS_EXPIRED,
    Subscription,
)
from app.db.models.tariff import Tariff
from app.db.models.user import User
from app.db.session import get_session_factory
from app.schemas.northline import KeyInfo
from app.services.subscription_reconcile_service import reconcile_subscriptions


async def _any_tariff_id() -> int:
    factory = get_session_factory()
    async with factory() as session:
        return (
            await session.execute(select(Tariff.id).order_by(Tariff.id.asc()).limit(1))
        ).scalar_one()


async def _make_user(tg_id: int) -> int:
    factory = get_session_factory()
    async with factory() as session:
        user = User(tg_id=tg_id, username=f"u{tg_id}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _make_active_sub(
    *,
    user_id: int,
    provider_subscription_id: str | None,
    expires_at: datetime,
    days: int = 30,
    devices: int = 3,
) -> int:
    tariff_id = await _any_tariff_id()
    factory = get_session_factory()
    async with factory() as session:
        sub = Subscription(
            user_id=user_id,
            tariff_id=tariff_id,
            tariff_duration_id=None,
            provider_subscription_id=provider_subscription_id,
            key_url="https://example.com/k",
            devices=devices,
            days=days,
            status=SUB_STATUS_ACTIVE,
            started_at=datetime.now(tz=timezone.utc),
            expires_at=expires_at,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _get_sub(sub_id: int) -> Subscription:
    factory = get_session_factory()
    async with factory() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.id == sub_id))
        ).scalar_one()
        # SQLite (used in unit tests) stores datetimes as naive even when
        # written through a TIMESTAMPTZ column. Re-attach UTC so callers
        # can subtract two tz-aware datetimes without a TypeError.
        if sub.expires_at is not None and sub.expires_at.tzinfo is None:
            sub.expires_at = sub.expires_at.replace(tzinfo=timezone.utc)
        return sub


@pytest.mark.asyncio
async def test_reconcile_skips_test_mode_subscription_ids(seed_db):  # noqa: ANN001
    """``nlsub_test_*`` IDs are fake — the provider doesn't track them.

    The service must not even try ``GET /keys/...`` for such rows; if it
    did, prod logs would fill with spurious 400s and we'd risk
    mis-deactivating real test fixtures.
    """
    uid = await _make_user(7001)
    expected_exp = datetime.now(tz=timezone.utc) + timedelta(days=30)
    sub_id = await _make_active_sub(
        user_id=uid,
        provider_subscription_id="nlsub_test_test_1778080",
        expires_at=expected_exp,
    )

    nl = AsyncMock()
    nl.get_key = AsyncMock(side_effect=AssertionError("must not be called"))

    factory = get_session_factory()
    async with factory() as session:
        result = await reconcile_subscriptions(session, northline=nl)

    assert result["skipped_test"] >= 1
    assert result["checked"] == 0
    assert nl.get_key.await_count == 0

    sub = await _get_sub(sub_id)
    assert sub.status == SUB_STATUS_ACTIVE
    assert abs((sub.expires_at - expected_exp).total_seconds()) < 1


@pytest.mark.asyncio
async def test_reconcile_extends_when_provider_has_later_expiry(seed_db):  # noqa: ANN001
    uid = await _make_user(7002)
    local_exp = datetime.now(tz=timezone.utc) + timedelta(days=5)
    provider_exp = local_exp + timedelta(days=10)
    sub_id = await _make_active_sub(
        user_id=uid,
        provider_subscription_id="real_provider_id_001",
        expires_at=local_exp,
    )

    nl = AsyncMock()
    nl.get_key = AsyncMock(
        return_value=KeyInfo(
            ok=True,
            subscription_id="real_provider_id_001",
            key="k",
            status="active",
            expires_at=provider_exp,
        )
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await reconcile_subscriptions(session, northline=nl)

    assert result["extended"] == 1
    sub = await _get_sub(sub_id)
    assert abs((sub.expires_at - provider_exp).total_seconds()) < 1
    assert sub.status == SUB_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_reconcile_does_not_shrink_when_provider_has_earlier_expiry(  # noqa: ANN001
    seed_db,
):
    """User paid for 30d; we never shorten on the provider's say-so."""
    uid = await _make_user(7003)
    local_exp = datetime.now(tz=timezone.utc) + timedelta(days=20)
    provider_exp = local_exp - timedelta(days=10)
    sub_id = await _make_active_sub(
        user_id=uid,
        provider_subscription_id="real_provider_id_002",
        expires_at=local_exp,
    )

    nl = AsyncMock()
    nl.get_key = AsyncMock(
        return_value=KeyInfo(
            ok=True,
            subscription_id="real_provider_id_002",
            key="k",
            status="active",
            expires_at=provider_exp,
        )
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await reconcile_subscriptions(session, northline=nl)

    assert result["shrink_warned"] == 1
    assert result["extended"] == 0
    sub = await _get_sub(sub_id)
    assert abs((sub.expires_at - local_exp).total_seconds()) < 1, (
        "Local expires_at must NOT be shortened by reconcile."
    )


@pytest.mark.asyncio
async def test_reconcile_flips_status_when_provider_says_expired(seed_db):  # noqa: ANN001
    uid = await _make_user(7004)
    sub_id = await _make_active_sub(
        user_id=uid,
        provider_subscription_id="real_provider_id_003",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=10),
    )

    nl = AsyncMock()
    nl.get_key = AsyncMock(
        return_value=KeyInfo(
            ok=True,
            subscription_id="real_provider_id_003",
            key="k",
            status="expired",
            expires_at=datetime.now(tz=timezone.utc),
        )
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await reconcile_subscriptions(session, northline=nl)

    assert result["flipped"] == 1
    sub = await _get_sub(sub_id)
    assert sub.status == SUB_STATUS_EXPIRED


@pytest.mark.asyncio
async def test_reconcile_flips_to_deactivated_on_invalid_provider_key(  # noqa: ANN001
    seed_db,
):
    """Provider doesn't recognize the key → user can't connect anyway,
    so the local row should reflect that as ``deactivated``."""
    uid = await _make_user(7005)
    sub_id = await _make_active_sub(
        user_id=uid,
        provider_subscription_id="real_provider_id_004",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=10),
    )

    nl = AsyncMock()
    nl.get_key = AsyncMock(
        side_effect=NorthLineClientError(
            "invalid_provider_key",
            "Provider key not recognized",
            400,
        )
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await reconcile_subscriptions(session, northline=nl)

    assert result["flipped"] == 1
    sub = await _get_sub(sub_id)
    assert sub.status == SUB_STATUS_DEACTIVATED
    assert sub.deactivated_at is not None
    assert "invalid_provider_key" in (sub.deactivation_reason or "")


@pytest.mark.asyncio
async def test_reconcile_leaves_row_alone_on_transient_error(seed_db):  # noqa: ANN001
    """5xx / network errors must not flip rows — try again next run."""
    uid = await _make_user(7006)
    local_exp = datetime.now(tz=timezone.utc) + timedelta(days=10)
    sub_id = await _make_active_sub(
        user_id=uid,
        provider_subscription_id="real_provider_id_005",
        expires_at=local_exp,
    )

    nl = AsyncMock()
    nl.get_key = AsyncMock(
        side_effect=NorthLineUnavailableError("connection reset")
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await reconcile_subscriptions(session, northline=nl)

    assert result["api_errors"] == 1
    assert result["flipped"] == 0
    sub = await _get_sub(sub_id)
    assert sub.status == SUB_STATUS_ACTIVE
    assert abs((sub.expires_at - local_exp).total_seconds()) < 1
