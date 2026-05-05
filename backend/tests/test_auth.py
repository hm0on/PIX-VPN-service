"""Admin auth tests: login, wrong key, rotation, grace period."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_login_ok(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["label"] == "test-main"
    assert body["kid"] >= 1


@pytest.mark.asyncio
async def test_login_wrong_key(client, seed_db):  # noqa: ANN001
    r = await client.post(
        "/api/admin/auth/login",
        json={"key": "definitely_wrong_key_value_long_enough"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_admin_key"


@pytest.mark.asyncio
async def test_me_with_token(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]

    r2 = await client.get(
        "/api/admin/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert r2.json()["label"] == "test-main"


@pytest.mark.asyncio
async def test_me_requires_jwt(client):  # noqa: ANN001
    r = await client.get("/api/admin/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rotate_key_grace(client, seed_db, admin_initial_key):  # noqa: ANN001
    # Login with initial key
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    assert r.status_code == 200
    token = r.json()["access_token"]
    initial_kid = r.json()["kid"]

    # Rotate
    r_rot = await client.post(
        "/api/admin/auth/refresh",
        json={"new_label": "rotated-key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_rot.status_code == 200, r_rot.text
    rot = r_rot.json()
    new_plaintext = rot["new_plaintext_key"]
    assert new_plaintext
    assert rot["previous_key_id"] == initial_kid
    assert rot["previous_valid_until"] is not None

    # New key works
    r_new = await client.post("/api/admin/auth/login", json={"key": new_plaintext})
    assert r_new.status_code == 200

    # Old key still works during grace (revoked_at set, but valid_until > now)
    r_old = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    assert r_old.status_code == 200, r_old.text


@pytest.mark.asyncio
async def test_list_keys(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    r_list = await client.get(
        "/api/admin/auth/keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_list.status_code == 200
    keys = r_list.json()
    assert len(keys) >= 1
    assert any(k["label"] == "test-main" for k in keys)
