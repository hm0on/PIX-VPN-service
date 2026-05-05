# Stage 5 — Админ-панель (полный функционал)

> Цель этапа: веб-админка как SPA на React, через которую ты управляешь всем сервисом — статистика, юзеры, подписки/ключи, тарифы, промокоды, рассылки, тексты бота, логи. Авторизация по уникальному ключу из `.env` с возможностью ротации (старый действует ещё 3 часа).

---

## 1. Стек админ-панели

| Слой         | Технология                                            |
|--------------|-------------------------------------------------------|
| Build tool   | Vite                                                  |
| Язык         | TypeScript 5                                          |
| UI lib       | React 18                                              |
| Стили        | Tailwind CSS                                          |
| Компоненты   | shadcn/ui (Radix-based, копируются в репозиторий)     |
| State        | Zustand (глобальный) + TanStack Query (server cache)  |
| Charts       | Recharts                                              |
| Forms        | react-hook-form + zod                                 |
| HTTP         | axios + interceptor для JWT                           |
| Routing      | react-router-dom v6                                   |
| WYSIWYG      | TipTap (HTML-редактор для рассылок и текстов бота)    |
| Date         | date-fns + react-day-picker                           |
| Tables       | TanStack Table (sortable, filterable, pagination)     |
| Realtime     | Server-Sent Events (SSE) для графиков и логов         |
| Иконки       | lucide-react                                          |
| Тема         | dark mode (default) + light                           |

Локализация интерфейса — русский (можно потом добавить i18n).

---

## 2. Структура `admin/`

```
admin/
├── src/
│   ├── main.tsx
│   ├── App.tsx                  # роутинг + ProtectedRoute
│   ├── pages/
│   │   ├── Login.tsx
│   │   ├── Dashboard.tsx
│   │   ├── users/
│   │   │   ├── UsersList.tsx
│   │   │   └── UserDetail.tsx   # вкладки: Профиль, Покупки, Тикеты, Рефералы, Баланс, Подписки
│   │   ├── subscriptions/
│   │   │   ├── SubsList.tsx
│   │   │   └── SubDetail.tsx
│   │   ├── tariffs/
│   │   │   └── Tariffs.tsx
│   │   ├── promos/
│   │   │   └── Promos.tsx
│   │   ├── broadcasts/
│   │   │   ├── BroadcastsList.tsx
│   │   │   └── BroadcastEditor.tsx
│   │   ├── texts/
│   │   │   └── BotTexts.tsx
│   │   ├── logs/
│   │   │   ├── EventLogs.tsx
│   │   │   └── TechLogs.tsx
│   │   └── settings/
│   │       └── AdminKeys.tsx
│   ├── components/
│   │   ├── ui/                  # shadcn (Button, Dialog, …)
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   └── Header.tsx
│   │   └── charts/
│   ├── api/
│   │   ├── client.ts
│   │   └── endpoints/
│   ├── stores/
│   │   ├── authStore.ts
│   │   └── uiStore.ts
│   ├── hooks/
│   ├── types/
│   └── utils/
├── public/
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
└── Dockerfile                   # multi-stage: build → nginx
```

---

## 3. Авторизация

- Страница `Login.tsx`: input для admin-ключа + кнопка "Войти".
- POST `/api/admin/auth/login` → JWT, сохраняем в `localStorage` (Zustand persisted).
- Все запросы — с `Authorization: Bearer <jwt>`.
- 401 от backend → редирект на `/login`.
- Кнопка в Header "Выход" → удаляет JWT.
- Страница `Settings → Admin Keys`:
  - Список существующих ключей (label, created_at, valid_until, кнопка "Отозвать").
  - Кнопка "Сгенерировать новый ключ" → backend создаёт ключ, возвращает plaintext один раз → modal "Скопируйте ключ — он больше не будет показан".
  - Опция "Отозвать старый сейчас" / "Дать 3 часа на ротацию".

---

## 4. Layout

