"""Outbox API endpoints used by the worker."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.models.text import Text
from app.deps import DBSession
from app.schemas.outbox import (
    OutboxAckResponse,
    OutboxFailedRequest,
    OutboxMessageResponse,
    OutboxPendingResponse,
    OutboxSentRequest,
)
from app.services import outbox_service

router = APIRouter()
log = get_logger("outbox.api")


class _SafeDict(dict[str, Any]):
    """Dict that returns ``{missing_key}`` for unknown placeholders.

    Used to keep ``str.format_map`` from raising on stale templates that
    reference a key the caller didn't pass — better to leave the placeholder
    visible than to fail the whole message.
    """

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return "{" + key + "}"


def _render_template(value_html: str, format_kwargs: dict[str, Any]) -> str:
    try:
        return value_html.format_map(_SafeDict(format_kwargs))
    except (IndexError, KeyError, ValueError) as exc:  # pragma: no cover
        # Truly malformed template (e.g. unbalanced braces) — log and return
        # the raw template so the user at least sees something.
        log.warning("outbox_template_format_error", error=str(exc))
        return value_html


def _buttons_to_reply_markup(buttons: Any) -> dict[str, Any] | None:
    """Convert backend's flat ``buttons`` list into Telegram ``reply_markup``.

    Accepts either a flat list (single row) or a list of rows. Each button is
    a dict with ``text`` plus one of ``url`` / ``callback_data``.
    """
    if not isinstance(buttons, list) or not buttons:
        return None

    # Detect: list-of-rows (list of lists) vs. flat list.
    is_grid = all(isinstance(row, list) for row in buttons)
    rows = buttons if is_grid else [buttons]

    keyboard: list[list[dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        rendered_row: list[dict[str, Any]] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            text = btn.get("text")
            if not isinstance(text, str) or not text:
                continue
            entry: dict[str, Any] = {"text": text}
            if isinstance(btn.get("url"), str) and btn["url"]:
                entry["url"] = btn["url"]
            elif isinstance(btn.get("callback_data"), str) and btn["callback_data"]:
                entry["callback_data"] = btn["callback_data"]
            else:
                # Button without a usable action — skip it.
                continue
            rendered_row.append(entry)
        if rendered_row:
            keyboard.append(rendered_row)

    if not keyboard:
        return None
    return {"inline_keyboard": keyboard}


async def _resolve_payload(
    payload: dict[str, Any],
    templates: dict[str, str],
    msg_id: int,
) -> dict[str, Any]:
    """Return a copy of ``payload`` with ``text_key`` rendered into ``text``
    and flat ``buttons`` converted into Telegram ``reply_markup``.

    The original ORM object is not mutated — we want the row to keep its
    templated payload so the next render (e.g. after retry, after an admin
    edited the text) uses fresh template values.
    """
    out = dict(payload)

    text_key = out.get("text_key")
    if isinstance(text_key, str) and text_key and not out.get("text"):
        value_html = templates.get(text_key)
        format_kwargs = out.get("format_kwargs") or {}
        if not isinstance(format_kwargs, dict):
            format_kwargs = {}
        if value_html is None:
            out["text"] = f"[text:{text_key} not found]"
            log.warning("outbox_text_key_missing", text_key=text_key, id=msg_id)
        else:
            out["text"] = _render_template(value_html, format_kwargs)

    if "reply_markup" not in out and out.get("buttons"):
        reply_markup = _buttons_to_reply_markup(out["buttons"])
        if reply_markup is not None:
            out["reply_markup"] = reply_markup

    return out


async def _load_templates(
    session: DBSession, rows: list[Any]
) -> dict[str, str]:
    needed_keys: set[str] = set()
    for r in rows:
        payload = r.payload or {}
        text_key = payload.get("text_key")
        if isinstance(text_key, str) and text_key and not payload.get("text"):
            needed_keys.add(text_key)
    if not needed_keys:
        return {}
    result = await session.execute(
        select(Text.key, Text.value_html).where(Text.key.in_(needed_keys))
    )
    return {key: value for key, value in result.all()}


@router.get("/outbox/pending", response_model=OutboxPendingResponse)
async def list_pending(
    session: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> OutboxPendingResponse:
    rows = await outbox_service.fetch_pending(session, limit=limit)
    templates = await _load_templates(session, rows)
    await session.commit()

    items: list[OutboxMessageResponse] = []
    for r in rows:
        resolved_payload = await _resolve_payload(
            r.payload or {}, templates, r.id
        )
        item = OutboxMessageResponse.model_validate(r)
        item.payload = resolved_payload
        items.append(item)
    return OutboxPendingResponse(items=items)


@router.post("/outbox/{message_id}/sent", response_model=OutboxAckResponse)
async def mark_sent(
    message_id: int,
    payload: OutboxSentRequest,
    session: DBSession,
) -> OutboxAckResponse:
    try:
        msg = await outbox_service.mark_sent(
            session,
            message_id=message_id,
            tg_message_id=payload.tg_message_id,
        )
    except NoResultFound as e:
        raise NotFoundError(
            f"Outbox message id={message_id} not found",
            error_code="outbox_not_found",
        ) from e
    await session.commit()
    return OutboxAckResponse(status=msg.status)


@router.post("/outbox/{message_id}/failed", response_model=OutboxAckResponse)
async def mark_failed(
    message_id: int,
    payload: OutboxFailedRequest,
    session: DBSession,
) -> OutboxAckResponse:
    try:
        msg = await outbox_service.mark_failed(
            session,
            message_id=message_id,
            error=payload.error,
        )
    except NoResultFound as e:
        raise NotFoundError(
            f"Outbox message id={message_id} not found",
            error_code="outbox_not_found",
        ) from e
    await session.commit()
    return OutboxAckResponse(status=msg.status)
