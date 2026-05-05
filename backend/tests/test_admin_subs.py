"""Stage 5 admin subscriptions tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.db.models.subscription import SUB_STATUS_ACTIVE, Subscription
from app.db.models.user import User
from app.db.session import get_session_factory


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key) -> dict[str, str]:  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def sub_factory(seed_db):  # noqa: ANN001
    async def _factory(**fields) -> tuple[int, int]:
        factory = get_session_factory()
        async with factory() as session:
            u = User(tg_id=fields.pop("tg_id", 700001), username="subuser")
            session.add(u)
            await session.flush()

            now = datetime.now(tz=UTC)
            sub = Subscription(
                user_id=u.id,
                tariff_id=fields.pop("tariff_id", 2),
                devices=fields.pop("devices", 3),
                days=fields.pop("days", 30),
                status=fields.pop("status", SUB_STATUS_ACTIVE),
                started_at=now,
                expires_at=now + timedelta(days=30),
                provider_subscription_id=fields.pop(
                    "provider_subscription_id", None
                ),
                key_url=fields.pop("key_url", "vless://example"),
                **fields,
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return u.id, sub.id

    return _factory


@pytest.mark.asyncio
async def test_list_subscriptions(client, sub_factory, admin_headers):  # noqa: ANN001
    _, sub_id = await sub_factory()
    r = await client.get("/api/admin/subscriptions", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(item["id"] == sub_id for item in body["items"])


@pytest.mark.asyncio
async def test_subscription_detail(client, sub_factory, admin_headers):  # noqa: ANN001
    _, sub_id = await sub_factory()
    r = await client.get(f"/api/admin/subscriptions/{sub_id}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sub_id
    assert body["status"] == SUB_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_subscription_404(client, admin_headers, seed_db):  # noqa: ANN001
    r = await client.get(
        "/api/admin/subscriptions/999999", headers=admin_headers
    )
    assert r.status_code == 404
