# VPN_PIX_bot — Worker (ARQ)

Background worker built on **ARQ** (Async Redis Queue).

## Stage 1 (current)

No tasks. The worker is a fully functional skeleton that:

- Connects to Redis (with retries) and Postgres.
- Opens an `httpx.AsyncClient` to Backend API for future use.
- Logs JSON to stdout via `structlog`.
- Logs `Worker started, no jobs configured` on startup and idles.

## Run

```bash
# Locally
arq app.main.WorkerSettings

# Docker (built from this directory)
docker build -t vpn-pix-worker .
docker run --rm --env-file ../.env vpn-pix-worker
```

In `docker-compose` the service depends on `redis` and `backend` healthchecks.

## Layout

```
worker/
├── pyproject.toml
├── Dockerfile
├── .dockerignore
└── app/
    ├── __init__.py
    ├── main.py            # WorkerSettings, on_startup/on_shutdown
    ├── config.py          # pydantic-settings
    ├── db.py              # async SQLAlchemy engine factory
    ├── api_client.py      # httpx client to Backend API
    ├── logging_setup.py   # structlog → JSON
    └── tasks/
        └── __init__.py    # empty until Stage 2+
```
