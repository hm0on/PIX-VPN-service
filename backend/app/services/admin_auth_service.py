"""Admin authentication service: login, key rotation, key listing/revocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.logging import LEVEL_INFO, LEVEL_WARNING, business_log
from app.core.security import (
    generate_admin_key,
    hash_secret,
    issue_admin_jwt,
    verify_secret,
)
from app.db.models.admin_key import AdminKey
from app.repositories.admin_key_repo import AdminKeyRepository


@dataclass(slots=True)
class LoginResult:
    access_token: str
    expires_at: datetime
    label: str
    kid: int


@dataclass(slots=True)
class RotationResult:
    new_plaintext_key: str
    new_key_id: int
    new_label: str
    previous_key_id: int | None
    previous_valid_until: datetime | None
    access_token: str
    expires_at: datetime


class AdminAuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AdminKeyRepository(session)

    async def login(self, *, key_plaintext: str) -> LoginResult:
        """Verify the supplied plaintext key against all usable keys."""
        if not key_plaintext:
            raise UnauthorizedError("Missing key", error_code="missing_key")

        usable = await self.repo.list_usable()
        for row in usable:
            if verify_secret(key_plaintext, row.key_hash):
                token, exp = issue_admin_jwt(label=row.label, kid=row.id)
                await business_log(
                    self.session,
                    level=LEVEL_INFO,
                    event="admin_login",
                    module="backend",
                    message=f"Admin '{row.label}' logged in",
                    context={"kid": row.id, "label": row.label},
                )
                await self.session.commit()
                return LoginResult(
                    access_token=token,
                    expires_at=exp,
                    label=row.label,
                    kid=row.id,
                )

        await business_log(
            self.session,
            level=LEVEL_WARNING,
            event="admin_login_failed",
            module="backend",
            message="Failed admin login attempt",
        )
        await self.session.commit()
        raise UnauthorizedError("Invalid admin key", error_code="invalid_admin_key")

    async def rotate_key(
        self,
        *,
        current_kid: int,
        new_label: str | None = None,
    ) -> RotationResult:
        """Rotate the currently used key.

        - Generate a new plaintext key (returned ONCE).
        - Insert it into admin_keys.
        - Mark the previous key as revoked with valid_until=now+grace.
        """
        settings = get_settings()
        now = datetime.now(UTC)
        grace_until = now + timedelta(hours=settings.admin_key_grace_hours)

        previous = await self.repo.get_by_id(current_kid)
        if previous is None:
            raise NotFoundError("Admin key not found", error_code="admin_key_not_found")

        # Create the new key
        new_plain = generate_admin_key()
        label = new_label or f"{previous.label}-rot-{int(now.timestamp())}"
        new_row: AdminKey = await self.repo.add(
            key_hash=hash_secret(new_plain), label=label
        )

        # Mark old key as revoked + grace
        previous_valid_until = grace_until
        await self.repo.revoke(previous, valid_until=grace_until, now=now)

        token, exp = issue_admin_jwt(label=new_row.label, kid=new_row.id)

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="admin_key_rotated",
            module="backend",
            message=(
                f"Admin key rotated: previous kid={previous.id} "
                f"grace_until={grace_until.isoformat()}"
            ),
            context={
                "previous_kid": previous.id,
                "new_kid": new_row.id,
                "valid_until": grace_until.isoformat(),
            },
        )
        await self.session.commit()

        return RotationResult(
            new_plaintext_key=new_plain,
            new_key_id=new_row.id,
            new_label=new_row.label,
            previous_key_id=previous.id,
            previous_valid_until=previous_valid_until,
            access_token=token,
            expires_at=exp,
        )

    async def rotate_with_grace(
        self,
        *,
        new_label: str,
        grace_hours: int,
        current_kid: int,
    ) -> tuple[str, AdminKey]:
        """Stage 5 rotation flow.

        - Creates a new key with label=`new_label`, returns plaintext ONCE.
        - Sets ``valid_until = now + grace_hours`` on every OTHER currently-active key
          (that is, every key except the new one) and stamps ``revoked_at = now``.
        - Returns ``(plaintext, new_admin_key)``.
        """
        now = datetime.now(UTC)
        grace_until = now + timedelta(hours=grace_hours) if grace_hours > 0 else now

        new_plain = generate_admin_key()
        new_row: AdminKey = await self.repo.add(
            key_hash=hash_secret(new_plain),
            label=new_label,
        )

        # Revoke all OTHER active (non-revoked or grace-still-valid) keys.
        usable = await self.repo.list_usable(now=now)
        for row in usable:
            if row.id == new_row.id:
                continue
            await self.repo.revoke(row, valid_until=grace_until, now=now)

        await business_log(
            self.session,
            level=LEVEL_INFO,
            event="admin_key_rotated",
            module="backend",
            message=f"Admin keys rotated by kid={current_kid} (grace_hours={grace_hours})",
            context={
                "new_kid": new_row.id,
                "actor_kid": current_kid,
                "grace_hours": grace_hours,
                "valid_until": grace_until.isoformat(),
            },
        )
        await self.session.commit()
        return new_plain, new_row

    async def revoke_key(self, key_id: int) -> AdminKey:
        row = await self.repo.get_by_id(key_id)
        if row is None:
            raise NotFoundError("Admin key not found", error_code="admin_key_not_found")
        # Hard revoke (no grace)
        now = datetime.now(UTC)
        await self.repo.revoke(row, valid_until=now, now=now)
        await business_log(
            self.session,
            level=LEVEL_WARNING,
            event="admin_key_revoked",
            module="backend",
            message=f"Admin key revoked: kid={row.id} label={row.label}",
            context={"kid": row.id, "label": row.label},
        )
        await self.session.commit()
        return row

    async def list_keys(self) -> list[AdminKey]:
        return await self.repo.list_all()

    async def get_key(self, key_id: int) -> AdminKey:
        row = await self.repo.get_by_id(key_id)
        if row is None:
            raise NotFoundError("Admin key not found", error_code="admin_key_not_found")
        return row
