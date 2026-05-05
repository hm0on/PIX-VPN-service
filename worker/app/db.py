"""Async SQLAlchemy engine factory for the worker.

The engine is created once on worker startup and stored in the ARQ
context (`ctx["db_engine"]`). Tasks (Stage 2+) acquire short-lived
sessions via `make_session_factory(engine)`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build an async SQLAlchemy engine from settings.

    `pool_pre_ping=True` keeps connections healthy across long idle
    periods (the worker may sit idle for hours waiting for cron jobs).
    """
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the given engine."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
