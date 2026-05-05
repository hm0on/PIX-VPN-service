# Деплой PIX-VPN на pix-app.xyz

> Инфра-гайд: DNS, TLS, первый запуск, webhook'и провайдеров.
> SSH-доступ к серверу — в [../SECURITY.md](../SECURITY.md).

## Архитектура доменов

| Хост / путь | Что |
|---|---|
| `https://pix-app.xyz/` | корень — глухая 404 (никаких намёков на админку) |
| `https://pix-app.xyz/<slug>/` | **админ-SPA** (slug — рандомный, из `ADMIN_PATH_SLUG`) |
| `https://pix-app.xyz/<slug>/api/` | API админки (proxy → backend) |
| `https://pix-app.xyz/how-to-connect` | публичный гайд по подключению |
| `https://pix-app.xyz/privacy` | политика конфиденциальности |
| `https://pix-app.xyz/terms` | пользовательское соглашение |
| `https://api.pix-app.xyz/webhook/<provider>` | webhook'и платёжных провайдеров |
| `https://sub.pix-app.xyz` | **НЕ наш** — API NorthLine, уже настроен у провайдера |

`<slug>` — это `ADMIN_PATH_SLUG` из `.env`. Сменить — три места:

1. `ADMIN_PATH_SLUG` + `VITE_BASE_PATH` + `VITE_API_BASE_URL` в `.env`
2. `location /<slug>/ ...` в `nginx/conf.d/00-default.conf` (4 location-блока)
3. `docker compose build admin && docker compose up -d admin nginx`

## 1. DNS-записи

| Тип | Имя | Значение | TTL |
|-----|-----|----------|-----|
| A | `pix-app.xyz` (или `@`) | `<IP_сервера>` | 300 |
| A | `api` | `<IP_сервера>` | 300 |
| A | `sub` | *(уже настроен на API NorthLine — не трогать)* | — |

Запись `www` не заводи — лишний поинт сканирования. IPv6 — параллельно `AAAA`.

Проверка: `dig +short pix-app.xyz` и `dig +short api.pix-app.xyz` должны вернуть IP сервера.

## 2. Файрвол и SSH

См. [SECURITY.md](../SECURITY.md). Кратко: нужны открытые `80/tcp`, `443/tcp` и `<SSH_PORT>/tcp` (SSH).

## 3. Положить проект на сервер

```bash
git clone https://github.com/hm0on/pix_vpn_service.git /opt/pix_vpn_service
cd /opt/pix_vpn_service
cp .env.example .env
# Заполнить обязательные поля:
#   BOT_TOKEN, ADMIN_TG_ID, REQUIRED_CHANNEL_ID, SUPPORT_GROUP_ID,
#   HOWTO_CONNECT_URL, PUBLIC_BOT_USERNAME, PUBLIC_WEBHOOK_BASE_URL,
#   ADMIN_PATH_SLUG, VITE_BASE_PATH, VITE_API_BASE_URL,
#   NORTHLINE_PROVIDER_KEY, NORTHLINE_BEARER_TOKEN,
#   PLATEGA_* / CRYPTOBOT_API_TOKEN (по выбранным провайдерам).
# Сгенерировать секреты:
#   openssl rand -hex 48      # BACKEND_SERVICE_TOKEN, JWT_SECRET, ADMIN_INITIAL_KEY
#   openssl rand -base64 32   # POSTGRES_PASSWORD, REDIS_PASSWORD
nano .env
```

## 4. Получить TLS-сертификат (Let's Encrypt SAN)

Один сертификат на 2 имени.

Первый запуск — поднимаем nginx без HTTPS-блоков, чтобы прошёл ACME challenge:

```bash
cd /opt/pix_vpn_service/infra
# временно: закомментируй все HTTPS server-блоки в nginx/conf.d/00-default.conf
docker compose up -d nginx

docker run --rm \
  -v /opt/pix_vpn_service/infra/nginx/ssl:/etc/letsencrypt \
  -v /opt/pix_vpn_service/infra/nginx/certbot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  --email you@pix-app.xyz --agree-tos --no-eff-email \
  -d pix-app.xyz \
  -d api.pix-app.xyz

# верни HTTPS-блоки и перезапусти
docker compose restart nginx
```

Сертификат лёг в `infra/nginx/ssl/live/pix-app.xyz/{fullchain,privkey}.pem` —
ровно по тому пути, что прописан в `00-default.conf`.

### Автообновление

В crontab сервера (под root):

```cron
17 3 * * * docker run --rm \
  -v /opt/pix_vpn_service/infra/nginx/ssl:/etc/letsencrypt \
  -v /opt/pix_vpn_service/infra/nginx/certbot:/var/www/certbot \
  certbot/certbot renew --quiet \
  && docker compose -f /opt/pix_vpn_service/infra/docker-compose.yml exec nginx nginx -s reload
```

## 5. Поднять весь стек

```bash
cd /opt/pix_vpn_service
make build
make up
make migrate
make ps                 # все healthy
make logs s=bot         # бот стартанул, getMe прошёл
```

Проверки:

- `curl -sI https://pix-app.xyz/` → `404 Not Found` (так и должно быть)
- `curl -sI https://api.pix-app.xyz/webhook/` → 4xx (порт открыт, путь не для GET)
- `curl -sI https://pix-app.xyz/<slug>/` → `200 OK`, в теле — index.html SPA
- `https://pix-app.xyz/<slug>/` в браузере → форма логина
- бот в Telegram → отвечает на `/start`

## 6. Webhook'и платёжных провайдеров

В личных кабинетах:

- **Platega**: callback URL → `https://api.pix-app.xyz/webhook/platega`
- **CryptoBot**: webhook URL → `https://api.pix-app.xyz/webhook/cryptobot`

(Совпадает с `${PUBLIC_WEBHOOK_BASE_URL}/webhook/<provider>` из `.env`.)

## 7. Первый вход в админку

1. Открыть `https://pix-app.xyz/<slug>/` (slug — из `.env`).
2. Логин — значение `ADMIN_INITIAL_KEY` из `.env`.
3. В разделе «Ключи доступа» создать **новый** ключ, выдать пользователю,
   старый initial — отозвать (с grace 3 ч., как в `ADMIN_KEY_GRACE_HOURS`).

## 8. Telegram-настройки

- **Бот** должен быть админом в:
  - канале `REQUIRED_CHANNEL_ID` (право `can_invite_users` достаточно для проверки подписки),
  - группе `SUPPORT_GROUP_ID` с правом `manage_topics` (Topics в группе должны быть **включены**).
- В `@BotFather` → `/setprivacy` → **Disable** (бот должен видеть сообщения в группе поддержки).

## 9. Сменить slug админки

1. Сгенерировать новый: `python3 -c "import secrets; print(''.join(secrets.choice('abcdefghijkmnpqrstuvwxyz23456789') for _ in range(8)))"`
2. В `.env` обновить `ADMIN_PATH_SLUG`, `VITE_BASE_PATH=/<new>/`, `VITE_API_BASE_URL=/<new>/api`.
3. В `nginx/conf.d/00-default.conf` заменить все вхождения старого slug'а на новый (4 location-блока).
4. `docker compose build admin && docker compose up -d admin nginx`.
