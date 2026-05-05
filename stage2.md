# Stage 2 — Каталог, оплата, выдача ключей, FREE-триал

> Цель этапа: основной денежный поток работает end-to-end. Юзер заходит в каталог, выбирает тариф и срок, оплачивает (СБП через Platega / крипту через Platega / CryptoBot / баланс), получает ключ и инструкцию. Также работает FREE-триал. Промокоды и рефералка — в Stage 3.

---

## 1. Новые модели БД

### `subscriptions`
| Поле                  | Тип          | Описание                                |
|-----------------------|--------------|-----------------------------------------|
| id                    | bigserial PK |                                         |
| user_id               | bigint FK    |                                         |
| tariff_id             | int FK       | NULL для FREE? Нет, FREE тоже tariff    |
| tariff_duration_id    | int FK NULL  | NULL для FREE                           |
| provider_subscription_id | varchar(128) UNIQUE NULL | от NorthLine        |
| key_url               | text NULL    | `https://sub.pixio.icu/...`             |
| devices               | int          | копия из тарифа на момент покупки       |
| days                  | int          | копия                                   |
| status                | varchar(16)  | `pending`, `active`, `expired`, `deactivated`, `failed` |
| started_at            | timestamptz NULL |                                     |
| expires_at            | timestamptz NULL |                                     |
| deactivated_at        | timestamptz NULL |                                     |
| deactivation_reason   | text NULL    |                                         |
| is_free_trial         | boolean default false |                                |
| created_at            | timestamptz  |                                         |
| updated_at            | timestamptz  |                                         |

Индексы: `user_id`, `status`, `expires_at`, `provider_subscription_id`

### `payments`
| Поле                  | Тип          | Описание                                |
|-----------------------|--------------|-----------------------------------------|
| id                    | bigserial PK |                                         |
| user_id               | bigint FK    |                                         |
| subscription_id       | bigint FK NULL | Привязка к подписке (NULL для пополнения баланса) |
| purpose               | varchar(32)  | `subscription`, `topup`                 |
| provider              | varchar(32)  | `platega_sbp`, `platega_crypto`, `cryptobot`, `balance` |
| external_id           | varchar(128) UNIQUE NULL | ID платежа у провайдера     |
| amount_kopecks        | bigint       |                                         |
| currency              | varchar(8)   | `RUB`                                   |
| status                | varchar(16)  | `pending`, `paid`, `failed`, `expired`, `refunded` |
| meta                  | jsonb        | invoice URL, raw response               |
| paid_at               | timestamptz NULL |                                     |
| created_at            | timestamptz  |                                         |
| updated_at            | timestamptz  |                                         |

Индексы: `user_id`, `status`, `external_id`, `created_at desc`

### `balance_transactions`
| Поле                | Тип           | Описание                                |
|---------------------|---------------|-----------------------------------------|
| id                  | bigserial PK  |                                         |
| user_id             | bigint FK     |                                         |
| amount_kopecks      | bigint        | положительное = зачисление, отрицательное = списание |
| reason              | varchar(32)   | `topup`, `purchase`, `referral_bonus`, `promo_bonus`, `refund`, `admin_adjust` |
| ref_payment_id      | bigint FK NULL|                                         |
| ref_subscription_id | bigint FK NULL|                                         |
| description         | text NULL     |                                         |
| balance_after_kopecks | bigint      | для аудита                              |
| created_at          | timestamptz   |                                         |

Индексы: `user_id`, `reason`, `created_at desc`

### `outbox`
Для надёжной отправки сообщений из бота (если бот лежит — воркер ретраит).

