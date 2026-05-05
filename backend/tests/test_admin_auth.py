"""Stage 5 admin auth tests: rotate-with-grace, list with is_current, self-revoke forbidden."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_keys_rotate_with_grace(client, seed_db, admin_initial_key):  # noqa: ANN001
    # Login with seeded key
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    initial_kid = r.json()["kid"]

    # Rotate with grace 1h
    r_rot = await client.post(
        "/api/admin/auth/keys/rotate",
        json={"label": "rotated-main", "grace_hours": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_rot.status_code == 200, r_rot.text
    body = r_rot.json()
    assert body["key"]
    assert body["label"] == "rotated-main"
    assert body["id"] != initial_kid

    # New key works
    r_new_login = await client.post(
        "/api/admin/auth/login", json={"key": body["key"]}
    )
    assert r_new_login.status_code == 200

    # Old key still works during grace
    r_old_login = await client.post(
        "/api/admin/auth/login", json={"key": admin_initial_key}
    )
    assert r_old_login.status_code == 200, r_old_login.text


@pytest.mark.asyncio
async def test_list_keys_marks_is_current(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    kid = r.json()["kid"]

    r_list = await client.get(
        "/api/admin/auth/keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_list.status_code == 200
    keys = r_list.json()
    current = [k for k in keys if k["is_current"]]
    assert len(current) == 1
    assert current[0]["id"] == kid


@pytest.mark.asyncio
async def test_cannot_revoke_current_key(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    kid = r.json()["kid"]

    r_del = await client.delete(
        f"/api/admin/auth/keys/{kid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_del.status_code == 403
    assert r_del.json()["error"]["code"] == "cannot_revoke_current_key"


@pytest.mark.asyncio
async def test_revoke_other_key(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    initial_kid = r.json()["kid"]

    # Create a new key via rotate
    r_rot = await client.post(
        "/api/admin/auth/keys/rotate",
        json={"label": "secondary", "grace_hours": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_rot.status_code == 200
    new_kid = r_rot.json()["id"]
    assert new_kid != initial_kid

    # Login with the new key
    new_token = (
        await client.post("/api/admin/auth/login", json={"key": r_rot.json()["key"]})
    ).json()["access_token"]

    # Now revoke the OLD (initial) key from the new key's session
    r_del = await client.delete(
        f"/api/admin/auth/keys/{initial_kid}",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert r_del.status_code == 200


@pytest.mark.asyncio
async def test_admin_endpoints_require_jwt(client, seed_db):  # noqa: ANN001
    """Sanity: protected endpoints reject missing JWT."""
    for path in (
        "/api/admin/users",
        "/api/admin/subscriptions",
        "/api/admin/stats/dashboard",
        "/api/admin/auth/keys",
    ):
        r = await client.get(path)
        assert r.status_code == 401, f"{path} should be 401, got {r.status_code}"
