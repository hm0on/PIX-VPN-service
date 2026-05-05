"""Stage 4 ticket endpoint tests."""

from __future__ import annotations

import pytest


async def _create_user(client, auth_headers, tg_id: int, username: str = "tk"):  # noqa: ANN001
    r = await client.post(
        "/api/bot/users",
        headers=auth_headers,
        json={"tg_id": tg_id, "username": username, "first_name": "Test"},
    )
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest.mark.asyncio
async def test_open_and_close_ticket(client, auth_headers):  # noqa: ANN001
    user = await _create_user(client, auth_headers, tg_id=8001, username="alice")

    # Open
    r = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8001, "kind": "support"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "open"
    assert body["kind"] == "support"
    assert body["user_id"] == user["id"]
    assert body["code"].startswith("TCK-") and len(body["code"]) == 10
    ticket_id = body["id"]

    # Active ticket lookup
    r2 = await client.get(
        f"/api/bot/users/{8001}/active-ticket", headers=auth_headers
    )
    assert r2.status_code == 200
    assert r2.json()["ticket"]["id"] == ticket_id

    # Close (by user)
    r3 = await client.post(
        f"/api/bot/tickets/{ticket_id}/close",
        headers=auth_headers,
        json={"by": "user", "tg_user_id": 8001},
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "closed"

    # No active ticket anymore
    r4 = await client.get(
        f"/api/bot/users/{8001}/active-ticket", headers=auth_headers
    )
    assert r4.status_code == 200
    assert r4.json()["ticket"] is None


@pytest.mark.asyncio
async def test_double_open_conflict(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=8002, username="bob")

    r1 = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8002, "kind": "support"},
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8002, "kind": "support"},
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "ticket_already_open"


@pytest.mark.asyncio
async def test_close_nonexistent_ticket_404(client, auth_headers):  # noqa: ANN001
    r = await client.post(
        "/api/bot/tickets/9999999/close",
        headers=auth_headers,
        json={"by": "admin"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ticket_not_found"


@pytest.mark.asyncio
async def test_close_by_user_with_wrong_tg_id_404(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=8003, username="carol")
    await _create_user(client, auth_headers, tg_id=8004, username="dave")

    r1 = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8003, "kind": "support"},
    )
    ticket_id = r1.json()["id"]

    # Wrong owner — must be 404 (we don't leak existence).
    r2 = await client.post(
        f"/api/bot/tickets/{ticket_id}/close",
        headers=auth_headers,
        json={"by": "user", "tg_user_id": 8004},
    )
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "ticket_not_found"


@pytest.mark.asyncio
async def test_close_already_closed_409(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=8005, username="eve")

    r1 = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8005, "kind": "support"},
    )
    ticket_id = r1.json()["id"]

    r2 = await client.post(
        f"/api/bot/tickets/{ticket_id}/close",
        headers=auth_headers,
        json={"by": "user", "tg_user_id": 8005},
    )
    assert r2.status_code == 200

    r3 = await client.post(
        f"/api/bot/tickets/{ticket_id}/close",
        headers=auth_headers,
        json={"by": "admin"},
    )
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "ticket_already_closed"


@pytest.mark.asyncio
async def test_topic_attach_and_lookup_by_thread(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=8006, username="frank")

    r1 = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8006, "kind": "support"},
    )
    ticket_id = r1.json()["id"]

    # Attach a thread.
    r2 = await client.post(
        f"/api/bot/tickets/{ticket_id}/topic",
        headers=auth_headers,
        json={"topic_thread_id": 4242},
    )
    assert r2.status_code == 204

    # Lookup by thread.
    r3 = await client.get(
        "/api/bot/tickets/by-thread/4242", headers=auth_headers
    )
    assert r3.status_code == 200
    assert r3.json()["ticket"]["id"] == ticket_id

    # Unknown thread → null.
    r4 = await client.get(
        "/api/bot/tickets/by-thread/9999", headers=auth_headers
    )
    assert r4.status_code == 200
    assert r4.json()["ticket"] is None


@pytest.mark.asyncio
async def test_record_message(client, auth_headers):  # noqa: ANN001
    await _create_user(client, auth_headers, tg_id=8007, username="gina")

    r1 = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 8007, "kind": "support"},
    )
    ticket_id = r1.json()["id"]

    r2 = await client.post(
        f"/api/bot/tickets/{ticket_id}/messages",
        headers=auth_headers,
        json={
            "direction": "from_user",
            "message_type": "text",
            "text": "hello",
            "tg_message_id": 12345,
        },
    )
    assert r2.status_code == 204

    # Recording a message on a missing ticket → 404.
    r3 = await client.post(
        "/api/bot/tickets/9999999/messages",
        headers=auth_headers,
        json={
            "direction": "from_admin",
            "message_type": "text",
            "text": "x",
        },
    )
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_support_topic_save_and_get(client, auth_headers):  # noqa: ANN001
    user = await _create_user(client, auth_headers, tg_id=8008, username="hank")

    # Initially: 200 with nulls.
    r1 = await client.get(
        f"/api/bot/support-topic/{user['id']}", headers=auth_headers
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["topic_thread_id"] is None
    assert body["topic_name"] is None

    # Save.
    r2 = await client.post(
        "/api/bot/support-topic",
        headers=auth_headers,
        json={
            "user_id": user["id"],
            "topic_thread_id": 555,
            "topic_name": "TCK-AAAAAA · Hank",
        },
    )
    assert r2.status_code == 204

    # Read back.
    r3 = await client.get(
        f"/api/bot/support-topic/{user['id']}", headers=auth_headers
    )
    assert r3.status_code == 200
    body = r3.json()
    assert body["topic_thread_id"] == 555
    assert body["topic_name"] == "TCK-AAAAAA · Hank"


@pytest.mark.asyncio
async def test_open_ticket_user_missing_404(client, auth_headers):  # noqa: ANN001
    r = await client.post(
        "/api/bot/tickets/open",
        headers=auth_headers,
        json={"tg_user_id": 999999991, "kind": "support"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_close_request_validation_user_requires_tg_id(client, auth_headers):  # noqa: ANN001
    # Missing tg_user_id when by='user' should fail validation (422).
    r = await client.post(
        "/api/bot/tickets/1/close",
        headers=auth_headers,
        json={"by": "user"},
    )
    assert r.status_code == 422
