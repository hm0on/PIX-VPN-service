"""Stage 4 ban / unban tests."""

from __future__ import annotations

import pytest


async def _create_user(client, auth_headers, tg_id: int):  # noqa: ANN001
    r = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": tg_id, "username": "ban", "first_name": "BanTest"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_ban_sets_flags(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=9001)

    r = await client.post(
        "/api/bot/users/9001/ban",
        headers=auth_headers,
        json={"reason": "spamming support"},
    )
    assert r.status_code == 204

    r2 = await client.get("/api/bot/users/9001", headers=auth_headers)
    assert r2.status_code == 200
    body = r2.json()
    assert body["is_banned"] is True
    assert body["banned_reason"] == "spamming support"


@pytest.mark.asyncio
async def test_unban_clears_flags(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=9002)

    r = await client.post(
        "/api/bot/users/9002/ban",
        headers=auth_headers,
        json={"reason": "test"},
    )
    assert r.status_code == 204

    r2 = await client.post(
        "/api/bot/users/9002/unban", headers=auth_headers
    )
    assert r2.status_code == 204

    r3 = await client.get("/api/bot/users/9002", headers=auth_headers)
    body = r3.json()
    assert body["is_banned"] is False
    assert body["banned_reason"] is None


@pytest.mark.asyncio
async def test_ban_unknown_user_404(client, auth_headers):  # noqa: ANN001
    r = await client.post(
        "/api/bot/users/9999999/ban",
        headers=auth_headers,
        json={"reason": "x"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_ban_validation_empty_reason(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=9003)
    r = await client.post(
        "/api/bot/users/9003/ban",
        headers=auth_headers,
        json={"reason": ""},
    )
    assert r.status_code == 422
