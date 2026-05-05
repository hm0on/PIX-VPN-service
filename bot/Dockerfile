FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# System deps (minimal): curl for diag, tzdata for timezone
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --system --gid 1000 botuser \
 && useradd --system --uid 1000 --gid botuser --home /app --shell /usr/sbin/nologin botuser

# Install dependencies first (better layer cache)
COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install \
        "aiogram>=3.13,<4.0" \
        "httpx>=0.27,<1.0" \
        "redis>=5.0,<6.0" \
        "pydantic>=2.7,<3.0" \
        "pydantic-settings>=2.4,<3.0" \
        "structlog>=24.1,<25.0" \
        "orjson>=3.10,<4.0" \
        "tenacity>=9.0,<10.0"

# Copy source
COPY app ./app

# Drop privileges
RUN chown -R botuser:botuser /app
USER botuser

# Long polling — no healthcheck (bot just polls Telegram)
ENTRYPOINT ["python", "-m", "app.main"]
