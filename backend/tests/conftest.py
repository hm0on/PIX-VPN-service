"""Test configuration: SQLite-backed in-memory DB + httpx ASGI client."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

# Set test env BEFORE importing the app.
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("BACKEND_SERVICE_TOKEN", "test_service_token_value")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_value_for_pytest_only")
os.environ.setdefault("ADMIN_INITIAL_KEY", "test_admin_initial_key_long_enough_value")
os.environ.setdefault("ADMIN_INITIAL_KEY_LABEL", "test-main")
os.environ.setdefault("ADMIN_KEY_GRACE_HOURS", "3")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("CORS_ORIGINS", "[]")
os.environ.setdefault("TECH_LOG_PERSIST", "0")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import get_settings  # noqa: E402

# IMPORTANT: re-evaluate settings (cached). Drop cache before any other module uses it.
get_settings.cache_clear()  # type: ignore[attr-defined]

from app.db import models as _models_pkg  # noqa: E402, F401  # ensure ORM registered
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest_asyncio.fixture
async def _engine_setup():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def app(_engine_setup):  # noqa: ANN001
    application = create_app()
    # Replace redis with a mock (avoid real connection in tests).
    application.state.redis = AsyncMock()
    application.state.redis.ping = AsyncMock(return_value=True)
    application.state.redis.aclose = AsyncMock(return_value=None)
    yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # noqa: ANN001
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seed_db(_engine_setup):
    """Run seeds against the in-memory DB."""
    from app.seeds import run_seeds

    await run_seeds()
    yield


@pytest.fixture
def service_token() -> str:
    return os.environ["BACKEND_SERVICE_TOKEN"]


@pytest.fixture
def admin_initial_key() -> str:
    return os.environ["ADMIN_INITIAL_KEY"]


@pytest.fixture
def auth_headers(service_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {service_token}"}
