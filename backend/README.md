# VPN_PIX Backend (Stage 1)

FastAPI service: bot-facing endpoints (`/api/bot/*`, service-token auth) and admin
endpoints (`/api/admin/*`, JWT auth). Postgres 16 + Redis 7. SQLAlchemy 2.0 async + asyncpg.

## Local run

```bash
cp ../.env.example ../.env   # configure values
docker compose up -d backend
```

The container's `entrypoint.sh` waits for Postgres, runs `alembic upgrade head`,
runs idempotent seeds (`python -m app.seeds`) and starts uvicorn.

## Tests

```bash
pip install -e .[dev]
pytest -v
```

## Endpoints (Stage 1)

- `GET  /health` — public
- `GET  /api/bot/health`           (Bearer service token)
- `POST /api/bot/users`            upsert by tg_id
- `GET  /api/bot/users/{tg_id}`
- `GET  /api/bot/texts`
- `GET  /api/bot/texts/{key}`
- `POST /api/bot/logs`
- `POST /api/admin/auth/login`     `{key}` → `{access_token, ...}`
- `POST /api/admin/auth/refresh`   rotate key (returns plaintext once)
- `GET  /api/admin/auth/me`
- `GET  /api/admin/auth/keys`
- `DELETE /api/admin/auth/keys/{id}`
- `GET  /api/admin/health`         (JWT)
