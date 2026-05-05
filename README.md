# VPN_PIX_bot — Stage 1

> Telegram-бот для продажи VPN-подписок (NorthLine), с админ-панелью на отдельном поддомене. Текущий этап — фундамент: каркас, БД, авторизация, базовое меню.

## Архитектура

- **backend** — FastAPI + PostgreSQL + Redis. Единственная точка работы с БД и внешними API.
- **bot** — aiogram 3, ходит в backend по REST.
- **worker** — ARQ (фоновые задачи). На Stage 1 без задач, просто рабочий каркас.
- **admin** — React SPA (Vite + TS + Tailwind + shadcn/ui). Логин по ключу из `.env`, JWT.
- **nginx** — reverse proxy + SSL.
- **postgres**, **redis** — данные и кэш / FSM.

Подробнее: см. [stage1.md](./stage1.md), [README_PLAN.md](./README_PLAN.md).

## Требования

- Сервер на Debian 12+ (или Ubuntu 22+). Минимум 2 CPU / 2 GB RAM.
- Docker 24+ и Docker Compose v2.
- Доменные A-записи: `api.pixio.icu`, `admin.pixio.icu`, `webhook.pixio.icu` → IP сервера.
- Бот в [@BotFather](https://t.me/BotFather) (BOT_TOKEN).
- Telegram-канал и группа поддержки (бот — админ в обоих).

## Установка с нуля (Debian)

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. Репозиторий
git clone <repo> vpn_pix && cd vpn_pix

# 3. Конфигурация
cp .env.example .env
# Сгенерировать секреты:
openssl rand -hex 48   # для BACKEND_SERVICE_TOKEN
openssl rand -hex 48   # для JWT_SECRET
openssl rand -hex 48   # для ADMIN_INITIAL_KEY
openssl rand -base64 32   # для POSTGRES_PASSWORD, REDIS_PASSWORD
nano .env

# 4. Первый запуск (без SSL)
make build
make up
make migrate

# 5. Проверить
make ps
curl http://api.pixio.icu/health
```

## SSL (Let's Encrypt)

```bash
# Установить certbot на хост
sudo apt install -y certbot

# Остановить nginx из контейнера на порту 80
docker compose -f infra/docker-compose.yml stop nginx

# Получить сертификаты
sudo certbot certonly --standalone \
  -d api.pixio.icu -d admin.pixio.icu -d webhook.pixio.icu \
  --email you@example.com --agree-tos --non-interactive

# Скопировать в проект (или симлинком)
sudo cp -rL /etc/letsencrypt/live /Users/.../infra/nginx/ssl/

# Раскомментировать HTTPS-блоки в infra/nginx/conf.d/00-default.conf
# Перезапустить nginx
make restart s=nginx

# Авто-продление (cron)
echo "0 3 * * * certbot renew --quiet --post-hook 'docker exec vpn_pix-nginx-1 nginx -s reload'" | sudo tee /etc/cron.d/certbot-renew
```

## Команды (Makefile)

```bash
make help                # список всех команд
make up                  # поднять всё
make down                # остановить
make logs s=backend      # логи сервиса
make migrate             # применить миграции
make psql                # консоль PostgreSQL
make redis-cli           # консоль Redis
make test-backend        # тесты
```

## Первый вход в админку

1. Открыть `https://admin.pixio.icu/`.
2. Ввести значение `ADMIN_INITIAL_KEY` из `.env`.
3. Получишь JWT, сохранённый в localStorage.
4. На Stage 1 видно только пустой Dashboard и страницу настроек (ротация ключа).

## Логи

```bash
make logs s=backend          # backend
make logs s=bot              # бот
make logs s=worker           # воркер
make logs s=nginx            # nginx
make psql -c 'SELECT * FROM logs ORDER BY id DESC LIMIT 50;'
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
backend/   FastAPI + SQLAlchemy + Alembic
bot/       aiogram 3
worker/    ARQ
admin/     React SPA
infra/     docker-compose, nginx, postgres init
```
