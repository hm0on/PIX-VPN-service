# Stage 3 — Промокоды, реферальная система, продление, напоминания

> Цель этапа: retention и growth-механики. Юзер может вводить промокоды (баланс или скидка), приглашать друзей по реферальной ссылке (+100₽ ему, -10% реферуемому), продлевать подписки, получать уведомления за 3 дня до окончания.

---

## 1. Новые модели БД

### `promo_codes`
| Поле                   | Тип           | Описание                                |
|------------------------|---------------|-----------------------------------------|
| id                     | bigserial PK  |                                         |
| code                   | varchar(64) UNIQUE (CITEXT) | регистронезависимо       |
| type                   | varchar(16)   | `balance`, `discount_percent`           |
| value                  | int           | сумма в копейках (для balance) или процент (для discount) |
| max_total_activations  | int NULL      | NULL = без ограничения                  |
| max_per_user           | int default 1 |                                         |
| current_activations    | int default 0 |                                         |
| valid_from             | timestamptz NULL |                                      |
| valid_until            | timestamptz NULL |                                      |
| is_active              | boolean default true |                                  |
| created_at             | timestamptz   |                                         |
| created_by_admin_key_label | varchar(64) NULL |                                  |
| description            | text NULL     | для админки                             |

Индексы: `code`, `is_active`, `valid_until`

### `promo_activations`
| Поле          | Тип          |                                          |
|---------------|--------------|------------------------------------------|
| id            | bigserial PK |                                          |
| promo_id      | bigint FK    |                                          |
| user_id       | bigint FK    |                                          |
| payment_id    | bigint FK NULL | для discount-промо: к какой покупке применён |
| amount_applied_kopecks | bigint | для balance: сумма пополнения; для discount: размер скидки в копейках |
| created_at    | timestamptz  |                                          |

Индексы: UNIQUE(promo_id, user_id) НЕТ (есть max_per_user, могут быть несколько). Просто индексы на `promo_id`, `user_id`.

### `referrals`
| Поле          | Тип          |                                          |
|---------------|--------------|------------------------------------------|
| id            | bigserial PK |                                          |
| referrer_id   | bigint FK→users.id |                                    |
| referee_id    | bigint FK→users.id UNIQUE | реферал может быть приглашён только одним юзером |
| bonus_paid    | boolean default false | выплачены ли 100₽ рефереру      |
| bonus_paid_at | timestamptz NULL |                                       |
| referee_first_purchase_id | bigint FK→payments.id NULL |          |
| created_at    | timestamptz  |                                          |

Индексы: `referrer_id`, `referee_id`

### `notifications_sent`
Чтобы не отправлять напоминание дважды.

| Поле             | Тип          |                                       |
|------------------|--------------|---------------------------------------|
| id               | bigserial PK |                                       |
| user_id          | bigint FK    |                                       |
| subscription_id  | bigint FK    |                                       |
| kind             | varchar(32)  | `expiry_3d`, `expiry_1d`, `expired`   |
| sent_at          | timestamptz  |                                       |

UNIQUE(subscription_id, kind)

---

## 2. Промокоды

### Бот-флоу
1. После выбора длительности → переход в `{Promo}` (пока было заглушкой).
2. Текст: "Введите промокод:" + кнопка "Нет промокода".
3. Юзер либо нажимает кнопку (→ к выбору оплаты), либо отправляет промокод.
4. Backend проверяет:
   - существует ли код, активен ли, в пределах `valid_from..valid_until`
   - не превышен ли `max_total_activations`
   - не превышен ли `max_per_user` для этого юзера
5. Если всё ок:
   - **balance-промо**: моментально начисляет на баланс через `balance_transactions`, инкрементит `current_activations`, шлёт юзеру "Промокод применён, на баланс зачислено X ₽". Возврат в каталог (без продолжения покупки), потому что покупка с балансом — отдельный флоу. *(Альтернатива: продолжить покупку, оплатив с баланса, если хватает. На усмотрение пользователя.)* — **берём вариант "вернуть в главное меню", т.к. иначе UX усложняется.**
   - **discount-промо**: сохраняем в FSM-state юзера (Redis), показываем "Промокод применён: скидка 10%. Итоговая сумма: X ₽" → переход к выбору оплаты. При создании Payment запоминаем promo_id → создаём `promo_activation` после успешной оплаты.
