# Stage 1 — Фундамент

> Цель этапа: рабочий каркас всей системы, на который мы будем наращивать функционал в следующих этапах. После этого этапа: бот отвечает на `/start`, показывает главное меню, проверяет подписку на канал, регистрирует юзера в БД через Backend API. Админ-панель отдаёт пустые страницы с авторизацией. Все сервисы поднимаются одной командой `docker compose up`.

---

## 1. Архитектура (микросервисы)

```
┌─────────────────────────────────────────────────────────┐
│                  Telegram (clients)                     │
└──────────────────────────┬──────────────────────────────┘
                           │
                  ┌────────▼────────┐
                  │   Bot Service   │  aiogram 3.x
                  │  (long polling) │
                  └────────┬────────┘
                           │ HTTP (JWT service token)
                           │
       ┌───────────────────▼───────────────────────┐
       │           Backend API (FastAPI)           │
       │  /api/bot/*   /api/admin/*   /webhook/*   │
       └────┬───────────┬────────────┬─────────────┘
            │           │            │
       ┌────▼────┐ ┌────▼────┐  ┌────▼────────┐
       │PostgreSQL│ │  Redis  │  │  External   │
       └─────────┘ └─────────┘  │ (заглушки)  │
                                 └─────────────┘

       ┌───────────────────────────────────────────┐
       │  Admin Frontend (React SPA, Vite)         │
       │  → ходит в Backend API через REST + JWT    │
       └───────────────────────────────────────────┘

       ┌───────────────────────────────────────────┐
       │  Worker (ARQ, на Redis) — пустой пока что │
       └───────────────────────────────────────────┘
```

---

## 2. Структура репозитория (monorepo)

```
VPN_PIX_bot/
├── backend/                  # FastAPI — основной API
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── deps.py
│   │   ├── api/
│   │   │   ├── bot/          # эндпоинты для бота
│   │   │   │   ├── users.py
│   │   │   │   └── texts.py
│   │   │   ├── admin/        # эндпоинты для админки
│   │   │   │   └── auth.py
│   │   │   └── webhook/      # webhooks (Platega, CryptoBot — позже)
│   │   ├── core/
│   │   │   ├── security.py   # JWT для бота, проверка admin-ключа
│   │   │   ├── logging.py    # structlog → БД + stdout
│   │   │   └── exceptions.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py    # async engine + session factory
│   │   │   └── models/
│   │   │       ├── user.py
│   │   │       ├── tariff.py
│   │   │       ├── text.py
│   │   │       ├── log.py
│   │   │       └── admin_key.py
│   │   ├── repositories/
│   │   ├── services/
│   │   └── schemas/          # pydantic
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── bot/                      # aiogram 3
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api_client.py     # клиент к Backend API
│   │   ├── handlers/
│   │   │   └── start.py
│   │   ├── keyboards/
│   │   │   └── main_menu.py
│   │   ├── middlewares/
│   │   │   ├── user.py       # регистрация / получение юзера
│   │   │   ├── subscription_check.py  # проверка подписки на канал
│   │   │   └── logging.py
│   │   ├── states/
│   │   └── utils/
│   │       └── texts.py      # получение HTML-текстов из Backend API
│   ├── pyproject.toml
│   └── Dockerfile
│
├── worker/                   # ARQ
│   ├── app/
│   │   ├── main.py
│   │   └── tasks/            # пустой пока
│   ├── pyproject.toml
│   └── Dockerfile
│
├── admin/                    # React SPA (Vite + TS + Tailwind + shadcn/ui)
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Login.tsx
│   │   │   └── Dashboard.tsx  # пустой каркас
│   │   ├── api/client.ts      # axios + interceptor JWT
│   │   ├── components/
│   │   └── stores/
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
│
├── infra/
│   ├── nginx/
│   │   └── nginx.conf        # SSL + reverse proxy
│   ├── postgres/
│   │   └── init.sql
│   └── docker-compose.yml
│
├── .env.example
├── README.md
├── TEMP_API.md               # уже создан
└── Makefile                  # удобные команды
```

---

## 3. Стек

| Слой         | Технология                                     |
|--------------|------------------------------------------------|
| Язык         | Python 3.12                                    |
| Backend      | FastAPI 0.115+, Pydantic v2, uvicorn (gunicorn в проде) |
| ORM          | SQLAlchemy 2.0 async, asyncpg                  |
| Миграции     | Alembic                                        |
| Bot          | aiogram 3.x                                    |
| HTTP-клиент  | httpx (async)                                  |
| Background   | ARQ (Redis-based)                              |
| DB           | PostgreSQL 16                                  |
| Cache/Queue  | Redis 7                                        |
| Логи         | structlog (JSON в stdout + сохранение в БД)    |
| Admin SPA    | React 18 + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query + Zustand |
| Charts       | Recharts                                       |
| Reverse proxy| nginx + Let's Encrypt (certbot)                |
| Контейнеры   | Docker, Docker Compose                         |
| Линтеры      | ruff, mypy, eslint, prettier                   |
| Тесты        | pytest, pytest-asyncio                         |

