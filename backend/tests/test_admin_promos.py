"""Stage 5 admin promos tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_and_list_promo(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 100, "max_per_user": 1},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    auto_code = r.json()["code"]
    assert len(auto_code) >= 6

    r_list = await client.get("/api/admin/promos", headers=admin_headers)
    assert r_list.status_code == 200
    body = r_list.json()
    assert body["total"] >= 1
    assert any(p["id"] == pid for p in body["items"])

    # Filter by code substring
    r_search = await client.get(
        f"/api/admin/promos?code={auto_code[:3]}",
        headers=admin_headers,
    )
    assert r_search.status_code == 200


@pytest.mark.asyncio
async def test_create_with_explicit_code_and_window(client, admin_headers):  # noqa: ANN001
    valid_from = datetime.now(timezone.utc).replace(microsecond=0)
    valid_until = valid_from + timedelta(days=7)
    r = await client.post(
        "/api/admin/promos",
        json={
            "code": "summer24",
            "type": "discount_percent",
            "value": 25,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "description": "Summer sale",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["code"] == "SUMMER24"


@pytest.mark.asyncio
async def test_invalid_window_rejected(client, admin_headers):  # noqa: ANN001
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/admin/promos",
        json={
            "type": "balance",
            "value": 100,
            "valid_from": now.isoformat(),
            "valid_until": (now - timedelta(days=1)).isoformat(),
        },
        headers=admin_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_only_allowed_fields(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 100},
        headers=admin_headers,
    )
    pid = r.json()["id"]

    # value and code are not editable — extra=forbid → 422
    rp_bad = await client.patch(
        f"/api/admin/promos/{pid}",
        json={"value": 200},
        headers=admin_headers,
    )
    assert rp_bad.status_code == 422

    rp = await client.patch(
        f"/api/admin/promos/{pid}",
        json={"is_active": False, "max_per_user": 5},
        headers=admin_headers,
    )
    assert rp.status_code == 200
    assert rp.json()["is_active"] is False
    assert rp.json()["max_per_user"] == 5


@pytest.mark.asyncio
async def test_activations_endpoint(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 100},
        headers=admin_headers,
    )
    pid = r.json()["id"]
    ra = await client.get(
        f"/api/admin/promos/{pid}/activations",
        headers=admin_headers,
    )
    assert ra.status_code == 200
    assert ra.json() == []


@pytest.mark.asyncio
async def test_requires_jwt(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/promos")
    assert r.status_code == 401
