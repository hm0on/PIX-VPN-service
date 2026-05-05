"""Stage 5 admin stats tests: dashboard KPIs, time series, recent lists."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio

from app.db.models.payment import (
    PAYMENT_PROVIDER_PLATEGA_SBP,
    PAYMENT_PURPOSE_TOPUP,
    PAYMENT_STATUS_PAID,
    Payment,
)
from app.db.models.user import User
from app.db.session import get_session_factory


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key) -> dict[str, str]:  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def seed_payments(seed_db):  # noqa: ANN001
    factory = get_session_factory()
    async with factory() as session:
        u = User(tg_id=900001, username="payer")
        session.add(u)
        await session.flush()

        now = datetime.now(tz=UTC)
        for amount in (10000, 20000, 30000):
            session.add(
                Payment(
                    user_id=u.id,
                    purpose=PAYMENT_PURPOSE_TOPUP,
                    provider=PAYMENT_PROVIDER_PLATEGA_SBP,
                    amount_kopecks=amount,
                    currency="RUB",
                    status=PAYMENT_STATUS_PAID,
                    paid_at=now,
                )
            )
        await session.commit()
    yield


@pytest.mark.asyncio
async def test_dashboard(client, seed_payments, admin_headers):  # noqa: ANN001
    r = await client.get("/api/admin/stats/dashboard", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_users"] >= 1
    assert body["revenue_today"] >= 60000  # 10000+20000+30000
    assert body["revenue_month"] >= 60000


@pytest.mark.asyncio
async def test_revenue_series(client, seed_payments, admin_headers):  # noqa: ANN001
    r = await client.get(
        "/api/admin/stats/revenue?period=30d", headers=admin_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert "points" in body
    assert len(body["points"]) == 30
    # at least one bucket should be > 0 (today)
    assert any(p["amount"] > 0 for p in body["points"])


@pytest.mark.asyncio
async def test_users_series(client, seed_payments, admin_headers):  # noqa: ANN001
    r = await client.get("/api/admin/stats/users?period=30d", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) == 30


@pytest.mark.asyncio
async def test_recent_payments(client, seed_payments, admin_headers):  # noqa: ANN001
    r = await client.get(
        "/api/admin/stats/dashboard/recent-payments", headers=admin_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert all("user_tg_id" in row for row in rows)


@pytest.mark.asyncio
async def test_recent_users(client, seed_payments, admin_headers):  # noqa: ANN001
    r = await client.get(
        "/api/admin/stats/dashboard/recent-users", headers=admin_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert any(row["tg_id"] == 900001 for row in rows)