---

## 4. База данных — модели Stage 1

### `users`
| Поле           | Тип        | Описание                                  |
|----------------|------------|-------------------------------------------|
| id             | bigserial PK |                                         |
| tg_id          | bigint UNIQUE | Telegram user id                       |
| username       | varchar(64) NULL |                                     |
| first_name     | varchar(128) NULL |                                    |
| last_name      | varchar(128) NULL |                                    |
| language_code  | varchar(8) NULL |                                      |
| balance_kopecks| bigint default 0 | Баланс в копейках (для точности)    |
| is_banned      | boolean default false |                                 |
| banned_reason  | text NULL  |                                           |
| ref_id         | bigint NULL FK→users.id | Кто пригласил                |
| created_at     | timestamptz |                                          |
| updated_at     | timestamptz |                                          |

Индексы: `tg_id`, `ref_id`, `created_at`

### `tariffs`
| Поле           | Тип        | Описание                                  |
|----------------|------------|-------------------------------------------|
| id             | serial PK  |                                           |
| code           | varchar(32) UNIQUE | `basic`, `plus`, `ultra`, `max`, `free` |
| name           | varchar(64) | "Basic", "Plus" …                        |
| description_html | text NULL |                                          |
| devices        | int        | 3, 5, 10, 16                              |
| sort_order     | int        | для отображения                           |
| is_active      | boolean default true |                                 |
| is_free_trial  | boolean default false | для FREE                       |
| free_trial_days| int NULL   | для FREE — 3                              |

### `tariff_durations` (матрица цен)
| Поле           | Тип        |                                           |
|----------------|------------|-------------------------------------------|
| id             | serial PK  |                                           |
| tariff_id      | int FK     |                                           |
| days           | int        | 30, 90, 180, 365                          |
| price_kopecks  | bigint     | цена в копейках                           |
| is_hot         | boolean    | значок 🔥                                 |
| is_active      | boolean default true |                                 |

UNIQUE(tariff_id, days)

### `texts` (HTML-тексты бота, редактируются из админки)
| Поле        | Тип         |                                         |
|-------------|-------------|-----------------------------------------|
| id          | serial PK   |                                         |
| key         | varchar(128) UNIQUE | `main_menu`, `catalog`, `pay`, … |
| value_html  | text        |                                         |
| description | text NULL   | для админа                              |
| updated_at  | timestamptz |                                         |
| updated_by  | varchar(128) NULL | название админ-ключа              |

### `logs` (для админки)
| Поле        | Тип         |                                         |
|-------------|-------------|-----------------------------------------|
| id          | bigserial PK|                                         |
| level       | smallint    | 0=info, 1=warning, 2=critical           |
| event       | varchar(128)| `payment_failed`, `key_issued`, …       |
| module      | varchar(64) | `bot`, `backend`, `worker`              |
| user_id     | bigint NULL FK→users.id |                             |
| message     | text        | HTML-safe                               |
| context     | jsonb NULL  | произвольные данные                     |
| created_at  | timestamptz |                                         |

Индексы: `level`, `module`, `user_id`, `created_at desc`, GIN на `context`

### `tech_logs` (детальные технические — отдельная таблица для производительности)
| Поле        | Тип         |                                         |
|-------------|-------------|-----------------------------------------|
| id          | bigserial PK|                                         |
| trace_id    | varchar(36) | для группировки                          |
| service     | varchar(32) | `bot`, `backend`, `worker`              |
| action      | varchar(128)| `handler:start`, `service:user.create`  |
| user_id     | bigint NULL |                                         |
| payload     | jsonb NULL  |                                         |
| duration_ms | int NULL    |                                         |
| created_at  | timestamptz |                                         |

Индексы: `trace_id`, `created_at desc`, `service`, `action`

> Партиционирование `tech_logs` по дате (раз в неделю) — настроим в Stage 5 при росте нагрузки.

### `admin_keys`
| Поле        | Тип         |                                         |
|-------------|-------------|-----------------------------------------|
| id          | serial PK   |                                         |
| key_hash    | varchar(255) UNIQUE | bcrypt/argon2 хэш ключа         |
| label       | varchar(64) | для удобства: "main", "backup-1"        |
| created_at  | timestamptz |                                         |
| revoked_at  | timestamptz NULL | при ротации                        |
| valid_until | timestamptz NULL | старый ключ действует ещё 3ч после ротации |