- Sidebar (фиксированный, collapsable):
  - 📊 Дашборд
  - 👥 Пользователи
  - 🔑 Подписки
  - 💳 Тарифы
  - 🎟 Промокоды
  - 📣 Рассылки
  - 📝 Тексты бота
  - 📋 Логи событий
  - 🔧 Технические логи
  - ⚙️ Настройки (Admin Keys, общие)
- Header: текущий админ-ключ (label), кнопка обновить, кнопка выход.

---

## 5. Дашборд

### Верхняя секция
- 4 KPI-карточки:
  - **Пользователей всего** + дельта за 24ч
  - **Активных подписок**
  - **Прибыль за месяц** (₽)
  - **Прибыль за сегодня**

### Графики
1. **Прибыль** (line chart): по дням за последние 30 / 90 / 365 дней (toggle).
2. **Пользователи** (line chart): новые регистрации по дням.

Обновление: каждые **60 секунд** через polling TanStack Query (refetchInterval). Можно переключить в "Live" режим — SSE на `/api/admin/stats/stream` (SSE keepalive каждые 30с). На старте используем polling (проще, работает за nginx без особых настроек).

### Дополнительно
- Таблица "Последние платежи" (10 шт.)
- Таблица "Последние регистрации"

---

## 6. Пользователи

### Список (`UsersList.tsx`)
- Таблица:
  - tg_id
  - username (@…)
  - first_name
  - balance
  - подписок (active count)
  - создан
  - is_banned (бейдж)
- Поиск по: tg_id, username, first_name.
- Фильтры: только забаненные / только с подписками / только с балансом > 0.
- Сортировка по любым колонкам.
- Pagination (50 на странице, server-side).
- Клик по строке → детальная страница.

### Детальная страница (`UserDetail.tsx`)
Вкладки:
1. **Профиль**:
   - tg_id, username, first_name, last_name, language_code
   - balance (с историей `balance_transactions` рядом)
   - referrer (если есть)
   - дата регистрации
   - статус (active/banned + reason)
   - Кнопки: "Заблокировать" (запрашивает reason), "Разблокировать", "Изменить баланс" (с указанием reason — пишется в `balance_transactions.reason='admin_adjust'`).
2. **Покупки** (`payments` + `subscriptions`):
   - Таблица всех платежей: дата, сумма, провайдер, статус, ссылка на подписку.
   - Кнопка "Перейти к подписке" → SubDetail.
3. **Подписки**:
   - Все подписки этого юзера (включая истёкшие/деактивированные).
   - Клик → SubDetail.
4. **Тикеты**:
   - Все тикеты юзера: code, kind, status, дата открытия, дата закрытия.
   - Клик → modal с историей переписки (или просто ссылка-jump в Telegram-топик).
5. **Рефералы**:
   - Кто его пригласил (referrer) — со ссылкой.
   - Кого пригласил он — таблица: tg_id, username, дата регистрации, paid (была ли первая платная покупка), сумма бонуса.
6. **Баланс**:
   - История `balance_transactions`.
   - Сумма пополнений / списаний.

---

## 7. Подписки / Ключи

### Список (`SubsList.tsx`)
- Колонки: id, user (clickable), tariff, devices, days, key_url (truncated), status, expires_at, created_at.
- Фильтры: status, tariff, is_free_trial, expires_at в диапазоне.
- Поиск по key, по subscription_id, по user.

### Детальная (`SubDetail.tsx`)
- Все поля подписки.
- Владелец → ссылка на UserDetail.
- Кнопки:
  - **Деактивировать ключ** (с reason, подтверждение в modal):
    - Backend → NorthLine.deactivate_key.
    - subscription.status='deactivated', deactivation_reason=...
    - Outbox → юзеру: "Ваш ключ #{id} деактивирован. Причина: {reason}".
- Секция "Статистика трафика":
  - Запрос к NorthLine.get_key → traffic_bytes, lte_traffic_bytes (если есть).
  - Если поле null/нет — показываем "Статистика недоступна".
