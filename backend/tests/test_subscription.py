"""Subscription read-path tests (list + detail + ownership)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NorthLineUnavailableError
from app.deps import get_northline_client
from app.schemas.northline import KeyResponse


def _make_nl_mock(*, fail: bool = False) -> AsyncMock:
    mock = AsyncMock()
    if fail:
        mock.create_key = AsyncMock(side_effect=NorthLineUnavailableError("err"))
    else:
        mock.create_key = AsyncMock(
            return_value=KeyResponse(
                ok=True,
                subscription_id="sub_test",
                key="https://sub.pixio.icu/k",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=3),
                devices=3,
                days=3,
            )
        )
    mock.aclose = AsyncMock(return_value=None)
    return mock


@pytest.mark.asyncio
async def test_list_user_subscriptions_empty(client, auth_headers, seed_db):  # noqa: ANN001
    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 7001, "username": "sub1"},
    )
    r = await client.get(
        "/api/bot/users/7001/subscriptions", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_subscriptions_after_free_trial(  # noqa: ANN001
    client, auth_headers, seed_db, app
):
    app.dependency_overrides[get_northline_client] = lambda: _make_nl_mock()

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 7002, "username": "sub2"},
    )
    r = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 7002},
    )
    assert r.status_code == 200
    sub_id = r.json()["subscription"]["id"]

    r2 = await client.get(
        "/api/bot/users/7002/subscriptions", headers=auth_headers
    )
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) == 1
    assert body[0]["id"] == sub_id
    assert body[0]["status"] == "active"


@pytest.mark.asyncio
async def test_get_subscription_detail_owner_check(  # noqa: ANN001
    client, auth_headers, seed_db, app
):
    app.dependency_overrides[get_northline_client] = lambda: _make_nl_mock()

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 7003, "username": "owner"},
    )
    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 7004, "username": "stranger"},
    )

    r = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 7003},
    )
    sub_id = r.json()["subscription"]["id"]

    # Owner can read.
    r_owner = await client.get(
        f"/api/bot/subscriptions/{sub_id}",
        headers=auth_headers,
        params={"tg_id": 7003},
    )
    assert r_owner.status_code == 200
    assert r_owner.json()["id"] == sub_id

    # Stranger cannot.
    r_other = await client.get(
        f"/api/bot/subscriptions/{sub_id}",
        headers=auth_headers,
        params={"tg_id": 7004},
    )
    assert r_other.status_code == 404
    assert r_other.json()["error"]["code"] == "subscription_not_found"


@pytest.mark.asyncio
async def test_get_balance_endpoint(client, auth_headers, seed_db):  # noqa: ANN001
    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 7005, "username": "bal"},
    )
    r = await client.get("/api/bot/users/7005/balance", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"balance_kopecks": 0}


@pytest.mark.asyncio
async def test_get_balance_user_not_found(client, auth_headers, seed_db):  # noqa: ANN001
    r = await client.get("/api/bot/users/9999991/balance", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"
