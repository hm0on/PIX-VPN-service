################################################################
# VPN_PIX_bot — Worker (ARQ) — Stage 1
################################################################
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONHASHSEED=random \
    TZ=Europe/Moscow

# ---- system deps ----
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# ---- non-root user ----
RUN groupadd --system --gid 1000 worker \
    && useradd  --system --uid 1000 --gid worker --create-home --home-dir /home/worker worker

WORKDIR /app

# ---- python deps (install first for cache) ----
COPY --chown=worker:worker pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install \
        "arq>=0.26" \
        "redis>=5.0" \
        "pydantic>=2.7" \
        "pydantic-settings>=2.4" \
        "sqlalchemy[asyncio]>=2.0.30" \
        "asyncpg>=0.29" \
        "httpx>=0.27" \
        "structlog>=24.1" \
        "orjson>=3.10"

# ---- source ----
COPY --chown=worker:worker app ./app

USER worker

# tini для корректного PID 1 + проброс сигналов
ENTRYPOINT ["/usr/bin/tini", "--", "arq", "app.main.WorkerSettings"]