- Секция "Устройства":
  - Список из NorthLine.get_key.devices.
  - Кнопка "Удалить" возле каждого → NorthLine.remove_device + подтверждение.

---

## 8. Тарифы

- Таблица: code, name, devices, sort_order, is_active.
- Кнопка "Создать тариф".
- Клик → редактор: name, description_html (TipTap), devices, sort_order, is_active.
- Подтаблица матрицы цен (`tariff_durations`): days, price, is_hot.
- Изменения применяются немедленно (юзер видит новые цены при следующем открытии каталога).
- На юзеров с уже созданными `Payment(status=pending)` изменения цен не влияют (цена снимается в момент создания платежа).

---

## 9. Промокоды

- Таблица: code, type, value, activations (current/max_total), max_per_user, valid_until, is_active.
- Кнопка "Создать промокод".
- Форма:
  - code (с генератором "случайный")
  - type: balance / discount_percent
  - value (₽ или %)
  - max_total_activations (NULL = безлимит)
  - max_per_user
  - valid_from / valid_until
  - description
  - is_active
- Изменение существующего промо: можно менять только `is_active`, `max_total_activations`, `max_per_user`, `valid_until`. Остальное — read-only после создания (для аудита).
- Просмотр активаций: модалка со списком (user, payment, applied_amount, дата).

---

## 10. Рассылки

### Список (`BroadcastsList.tsx`)
- Таблица: id, статус (`draft`, `scheduled`, `sending`, `done`, `cancelled`), target, scheduled_at, recipients_total, sent, failed, created_at.
- Фильтры по статусу.
- Кнопка "Создать рассылку".
- Кнопка "Отменить" (если scheduled или sending — приостанавливаем).

### Редактор (`BroadcastEditor.tsx`)
- HTML-редактор (TipTap): жирный, курсив, спойлер, ссылки, вставка `<tg-emoji emoji-id="...">`.
- Drag-and-drop поле для **одного фото** (jpg/png, до 10 МБ): можно перетянуть с компьютера.
- Кнопки сообщения: добавить inline-кнопки (text + URL); до 8 кнопок, layout — задаём количество в строке.
- **Target**: radio
  - Все пользователи бота
  - Только с активной подпиской
  - (опционально) только конкретный сегмент по фильтру
- **Дата отправки**:
  - "Отправить сейчас" (после клика — статус `sending`)
  - "Запланировать": date+time picker
- Кнопка "Превью": показывает, как будет выглядеть в Telegram (mock).
- Кнопка "Отправить тестовое мне" — присылает админу (на tg_id из admin-ключа? нет, попросим юзера ввести tg_id или возьмём из конфига `ADMIN_TG_ID`).
- Кнопка "Создать" → backend сохраняет в `broadcasts(status=draft|scheduled)`.

### Модель `broadcasts`
| Поле          | Тип          |                                          |
|---------------|--------------|------------------------------------------|
| id            | bigserial PK |                                          |
| html_text     | text         |                                          |
| photo_file_id | varchar(255) NULL |                                     |
| photo_path    | varchar(512) NULL | путь к загруженному файлу (если без file_id) |
| buttons       | jsonb NULL   | [{text, url}, …]                         |
| target        | varchar(32)  | `all`, `subscribers`                     |
| scheduled_at  | timestamptz NULL |                                      |
| status        | varchar(16)  | `draft`, `scheduled`, `sending`, `done`, `cancelled` |
| recipients_total | int default 0 |                                       |
| sent          | int default 0 |                                         |
| failed        | int default 0 |                                         |
| created_at    | timestamptz  |                                          |
| created_by_admin_key_label | varchar(64) NULL |                       |
| started_at    | timestamptz NULL |                                      |
| finished_at   | timestamptz NULL |                                      |

### `broadcast_recipients`
| Поле          | Тип          |                                          |
|---------------|--------------|------------------------------------------|
| id            | bigserial PK |                                          |
| broadcast_id  | bigint FK    |                                          |
| user_id       | bigint FK    |                                          |
| status        | varchar(16)  | `pending`, `sent`, `failed`              |
| error         | text NULL    |                                          |
| sent_at       | timestamptz NULL |                                      |

