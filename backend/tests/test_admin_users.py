"""Stage 5 admin users tests: list filter/sort, ban, unban, balance adjust."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.db.models.user import User
from app.db.session import get_session_factory


@pytest_asyncio.fixture
async def admin_token(client, seed_db, admin_initial_key) -> str:  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def auth_admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def make_user(seed_db):  # noqa: ANN001
    async def _factory(**fields) -> int:
        defaults = {
            "tg_id": 100001,
            "username": "alice",
            "first_name": "Alice",
            "balance_kopecks": 1000,
        }
        defaults.update(fields)
        factory = get_session_factory()
        async with factory() as session:
            u = User(**defaults)
            session.add(u)
            await session.commit()
            await session.refresh(u)
            return u.id

    return _factory


@pytest.mark.asyncio
async def test_list_users(client, make_user, auth_admin_headers):  # noqa: ANN001
    uid = await make_user()
    r = await client.get("/api/admin/users", headers=auth_admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert any(item["id"] == uid for item in body["items"])


@pytest.mark.asyncio
async def test_list_users_search(client, make_user, auth_admin_headers):  # noqa: ANN001
    await make_user(tg_id=200001, username="bob_unique", first_name="Bob")
    await make_user(tg_id=200002, username="other_user", first_name="Other")
    r = await client.get(
        "/api/admin/users?q=bob_unique",
        headers=auth_admin_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["username"] == "bob_unique"


@pytest.mark.asyncio
async def test_user_detail_404(client, auth_admin_headers, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/users/999999", headers=auth_admin_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_ban_unban(client, make_user, auth_admin_headers):  # noqa: ANN001
    uid = await make_user(tg_id=300001, username="banme")

    r_ban = await client.post(
        f"/api/admin/users/{uid}/ban",
        headers=auth_admin_headers,
        json={"reason": "spam"},
    )
    assert r_ban.status_code == 200, r_ban.text

    r_get = await client.get(
        f"/api/admin/users/{uid}", headers=auth_admin_headers
    )
    body = r_get.json()
    assert body["is_banned"] is True
    assert body["ban_reason"] == "spam"

    r_unban = await client.post(
        f"/api/admin/users/{uid}/unban", headers=auth_admin_headers
    )
    assert r_unban.status_code == 200

    r_get = await client.get(f"/api/admin/users/{uid}", headers=auth_admin_headers)
    assert r_get.json()["is_banned"] is False


@pytest.mark.asyncio
async def test_balance_adjust(client, make_user, auth_admin_headers):  # noqa: ANN001
    uid = await make_user(tg_id=400001, username="adjust", balance_kopecks=500)

    r = await client.post(
        f"/api/admin/users/{uid}/balance/adjust",
        headers=auth_admin_headers,
        json={"amount_kop": 1500, "reason": "manual top-up"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_kop"] == 2000
    assert body["delta_kop"] == 1500

    # History
    r_h = await client.get(
        f"/api/admin/users/{uid}/balance-history", headers=auth_admin_headers
    )
    assert r_h.status_code == 200
    rows = r_h.json()
    assert any(r["reason"] == "admin_adjust" and r["amount_kop"] == 1500 for r in rows)


@pytest.mark.asyncio
async def test_balance_adjust_negative_blocked_below_zero(
    client, make_user, auth_admin_headers
):  # noqa: ANN001
    uid = await make_user(tg_id=500001, username="cantgo", balance_kopecks=100)
    r = await client.post(
        f"/api/admin/users/{uid}/balance/adjust",
        headers=auth_admin_headers,
        json={"amount_kop": -1000, "reason": "wipe"},
    )
    assert r.status_code == 402  # InsufficientBalanceError