> На старте: 1 ключ из `.env` сидится в БД при первом запуске.

---

## 5. API эндпоинты Stage 1

### Backend API

#### Internal-only (для бота, защита через service-token из `.env`)
```
GET  /api/bot/users/{tg_id}              -> User | 404
POST /api/bot/users                      -> регистрация / upsert
GET  /api/bot/texts/{key}                -> {value_html}
GET  /api/bot/texts                      -> [{key, value_html}, ...]
GET  /api/bot/health                     -> {ok: true}
POST /api/bot/logs                       -> запись лога (от бота)
```

#### Admin (защита через JWT, выданный после авторизации по admin-ключу)
```
POST /api/admin/auth/login               -> {key} → {access_token}
POST /api/admin/auth/refresh             -> ротация ключа
GET  /api/admin/auth/me                  -> {label, valid_until}
GET  /api/admin/health                   -> {ok: true}
```

#### Public
```
GET  /health                             -> {status: "ok"}
```

---

## 6. Авторизация

### Бот ↔ Backend
- В `.env`: `BACKEND_SERVICE_TOKEN=<long_random>`.
- Бот шлёт `Authorization: Bearer <BACKEND_SERVICE_TOKEN>` на все `/api/bot/*`.
- Backend проверяет совпадение строкой через `secrets.compare_digest`.

### Админка ↔ Backend
- В `.env`: `ADMIN_INITIAL_KEY=<long_random_64_chars>`.
- При первом старте Backend хэширует ключ и пишет в `admin_keys`.
- Юзер вводит ключ на странице логина → POST `/api/admin/auth/login` → backend проверяет хэш → выдаёт JWT (access на 24ч, без refresh, ротация ключа отдельным флоу).
- JWT хранится в localStorage (для SPA это нормально, доп. защита — короткий TTL и rate-limit).
- Ротация: админ нажимает "Сменить ключ" → POST `/api/admin/auth/refresh` → backend генерирует новый ключ, кладёт в БД, старому ставит `valid_until = now + 3h`. На фронт возвращается plaintext-ключ — он показывается ОДИН РАЗ.

---

## 7. Бот — функционал Stage 1

### `/start`
1. Middleware регистрирует юзера через POST `/api/bot/users` (upsert).
2. Middleware проверяет `is_banned` — если бан, отвечает текстом и блокирует все апдейты (см. Stage 4 — добавим причину).
3. Middleware проверяет подписку на канал (см. ниже).
4. Хэндлер `/start` вытягивает текст `main_menu` из Backend API и отправляет с фото.

### Главное меню
Текст: "Интернет без границ! Основное меню:"

Кнопки (inline):
```
[ Каталог 🟦 ]   [ Профиль ]
[ Поддержка ]    [ Промокод ]
[ Предложить идею ]
[ О проекте ]
```

Цветные кнопки в Telegram реализуются через `InlineKeyboardMarkup` — на момент реализации проверим текущее API aiogram (через `KeyboardButtonColor`/`button_color` или через эмодзи как fallback). На Stage 1 кнопки уже настоящие inline, с правильным разбиением на ряды.

### Проверка подписки на канал
- ID канала из `.env`: `REQUIRED_CHANNEL_ID=-100xxxxxxxxxx`, `REQUIRED_CHANNEL_URL=https://t.me/...`.
- Middleware: `bot.get_chat_member(channel_id, user.id)` → если статус `left`/`kicked` → отправляем сообщение "Подпишитесь на канал, чтобы пользоваться ботом" с кнопками "Подписаться" + "Я подписался".
- Кэширование результата проверки в Redis на 5 минут (ключ `sub_check:{tg_id}`).
- Кнопка "Я подписался" принудительно обновляет кэш и повторяет проверку.

### Заглушки
- Все остальные кнопки отвечают: `<b>Раздел в разработке</b>` с кнопкой "Назад".

---

## 8. Логирование

### Бизнес-логи (`logs`)
- Используем в коде: `await log_service.info(event="user_registered", user_id=..., context={...})`.
- Запись и в stdout (JSON через structlog), и в БД (через отдельную фоновую очередь — на Stage 1 пишем синхронно, в Stage 5 переведём на буфер).

### Технические логи (`tech_logs`)
- Middleware на FastAPI: каждый запрос → одна запись с trace_id, action, duration_ms.
- Middleware на aiogram: каждый апдейт → запись.
- На каждый вызов сервиса/репозитория — декоратор `@traced`.