Индексы: `broadcast_id, status` (для воркера).

### Worker — рассылка
- ARQ-задача `run_broadcast(broadcast_id)`:
  - Снимает список юзеров по target → пишет в `broadcast_recipients(status=pending)`.
  - Шлёт партиями: ~25 сообщений/сек (Telegram limit 30 msg/sec для бота).
  - На каждую отправку обновляет recipient.status.
  - При rate-limit от TG (`429`) — sleep + retry.
- Cron-задача `pick_scheduled_broadcasts` (каждую минуту): находит `status=scheduled AND scheduled_at<=now()` → ставит `status=sending` и кикает воркер.

---

## 11. Тексты бота

- Таблица: key, description, value_html (truncated), updated_at.
- Клик → редактор (TipTap, HTML).
- Сохранение → `texts.value_html = ...`, инвалидация кэша Redis (бот при следующем запросе подтянет новое значение).
- Кнопка "Превью" — рендерит как в боте.

---

## 12. Логи

### События (`EventLogs.tsx`)
- Таблица из `logs`.
- Колонки: created_at, level (badge), event, module, user (clickable), message.
- Фильтры:
  - Уровень: info / warning / critical (multi-select)
  - Модуль: bot / backend / worker
  - Дата: range
  - User: поиск по tg_id/username
  - Event: dropdown с уникальными event-кодами
- Realtime обновление через SSE (опционально, на старте — авто-refresh каждые 10с).

### Технические логи (`TechLogs.tsx`)
- Таблица из `tech_logs`.
- Фильтры: trace_id (для отслеживания цепочки), service, action, user, дата.
- Клик по trace_id → группированный просмотр всей цепочки.
- Партиционирование: на старте — обычная таблица, в Stage 5+ настроим партиционирование по дате (раз в неделю), retention 30 дней.

---

## 13. Бэкап и retention

- pg_dump раз в сутки на S3-совместимое хранилище (или просто на диск + cron).
- Логи: `tech_logs` хранятся 30 дней, `logs` — 365 дней. ARQ-задача `cleanup_logs` раз в сутки.
- Брoadcast_recipients: после `done` оставляем 90 дней, потом удаляем (статистика остаётся в `broadcasts.sent/failed`).

---

## 14. Backend API эндпоинты Stage 5

### Auth (расширение Stage 1)
```
POST /api/admin/auth/keys/rotate           -> создать новый ключ, отозвать старые с grace
GET  /api/admin/auth/keys                  -> список ключей
DELETE /api/admin/auth/keys/{id}           -> отозвать сейчас
```

### Stats
```
GET /api/admin/stats/dashboard             -> KPI
GET /api/admin/stats/revenue?period=30d
GET /api/admin/stats/users?period=30d
GET /api/admin/stats/stream                -> SSE
```

### Users
```
GET /api/admin/users                       -> list, filters, pagination
GET /api/admin/users/{id}                  -> detail
GET /api/admin/users/{id}/payments
GET /api/admin/users/{id}/subscriptions
GET /api/admin/users/{id}/tickets
GET /api/admin/users/{id}/referrals
GET /api/admin/users/{id}/balance-history
POST /api/admin/users/{id}/ban
POST /api/admin/users/{id}/unban
POST /api/admin/users/{id}/balance/adjust
```

### Subscriptions
```
GET /api/admin/subscriptions
GET /api/admin/subscriptions/{id}
GET /api/admin/subscriptions/{id}/info     -> proxy to NorthLine.get_key
POST /api/admin/subscriptions/{id}/deactivate
DELETE /api/admin/subscriptions/{id}/devices/{device_id}
```