| Поле          | Тип          |                                          |
|---------------|--------------|------------------------------------------|
| id            | bigserial PK |                                          |
| user_id       | bigint FK    |                                          |
| chat_id       | bigint       |                                          |
| message_type  | varchar(16)  | `text`, `photo`, `document`              |
| payload       | jsonb        | текст, кнопки, file_id, parse_mode       |
| status        | varchar(16)  | `pending`, `sent`, `failed`              |
| attempts      | int default 0|                                          |
| last_error    | text NULL    |                                          |
| send_after    | timestamptz  | для отложенной отправки                  |
| sent_at       | timestamptz NULL |                                      |
| created_at    | timestamptz  |                                          |

Индексы: `status`, `send_after`

### `idempotency_keys`
| Поле          | Тип          |                                          |
|---------------|--------------|------------------------------------------|
| key           | varchar(64) PK|                                         |
| operation     | varchar(64)  | `northline_create`, …                    |
| response      | jsonb        |                                          |
| created_at    | timestamptz  | TTL 24ч (cleanup воркером)               |

---

## 2. Бот — флоу покупки

### Каталог
Кнопка "Каталог" в главном меню → отправка картинки + текст "Каталог" + кнопки (1 столбец):
```
[ FREE — 3 дня ]
[ Basic — 3 устройства ]
[ Plus — 5 устройств ]
[ Ultra — 10 устройств ]
[ Max — 16 устройств ]
[ ← Назад ]
```

### Длительность (для платных)
После выбора тарифа → картинка + текст "Выберите длительность" + 4 кнопки:
```
[ 1 месяц — 189 ₽ ]
[ 3 месяца — 459 ₽ 🔥 ]
[ 6 месяцев — 1190 ₽ ]
[ 12 месяцев — 1590 ₽ ]
[ ← Назад ]
```
Цены и эмодзи 🔥 берутся из `tariff_durations`.

### Промокод (заглушка для Stage 2)
Текст "Введите промокод:" + кнопка "Нет промокода".
На Stage 2 — кнопка "Нет промокода" сразу ведёт дальше; ввод промо игнорируется с ответом "Раздел в разработке".

### Способ оплаты
Картинка + текст "Выберите способ оплаты" + 4 кнопки в 2 столбца (синие):
```
[ СБП ]            [ CryptoBot ]
[ Криптовалюта ]   [ Баланс ]
```
Если на балансе < суммы заказа — кнопка "Баланс" показывается серой/неактивной (или при нажатии — сообщение "Недостаточно средств. Текущий баланс: X ₽. Пополните в профиле").

### После оплаты (sucess)
Картинка + текст:
```html
✅ Вы успешно оплатили заказ <b>#{payment_id}</b>

Ваш ключ:
<code>{key_url}</code>
```
Кнопка inline: "Как подключиться" → ссылка на пост в канале (`HOWTO_CONNECT_URL` из `.env`).

### Профиль
Кнопка "Профиль" → текст с балансом + список активных подписок:
```
👤 Ваш профиль

Баланс: <b>500 ₽</b>

Активные подписки:
```
Кнопки (в 1 столбце):
```
[ Plus, до 03.06.2026 ]
[ Ultra, до 14.07.2026 ]
[ ➕ Оформить ещё ]
[ 💰 Пополнить баланс ]
[ ← Назад ]
```

При клике на подписку — детали (тариф, устройства, дата окончания, ключ) + кнопки "Продлить" (Stage 3) и "Как подключиться".

---

## 3. FREE-триал

- Кнопка "FREE — 3 дня" в каталоге.
- Проверка: не было ли FREE-триала у этого `tg_id` (по `subscriptions.is_free_trial=true AND user_id=...`).
- Если был — отвечаем: "Бесплатный пробный период уже был использован."
- Если нет — сразу вызов NorthLine API: `days=3, devices=3, provider_key=...`
- Создаём `Subscription(is_free_trial=true, status=active, ...)`.
- Шлём ключ юзеру тем же сообщением, что и после оплаты.

---

## 4. Платёжки

### Platega (СБП и крипта)
> Документация: https://platega.io (читаем актуальную). Ниже — обобщённая интеграция.

