"""Stage 5 admin tariffs tests."""

from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_tariffs_includes_inactive(client, admin_headers):  # noqa: ANN001
    r = await client.get("/api/admin/tariffs", headers=admin_headers)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    assert any(t["code"] == "basic" for t in items)


@pytest.mark.asyncio
async def test_create_and_patch_tariff(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/tariffs",
        json={
            "code": "vip",
            "name": "VIP",
            "description_html": "<b>VIP</b>",
            "devices": 5,
            "sort_order": 100,
            "is_active": True,
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["id"]
    assert body["code"] == "vip"

    # Duplicate code → conflict
    r_dup = await client.post(
        "/api/admin/tariffs",
        json={
            "code": "vip",
            "name": "VIP-2",
            "devices": 5,
        },
        headers=admin_headers,
    )
    assert r_dup.status_code == 409

    # Patch
    r_pat = await client.patch(
        f"/api/admin/tariffs/{tid}",
        json={"name": "VIP+", "sort_order": 50},
        headers=admin_headers,
    )
    assert r_pat.status_code == 200
    assert r_pat.json()["name"] == "VIP+"
    assert r_pat.json()["sort_order"] == 50


@pytest.mark.asyncio
async def test_soft_delete_tariff(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/tariffs",
        json={"code": "tmp", "name": "Tmp", "devices": 1},
        headers=admin_headers,
    )
    tid = r.json()["id"]
    rd = await client.delete(
        f"/api/admin/tariffs/{tid}", headers=admin_headers
    )
    assert rd.status_code == 200

    rg = await client.get("/api/admin/tariffs", headers=admin_headers)
    found = next((t for t in rg.json() if t["id"] == tid), None)
    assert found is not None
    assert found["is_active"] is False


@pytest.mark.asyncio
async def test_duration_crud(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/tariffs",
        json={"code": "dur1", "name": "Dur1", "devices": 2},
        headers=admin_headers,
    )
    tid = r.json()["id"]

    rd = await client.post(
        f"/api/admin/tariffs/{tid}/durations",
        json={"days": 30, "price_kopecks": 9900, "is_hot": True},
        headers=admin_headers,
    )
    assert rd.status_code == 201, rd.text
    durations = rd.json()["durations"]
    assert len(durations) == 1
    did = durations[0]["id"]

    rp = await client.patch(
        f"/api/admin/tariffs/{tid}/durations/{did}",
        json={"price_kopecks": 12000, "is_hot": False},
        headers=admin_headers,
    )
    assert rp.status_code == 200
    new_durations = rp.json()["durations"]
    assert new_durations[0]["price_kopecks"] == 12000
    assert new_durations[0]["is_hot"] is False

    rdel = await client.delete(
        f"/api/admin/tariffs/{tid}/durations/{did}",
        headers=admin_headers,
    )
    assert rdel.status_code == 200


@pytest.mark.asyncio
async def test_requires_jwt(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/tariffs")
    assert r.status_code == 401