### Корреляция
- `trace_id` (UUIDv4) генерируется на входе (бот или admin), пробрасывается в Backend через заголовок `X-Trace-ID`, используется во всех логах одной операции.

---

## 9. Docker Compose

```yaml
services:
  postgres:    # 16-alpine, volume, healthcheck
  redis:       # 7-alpine, volume, healthcheck
  backend:     # depends_on: postgres, redis. Порт 8000 (за nginx)
  bot:         # depends_on: backend
  worker:      # depends_on: backend, redis
  admin:       # сборка React → отдача через nginx (статика)
  nginx:       # 80, 443 → backend + admin SPA + webhook
```

---

## 10. nginx + SSL

- nginx на хосте (или в контейнере), Let's Encrypt через certbot.
- Маршруты:
  - `https://api.pixio.icu/` → backend:8000 (для бота — внутренний, для админки — публичный)
  - `https://admin.pixio.icu/` → admin SPA (статика) + `/api/*` проксируется на backend
  - `https://webhook.pixio.icu/` → backend:8000/webhook/* (для платежек, Stage 2)
- HSTS, gzip, rate-limit на /api/admin/auth/login (5 запросов/мин).

---

## 11. Конфигурация (`.env.example`)

```env
# Common
ENV=production
LOG_LEVEL=INFO
TZ=Europe/Moscow

# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=vpn_pix
POSTGRES_USER=vpn_pix
POSTGRES_PASSWORD=<change_me>

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=<change_me>

# Backend
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
BACKEND_SERVICE_TOKEN=<long_random_64_chars>
JWT_SECRET=<long_random_64_chars>
JWT_TTL_HOURS=24

# Admin
ADMIN_INITIAL_KEY=<long_random_64_chars>
ADMIN_KEY_GRACE_HOURS=3

# Bot
BOT_TOKEN=<from @BotFather>
BACKEND_API_URL=http://backend:8000
REQUIRED_CHANNEL_ID=-1001234567890
REQUIRED_CHANNEL_URL=https://t.me/yourchannel
SUPPORT_GROUP_ID=-1001234567891          # для Stage 4
SUPPORT_GROUP_URL=https://t.me/yourgroup

# External (заглушки на Stage 1)
NORTHLINE_API_URL=https://api.northline.vpn
NORTHLINE_PROVIDER_KEY=<from_provider>
NORTHLINE_BEARER_TOKEN=<from_provider>

PLATEGA_API_KEY=<later>
PLATEGA_SHOP_ID=<later>
CRYPTOBOT_API_TOKEN=<later>
```

---

## 12. Тесты Stage 1

- `backend`: pytest + httpx AsyncClient. Покрытие: auth (login, неверный ключ, ротация), users (upsert), texts (get).
- `bot`: smoke-тест на `/start` через aiogram-test (опционально).

---

## 13. README — что должно быть

1. Описание архитектуры
2. Требования (Docker, домены, Telegram BotFather, канал)
3. Шаги установки (на чистом Debian):
   - установка Docker
   - clone repo
   - cp .env.example .env, заполнить
   - certbot для SSL
   - `docker compose up -d`
   - применение миграций
   - первый логин в админку
4. Как обновлять
5. Как смотреть логи

---

## 14. Acceptance Criteria

- [ ] `docker compose up` поднимает все сервисы без ошибок.
- [ ] Миграции применены, в БД созданы все таблицы Stage 1.
- [ ] Сидинг тарифов из конфига отрабатывает (Basic/Plus/Ultra/Max + FREE) с матрицей цен.
- [ ] Сидинг базовых текстов в `texts`.
- [ ] Сидинг первого admin-ключа из `.env`.
- [ ] Бот принимает `/start`, регистрирует юзера, показывает главное меню.
- [ ] Без подписки на канал — блокирующее сообщение с кнопкой "Я подписался".
- [ ] Логи (бизнес и технические) пишутся в БД при каждом действии.
- [ ] Админка открывается, страница логина принимает ключ из `.env` и выдаёт JWT.
- [ ] После логина — пустой Dashboard с заголовком "Готово".
- [ ] Ротация ключа работает (старый действует ещё 3 часа).
- [ ] nginx + SSL работает на всех 3 поддоменах.
- [ ] Healthchecks проходят на всех сервисах.

---

## 15. Что НЕ делаем на Stage 1 (отложено)

- Покупка, тарифы в каталоге функционально (только сидинг)
- Платёжки
- Webhook-эндпоинты для платёжек
- Промокоды, рефералка
- Тикеты поддержки
- ARQ-задачи
- Графики и страницы админки (только пустой каркас + Login)
- Деактивация подписок, статистика по ключам
