"""Admin Broadcasts router.

The actual delivery is handled by the worker task ``run_broadcast``
(worker/app/tasks/broadcasts.py); this router only manipulates DB state,
uploads photos, fires off the ARQ job and exposes recipient lists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.config import get_settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.db.models.broadcast import (
    BROADCAST_STATUS_CANCELLED,
    BROADCAST_STATUS_DRAFT,
    BROADCAST_STATUS_SCHEDULED,
    BROADCAST_STATUS_SENDING,
    BROADCAST_TARGETS,
    Broadcast,
)
from app.db.models.broadcast_recipient import BroadcastRecipient
from app.deps import AdminDep, DBSession, RedisDep
from app.schemas.admin_panel.broadcast import (
    AdminBroadcast,
    AdminBroadcastCreate,
    AdminBroadcastPatch,
    AdminBroadcastRecipient,
    AdminBroadcastRecipientsPage,
    AdminBroadcastSchedule,
    AdminBroadcastsPage,
    AdminBroadcastTestRequest,
    AdminBroadcastTestResponse,
)
from app.services import arq_client, telegram_admin_client
from app.services.audit_service import record_admin_action
from app.services.tg_html import to_telegram_html

router = APIRouter()
logger = get_logger("admin.broadcasts")


# Absolute path so it doesn't depend on cwd. The Dockerfile pre-creates this
# directory with chown app:app, and infra/docker-compose.yml mounts a named
# volume here so uploads survive image rebuilds.
_PHOTO_ROOT = Path("/app/var/broadcasts")
_PHOTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_PHOTO_ALLOWED_EXT = {"jpg", "jpeg", "png"}
_PHOTO_ALLOWED_CT = {"image/jpeg", "image/png", "image/jpg"}


def _photo_url(b: Broadcast) -> str | None:
    """Build the URL the admin UI should hit for the previously uploaded photo.

    The actual bytes are served by ``GET /api/admin/broadcasts/{id}/photo``;
    we only return that URL when there's a file on disk to serve. The path is
    relative to the API base, so the frontend's apiClient (with JWT) handles it.
    """
    if not b.photo_path:
        return None
    return f"/admin/broadcasts/{b.id}/photo"


def _serialize(b: Broadcast) -> AdminBroadcast:
    obj = AdminBroadcast.model_validate(b)
    obj.photo_url = _photo_url(b)
    return obj


# --------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------- #
@router.get("", response_model=AdminBroadcastsPage)
async def list_broadcasts(
    session: DBSession,
    _: AdminDep,
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AdminBroadcastsPage:
    stmt = select(Broadcast)
    if status_filter:
        stmt = stmt.where(Broadcast.status == status_filter)

    total_res = await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = int(total_res.scalar() or 0)

    rows_res = await session.execute(
        stmt.order_by(Broadcast.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = rows_res.scalars().all()
    return AdminBroadcastsPage(
        items=[_serialize(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=AdminBroadcast,
    status_code=status.HTTP_201_CREATED,
)
async def create_broadcast(
    payload: AdminBroadcastCreate,
    session: DBSession,
    admin: AdminDep,
) -> AdminBroadcast:
    if payload.target not in BROADCAST_TARGETS:
        raise ValidationError(
            f"Invalid target '{payload.target}'", error_code="invalid_target"
        )
    new_status = (
        BROADCAST_STATUS_SCHEDULED
        if payload.scheduled_at is not None
        else BROADCAST_STATUS_DRAFT
    )

    bc = Broadcast(
        html_text=payload.html_text,
        target=payload.target,
        scheduled_at=payload.scheduled_at,
        buttons=[b.model_dump() for b in payload.buttons]
        if payload.buttons
        else None,
        buttons_per_row=payload.buttons_per_row,
        status=new_status,
        created_by_admin_key_id=admin.kid,
        created_by_admin_key_label=admin.label,
    )
    session.add(bc)
    await session.flush()

    await record_admin_action(
        session,
        admin,
        "broadcast.create",
        extra={"broadcast_id": bc.id, "status": new_status},
    )
    await session.commit()
    await session.refresh(bc)
    return _serialize(bc)


@router.get("/{broadcast_id}", response_model=AdminBroadcast)
async def get_broadcast(
    broadcast_id: int,
    session: DBSession,
    _: AdminDep,
) -> AdminBroadcast:
    """Single-broadcast fetch — used by the editor when navigating to /edit."""
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )
    return _serialize(bc)


@router.patch("/{broadcast_id}", response_model=AdminBroadcast)
async def patch_broadcast(
    broadcast_id: int,
    payload: AdminBroadcastPatch,
    session: DBSession,
    admin: AdminDep,
) -> AdminBroadcast:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )
    if bc.status not in (BROADCAST_STATUS_DRAFT, BROADCAST_STATUS_SCHEDULED):
        raise ConflictError(
            f"Cannot edit broadcast in status '{bc.status}'",
            error_code="broadcast_not_editable",
        )

    changes: dict[str, object] = {}
    if payload.html_text is not None:
        bc.html_text = payload.html_text
        changes["html_text"] = True
    if payload.target is not None:
        if payload.target not in BROADCAST_TARGETS:
            raise ValidationError(
                f"Invalid target '{payload.target}'",
                error_code="invalid_target",
            )
        bc.target = payload.target
        changes["target"] = payload.target
    if payload.buttons is not None:
        bc.buttons = [b.model_dump() for b in payload.buttons]
        changes["buttons"] = len(payload.buttons)
    if payload.buttons_per_row is not None:
        bc.buttons_per_row = payload.buttons_per_row
        changes["buttons_per_row"] = payload.buttons_per_row
    if payload.scheduled_at is not None:
        bc.scheduled_at = payload.scheduled_at
        bc.status = BROADCAST_STATUS_SCHEDULED
        changes["scheduled_at"] = payload.scheduled_at.isoformat()

    if changes:
        await session.flush()
        await record_admin_action(
            session,
            admin,
            "broadcast.update",
            extra={"broadcast_id": bc.id, "changes": changes},
        )
    await session.commit()
    await session.refresh(bc)
    return _serialize(bc)


# --------------------------------------------------------------------- #
# Photo upload
# --------------------------------------------------------------------- #
@router.post(
    "/{broadcast_id}/photo",
    response_model=AdminBroadcast,
)
async def upload_photo(
    broadcast_id: int,
    session: DBSession,
    admin: AdminDep,
    file: UploadFile = File(...),
) -> AdminBroadcast:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in _PHOTO_ALLOWED_EXT:
        raise ValidationError(
            "Only jpg/png are allowed",
            error_code="photo_invalid_ext",
        )
    if file.content_type and file.content_type.lower() not in _PHOTO_ALLOWED_CT:
        raise ValidationError(
            "Only image/jpeg or image/png are allowed",
            error_code="photo_invalid_content_type",
        )

    body = await file.read()
    if len(body) > _PHOTO_MAX_BYTES:
        raise ValidationError(
            "Photo exceeds 10 MB limit", error_code="photo_too_large"
        )
    if not body:
        raise ValidationError("Empty photo", error_code="photo_empty")

    target_dir = _PHOTO_ROOT / str(broadcast_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.{ext if ext != 'jpeg' else 'jpg'}"
    target_path = target_dir / fname
    # Best-effort write — small files only.
    with open(target_path, "wb") as fp:  # noqa: ASYNC230 — small one-shot write
        fp.write(body)

    bc.photo_path = str(target_path)
    bc.photo_file_id = None  # invalidate any prior file_id

    await session.flush()
    await record_admin_action(
        session,
        admin,
        "broadcast.photo_upload",
        extra={"broadcast_id": broadcast_id, "size": len(body)},
    )
    await session.commit()
    await session.refresh(bc)

    # Frontend re-hydrates the editor from this response (photo_url, etc.).
    return _serialize(bc)


# Map of allowed extensions → content types for the photo serve endpoint.
_PHOTO_CT_BY_EXT: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


@router.get("/{broadcast_id}/photo")
async def serve_photo(
    broadcast_id: int,
    session: DBSession,
    _: AdminDep,
) -> Response:
    """Stream back the previously uploaded photo for the broadcast editor.

    The admin UI fetches this via the JWT-authenticated apiClient, wraps the
    bytes in URL.createObjectURL() and uses the resulting blob: URL as <img src=...>
    (CSP allows blob: under img-src for exactly this case).
    """
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )
    if not bc.photo_path:
        raise NotFoundError(
            "Broadcast has no photo", error_code="broadcast_no_photo"
        )

    path = Path(bc.photo_path)
    # Defence in depth: photo_path is set by us, but make sure we never serve
    # arbitrary files outside the broadcasts root.
    try:
        path = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise NotFoundError(
            "Photo file missing on disk", error_code="broadcast_photo_missing"
        ) from exc
    photo_root = _PHOTO_ROOT.resolve()
    if not str(path).startswith(str(photo_root)):
        raise NotFoundError(
            "Photo path escapes broadcasts root",
            error_code="broadcast_photo_invalid",
        )

    ext = path.suffix.lstrip(".").lower()
    media_type = _PHOTO_CT_BY_EXT.get(ext, "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=60"},
    )


# --------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------- #
@router.post(
    "/{broadcast_id}/send",
    response_model=AdminBroadcast,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_broadcast(
    broadcast_id: int,
    session: DBSession,
    admin: AdminDep,
) -> AdminBroadcast:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )
    if bc.status not in (BROADCAST_STATUS_DRAFT, BROADCAST_STATUS_SCHEDULED):
        raise ConflictError(
            f"Cannot send broadcast in status '{bc.status}'",
            error_code="broadcast_not_sendable",
        )

    bc.status = BROADCAST_STATUS_SENDING
    bc.scheduled_at = None
    await session.flush()
    await record_admin_action(
        session,
        admin,
        "broadcast.send",
        extra={"broadcast_id": broadcast_id},
    )
    await session.commit()

    await arq_client.enqueue("run_broadcast", broadcast_id)
    await session.refresh(bc)
    return _serialize(bc)


@router.post(
    "/{broadcast_id}/schedule",
    response_model=AdminBroadcast,
    status_code=status.HTTP_202_ACCEPTED,
)
async def schedule_broadcast(
    broadcast_id: int,
    payload: AdminBroadcastSchedule,
    session: DBSession,
    admin: AdminDep,
) -> AdminBroadcast:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )
    if bc.status not in (BROADCAST_STATUS_DRAFT, BROADCAST_STATUS_SCHEDULED):
        raise ConflictError(
            f"Cannot schedule broadcast in status '{bc.status}'",
            error_code="broadcast_not_schedulable",
        )

    bc.status = BROADCAST_STATUS_SCHEDULED
    bc.scheduled_at = payload.scheduled_at
    await session.flush()
    await record_admin_action(
        session,
        admin,
        "broadcast.schedule",
        extra={
            "broadcast_id": broadcast_id,
            "scheduled_at": payload.scheduled_at.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(bc)
    return _serialize(bc)


@router.post("/{broadcast_id}/cancel", response_model=AdminBroadcast)
async def cancel_broadcast(
    broadcast_id: int,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> AdminBroadcast:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )
    if bc.status not in (
        BROADCAST_STATUS_DRAFT,
        BROADCAST_STATUS_SCHEDULED,
        BROADCAST_STATUS_SENDING,
    ):
        raise ConflictError(
            f"Cannot cancel broadcast in status '{bc.status}'",
            error_code="broadcast_not_cancellable",
        )

    if bc.status == BROADCAST_STATUS_SENDING:
        # Set Redis stop-flag — the worker checks it between batches.
        try:
            await redis.set(f"broadcast:cancel:{broadcast_id}", "1", ex=3600)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "broadcast_cancel_redis_set_failed",
                broadcast_id=broadcast_id,
                error=str(exc),
            )

    bc.status = BROADCAST_STATUS_CANCELLED
    bc.finished_at = datetime.now(UTC)
    await session.flush()
    await record_admin_action(
        session,
        admin,
        "broadcast.cancel",
        extra={"broadcast_id": broadcast_id},
    )
    await session.commit()
    await session.refresh(bc)
    return _serialize(bc)


# --------------------------------------------------------------------- #
# Test send
# --------------------------------------------------------------------- #
@router.post(
    "/{broadcast_id}/test",
    response_model=AdminBroadcastTestResponse,
)
async def test_broadcast(
    broadcast_id: int,
    payload: AdminBroadcastTestRequest,
    session: DBSession,
    admin: AdminDep,
) -> AdminBroadcastTestResponse:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )

    reply_markup: dict[str, object] | None = None
    if bc.buttons:
        per_row = max(1, min(int(bc.buttons_per_row or 1), 4))
        flat = [{"text": btn["text"], "url": btn["url"]} for btn in bc.buttons]
        rows = [flat[i : i + per_row] for i in range(0, len(flat), per_row)]
        reply_markup = {"inline_keyboard": rows}

    settings = get_settings()  # noqa: F841 — reserved for future ADMIN_TG_ID default
    chat_id = payload.tg_id

    # Sanitize TipTap HTML to Telegram's whitelist — same converter the
    # worker uses for real broadcasts, so the test send is representative.
    tg_html_text = to_telegram_html(bc.html_text)

    if bc.photo_path and Path(bc.photo_path).exists():  # noqa: ASYNC240 — local stat is fine
        envelope = await telegram_admin_client.send_photo_path(
            chat_id,
            bc.photo_path,
            caption=tg_html_text,
            reply_markup=reply_markup,
        )
    else:
        envelope = await telegram_admin_client.send_message(
            chat_id,
            tg_html_text,
            reply_markup=reply_markup,
        )

    ok = bool(envelope.get("ok"))
    msg_id = None
    if ok:
        result = envelope.get("result") or {}
        if isinstance(result, dict):
            msg_id = result.get("message_id")

    await record_admin_action(
        session,
        admin,
        "broadcast.test",
        extra={"broadcast_id": broadcast_id, "tg_id": chat_id, "ok": ok},
    )
    await session.commit()

    return AdminBroadcastTestResponse(
        ok=ok,
        message_id=int(msg_id) if isinstance(msg_id, int) else None,
        error=None if ok else (envelope.get("description") or "send failed"),
    )


# --------------------------------------------------------------------- #
# Recipients
# --------------------------------------------------------------------- #
@router.get(
    "/{broadcast_id}/recipients",
    response_model=AdminBroadcastRecipientsPage,
)
async def list_recipients(
    broadcast_id: int,
    session: DBSession,
    _: AdminDep,
    status_filter: str | None = Query(
        default=None, alias="status", max_length=16
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> AdminBroadcastRecipientsPage:
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None:
        raise NotFoundError(
            "Broadcast not found", error_code="broadcast_not_found"
        )

    stmt = select(BroadcastRecipient).where(
        BroadcastRecipient.broadcast_id == broadcast_id
    )
    if status_filter:
        stmt = stmt.where(BroadcastRecipient.status == status_filter)

    total_res = await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = int(total_res.scalar() or 0)

    rows_res = await session.execute(
        stmt.order_by(BroadcastRecipient.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = rows_res.scalars().all()
    return AdminBroadcastRecipientsPage(
        items=[AdminBroadcastRecipient.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# Keep an explicit handler so OpenAPI shows a dedicated 404 for missing IDs.
__all__ = ["router"]
# Suppress unused-import noise from FastAPI types.
_ = HTTPException, Body
