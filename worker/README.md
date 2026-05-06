# PIX-VPN — Worker

Фоновые задачи на **ARQ** (async Redis queue). Подключается к Redis,
открывает HTTP-клиент к backend API, ходит в Postgres напрямую только
из задач, которым нужны массовые выборки (рассылки, retention).

## Задачи

Все задачи — в `worker/app/tasks/`:

| Файл                          | Что делает                                                              |
|-------------------------------|-------------------------------------------------------------------------|
| `outbox_dispatcher.py`        | Раз в N секунд читает таблицу outbox и шлёт сообщения в Telegram. Гарантирует at-least-once. |
| `broadcasts.py`               | Запуск рассылок (`run_broadcast`) и retention-чистка логов (`cleanup_logs`). |
| `expire_payments.py`          | Маркирует «висящие» платежи как expired, если webhook не пришёл за N минут. |
| `mark_expired.py`             | Маркирует подписки expired по `expires_at`, шлёт нотификацию в outbox.  |
| `notify_expiring.py`          | За 3 дня до истечения подписки — уведомление пользователю с кнопкой «Продлить». |
| `notify_expired.py`           | Уведомление об уже истёкшей подписке.                                   |
| `reconcile_subscriptions.py`  | Сверяет наши `expires_at` со стороной NorthLine, ловит расхождения.     |
| `cleanup_idempotency.py`      | Чистит протухшие idempotency-ключи.                                     |

`common.py` — общие хелперы для задач.

Расписание (cron-стиль) задаётся в `WorkerSettings.cron_jobs` в `app/main.py`.

## Запуск

```bash
# Локально (нужен установленный backend и поднятый Redis)
arq app.main.WorkerSettings

# Через корневой compose
make logs s=worker
make restart s=worker
```

## Структура

```
worker/
├── app/
│   ├── main.py                WorkerSettings, on_startup/on_shutdown, cron_jobs
│   ├── config.py              pydantic-settings
│   ├── db.py                  async SQLAlchemy engine factory
│   ├── api_client.py          httpx.AsyncClient к backend API
│   ├── logging_setup.py       structlog → JSON
│   └── tasks/                 модули с задачами
├── pyproject.toml
└── Dockerfile
```

## Особенности

- **Outbox-pattern**: backend пишет «отправь сообщение X юзеру Y» в таблицу
  `outbox`, worker вычитывает и шлёт. Если Telegram упал — повторим.
  Идемпотентность по `outbox_id`.
- **Идемпотентность ARQ-задач**: при `_job_id`, заданном из вызывающего
  кода, повторный enqueue не создаст дубликат.
- **Логи** — JSON в stdout, попадают в `docker compose logs worker`.