- `POST /create_invoice` → передаём `amount, currency=RUB, payment_method=sbp|crypto, callback_url, success_url, order_id`.
- Получаем `payment_url`, отдаём юзеру в кнопке "Оплатить".
- Webhook `POST /webhook/platega` от Platega → проверка подписи (HMAC-SHA256 от тела с секретом из `.env`), проверка статуса, обновление `Payment`, триггер выдачи ключа.
- Идемпотентность: external_id уникален, повторный webhook не дублирует.

### CryptoBot
- API: https://help.crypt.bot/crypto-pay-api
- `POST createInvoice` с `currency_type=fiat, fiat=RUB, amount=...` — CryptoBot сам конвертирует в крипту при оплате.
- Webhook `POST /webhook/cryptobot` → проверка подписи `crypto-pay-api-signature` (HMAC-SHA256 с токеном).
- Выдача ключа после `invoice_paid`.

### Оплата с баланса
- Атомарная транзакция:
  1. Lock пользователя `SELECT ... FOR UPDATE`.
  2. Проверка `balance_kopecks >= price`.
  3. Списание (`balance_transactions` запись + обновление `users.balance_kopecks`).
  4. Создание `Payment(provider='balance', status='paid')`.
  5. Создание `Subscription(status='pending')`.
  6. Вызов NorthLine API.
  7. Обновление `Subscription(status='active', key_url=...)`.
  8. Outbox-сообщение юзеру.
- Если NorthLine упал — откат списания, возврат на баланс, отправка юзеру сообщения "Не удалось выдать ключ, средства возвращены на баланс".

### Пополнение баланса
- В профиле "Пополнить баланс" → ввод суммы (минимум 10 ₽) → выбор метода (СБП / CryptoBot / Crypto через Platega).
- После оплаты — зачисление на баланс через `balance_transactions`.

---

## 5. Архитектура флоу оплаты

```
Юзер → Бот → Backend.create_payment(...)
                    │
                    ├─ создаёт Payment(status=pending)
                    ├─ создаёт Subscription(status=pending) [для subscription-purpose]
                    ├─ вызывает Platega/CryptoBot.create_invoice
                    └─ возвращает payment_url

Бот → шлёт юзеру кнопку с payment_url

[пользователь оплачивает]

Платёжка → POST /webhook/{provider} → Backend
                    │
                    ├─ проверка подписи
                    ├─ идемпотентность (external_id)
                    ├─ обновление Payment(status=paid)
                    ├─ для subscription:
                    │     ├─ NorthLine.create_key(idempotency_key=...)
                    │     ├─ обновление Subscription(status=active, key_url)
                    │     └─ outbox: ключ юзеру
                    └─ для topup:
                          ├─ balance_transaction
                          └─ outbox: "Баланс пополнен на X ₽"
```

---

## 6. NorthLine API клиент

```python
class NorthLineClient:
    def __init__(self, base_url, bearer_token, provider_key):
        ...

    async def create_key(self, days: int, devices: int, idempotency_key: str, metadata: dict) -> KeyResponse:
        # POST /v1/keys, retries 3x с exponential backoff на 5xx/timeout
        ...

    async def extend_key(self, subscription_id: str, days: int, idempotency_key: str) -> ExtendResponse:
        ...

    async def deactivate_key(self, subscription_id: str, reason: str) -> DeactivateResponse:
        ...

    async def get_key(self, subscription_id: str) -> KeyInfo:
        ...

    async def remove_device(self, subscription_id: str, device_id: str) -> None:
        ...
```

Особенности:
- httpx с timeout=15s, connect_timeout=5s.
- Retry на сетевые ошибки и 5xx (max 3, backoff 1s, 2s, 4s).
- На 4xx — никаких retry, raise NorthLineClientError.
- Все вызовы логируются в `tech_logs` с trace_id.

---

## 7. Worker (ARQ) — задачи Stage 2

