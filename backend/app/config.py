"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic-based settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Common
    env: Literal["production", "development", "test"] = "production"
    log_level: str = "INFO"
    tz: str = "Europe/Moscow"

    # Postgres
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "vpn_pix"
    postgres_user: str = "vpn_pix"
    postgres_password: str = "change_me"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_database: int = Field(default=0, alias="REDIS_DATABASE")

    # ARQ — must match the worker's queue, otherwise enqueued jobs vanish
    # into ARQ's default `arq:queue` while the worker polls a custom one.
    arq_queue_name: str = Field(default="default", alias="ARQ_QUEUE_NAME")

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_service_token: str = "change_me_to_long_random_64_chars"
    jwt_secret: str = "change_me_to_long_random_64_chars"
    jwt_ttl_hours: int = 24
    # NoDecode tells pydantic-settings v2 NOT to attempt JSON-parsing the raw env
    # value before our before-validator runs. Without this, `CORS_ORIGINS=a,b`
    # raises JSONDecodeError because the source layer treats list[str] as "complex".
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
    )

    # Admin
    admin_initial_key: str = "change_me_to_long_random_64_chars"
    admin_initial_key_label: str = "main"
    admin_key_grace_hours: int = 3
    admin_key_grace_hours_default: int = 3
    admin_tg_id: int | None = None

    # Bot (used by other services, kept here for ENV cohesion)
    bot_token: str | None = None
    backend_api_url: str | None = None
    required_channel_id: str | None = None
    required_channel_url: str | None = None
    support_group_id: str | None = None
    support_group_url: str | None = None
    howto_connect_url: str | None = None

    # NorthLine (reseller API)
    northline_api_url: str | None = None
    northline_provider_key: str | None = None
    northline_bearer_token: str | None = None
    # When true, ``NorthLineClient.create_key`` adds ``"test": true`` so the
    # provider returns a fake subscription without debiting the reseller
    # balance. Useful for end-to-end smoke tests in staging. Keep ``false``
    # in production.
    northline_test_mode: bool = False

    # Platega
    platega_api_key: str = ""
    platega_shop_id: str = ""
    platega_secret: str = ""
    platega_api_url: str = "https://api.platega.io"

    # CryptoBot
    cryptobot_api_token: str = ""
    cryptobot_api_url: str = "https://pay.crypt.bot/api"
    cryptobot_testnet: bool = False

    # Payments common
    payment_pending_ttl_minutes: int = 30
    public_webhook_base_url: str = ""
    public_bot_username: str = ""

    # Optional override of database URL (for tests).
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Sync URL for Alembic offline mode (rarely used here)."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
