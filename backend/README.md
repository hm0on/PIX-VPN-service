# PIX-VPN Backend

FastAPI service. Единственная точка работы с БД и внешними API
(NorthLine, Platega, CryptoBot). Постгрес 16 + Redis 7 (FSM, ARQ, кэш).
SQLAlchemy 2.0 async + asyncpg, Alembic, structlog (JSON-логи).

## Что снаружи

| Префикс       | Auth                  | Кто использует                  |
|---------------|-----------------------|---------------------------------|
| `/api/bot/*`  | `Bearer <service_token>` | bot, worker                  |
| `/api/admin/*`| `Bearer <jwt>`        | admin SPA                       |
| `/webhook/*`  | подпись провайдера    | Platega, CryptoBot              |
| `/health`     | публичный             | мониторинг / nginx healthcheck  |

Полный список эндпоинтов и схемы — в Swagger:
`http://localhost:8000/docs` локально или внутри docker-сети.

## Локально

Удобнее запускать через корневой `Makefile` (см. `make help` в корне репо):

```bash
make up                 # backend + зависимости
make migrate            # alembic upgrade head
make logs s=backend
make psql               # консоль БД
make test-backend       # pytest
make lint-backend       # ruff + mypy
make shell-backend      # bash в контейнере
```

`entrypoint.sh` ждёт Postgres, накатывает миграции, прогоняет
идемпотентные сиды (`python -m app.seeds`, тарифы и базовые тексты)
и стартует uvicorn.

## Структура

```
backend/
├── alembic/              миграции
├── app/
│   ├── api/
│   │   ├── bot/          /api/bot/* (service-token auth)
│   │   ├── admin/        /api/admin/* (JWT)
│   │   ├── webhook/      /webhook/<provider>
│   │   └── health.py
│   ├── core/             конфиг, security, deps
│   ├── db/               модели SQLAlchemy
│   ├── services/         бизнес-логика (покупки, баланс, NorthLine, рефералы…)
│   ├── schemas/          pydantic-схемы
│   ├── seeds.py          идемпотентные сиды
│   └── main.py
├── tests/                pytest
└── Dockerfile
```

## Особенности

- **Все деньги — в копейках** (BIGINT в БД, никаких float).
- **Тексты бота — в БД**, редактируются админкой без редеплоя.
- **Outbox-pattern**: отправки в Telegram пишутся в outbox-таблицу, worker
  вычитывает и шлёт. При падении — реплей.
- **Идемпотентность**: каждый платёж и каждая операция NorthLine ходят с
  `idempotency_key`, повторы не дублируют ключи.
- **Reconcile-cron**: worker сверяет наши `expires_at` со стороной NorthLine,
  тащит расхождения в логи.
- **Аудит-лог** (таблица `event_log`) — всё, что видно в админке.
