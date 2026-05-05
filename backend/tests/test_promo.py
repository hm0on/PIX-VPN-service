"""Promo-code apply endpoint + service tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture
async def seeded_user(client, auth_headers):  # noqa: ANN001
    payload = {"tg_id": 880001, "username": "promo_user"}
    r = await client.post("/api/bot/users", json=payload, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["user"]


async def _insert_promo(**kwargs) -> int:
    """Insert a PromoCode row directly. Returns its id."""
    from app.db.models.promo_code import PromoCode
    from app.db.session import get_session_factory

    defaults = {
        "type": "balance",
        "value": 10000,
        "max_total_activations": None,
        "max_per_user": 1,
        "current_activations": 0,
        "valid_from": None,
        "valid_until": None,
        "is_active": True,
        "description": None,
    }
    defaults.update(kwargs)

    factory = get_session_factory()
    async with factory() as session:
        promo = PromoCode(**defaults)
        session.add(promo)
        await session.flush()
        await session.commit()
        return int(promo.id)


async def _get_promo(promo_id: int):
    from app.db.models.promo_code import PromoCode
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(PromoCode).where(PromoCode.id == promo_id)
        )
        return result.scalar_one()


async def _get_user_balance(tg_id: int) -> int:
    from app.db.models.user import User
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        return int(result.scalar_one().balance_kopecks)


async def _list_activations(promo_id: int):
    from app.db.models.promo_activation import PromoActivation
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(PromoActivation).where(
                PromoActivation.promo_id == promo_id
            )
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_unknown_promo_returns_404(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    r = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "NOPE_XX"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "promo_not_found"


@pytest.mark.asyncio
async def test_apply_expired_promo_returns_400(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    promo_id = await _insert_promo(
        code="EXPIRED1",
        type="balance",
        value=10000,
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
    )
    r = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "EXPIRED1"},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"]["code"] == "promo_unavailable"
    assert body["error"]["details"]["reason"] == "expired"

    # current_activations untouched.
    promo = await _get_promo(promo_id)
    assert promo.current_activations == 0


@pytest.mark.asyncio
async def test_apply_max_total_activations_exceeded(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    await _insert_promo(
        code="FULL1",
        type="balance",
        value=5000,
        max_total_activations=3,
        current_activations=3,
    )
    r = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "FULL1"},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"]["code"] == "promo_unavailable"
    assert (
        body["error"]["details"]["reason"] == "max_total_activations_exceeded"
    )


@pytest.mark.asyncio
async def test_apply_max_per_user_exceeded_after_first_apply(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    promo_id = await _insert_promo(
        code="ONCE1",
        type="balance",
        value=15000,
        max_per_user=1,
    )

    # First application succeeds.
    r1 = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "ONCE1"},
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["type"] == "balance"
    assert body1["amount_kopecks"] == 15000

    # Second application by the same user — rejected.
    r2 = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "ONCE1"},
    )
    assert r2.status_code == 400, r2.text
    body2 = r2.json()
    assert body2["error"]["code"] == "promo_unavailable"
    assert body2["error"]["details"]["reason"] == "max_per_user_exceeded"

    # Activation count still 1.
    promo = await _get_promo(promo_id)
    assert promo.current_activations == 1


@pytest.mark.asyncio
async def test_apply_balance_credits_user_creates_activation_and_outbox(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    from app.db.models.outbox import Outbox
    from app.db.session import get_session_factory

    promo_id = await _insert_promo(
        code="GIFT100",
        type="balance",
        value=10000,  # 100 ₽
        max_per_user=1,
    )

    starting_balance = await _get_user_balance(seeded_user["tg_id"])

    r = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "GIFT100"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "balance"
    assert body["amount_kopecks"] == 10000
    assert body["promo_id"] == promo_id
    assert body["percent"] is None
    assert body["message"] is not None

    # Balance credited.
    new_balance = await _get_user_balance(seeded_user["tg_id"])
    assert new_balance == starting_balance + 10000

    # current_activations incremented.
    promo = await _get_promo(promo_id)
    assert promo.current_activations == 1

    # Activation row created.
    activations = await _list_activations(promo_id)
    assert len(activations) == 1
    assert activations[0].user_id == seeded_user["id"]
    assert activations[0].amount_applied_kopecks == 10000
    assert activations[0].payment_id is None

    # Outbox message enqueued for this user.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Outbox).where(Outbox.user_id == seeded_user["id"])
        )
        rows = list(result.scalars().all())
        assert any(
            (r.payload or {}).get("text_key") == "promo_balance_applied"
            for r in rows
        )


@pytest.mark.asyncio
async def test_apply_balance_case_insensitive(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    await _insert_promo(
        code="MixedCase1",
        type="balance",
        value=20000,
        max_per_user=1,
    )

    r = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "mixedcase1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["amount_kopecks"] == 20000


@pytest.mark.asyncio
async def test_apply_discount_does_not_touch_balance_or_activations(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    from app.db.models.outbox import Outbox
    from app.db.session import get_session_factory

    promo_id = await _insert_promo(
        code="SAVE10",
        type="discount_percent",
        value=10,
        max_per_user=5,
    )

    starting_balance = await _get_user_balance(seeded_user["tg_id"])

    r = await client.post(
        "/api/bot/promo/apply",
        headers=auth_headers,
        json={"tg_id": seeded_user["tg_id"], "code": "SAVE10"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "discount_percent"
    assert body["percent"] == 10
    assert body["promo_id"] == promo_id
    assert body["amount_kopecks"] is None

    # Balance NOT touched.
    new_balance = await _get_user_balance(seeded_user["tg_id"])
    assert new_balance == starting_balance

    # current_activations NOT incremented.
    promo = await _get_promo(promo_id)
    assert promo.current_activations == 0

    # No PromoActivation row yet.
    activations = await _list_activations(promo_id)
    assert activations == []

    # No "promo_balance_applied" outbox message.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Outbox).where(Outbox.user_id == seeded_user["id"])
        )
        rows = list(result.scalars().all())
        assert not any(
            (r.payload or {}).get("text_key") == "promo_balance_applied"
            for r in rows
        )


# ---------------------------------------------------------------------------
# Service-level helpers
# ---------------------------------------------------------------------------


def test_compute_discounted_price_floor():
    from app.services.promo_service import compute_discounted_price

    # 199 ₽ * 90% = 179.10 ₽ -> 179 ₽ (rounded down).
    assert compute_discounted_price(19900, 10) == 17910
    # Exact division.
    assert compute_discounted_price(10000, 25) == 7500
    # 0% -> unchanged.
    assert compute_discounted_price(12345, 0) == 12345
    # 100% -> 0.
    assert compute_discounted_price(12345, 100) == 0
    # Floor down: 199 * 90 // 100 = 179.
    assert compute_discounted_price(199, 10) == 179


@pytest.mark.asyncio
async def test_record_discount_activation_after_payment(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    """record_discount_activation creates a PromoActivation and bumps the counter."""
    from app.db.session import get_session_factory
    from app.services.promo_service import PromoService

    promo_id = await _insert_promo(
        code="WEBHOOK10",
        type="discount_percent",
        value=10,
        max_per_user=5,
    )

    factory = get_session_factory()
    async with factory() as session:
        svc = PromoService(session)
        result = await svc.record_discount_activation(
            promo_id=promo_id,
            user_id=seeded_user["id"],
            payment_id=None,  # payment_id is NULLable in model
            discount_kopecks=1990,
        )
        await session.commit()
        assert result is not None
        assert result.amount_applied_kopecks == 1990

    promo = await _get_promo(promo_id)
    assert promo.current_activations == 1
    activations = await _list_activations(promo_id)
    assert len(activations) == 1
    assert activations[0].amount_applied_kopecks == 1990


@pytest.mark.asyncio
async def test_record_discount_activation_no_raise_when_exhausted(  # noqa: ANN001
    client, auth_headers, seeded_user
):
    """When max_total_activations was hit between checkout and webhook,
    we must not raise — user already paid."""
    from app.db.session import get_session_factory
    from app.services.promo_service import PromoService

    promo_id = await _insert_promo(
        code="TIGHT1",
        type="discount_percent",
        value=10,
        max_total_activations=1,
        current_activations=1,  # already exhausted
    )

    factory = get_session_factory()
    async with factory() as session:
        svc = PromoService(session)
        result = await svc.record_discount_activation(
            promo_id=promo_id,
            user_id=seeded_user["id"],
            payment_id=None,
            discount_kopecks=1000,
        )
        await session.commit()

    assert result is None
    activations = await _list_activations(promo_id)
    assert activations == []
