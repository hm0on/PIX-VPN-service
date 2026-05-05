"""User endpoints tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upsert_user_creates(client, auth_headers):  # noqa: ANN001
    payload = {
        "tg_id": 1001,
        "username": "alice",
        "first_name": "Alice",
        "language_code": "en",
    }
    r = await client.post("/api/bot/users", json=payload, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["user"]["tg_id"] == 1001
    assert body["user"]["username"] == "alice"
    assert body["user"]["balance_kopecks"] == 0


@pytest.mark.asyncio
async def test_upsert_user_updates_existing(client, auth_headers):  # noqa: ANN001
    p1 = {"tg_id": 1002, "username": "bob"}
    r1 = await client.post("/api/bot/users", json=p1, headers=auth_headers)
    assert r1.status_code == 200
    assert r1.json()["created"] is True

    p2 = {"tg_id": 1002, "username": "bob_new", "first_name": "Robert"}
    r2 = await client.post("/api/bot/users", json=p2, headers=auth_headers)
    assert r2.status_code == 200
    body = r2.json()
    assert body["created"] is False
    assert body["user"]["username"] == "bob_new"
    assert body["user"]["first_name"] == "Robert"


@pytest.mark.asyncio
async def test_get_user_by_tg_id(client, auth_headers):  # noqa: ANN001
    p = {"tg_id": 1003, "username": "carol"}
    await client.post("/api/bot/users", json=p, headers=auth_headers)

    r = await client.get("/api/bot/users/1003", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["tg_id"] == 1003


@pytest.mark.asyncio
async def test_get_user_not_found(client, auth_headers):  # noqa: ANN001
    r = await client.get("/api/bot/users/999999999", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_get_user_by_pk_id(client, auth_headers):  # noqa: ANN001
    """The bot's admin-side support flow looks users up by PK id (FK on
    tickets) to recover ``tg_id`` for replies/notices."""
    p = {"tg_id": 1004, "username": "dave"}
    upsert = await client.post("/api/bot/users", json=p, headers=auth_headers)
    assert upsert.status_code == 200
    user_id = upsert.json()["user"]["id"]

    r = await client.get(f"/api/bot/users/by-id/{user_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == user_id
    assert body["tg_id"] == 1004
    assert body["username"] == "dave"


@pytest.mark.asyncio
async def test_get_user_by_pk_id_not_found(client, auth_headers):  # noqa: ANN001
    r = await client.get("/api/bot/users/by-id/999999999", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_users_require_service_token(client):  # noqa: ANN001
    r = await client.get("/api/bot/users/1")
    assert r.status_code == 401
