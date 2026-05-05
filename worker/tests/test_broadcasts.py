"""Sanity tests for broadcast worker helpers (Stage 5).

The worker SQL uses Postgres-specific syntax (``interval``, ``FOR UPDATE
SKIP LOCKED``), so we don't exercise the full ``run_broadcast`` pipeline
against SQLite. Instead we cover the pure helpers:

* ``_build_reply_markup`` — JSON button → Telegram inline_keyboard shape
* ``_maybe_extract_photo_file_id`` — pulls the largest thumb's file_id
* ``_send_one`` — picks the right Telegram method (file_id / multipart /
  text-only) without touching the network
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.tasks.broadcasts import (
    _build_reply_markup,
    _maybe_extract_photo_file_id,
    _send_one,
)


def test_build_reply_markup_none_or_empty():
    assert _build_reply_markup(None) is None
    assert _build_reply_markup([]) is None
    assert _build_reply_markup("not a list") is None


def test_build_reply_markup_filters_invalid_items():
    buttons: list[Any] = [
        {"text": "A", "url": "https://a.example"},
        {"text": "B"},  # missing url — dropped
        {"url": "https://c.example"},  # missing text — dropped
        {"text": "D", "url": "https://d.example"},
    ]
    markup = _build_reply_markup(buttons)
    assert markup is not None
    rows = markup["inline_keyboard"]
    assert rows == [
        [{"text": "A", "url": "https://a.example"}],
        [{"text": "D", "url": "https://d.example"}],
    ]


def test_extract_photo_file_id_picks_largest():
    envelope = {
        "ok": True,
        "result": {
            "photo": [
                {"file_id": "small", "file_size": 100},
                {"file_id": "medium", "file_size": 500},
                {"file_id": "large", "file_size": 1000},
            ]
        },
    }
    assert _maybe_extract_photo_file_id(envelope) == "large"


def test_extract_photo_file_id_no_photo():
    assert _maybe_extract_photo_file_id({"ok": True, "result": {}}) is None
    assert _maybe_extract_photo_file_id({"ok": False}) is None


@pytest.mark.asyncio
async def test_send_one_uses_file_id_when_available():
    tg = AsyncMock()
    tg.send_photo = AsyncMock(return_value={"ok": True, "result": {"message_id": 9}})
    tg.send_message = AsyncMock(return_value={"ok": True})

    envelope = await _send_one(
        tg,
        chat_id=42,
        html_text="<b>hi</b>",
        photo_file_id="cached_fid",
        photo_path=None,
        reply_markup=None,
        token="t",
    )
    assert envelope["ok"] is True
    tg.send_photo.assert_awaited_once()
    tg.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_one_text_only_when_no_photo():
    tg = AsyncMock()
    tg.send_photo = AsyncMock(return_value={"ok": True})
    tg.send_message = AsyncMock(
        return_value={"ok": True, "result": {"message_id": 10}}
    )

    envelope = await _send_one(
        tg,
        chat_id=42,
        html_text="hello",
        photo_file_id=None,
        photo_path=None,
        reply_markup=None,
        token="t",
    )
    assert envelope["ok"] is True
    tg.send_message.assert_awaited_once()
    tg.send_photo.assert_not_awaited()
