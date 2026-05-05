"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bot service settings.

    Values are loaded from environment variables (and optionally a `.env`
    file in development). Names match `.env.example` from the project root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- Common ----
    ENV: str = Field(default="production")
    LOG_LEVEL: str = Field(default="INFO")

    # ---- Bot ----
    BOT_TOKEN: str

    # ---- Backend ----
    BACKEND_API_URL: str = Field(default="http://backend:8000")
    BACKEND_SERVICE_TOKEN: str

    # ---- Redis (FSM + sub-check cache) ----
    REDIS_HOST: str = Field(default="redis")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: str | None = Field(default=None)
    REDIS_DB: int = Field(default=0)

    # ---- Required Telegram channel ----
    REQUIRED_CHANNEL_ID: int
    REQUIRED_CHANNEL_URL: str

    # ---- Support group (used in Stage 4) ----
    SUPPORT_GROUP_ID: int | None = Field(default=None)
    SUPPORT_GROUP_URL: str | None = Field(default=None)

    # ---- "How to connect" link (Stage 2+) ----
    HOWTO_CONNECT_URL: str | None = Field(default=None)

    # ---- Tunables ----
    SUB_CHECK_TTL_SECONDS: int = Field(default=300)
    TEXTS_CACHE_TTL_SECONDS: int = Field(default=60)
    BACKEND_TIMEOUT_SECONDS: float = Field(default=10.0)

    @property
    def redis_url(self) -> str:
        """Return Redis URL for aiogram RedisStorage / generic redis client."""
        if self.REDIS_PASSWORD:
            return (
                f"redis://:{self.REDIS_PASSWORD}@"
                f"{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            )
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


def get_settings() -> Settings:
    """Build a Settings instance. Kept as a function to ease testing."""
    return Settings()  # type: ignore[call-arg]