6. Если не ок — "Этот промокод уже истёк либо не соблюдены условия." → кнопки "Ввести другой" / "Без промокода".

### Применение скидки
- Скидка — это % от цены тарифа.
- Цена платежа = `price_kopecks * (1 - discount/100)` округление вниз до копейки.
- Запись `promo_activation` создаётся **только после успешной оплаты** (webhook → paid). Иначе промо мог бы быть "потрачен" без покупки.

### Конкурентность
- При активации промо: транзакция `SELECT ... FOR UPDATE` на `promo_codes`.
- Проверка `current_activations < max_total_activations` внутри транзакции.

---

## 3. Реферальная система

### Deep-link
- Реферальная ссылка: `https://t.me/your_bot?start=ref_<referrer_user_id>`.
- В боте на `/start` парсится payload, если `ref_<id>`:
  - находим `referrer_user`
  - если новый юзер только что зарегистрировался И `referrer != referee` → создаём `referrals(referrer_id, referee_id)`
  - если юзер уже был зарегистрирован раньше — ссылка игнорируется (нельзя задним числом)

### Бонусы
- **Реферуемому (тому, кто зашёл по ссылке)**: 10% скидка на ПЕРВУЮ покупку. Реализуется как авто-промо: при первом переходе к выбору оплаты — система автоматически применяет скидку 10% (без ввода промокода). Применяется только к первой `paid` покупке. После применения — поле в `users` или вычисляется по факту наличия `payments.status=paid` для этого юзера.
- **Рефереру**: +100₽ на баланс при первой PAID покупке реферала. Триггер в обработчике webhook → `paid`:
  ```python
  if user.referrer and not referral.bonus_paid:
      credit_balance(referrer, 10000)  # 100 ₽ = 10000 копеек
      referral.bonus_paid = True
      send_outbox(referrer, "По твоей реферальной ссылке зарегистрировался @{username}, +100₽ на баланс!")
  ```
- Бонус выплачивается ОДИН РАЗ за реферала.
- FREE-триал реферала **не считается** как покупка (платёж = 0). Бонус только за платный заказ.

### В профиле
- Раздел "Профиль" получает кнопку "🎁 Реферальная программа".
- Открывает экран:
  ```html
  <b>🎁 Реферальная программа</b>

  Приглашайте друзей и получайте <b>100 ₽</b> на баланс за каждого, кто оформит подписку!
  Друзья получат скидку <b>10%</b> на первую покупку.

  Ваша ссылка:
  <code>https://t.me/your_bot?start=ref_{user_id}</code>

  Приглашено: <b>{count}</b>
  Заработано: <b>{earned} ₽</b>
  ```
  Кнопки: "Поделиться" (через `switch_inline_query`), "← Назад".

---

## 4. Продление подписки

### Бот-флоу
- В детальном экране подписки (Stage 2) кнопка "Продлить".
- Открывает выбор длительности (тариф уже зафиксирован) → промокод → оплата.
- После оплаты:
  - Backend вызывает `northline.extend_key(provider_subscription_id, days, idempotency_key)`.
  - Обновляет `subscriptions.expires_at += days`.
  - Шлёт юзеру "Подписка продлена до {новая дата}".
- Если подписка уже `expired` или `deactivated` — продлить нельзя, показываем сообщение "Подписка истекла, оформите новую".

### Уведомление за 3 дня
- ARQ-задача `notify_expiring_subscriptions` (раз в час):
  ```sql
  SELECT id, user_id FROM subscriptions
  WHERE status = 'active'
    AND expires_at BETWEEN now() + interval '2 days 23 hours' AND now() + interval '3 days 1 hour'
    AND id NOT IN (SELECT subscription_id FROM notifications_sent WHERE kind='expiry_3d')
  ```
  → outbox для каждого юзера + запись в `notifications_sent`.
