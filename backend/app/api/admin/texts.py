"""Admin Texts router (Stage 5)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from fastapi import HTTPException, status

from fastapi import HTTPException, status

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.models.text import Text as TextModel
from app.deps import AdminDep, DBSession, RedisDep
from app.schemas.admin_panel.text import (
    AdminButtonValidatedPatch,
    AdminText,
    AdminTextPatch,
    AdminTextsPage,
)
from app.services.audit_service import record_admin_action

router = APIRouter()
logger = get_logger("admin_texts")


@router.get("", response_model=AdminTextsPage)
async def list_texts(
    session: DBSession,
    _: AdminDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=1000),
) -> AdminTextsPage:
    total_res = await session.execute(select(func.count()).select_from(TextModel))
    total = int(total_res.scalar() or 0)

    res = await session.execute(
        select(TextModel)
        .order_by(TextModel.key)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = res.scalars().all()
    return AdminTextsPage(
        items=[AdminText.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/{key}", response_model=AdminText)
async def patch_text(
    key: str,
    payload: AdminTextPatch,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> AdminText:
    res = await session.execute(
        select(TextModel).where(TextModel.key == key)
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise NotFoundError(
            f"Text '{key}' not found",
            error_code="text_not_found",
        )

    # For button-kind rows, re-validate the same payload with the stricter
    # "no HTML in label" rule so we surface a 422 before a Telegram surprise.
    if row.kind == "button":
        try:
            AdminButtonValidatedPatch(**payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    # Use Pydantic's exclude_unset so we can tell "field omitted" (no change)
    # from "field set to null" (clear). This lets the operator clear the
    # attachment by sending media_file_id=null + media_kind=null.
    fields = payload.model_dump(exclude_unset=True)

    if "value_html" in fields and fields["value_html"] is not None:
        row.value_html = fields["value_html"]
    if "description" in fields:
        row.description = fields["description"]
    if "icon_custom_emoji_id" in fields:
        # Buttons may have a premium-emoji icon. For messages this column is
        # always null but allowing the explicit null-set keeps the API uniform.
        row.icon_custom_emoji_id = fields["icon_custom_emoji_id"]
    if "url" in fields:
        # Outbound URL — only meaningful for kind='button'. For messages we
        # still allow setting it to null so callers can use the same payload
        # shape; the bot ignores the column for non-button rows.
        row.url = fields["url"]

    # Media: must travel together. Allow both null (clear) or both set (apply).
    has_file = "media_file_id" in fields
    has_kind = "media_kind" in fields
    if has_file or has_kind:
        new_file = fields.get("media_file_id") if has_file else row.media_file_id
        new_kind = fields.get("media_kind") if has_kind else row.media_kind
        # Both null → clear. Both set → apply. Otherwise reject.
        if (new_file is None) != (new_kind is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "media_file_id and media_kind must be set together "
                    "(or both null to clear)."
                ),
            )
        row.media_file_id = new_file
        row.media_kind = new_kind

    row.updated_by = admin.label

    await session.flush()

    await record_admin_action(
        session,
        admin,
        "text.update",
        extra={
            "key": key,
            "kind": row.kind,
            "media_file_id": row.media_file_id,
            "media_kind": row.media_kind,
            "icon_custom_emoji_id": row.icon_custom_emoji_id,
            "url": row.url,
        },
    )
    await session.commit()

    # Invalidate per-key Redis cache (bot/backend may cache by `text:{key}` —
    # delete it so the next read pulls a fresh row). Bot's TextService uses an
    # in-memory TTL cache (≤60s) so propagation delay is bounded; this is a
    # best-effort hint for any future Redis-backed cache.
    try:
        await redis.delete(f"text:{key}")
        await redis.publish("texts:invalidate", key)
    except Exception as e:  # noqa: BLE001
        logger.warning("text_cache_invalidate_failed", key=key, error=str(e))

    await session.refresh(row)
    return AdminText.model_validate(row)
