# PIX-VPN

Telegram-бот для продажи VPN-подписок (через провайдера NorthLine) с
веб-админкой и фоновыми задачами. Запускается одной командой через Docker
Compose.

> Прод: [`pix-app.xyz`](https://pix-app.xyz). Бот: [@pix_vpn_robot](https://t.me/pix_vpn_robot).
> Доступ к серверу и SSH-настройки — см. [SECURITY.md](./SECURITY.md).
> Деплой и DNS — см. [infra/DEPLOY.md](./infra/DEPLOY.md).

## Архитектура

```
┌──────────────┐  long-poll   ┌───────────┐    HTTP+JWT    ┌──────────┐
│   Telegram   │ ───────────► │    bot    │ ─────────────► │ backend  │
└──────────────┘              │ (aiogram) │                │ (FastAPI)│
                              └───────────┘                └────┬─────┘
                                                                │
       ┌────────────────────────────────────────────────────────┤
       │                                                        │
  ┌────▼──────┐                                            ┌────▼─────┐
  │  worker   │  ARQ tasks: broadcasts, expiry-notify,     │ Postgres │
  │   (ARQ)   │  outbox, reconcile, cleanup                │   16     │
  └─────┬─────┘                                            └──────────┘
        │                                                  ┌──────────┐
        └────────────────── Redis 7 ──────────────────────►│  Redis   │
                                                            └──────────┘

  ┌──────────────┐                                       ┌──────────────┐
  │  admin SPA   │ ◄── nginx (reverse proxy + TLS) ────► │ public web   │
  │ React + Vite │     /privacy, /terms, /how-to-connect │ static pages │
  └──────────────┘                                       └──────────────┘
```

| Сервис      | Что делает                                                            |
|-------------|-----------------------------------------------------------------------|
| **backend** | FastAPI. Единственная точка работы с БД и внешними API. Эндпоинты `/api/bot/*` (service token), `/api/admin/*` (JWT), `/webhook/*` (платежи). |
| **bot**     | aiogram 3, long-polling. Каталог, покупки, профиль, поддержка-тикеты, рефералы, промокоды. |
| **worker**  | ARQ. Рассылки, уведомления о подписках, outbox для надёжной отправки в Telegram, retention-чистка логов, реконсил со стороны NorthLine. |
| **admin**   | React 18 + Vite + Tailwind + shadcn/ui. Дашборд, юзеры, подписки/ключи, тарифы, промокоды, рассылки, тексты бота, логи. |
| **nginx**   | Reverse-proxy + TLS. Отдаёт админку, проксирует API, держит публичные страницы (`/privacy`, `/terms`, `/how-to-connect`). |
| **postgres / redis** | Данные, FSM, очередь ARQ.                                    |

Технологии: Python 3.12, PostgreSQL 16, Redis 7, Docker, nginx + Let's Encrypt.

## Принципы

- Бот **не ходит в БД напрямую**, только через backend API.
- Все деньги — в **копейках**, никаких float.
- Все тексты бота — **в БД** (HTML, редактируются из админки без редеплоя).
- Идемпотентность платежей и outbox-pattern для отправок в Telegram.
- Все суммы и состояния — **аудит-лог**, видимый в админке.

## Требования

- Сервер на Debian 12+ или Ubuntu 22+. Минимум 2 CPU / 2 GB RAM (на 1 GB упирается в OOM при рассылках).
- Docker 24+ и Docker Compose v2.
- Доменные A-записи: `pix-app.xyz`, `api.pix-app.xyz` → IP сервера.
- Бот в [@BotFather](https://t.me/BotFather) (`BOT_TOKEN`).
- Telegram-канал и группа поддержки (бот — админ в обоих, в группе включены Topics).

## Установка с нуля

Полный гайд (DNS, TLS, проверки) — в [infra/DEPLOY.md](./infra/DEPLOY.md). Кратко:

```bash
# 1. Поставить Docker
curl -fsSL https://get.docker.com | sh

# 2. Клонировать
git clone https://github.com/hm0on/pix_vpn_service.git /opt/pix_vpn_service
cd /opt/pix_vpn_service

# 3. Конфиг
cp .env.example .env
# Сгенерировать секреты:
openssl rand -hex 48     # BACKEND_SERVICE_TOKEN, JWT_SECRET, ADMIN_INITIAL_KEY
openssl rand -base64 32  # POSTGRES_PASSWORD, REDIS_PASSWORD
nano .env

# 4. Поднять (см. DEPLOY.md про порядок с TLS)
make up
make migrate
```

## Команды (Makefile)

```bash
make help                # список всех команд
make up                  # поднять всё
make down                # остановить
make ps                  # статус контейнеров
make logs s=backend      # логи сервиса (backend|bot|worker|admin|nginx|postgres|redis)
make restart s=backend   # рестарт сервиса
make build               # пересобрать образы
make migrate             # применить миграции
make makemigration m="msg" # создать новую миграцию
make psql                # консоль PostgreSQL
make redis-cli           # консоль Redis
make test-backend        # тесты бэка
make lint-backend        # ruff + mypy
make lint-admin          # eslint
make admin-dev           # фронт локально (vite dev на :5173)
make admin-build         # production-сборка фронта
```

## Обновление

```bash
git pull
make build
make migrate
make up
```

## Структура

```
backend/        FastAPI + SQLAlchemy 2.0 async + Alembic
bot/            aiogram 3
worker/         ARQ
admin/          React SPA (Vite + TS + Tailwind + shadcn/ui)
infra/          docker-compose, nginx-конфиги, статические страницы, TLS
SECURITY.md     SSH/firewall/fail2ban — как заходить на сервер
```

В каждом сервисе свой README с локальными командами и описанием.

## Публичные страницы

- [`/how-to-connect`](https://pix-app.xyz/how-to-connect) — гайд по подключению клиентов VPN.
- [`/privacy`](https://pix-app.xyz/privacy) — политика конфиденциальности.
- [`/terms`](https://pix-app.xyz/terms) — пользовательское соглашение.

Все три — статический HTML в `infra/nginx/static/<name>/`, монтируется в
nginx, локейшены в `infra/nginx/conf.d/00-default.conf`.
