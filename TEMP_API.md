# TEMP_API.md — Спецификация API сервиса NorthLine

> Документ для второго разработчика, реализующего backend API провайдера VPN-ключей (`api.northline.vpn`).
> Все эндпоинты вызываются нашим Backend API (не ботом напрямую).

---

## Общие требования

- **Base URL**: `https://api.northline.vpn`
- **Авторизация**: `Authorization: Bearer <PROVIDER_TOKEN>` (токен сервиса в каждом запросе)
- **Content-Type**: `application/json` для тел запросов; для GET — query-параметры
- **Кодировка**: UTF-8
- **Timeout рекомендуемый со стороны клиента**: 15 секунд
- **Идемпотентность**: см. ниже, поле `idempotency_key`
- **Возвращаемый формат**: всегда JSON
- **Коды ответа**: HTTP 2xx — успех, 4xx — ошибка клиента, 5xx — ошибка сервера

### Стандартные коды ошибок

```json
{
  "ok": false,
  "error_code": "INVALID_PROVIDER_KEY",
  "error_message": "Provider key not recognized"
}
```

| `error_code`              | HTTP | Описание                                       |
|---------------------------|------|------------------------------------------------|
| `UNAUTHORIZED`            | 401  | Невалидный или отсутствует Bearer-токен        |
| `INVALID_PROVIDER_KEY`    | 400  | Неизвестный `provider_key`                     |
| `INVALID_PARAMS`          | 400  | Некорректные параметры (дни, устройства)       |
| `KEY_NOT_FOUND`           | 404  | Подписка с таким `subscription_id` не найдена  |
| `KEY_ALREADY_DEACTIVATED` | 409  | Ключ уже деактивирован                         |
| `RATE_LIMITED`            | 429  | Слишком много запросов                         |
| `INTERNAL_ERROR`          | 500  | Внутренняя ошибка                              |

---

## 1. Создание ключа подписки

`POST /v1/keys`

### Request body
```json
{
  "provider_key": "northline_provider_uuid_or_token",
  "days": 30,
  "devices": 5,
  "idempotency_key": "uuid-генерируется-нашим-backend",
  "metadata": {
    "user_tg_id": 123456789,
    "internal_subscription_id": "sub_abc123"
  }
}
```

| Поле                | Тип    | Обязат. | Описание                                                                |
|---------------------|--------|---------|-------------------------------------------------------------------------|
| `provider_key`      | string | да      | Уникальный ключ сервиса-перепродавца (NorthLine). Идентифицирует, от какого ребрендинга пришёл запрос. |
| `days`              | int    | да      | Срок подписки в днях (3, 30, 90, 180, 365 …)                            |
| `devices`           | int    | да      | Количество устройств (1, 3, 5, 10, 16 …)                                |
| `idempotency_key`   | string | да      | UUIDv4. Повторный запрос с тем же ключом возвращает тот же результат.   |
| `metadata`          | object | нет     | Произвольные данные (для логов на стороне провайдера)                   |

### Response 200
```json
{
  "ok": true,
  "subscription_id": "northline_sub_abc123xyz",
  "key": "https://sub.pixio.icu/abcdef123456",
  "expires_at": "2026-06-03T22:30:00Z",
  "devices": 5,
  "days": 30
}
```

| Поле              | Тип    | Описание                                                  |
|-------------------|--------|-----------------------------------------------------------|
| `subscription_id` | string | Внутренний ID подписки у провайдера (для продления и т.д.)|
| `key`             | string | Готовая ссылка-ключ на нашем поддомене `sub.pixio.icu`    |
| `expires_at`      | string | ISO 8601 UTC                                              |
| `devices`         | int    | Количество устройств                                      |
| `days`            | int    | Срок                                                      |

---

## 2. Продление ключа

`POST /v1/keys/{subscription_id}/extend`

### Request body
```json
{
  "provider_key": "northline_provider_uuid",
  "days": 30,
  "idempotency_key": "uuid"
}
```

### Response 200
```json
{
  "ok": true,
  "subscription_id": "northline_sub_abc123xyz",
  "expires_at": "2026-07-03T22:30:00Z",
  "added_days": 30
}
```

> При продлении не меняется `key` и `devices`. Только увеличивается срок.

---

## 3. Деактивация ключа (полное удаление)

`POST /v1/keys/{subscription_id}/deactivate`

Используется в админке: ручная деактивация подписки (без возможности восстановления).

### Request body
```json
{
  "provider_key": "northline_provider_uuid",
  "reason": "Admin deactivation: refund issued"
}
```

### Response 200
```json
{
  "ok": true,
  "subscription_id": "northline_sub_abc123xyz",
  "deactivated_at": "2026-05-04T22:30:00Z"
}
```

---

## 4. Получение информации о ключе

`GET /v1/keys/{subscription_id}?provider_key=northline_provider_uuid`

Используется в админке для отображения статистики подписки.

### Response 200
```json
{
  "ok": true,
  "subscription_id": "northline_sub_abc123xyz",
  "key": "https://sub.pixio.icu/abcdef123456",
  "status": "active",
  "expires_at": "2026-06-03T22:30:00Z",
  "devices_total": 5,
  "devices_used": 3,
  "traffic_bytes": 12884901888,
  "lte_traffic_bytes": 5368709120,
  "devices": [
    {
      "device_id": "dev_001",
      "name": "iPhone 14",
      "platform": "ios",
      "last_seen": "2026-05-04T20:11:00Z",
      "traffic_bytes": 5368709120
    },
    {
      "device_id": "dev_002",
      "name": "MacBook Pro",
      "platform": "macos",
      "last_seen": "2026-05-04T22:01:00Z",
      "traffic_bytes": 4294967296
    }
  ]
}
```

| Поле                | Тип       | Описание                                            |
|---------------------|-----------|-----------------------------------------------------|
| `status`            | string    | `active`, `expired`, `deactivated`                  |
| `traffic_bytes`     | int       | Общий трафик в байтах                               |
| `lte_traffic_bytes` | int       | Трафик через LTE-локации (если поддерживается)      |
| `devices`           | array     | Список подключённых устройств                       |

> Если функционал статистики LTE/устройств ещё не реализован — возвращайте поля как `null` или пустой массив, наша админка готова к этому.

---

## 5. Удаление устройства

`DELETE /v1/keys/{subscription_id}/devices/{device_id}?provider_key=northline_provider_uuid`

### Response 200
```json
{
  "ok": true,
  "subscription_id": "northline_sub_abc123xyz",
  "device_id": "dev_001",
  "removed_at": "2026-05-04T22:30:00Z"
}
```

---

## 6. Healthcheck

`GET /v1/ping`

### Response 200
```json
{ "ok": true, "version": "1.0.0", "time": "2026-05-04T22:30:00Z" }
```

---

## Идемпотентность

- Все мутирующие запросы (`POST /v1/keys`, `POST .../extend`, `POST .../deactivate`) принимают `idempotency_key`.
- Если запрос с тем же `idempotency_key` уже был обработан — возвращается тот же ответ (HTTP 200), без повторного выполнения.
- TTL на хранение `idempotency_key` — минимум 24 часа.

## Безопасность

- Bearer-токен только по HTTPS.
- Логировать каждый входящий запрос с `provider_key` и `idempotency_key` (для аудита).
- Rate-limit: 60 RPS на `provider_key` (ошибка 429 при превышении).

## Будущие эндпоинты (на согласование)

- `POST /v1/keys/{subscription_id}/regenerate` — пересоздать ссылку-ключ (если юзер скомпрометировал)
- `GET /v1/stats?provider_key=...&from=...&to=...` — агрегированная статистика для нашей админки
