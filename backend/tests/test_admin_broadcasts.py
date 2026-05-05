"""Stage 5 admin broadcasts tests (router-level only — worker pieces in
test_worker_broadcasts.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_draft_broadcast(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "<b>Hello</b>", "target": "all"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["recipients_total"] == 0


@pytest.mark.asyncio
async def test_create_scheduled_broadcast(client, admin_headers):  # noqa: ANN001
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(
        microsecond=0
    )
    r = await client.post(
        "/api/admin/broadcasts",
        json={
            "html_text": "<i>later</i>",
            "target": "subscribers",
            "scheduled_at": when.isoformat(),
            "buttons": [{"text": "Click", "url": "https://example.com"}],
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "scheduled"
    assert r.json()["buttons"][0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_patch_only_when_draft_or_scheduled(
    client, admin_headers
):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "x", "target": "all"},
        headers=admin_headers,
    )
    bid = r.json()["id"]

    rp = await client.patch(
        f"/api/admin/broadcasts/{bid}",
        json={"html_text": "y"},
        headers=admin_headers,
    )
    assert rp.status_code == 200
    assert rp.json()["html_text"] == "y"


@pytest.mark.asyncio
async def test_send_enqueues_and_marks_sending(
    client, admin_headers
):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "send me", "target": "all"},
        headers=admin_headers,
    )
    bid = r.json()["id"]

    with patch(
        "app.api.admin.broadcasts.arq_client.enqueue", new=AsyncMock(return_value=True)
    ) as enq:
        rs = await client.post(
            f"/api/admin/broadcasts/{bid}/send", headers=admin_headers
        )
        assert rs.status_code == 202, rs.text
        assert rs.json()["status"] == "sending"
        enq.assert_awaited_once_with("run_broadcast", bid)


@pytest.mark.asyncio
async def test_schedule_endpoint(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "x", "target": "all"},
        headers=admin_headers,
    )
    bid = r.json()["id"]
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(
        microsecond=0
    )
    rs = await client.post(
        f"/api/admin/broadcasts/{bid}/schedule",
        json={"scheduled_at": when.isoformat()},
        headers=admin_headers,
    )
    assert rs.status_code == 202, rs.text
    assert rs.json()["status"] == "scheduled"


@pytest.mark.asyncio
async def test_cancel(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "x", "target": "all"},
        headers=admin_headers,
    )
    bid = r.json()["id"]
    rs = await client.post(
        f"/api/admin/broadcasts/{bid}/cancel", headers=admin_headers
    )
    assert rs.status_code == 200, rs.text
    assert rs.json()["status"] == "cancelled"

    # Re-cancel should 409.
    rs2 = await client.post(
        f"/api/admin/broadcasts/{bid}/cancel", headers=admin_headers
    )
    assert rs2.status_code == 409


@pytest.mark.asyncio
async def test_test_endpoint(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "<b>test</b>", "target": "all"},
        headers=admin_headers,
    )
    bid = r.json()["id"]

    fake_response = {
        "ok": True,
        "result": {"message_id": 42},
    }
    with patch(
        "app.api.admin.broadcasts.telegram_admin_client.send_message",
        new=AsyncMock(return_value=fake_response),
    ):
        rt = await client.post(
            f"/api/admin/broadcasts/{bid}/test",
            json={"tg_id": 123},
            headers=admin_headers,
        )
    assert rt.status_code == 200, rt.text
    body = rt.json()
    assert body["ok"] is True
    assert body["message_id"] == 42


@pytest.mark.asyncio
async def test_recipients_list_empty(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "x", "target": "all"},
        headers=admin_headers,
    )
    bid = r.json()["id"]
    rl = await client.get(
        f"/api/admin/broadcasts/{bid}/recipients", headers=admin_headers
    )
    assert rl.status_code == 200
    assert rl.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_with_status_filter(client, admin_headers):  # noqa: ANN001
    await client.post(
        "/api/admin/broadcasts",
        json={"html_text": "draft1", "target": "all"},
        headers=admin_headers,
    )
    r = await client.get(
        "/api/admin/broadcasts?status=draft", headers=admin_headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(b["status"] == "draft" for b in items)


@pytest.mark.asyncio
async def test_requires_jwt(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/broadcasts")
    assert r.status_code == 401
