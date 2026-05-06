"""Balance purchase tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import NorthLineUnavailableError
from app.db.models.tariff import Tariff, TariffDuration
from app.db.models.user import User
from app.db.session import get_session_factory
from app.deps import get_northline_client
from app.schemas.northline import KeyResponse


def _make_northline_mock(*, fail: bool = False) -> AsyncMock:
    mock = AsyncMock()
    if fail:
        mock.create_key = AsyncMock(side_effect=NorthLineUnavailableError("nl down"))
    else:
        mock.create_key = AsyncMock(
            return_value=KeyResponse(
                ok=True,
                subscription_id="northline_sub_balance_001",
                key="https://sub.pixio.icu/balance001",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
                devices=3,
                days=30,
            )
        )
    mock.aclose = AsyncMock(return_value=None)
    return mock


async def _credit_balance(tg_id: int, kopecks: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = result.scalar_one()
        user.balance_kopecks = kopecks
        await session.commit()


async def _get_basic_30_days() -> tuple[int, int, int]:
    """Return (tariff_id, duration_id, price_kopecks) for 'basic' / 30 days."""
    factory = get_session_factory()
    async with factory() as session:
        t_res = await session.execute(select(Tariff).where(Tariff.code == "basic"))
        tariff = t_res.scalar_one()
        d_res = await session.execute(
            select(TariffDuration).where(
                TariffDuration.tariff_id == tariff.id,
                TariffDuration.days == 30,
            )
        )
        duration = d_res.scalar_one()
        return tariff.id, duration.id, int(duration.price_kopecks)


@pytest.mark.asyncio
async def test_purchase_with_balance_happy(client, auth_headers, seed_db, app):  # noqa: ANN001
    nl_mock = _make_northline_mock()
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 6001, "username": "buy1"},
    )
    tariff_id, duration_id, price = await _get_basic_30_days()
    await _credit_balance(6001, price + 50000)

    r = await client.post(
        "/api/bot/purchase/balance",
        headers=auth_headers,
        json={"tg_id": 6001, "tariff_id": tariff_id, "duration_id": duration_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subscription"]["status"] == "active"
    assert body["subscription"]["key_url"] == "https://sub.pixio.icu/balance001"
    assert body["balance_after_kopecks"] == 50000
    # ``payment_id`` is exposed at the top level so the bot can render it
    # in the post-success "✅ Вы успешно оплатили заказ #N" message that
    # it edits in place. Must be a positive int.
    assert isinstance(body["payment_id"], int)
    assert body["payment_id"] > 0

    # Check user balance was actually debited.
    r2 = await client.get("/api/bot/users/6001/balance", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["balance_kopecks"] == 50000


@pytest.mark.asyncio
async def test_purchase_with_insufficient_balance(  # noqa: ANN001
    client, auth_headers, seed_db, app
):
    nl_mock = _make_northline_mock()
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 6002, "username": "buy2"},
    )
    tariff_id, duration_id, price = await _get_basic_30_days()
    await _credit_balance(6002, price - 100)

    r = await client.post(
        "/api/bot/purchase/balance",
        headers=auth_headers,
        json={"tg_id": 6002, "tariff_id": tariff_id, "duration_id": duration_id},
    )
    assert r.status_code == 402
    body = r.json()
    assert body["error"]["code"] == "insufficient_balance"
    assert body["error"]["details"]["current_balance_kopecks"] == price - 100
    assert body["error"]["details"]["required_kopecks"] == price

    nl_mock.create_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_purchase_with_balance_refund_on_provider_failure(  # noqa: ANN001
    client, auth_headers, seed_db, app
):
    nl_mock = _make_northline_mock(fail=True)
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 6003, "username": "buy3"},
    )
    tariff_id, duration_id, price = await _get_basic_30_days()
    starting = price + 12345
    await _credit_balance(6003, starting)

    r = await client.post(
        "/api/bot/purchase/balance",
        headers=auth_headers,
        json={"tg_id": 6003, "tariff_id": tariff_id, "duration_id": duration_id},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "vpn_provider_unavailable"

    # Balance should be refunded back to original.
    r2 = await client.get("/api/bot/users/6003/balance", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["balance_kopecks"] == starting
