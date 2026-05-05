"""Referral system tests.

Covers:
  - register_referral skipped for old users / self-referrals / duplicates;
  - auto_discount_for_referee returns 10 only on the first paid purchase;
  - apply_referrer_bonus is one-shot and produces an outbox row + balance txn;
  - FREE-trial / topup payments do not trigger the bonus.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.balance_transaction import BalanceTransaction
from app.db.models.outbox import Outbox
from app.db.models.payment import (
    PAYMENT_PROVIDER_PLATEGA_SBP,
    PAYMENT_PURPOSE_SUBSCRIPTION,
    PAYMENT_PURPOSE_TOPUP,
    PAYMENT_STATUS_PAID,
    Payment,
)
from app.db.models.referral import Referral
from app.db.models.user import User
from app.db.session import get_session_factory
from app.services import referral_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(_engine_setup):  # noqa: ANN001
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def _create_user(
    session,  # noqa: ANN001
    *,
    tg_id: int,
    username: str | None = None,
    balance: int = 0,
) -> User:
    user = User(
        tg_id=tg_id,
        username=username,
        balance_kopecks=balance,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_payment(
    session,  # noqa: ANN001
    *,
    user_id: int,
    purpose: str = PAYMENT_PURPOSE_SUBSCRIPTION,
    status: str = PAYMENT_STATUS_PAID,
    amount: int = 18900,
) -> Payment:
    payment = Payment(
        user_id=user_id,
        subscription_id=None,
        purpose=purpose,
        provider=PAYMENT_PROVIDER_PLATEGA_SBP,
        amount_kopecks=amount,
        currency="RUB",
        status=status,
    )
    session.add(payment)
    await session.flush()
    await session.refresh(payment)
    return payment


# ---------------------------------------------------------------------------
# register_referral
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_referral_creates_row(db_session):  # noqa: ANN001
    referrer = await _create_user(db_session, tg_id=11001, username="ref")
    referee = await _create_user(db_session, tg_id=11002, username="ree")

    row = await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=True,
    )
    assert row is not None
    assert row.referrer_id == referrer.id
    assert row.referee_id == referee.id
    assert row.bonus_paid is False


@pytest.mark.asyncio
async def test_register_referral_skip_when_not_new(db_session):  # noqa: ANN001
    referrer = await _create_user(db_session, tg_id=11003)
    referee = await _create_user(db_session, tg_id=11004)

    row = await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=False,
    )
    assert row is None
    res = await db_session.execute(
        select(Referral).where(Referral.referee_id == referee.id)
    )
    assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_register_referral_self_referral_raises(db_session):  # noqa: ANN001
    user = await _create_user(db_session, tg_id=11005)
    from app.core.exceptions import ReferralSelfReferralError

    with pytest.raises(ReferralSelfReferralError):
        await referral_service.register_referral(
            db_session,
            referrer_user=user,
            referee_user=user,
            is_new=True,
        )


@pytest.mark.asyncio
async def test_register_referral_already_exists(db_session):  # noqa: ANN001
    referrer1 = await _create_user(db_session, tg_id=11006)
    referrer2 = await _create_user(db_session, tg_id=11007)
    referee = await _create_user(db_session, tg_id=11008)

    await referral_service.register_referral(
        db_session,
        referrer_user=referrer1,
        referee_user=referee,
        is_new=True,
    )

    from app.core.exceptions import ReferralAlreadyExistsError

    with pytest.raises(ReferralAlreadyExistsError):
        await referral_service.register_referral(
            db_session,
            referrer_user=referrer2,
            referee_user=referee,
            is_new=True,
        )


# ---------------------------------------------------------------------------
# auto_discount_for_referee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_discount_returns_10_for_unpaid_referee(  # noqa: ANN001
    db_session,
):
    referrer = await _create_user(db_session, tg_id=11009)
    referee = await _create_user(db_session, tg_id=11010)
    await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=True,
    )
    pct = await referral_service.auto_discount_for_referee(db_session, referee)
    assert pct == referral_service.REFERRAL_AUTO_DISCOUNT_PERCENT == 10


@pytest.mark.asyncio
async def test_auto_discount_none_for_referee_with_paid_history(  # noqa: ANN001
    db_session,
):
    referrer = await _create_user(db_session, tg_id=11011)
    referee = await _create_user(db_session, tg_id=11012)
    await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=True,
    )
    await _create_payment(db_session, user_id=referee.id, amount=18900)
    pct = await referral_service.auto_discount_for_referee(db_session, referee)
    assert pct is None


@pytest.mark.asyncio
async def test_auto_discount_none_for_non_referee(db_session):  # noqa: ANN001
    user = await _create_user(db_session, tg_id=11013)
    pct = await referral_service.auto_discount_for_referee(db_session, user)
    assert pct is None


# ---------------------------------------------------------------------------
# apply_referrer_bonus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_referrer_bonus_credits_balance_once(db_session):  # noqa: ANN001
    referrer = await _create_user(db_session, tg_id=11014, balance=0)
    referee = await _create_user(db_session, tg_id=11015, username="alice")

    await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=True,
    )
    payment = await _create_payment(
        db_session, user_id=referee.id, amount=18900
    )

    await referral_service.apply_referrer_bonus(
        db_session,
        referee_user=referee,
        referee_payment=payment,
    )

    # Balance updated.
    await db_session.refresh(referrer)
    assert referrer.balance_kopecks == 10000  # +100 RUB

    # Outbox has the message.
    outbox_rows = (
        await db_session.execute(
            select(Outbox).where(Outbox.user_id == referrer.id)
        )
    ).scalars().all()
    assert len(outbox_rows) == 1
    assert outbox_rows[0].payload["text_key"] == "referral_bonus_credited"
    assert outbox_rows[0].payload["format_kwargs"]["username"] == "alice"

    # BalanceTransaction recorded.
    bt_rows = (
        await db_session.execute(
            select(BalanceTransaction).where(
                BalanceTransaction.user_id == referrer.id,
                BalanceTransaction.reason == "referral_bonus",
            )
        )
    ).scalars().all()
    assert len(bt_rows) == 1
    assert bt_rows[0].amount_kopecks == 10000

    # Referral row marked paid.
    referral = (
        await db_session.execute(
            select(Referral).where(Referral.referee_id == referee.id)
        )
    ).scalar_one()
    assert referral.bonus_paid is True
    assert referral.referee_first_purchase_id == payment.id

    # Idempotent: second call must NOT double-credit.
    await referral_service.apply_referrer_bonus(
        db_session,
        referee_user=referee,
        referee_payment=payment,
    )
    await db_session.refresh(referrer)
    assert referrer.balance_kopecks == 10000


@pytest.mark.asyncio
async def test_apply_referrer_bonus_skips_topup(db_session):  # noqa: ANN001
    referrer = await _create_user(db_session, tg_id=11016, balance=0)
    referee = await _create_user(db_session, tg_id=11017)
    await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=True,
    )
    topup = await _create_payment(
        db_session, user_id=referee.id, purpose=PAYMENT_PURPOSE_TOPUP, amount=10000
    )
    await referral_service.apply_referrer_bonus(
        db_session,
        referee_user=referee,
        referee_payment=topup,
    )
    await db_session.refresh(referrer)
    assert referrer.balance_kopecks == 0


@pytest.mark.asyncio
async def test_apply_referrer_bonus_skips_zero_amount(db_session):  # noqa: ANN001
    """FREE-trial and similar zero-amount payments must not trigger the bonus."""
    referrer = await _create_user(db_session, tg_id=11018, balance=0)
    referee = await _create_user(db_session, tg_id=11019)
    await referral_service.register_referral(
        db_session,
        referrer_user=referrer,
        referee_user=referee,
        is_new=True,
    )
    free = await _create_payment(
        db_session, user_id=referee.id, amount=0
    )
    await referral_service.apply_referrer_bonus(
        db_session,
        referee_user=referee,
        referee_payment=free,
    )
    await db_session.refresh(referrer)
    assert referrer.balance_kopecks == 0


@pytest.mark.asyncio
async def test_apply_referrer_bonus_no_referral_row(db_session):  # noqa: ANN001
    """User without a Referral row must not produce any side-effects."""
    user = await _create_user(db_session, tg_id=11020, balance=0)
    payment = await _create_payment(db_session, user_id=user.id)
    # No raise, no balance change anywhere.
    await referral_service.apply_referrer_bonus(
        db_session,
        referee_user=user,
        referee_payment=payment,
    )


# ---------------------------------------------------------------------------
# /api/bot/users/{tg_id}/referral-stats endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_referral_stats_endpoint(client, auth_headers, seed_db):  # noqa: ANN001
    # Create a user.
    r = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 12001, "username": "stats"},
    )
    assert r.status_code == 200

    r2 = await client.get(
        "/api/bot/users/12001/referral-stats", headers=auth_headers
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["invited"] == 0
    assert data["earned_kopecks"] == 0
    assert data["ref_link"].startswith("https://t.me/")
    assert "?start=ref_" in data["ref_link"]


@pytest.mark.asyncio
async def test_referral_stats_user_not_found(client, auth_headers):  # noqa: ANN001
    r = await client.get(
        "/api/bot/users/999999990/referral-stats", headers=auth_headers
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


# ---------------------------------------------------------------------------
# /api/bot/users upsert with start_payload `ref_<id>`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_user_with_ref_payload_creates_referral(  # noqa: ANN001
    client, auth_headers
):
    # Create the referrer first.
    r1 = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 13001, "username": "rfr"},
    )
    assert r1.status_code == 200
    referrer_id = r1.json()["user"]["id"]

    # Create a brand-new referee with a ref payload.
    r2 = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={
            "tg_id": 13002,
            "username": "ree",
            "start_payload": f"ref_{referrer_id}",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["created"] is True

    # Verify a Referral row was inserted.
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(
            select(Referral).where(
                Referral.referrer_id == referrer_id,
            )
        )
        row = res.scalar_one_or_none()
        assert row is not None
        assert row.bonus_paid is False


@pytest.mark.asyncio
async def test_upsert_user_existing_user_ref_payload_ignored(  # noqa: ANN001
    client, auth_headers
):
    # Existing referee.
    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 13003, "username": "old"},
    )
    # Referrer.
    r1 = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 13004, "username": "rfr2"},
    )
    referrer_id = r1.json()["user"]["id"]

    # Re-upsert (not new) with ref payload — must NOT create a Referral.
    r2 = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={
            "tg_id": 13003,
            "start_payload": f"ref_{referrer_id}",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["created"] is False

    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(
            select(Referral).where(Referral.referrer_id == referrer_id)
        )
        assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_upsert_user_malformed_payload_ignored(client, auth_headers):  # noqa: ANN001
    r = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={
            "tg_id": 13005,
            "username": "noref",
            "start_payload": "garbage_value",
        },
    )
    assert r.status_code == 200
    assert r.json()["created"] is True


@pytest.mark.asyncio
async def test_upsert_user_self_ref_ignored(client, auth_headers):  # noqa: ANN001
    """ref_<own_id> must not create a self-referral row."""
    # Brand-new user can't refer themselves because they don't have an id yet,
    # but upsert is idempotent — the path should refuse silently anyway.
    r1 = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 13006, "username": "self"},
    )
    own_id = r1.json()["user"]["id"]

    # Repeat with own id payload — must be a no-op (user is no longer new).
    r2 = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={
            "tg_id": 13006,
            "start_payload": f"ref_{own_id}",
        },
    )
    assert r2.status_code == 200

    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(
            select(Referral).where(Referral.referee_id == own_id)
        )
        assert res.scalar_one_or_none() is None
