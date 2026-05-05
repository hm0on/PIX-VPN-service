"""Worker configuration loaded from environment variables.

Mirrors the relevant slice of the project's `.env` file:
- Redis connection (queue broker)
- Postgres connection (engine for future tasks)
- Backend API base URL + service token (HTTP client for future tasks)
- Common: ENV, LOG_LEVEL
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed worker settings.

    Read from environment (case-insensitive). `.env` is supported for
    local development; in Docker variables are injected by compose.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Common -----
    env: Literal["development", "staging", "production"] = Field(
        default="production", alias="ENV"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )

    # ----- Redis -----
    redis_host: str = Field(default="redis", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: SecretStr | None = Field(default=None, alias="REDIS_PASSWORD")
    redis_database: int = Field(default=0, alias="REDIS_DATABASE")

    # ----- Postgres -----
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="vpn_pix", alias="POSTGRES_DB")
    postgres_user: str = Field(default="vpn_pix", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(
        default=SecretStr(""), alias="POSTGRES_PASSWORD"
    )

    # ----- Backend API (used by future tasks) -----
    backend_api_url: str = Field(
        default="http://backend:8000", alias="BACKEND_API_URL"
    )
    backend_service_token: SecretStr = Field(
        default=SecretStr(""), alias="BACKEND_SERVICE_TOKEN"
    )

    # ----- Telegram Bot API (worker sends outbox messages directly) -----
    bot_token: SecretStr = Field(default=SecretStr(""), alias="BOT_TOKEN")

    # ----- Outbox dispatcher tuning (Stage 2) -----
    outbox_batch_size: int = Field(default=50, alias="OUTBOX_BATCH_SIZE")
    outbox_max_attempts: int = Field(default=5, alias="OUTBOX_MAX_ATTEMPTS")
    outbox_concurrency: int = Field(default=20, alias="OUTBOX_CONCURRENCY")

    # ----- Maintenance jobs tuning (Stage 2) -----
    payment_pending_ttl_minutes: int = Field(
        default=30, alias="PAYMENT_PENDING_TTL_MINUTES"
    )
    idempotency_keys_ttl_hours: int = Field(
        default=24, alias="IDEMPOTENCY_KEYS_TTL_HOURS"
    )

    # ----- ARQ tuning -----
    arq_max_jobs: int = Field(default=10, alias="ARQ_MAX_JOBS")
    arq_job_timeout_seconds: int = Field(default=120, alias="ARQ_JOB_TIMEOUT")
    arq_keep_result_seconds: int = Field(default=600, alias="ARQ_KEEP_RESULT")
    arq_queue_name: str = Field(default="default", alias="ARQ_QUEUE_NAME")

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL using asyncpg driver."""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