### Tariffs
```
GET    /api/admin/tariffs
POST   /api/admin/tariffs
PATCH  /api/admin/tariffs/{id}
DELETE /api/admin/tariffs/{id}
POST   /api/admin/tariffs/{id}/durations
PATCH  /api/admin/tariffs/{id}/durations/{did}
DELETE /api/admin/tariffs/{id}/durations/{did}
```

### Promos
```
GET    /api/admin/promos
POST   /api/admin/promos
PATCH  /api/admin/promos/{id}
GET    /api/admin/promos/{id}/activations
```

### Broadcasts
```
GET    /api/admin/broadcasts
POST   /api/admin/broadcasts                -> draft
PATCH  /api/admin/broadcasts/{id}
POST   /api/admin/broadcasts/{id}/photo     -> upload
POST   /api/admin/broadcasts/{id}/send      -> сразу
POST   /api/admin/broadcasts/{id}/schedule  -> отложенно
POST   /api/admin/broadcasts/{id}/cancel
POST   /api/admin/broadcasts/{id}/test      -> тестовый ТГ
GET    /api/admin/broadcasts/{id}/recipients
```

### Texts
```
GET   /api/admin/texts
PATCH /api/admin/texts/{key}
```

### Logs
```
GET /api/admin/logs/events                 -> filters, pagination
GET /api/admin/logs/events/stream          -> SSE
GET /api/admin/logs/tech                   -> filters, pagination
GET /api/admin/logs/tech/trace/{trace_id}  -> цепочка
```

---

## 15. Безопасность админки

- JWT TTL 24ч.
- Rate-limit на login (5 попыток / 15 минут на IP).
- CORS: только домен админки (`admin.pixio.icu`).
- CSP-заголовки.
- Все мутирующие запросы — POST/PATCH/DELETE с `Content-Type: application/json`.
- Аудит-лог: каждое мутирующее действие администратора → запись в `logs(event='admin_action', module='admin', context={...})`.
- Отдельный аудит-лог: какой ключ использован, какие изменения внесены.

---

## 16. Производительность

- TanStack Query кэширование на 30с для списков.
- Server-side пагинация на всех таблицах (cursor-based для logs, offset — для остальных).
- Индексы на все колонки фильтрации/сортировки.
- Партиционирование `tech_logs` по неделям (auto-create через pg_partman или ручной миграцией).
- Connection pooling: SQLAlchemy pool_size=20, max_overflow=10. На большом росте — pgBouncer.
- Redis-кэш на: список тарифов, тексты бота (TTL 60с, инвалидация при апдейте из админки).
- В рассылках: батчинг + sleep между батчами (соблюдение TG rate limit).

---

## 17. Acceptance Criteria

- [ ] Логин по ключу, JWT работает.
- [ ] Ротация ключей с grace period 3ч.
- [ ] Дашборд показывает 2 графика (прибыль, юзеры) + 4 KPI, обновление каждый час.
- [ ] Список пользователей с фильтрами и поиском.
- [ ] Детальная страница юзера со всеми вкладками.
- [ ] Бан/разбан с уведомлением юзеру.
- [ ] Корректировка баланса с reason.
- [ ] Список подписок с фильтрами.
- [ ] Деактивация ключа → NorthLine.deactivate + уведомление юзеру.
- [ ] Статистика трафика и устройств (если данные доступны).
- [ ] Удаление устройства из подписки.
- [ ] CRUD тарифов (с матрицей цен).
- [ ] CRUD промокодов.
- [ ] Создание рассылки с HTML, фото (drag-and-drop), кнопками.
- [ ] Запланированная рассылка отправляется в назначенное время.
- [ ] Отмена рассылки в очереди работает.
- [ ] Тестовая рассылка приходит админу.
- [ ] Редактирование текстов бота с моментальным применением.
- [ ] Логи событий с фильтрами по уровню, модулю, юзеру, дате.
- [ ] Технические логи с поиском по trace_id.
- [ ] Realtime/частичный realtime обновления (polling 60с минимум).
- [ ] Аудит действий админа.
- [ ] Все таблицы — server-side pagination.
- [ ] Dark/light theme.
