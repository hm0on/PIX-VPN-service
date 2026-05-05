"""Sanity tests for ``outbox_dispatcher_task``.

We cover the three branches the dispatcher must handle:

- happy path → mark as ``sent`` with the returned ``tg_message_id``
- permanent TG error (HTTP 403) → mark as ``failed`` (no retry)
- transient TG error (HTTP 5xx) → mark as ``failed`` (Backend re-queues)

The dispatcher is exercised end-to-end via mocks; we never touch real
Telegram or Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.tasks.outbox_dispatcher import outbox_dispatcher_task


# --------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body: Any = None) -> None:
        self.status_code = status_code
        self._json = json_body if json_body is not None else []
        self.text = "" if json_body is None else "<body>"

    def json(self) -> Any:
        return self._json


class FakeAPIClient:
    """Captures all calls so we can assert /sent vs /failed routing."""

    def __init__(self, pending: list[dict[str, Any]]) -> None:
        self._pending = pending
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> _FakeResponse:
        self.calls.append(("GET", path, params))
        return _FakeResponse(200, self._pending)

    async def post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> _FakeResponse:
        self.calls.append(("POST", path, json))
        return _FakeResponse(204, None)

    @property
    def sent_paths(self) -> list[str]:
        return [p for m, p, _ in self.calls if m == "POST" and p.endswith("/sent")]

    @property
    def failed_paths(self) -> list[str]:
        return [p for m, p, _ in self.calls if m == "POST" and p.endswith("/failed")]

    def failed_payload(self, path: str) -> dict[str, Any] | None:
        for method, p, body in self.calls:
            if method == "POST" and p == path:
                return body
        return None


class FakeTelegramClient:
    """Returns a scripted envelope for each call."""

    def __init__(self, envelopes: list[dict[str, Any]]) -> None:
        self._envelopes = list(envelopes)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "reply_markup": reply_markup,
                },
            )
        )
        return self._envelopes.pop(0)

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            ("sendPhoto", {"chat_id": chat_id, "photo": photo, "caption": caption})
        )
        return self._envelopes.pop(0)


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _make_ctx(
    api_client: FakeAPIClient,
    tg_client: FakeTelegramClient,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> dict[str, Any]:
    if monkeypatch is not None:
        monkeypatch.setenv("BOT_TOKEN", "test-token")
        monkeypatch.setenv("OUTBOX_BATCH_SIZE", "10")
        monkeypatch.setenv("OUTBOX_CONCURRENCY", "4")
    settings = Settings()
    return {
        "settings": settings,
        "api_client": api_client,
        "telegram_client": tg_client,
    }


def _msg(msg_id: int, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": msg_id,
        "chat_id": 1000 + msg_id,
        "message_type": "text",
        "payload": {"text": f"hello {msg_id}", "parse_mode": "HTML"},
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_success_marks_sent_with_tg_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeAPIClient(pending=[_msg(1)])
    tg = FakeTelegramClient(
        envelopes=[{"ok": True, "result": {"message_id": 42}}]
    )

    counters = await outbox_dispatcher_task(_make_ctx(api, tg, monkeypatch))

    assert counters == {"fetched": 1, "sent": 1, "failed": 0, "skipped": 0}
    assert api.sent_paths == ["/api/bot/outbox/1/sent"]
    assert api.failed_paths == []


@pytest.mark.asyncio
async def test_permanent_403_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeAPIClient(pending=[_msg(2)])
    tg = FakeTelegramClient(
        envelopes=[
            {
                "ok": False,
                "result": None,
                "error_code": 403,
                "description": "Forbidden: bot was blocked by the user",
            }
        ]
    )

    counters = await outbox_dispatcher_task(_make_ctx(api, tg, monkeypatch))

    assert counters == {"fetched": 1, "sent": 0, "failed": 1, "skipped": 0}
    assert api.failed_paths == ["/api/bot/outbox/2/failed"]
    payload = api.failed_payload("/api/bot/outbox/2/failed")
    assert payload is not None
    assert "403" in payload["error"]


@pytest.mark.asyncio
async def test_transient_5xx_marks_failed_for_backend_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeAPIClient(pending=[_msg(3)])
    tg = FakeTelegramClient(
        envelopes=[
            {
                "ok": False,
                "result": None,
                "error_code": 500,
                "description": "Internal Server Error",
            }
        ]
    )

    counters = await outbox_dispatcher_task(_make_ctx(api, tg, monkeypatch))

    assert counters == {"fetched": 1, "sent": 0, "failed": 1, "skipped": 0}
    assert api.sent_paths == []
    assert api.failed_paths == ["/api/bot/outbox/3/failed"]


@pytest.mark.asyncio
async def test_empty_batch_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeAPIClient(pending=[])
    tg = FakeTelegramClient(envelopes=[])

    counters = await outbox_dispatcher_task(_make_ctx(api, tg, monkeypatch))

    assert counters == {"fetched": 0, "sent": 0, "failed": 0, "skipped": 0}
    assert api.sent_paths == []
    assert api.failed_paths == []


@pytest.mark.asyncio
async def test_invalid_payload_is_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # message_type=text but no `text` field — dispatcher must not call TG
    # and must report as failed permanently.
    api = FakeAPIClient(pending=[_msg(4, payload={"parse_mode": "HTML"})])
    tg = FakeTelegramClient(envelopes=[])

    counters = await outbox_dispatcher_task(_make_ctx(api, tg, monkeypatch))

    assert counters["failed"] == 1
    assert tg.calls == []
    assert api.failed_paths == ["/api/bot/outbox/4/failed"]


class _DictEnvelopeAPIClient(FakeAPIClient):
    """API fake that returns the real backend shape: ``{"items": [...]}``.

    The original FakeAPIClient hands back a bare list, which papered over a
    real bug — backend's ``OutboxPendingResponse`` is a dict envelope, and
    the dispatcher silently dropped every poll as "unexpected shape" until
    we taught it to unwrap ``items``.
    """

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> _FakeResponse:
        self.calls.append(("GET", path, params))
        return _FakeResponse(200, {"items": self._pending})


@pytest.mark.asyncio
async def test_dispatcher_unwraps_items_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: backend returns ``{"items": [...]}``, not a bare list."""
    api = _DictEnvelopeAPIClient(pending=[_msg(5)])
    tg = FakeTelegramClient(
        envelopes=[{"ok": True, "result": {"message_id": 99}}]
    )

    counters = await outbox_dispatcher_task(_make_ctx(api, tg, monkeypatch))

    assert counters == {"fetched": 1, "sent": 1, "failed": 0, "skipped": 0}
    assert api.sent_paths == ["/api/bot/outbox/5/sent"]
