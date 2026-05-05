# syntax=docker/dockerfile:1.7

# ===== Builder =====
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# Keep this list in sync with pyproject.toml [project.dependencies].
RUN pip install --upgrade pip wheel setuptools && \
    pip wheel --wheel-dir=/wheels \
        "fastapi>=0.115" "uvicorn[standard]>=0.30" "gunicorn>=22.0" \
        "pydantic>=2.7" "pydantic-settings>=2.4" \
        "sqlalchemy[asyncio]>=2.0.30" "asyncpg>=0.29" "alembic>=1.13" \
        "redis>=5.0" "httpx>=0.27" "structlog>=24.1" \
        "argon2-cffi>=23.1" "pyjwt[crypto]>=2.9" \
        "python-multipart>=0.0.9" "orjson>=3.10" \
        "tenacity>=8.5" "sse-starlette>=2.1" "arq>=0.26"

# ===== Runtime =====
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels

COPY --chown=app:app app /app/app
COPY --chown=app:app alembic /app/alembic
COPY --chown=app:app alembic.ini /app/alembic.ini
COPY --chown=app:app entrypoint.sh /app/entrypoint.sh

# /app/var is the writable persistence root inside the container. Broadcast
# photo uploads land in /app/var/broadcasts/<id>/<uuid>.jpg. A named volume
# is mounted here in compose so files survive image rebuilds. We pre-create
# the dir owned by `app` because the runtime user can't mkdir under /app.
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/var/broadcasts \
    && chown -R app:app /app/var

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
