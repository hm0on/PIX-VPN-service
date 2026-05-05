"""Outbox service + endpoints tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def seeded_user(client, auth_headers):  # noqa: ANN001
    payload = {"tg_id": 777001, "username": "outbox_user"}
    r = await client.post("/api/bot/users", json=payload, headers=auth_headers)
    assert r.status_code == 200
    return r.json()["user"]


@pytest.mark.asyncio
async def test_enqueue_and_pending(seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        msg = await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "hello", "parse_mode": "HTML"},
        )
        await session.commit()
        msg_id = msg.id

    async with factory() as session:
        rows = await outbox_service.fetch_pending(session, limit=10)
        await session.commit()
        assert len(rows) == 1
        assert rows[0].id == msg_id
        assert rows[0].status == "dispatching"
        assert rows[0].attempts == 1


@pytest.mark.asyncio
async def test_pending_skip_future_send_after(seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "future"},
            send_after=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

    async with factory() as session:
        rows = await outbox_service.fetch_pending(session, limit=10)
        assert rows == []


@pytest.mark.asyncio
async def test_mark_sent(seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        msg = await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "x"},
        )
        await session.commit()
        msg_id = msg.id

    async with factory() as session:
        rows = await outbox_service.fetch_pending(session, limit=10)
        await session.commit()
        assert rows[0].id == msg_id

    async with factory() as session:
        marked = await outbox_service.mark_sent(
            session, message_id=msg_id, tg_message_id=12345
        )
        await session.commit()
        assert marked.status == "sent"
        assert marked.sent_at is not None
        assert marked.payload.get("tg_message_id") == 12345


@pytest.mark.asyncio
async def test_mark_failed_retry(seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        msg = await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "x"},
        )
        await session.commit()
        msg_id = msg.id

    async with factory() as session:
        await outbox_service.fetch_pending(session, limit=10)
        await session.commit()

    async with factory() as session:
        m = await outbox_service.mark_failed(session, message_id=msg_id, error="boom")
        await session.commit()
        assert m.status == "pending"  # 1 attempt, retry scheduled
        assert m.last_error == "boom"
        assert m.send_after > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_mark_failed_terminal(seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        msg = await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "x"},
        )
        await session.commit()
        msg_id = msg.id

    # Force attempts to 5 by manually setting it.
    async with factory() as session:
        from sqlalchemy import select

        from app.db.models.outbox import Outbox

        m = (await session.execute(select(Outbox).where(Outbox.id == msg_id))).scalar_one()
        m.attempts = 5
        await session.commit()

    async with factory() as session:
        m = await outbox_service.mark_failed(
            session, message_id=msg_id, error="terminal", max_attempts=5
        )
        await session.commit()
        assert m.status == "failed"


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_endpoint(client, auth_headers, seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "via endpoint"},
        )
        await session.commit()

    r = await client.get("/api/bot/outbox/pending?limit=10", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "dispatching"
    assert data["items"][0]["attempts"] == 1


@pytest.mark.asyncio
async def test_sent_endpoint(client, auth_headers, seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        msg = await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "x"},
        )
        await session.commit()
        msg_id = msg.id

    # Claim it first.
    await client.get("/api/bot/outbox/pending?limit=10", headers=auth_headers)

    r = await client.post(
        f"/api/bot/outbox/{msg_id}/sent",
        json={"tg_message_id": 1},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_failed_endpoint_retry(client, auth_headers, seeded_user):  # noqa: ANN001
    from app.db.session import get_session_factory
    from app.services import outbox_service

    factory = get_session_factory()
    async with factory() as session:
        msg = await outbox_service.enqueue_message(
            session,
            user_id=seeded_user["id"],
            chat_id=seeded_user["tg_id"],
            message_type="text",
            payload={"text": "x"},
        )
        await session.commit()
        msg_id = msg.id

    await client.get("/api/bot/outbox/pending?limit=10", headers=auth_headers)

    r = await client.post(
        f"/api/bot/outbox/{msg_id}/failed",
        json={"error": "tg api timed out"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"  # rescheduled


@pytest.mark.asyncio
async def test_outbox_endpoints_require_token(client):  # noqa: ANN001
    r = await client.get("/api/bot/outbox/pending")
    assert r.status_code == 401