- Текст (заглушка, потом отредактируете):
  ```html
  ⚠️ Ваша подписка <b>#{subscription_id}</b> закончится через <b>3 дня</b>.
  ```
  Кнопка inline: "Продлить" (deep-link → бот сразу открывает экран продления).

### Деактивация истёкших
- ARQ-задача `mark_expired_subscriptions` (раз в час):
  ```sql
  UPDATE subscriptions SET status='expired', updated_at=now()
  WHERE status='active' AND expires_at < now()
  ```
- Провайдер удаляет ключ сам (по словам юзера). Никаких вызовов `deactivate` не делаем.
- Опциональное уведомление "Ваша подписка истекла" — можно тоже добавить через `notifications_sent.kind='expired'`. **Делаем:** да, с кнопкой "Продлить" / "Купить новую".

---

## 5. Бот-флоу промокода (детально)

```
{Catalog} → выбор тарифа → {Sub-Time} → выбор длительности →
{Promo}
  Текст "Введите промокод:" + кнопка [Нет промокода]
  ├─ нажимает [Нет промокода] → {Pay}
  └─ отправляет код "ABC123"
        ├─ ok, balance-type → "Промокод применён, +X ₽" → {Main menu}
        ├─ ok, discount-type → "Скидка 10% применена, итого X ₽" → {Pay}
        └─ ошибка → "Этот промокод уже истёк либо не соблюдены условия" + [Ввести другой] [Без промокода]
```

Состояние FSM в Redis:
- `purchase:{user_id}` = `{tariff_id, duration_id, promo_id?, ref_discount_applied?}`

---

## 6. Backend API эндпоинты Stage 3

```
# Bot
POST /api/bot/promo/apply                  -> {code, user_id} → результат
GET  /api/bot/users/{tg_id}/referral-stats -> {invited, earned}
POST /api/bot/subscriptions/{id}/extend    -> создать платёж на продление
GET  /api/bot/subscriptions/{id}           -> детали подписки

# Webhook
(те же, что в Stage 2, но обрабатываем ещё и promo + referral бонусы)
```

---

## 7. Worker (ARQ) — новые задачи

| Задача                          | Расписание | Описание                                |
|---------------------------------|------------|-----------------------------------------|
| `notify_expiring_subscriptions` | каждый час | Уведомление за 3 дня и за 1 день (опц.) |
| `mark_expired_subscriptions`    | каждый час | Перевод истёкших подписок в `expired`   |
| `notify_expired_subscriptions`  | каждый час | Уведомление "Подписка истекла"          |

---

## 8. Acceptance Criteria

- [ ] Юзер вводит валидный promo-balance — на баланс приходит сумма, активации инкрементятся.
- [ ] Юзер вводит валидный promo-discount — итоговая цена снижается, после оплаты записывается `promo_activation`.
- [ ] Невалидный/истёкший/исчерпанный промокод — единое сообщение об ошибке.
- [ ] Лимиты `max_per_user` и `max_total_activations` соблюдаются под нагрузкой (race condition тестируется).
- [ ] Реферальная ссылка `?start=ref_<id>` работает на новых юзерах.
- [ ] Реферуемый получает 10% скидку только на первую paid-покупку.
- [ ] Реферер получает 100₽ при первой paid-покупке реферала + уведомление.
- [ ] FREE-триал реферала не триггерит бонус.
- [ ] Кнопка "Продлить" в профиле создаёт платёж, после оплаты `expires_at` увеличивается.
- [ ] За 3 дня до истечения — уведомление приходит ровно один раз.
- [ ] Истёкшие подписки переводятся в `expired`.
- [ ] Все денежные операции — в копейках, без float.
- [ ] Race conditions на промокодах закрыты транзакциями.
