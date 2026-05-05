"""FREE-trial endpoint tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NorthLineUnavailableError
from app.deps import get_northline_client
from app.schemas.northline import KeyResponse


def _make_northline_mock(*, fail: bool = False) -> AsyncMock:
    mock = AsyncMock()
    if fail:
        mock.create_key = AsyncMock(side_effect=NorthLineUnavailableError("boom"))
    else:
        mock.create_key = AsyncMock(
            return_value=KeyResponse(
                ok=True,
                subscription_id="northline_sub_test_123",
                key="https://sub.pixio.icu/abcdef",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=3),
                devices=3,
                days=3,
            )
        )
    mock.aclose = AsyncMock(return_value=None)
    return mock


@pytest.mark.asyncio
async def test_free_trial_happy_path(client, auth_headers, seed_db, app):  # noqa: ANN001
    nl_mock = _make_northline_mock()
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    # create user
    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 5001, "username": "ft1"},
    )

    r = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 5001},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    sub = body["subscription"]
    assert sub["status"] == "active"
    assert sub["is_free_trial"] is True
    assert sub["key_url"] == "https://sub.pixio.icu/abcdef"
    assert sub["devices"] == 3
    assert sub["days"] == 3

    nl_mock.create_key.assert_awaited_once()


@pytest.mark.asyncio
async def test_free_trial_already_used(client, auth_headers, seed_db, app):  # noqa: ANN001
    nl_mock = _make_northline_mock()
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 5002, "username": "ft2"},
    )

    r1 = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 5002},
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 5002},
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "free_trial_already_used"


@pytest.mark.asyncio
async def test_free_trial_user_not_found(client, auth_headers, seed_db, app):  # noqa: ANN001
    nl_mock = _make_northline_mock()
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    r = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 99999999},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_free_trial_provider_unavailable(client, auth_headers, seed_db, app):  # noqa: ANN001
    nl_mock = _make_northline_mock(fail=True)
    app.dependency_overrides[get_northline_client] = lambda: nl_mock

    await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": 5003, "username": "ft3"},
    )

    r = await client.post(
        "/api/bot/free-trial",
        headers=auth_headers,
        json={"tg_id": 5003},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "vpn_provider_unavailable"
