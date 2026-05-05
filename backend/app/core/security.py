"""Security primitives: argon2 hashing, JWT issue/verify, secure compare."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.config import get_settings

_password_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"


# ---------- argon2 hashing ----------

def hash_secret(secret: str) -> str:
    """Hash a secret (admin key) with argon2id."""
    return _password_hasher.hash(secret)


def verify_secret(secret: str, hashed: str) -> bool:
    """Verify secret against stored argon2 hash. Returns False on mismatch / invalid hash."""
    try:
        return _password_hasher.verify(hashed, secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ---------- key generation ----------

def generate_admin_key(byte_length: int = 32) -> str:
    """Generate a 32-byte cryptographically random hex key (64 hex chars)."""
    return secrets.token_hex(byte_length)


# ---------- constant-time compare ----------

def constant_time_compare(a: str, b: str) -> bool:
    """secrets.compare_digest wrapper guarding against type errors."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ---------- JWT ----------

def issue_admin_jwt(*, label: str, kid: int, ttl_hours: int | None = None) -> tuple[str, datetime]:
    """Issue an admin JWT.

    Returns (token, expires_at).
    """
    settings = get_settings()
    ttl = ttl_hours if ttl_hours is not None else settings.jwt_ttl_hours
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=ttl)
    payload: dict[str, Any] = {
        "sub": label,
        "kid": kid,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    return token, exp


def verify_admin_jwt(token: str) -> dict[str, Any]:
    """Verify and decode an admin JWT. Raises jwt.InvalidTokenError on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