| Задача                    | Расписание | Описание                                               |
|---------------------------|------------|--------------------------------------------------------|
| `outbox_dispatcher`       | каждые 5с  | Берёт `outbox.status=pending AND send_after<=now()`, отсылает в TG, обновляет статус. Ретрай при ошибке (max 5 попыток с backoff). |
| `expire_pending_payments` | каждые 5 мин | `payments.status=pending AND created_at < now()-30min` → status=`expired`. Если есть subscription_id → status=`failed`. |
| `cleanup_idempotency`     | каждый час | Удаляет `idempotency_keys` старше 24ч.                |

---

## 8. Backend API эндпоинты Stage 2

```
# Bot
GET  /api/bot/tariffs                              -> [{tariff + durations}]
POST /api/bot/purchase/start                        -> создаёт Payment+Subscription, возвращает payment_url
POST /api/bot/purchase/balance                      -> покупка с баланса (sync)
POST /api/bot/free-trial                            -> выдача FREE-триала
POST /api/bot/topup/create                          -> создание платежа на пополнение
GET  /api/bot/users/{tg_id}/subscriptions           -> [{subscription}]
GET  /api/bot/users/{tg_id}/balance                 -> {balance_kopecks}

# Webhooks
POST /webhook/platega                               -> webhook Platega
POST /webhook/cryptobot                             -> webhook CryptoBot
```

---

## 9. Безопасность

- Все webhook-эндпоинты проверяют подпись провайдера; невалидные — 403.
- Rate-limit на `/webhook/*` (100 req/min per IP) — защита от перегрузки.
- IP allowlist для webhook (опционально, если у Platega/CryptoBot фиксированные IP).
- Логируем каждый webhook (даже невалидный) в `tech_logs`.
- Транзакции БД на критических операциях с `SELECT ... FOR UPDATE`.
- Все суммы — в копейках, никаких float.

---

## 10. Обработка ошибок (юзер-friendly)

| Ситуация                       | Сообщение юзеру                                                |
|--------------------------------|----------------------------------------------------------------|
| Platega/CryptoBot не отвечает  | "Похоже, оплата временно недоступна. Попробуйте позже или обратитесь в поддержку." |
| NorthLine упал после оплаты    | "Оплата прошла, но возникла техническая ошибка с выдачей ключа. Обратитесь в поддержку — мы всё решим." (плюс лог уровня critical, плюс уведомление админу — на Stage 5) |
| Недостаточно баланса           | "Недостаточно средств на балансе. Текущий баланс: X ₽. Пополните баланс в профиле." |
| FREE уже активирован           | "Бесплатный пробный период уже был использован на этом аккаунте." |
| Webhook с невалидной подписью  | 403 (никакого пользовательского ответа)                        |

Все технические детали — только в логах.

---

## 11. Acceptance Criteria

- [ ] Юзер видит каталог с актуальными ценами из БД.
- [ ] Можно купить любой тариф через СБП (Platega) — после оплаты приходит ключ.
- [ ] Можно купить через крипту Platega.
- [ ] Можно купить через CryptoBot.
- [ ] Можно купить с баланса (если хватает).
- [ ] Можно пополнить баланс (минимум 10 ₽) — баланс обновляется после webhook.
- [ ] FREE-триал выдаётся ровно 1 раз на `tg_id`.
- [ ] Параллельные подписки работают независимо.
- [ ] При ошибке NorthLine после оплаты средства не теряются (баланс — возврат, платёжка — лог критический + сообщение юзеру).
- [ ] Webhook'и идемпотентны: повторный приход не создаёт дубль.
- [ ] Outbox надёжно доставляет сообщения юзеру (даже если бот рестартует).
- [ ] Профиль показывает актуальный баланс и активные подписки.
- [ ] Кнопка "Как подключиться" ведёт на пост в канале.
- [ ] Все тексты в боте — HTML (parse_mode=HTML), редактируются через таблицу `texts`.
- [ ] Логи всех операций (бизнес и технические) пишутся.
