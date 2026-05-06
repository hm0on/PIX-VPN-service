# PIX-VPN — Admin SPA

Веб-админка: React 18 + Vite + TypeScript + Tailwind + shadcn/ui.

## Что внутри

- **Login** — вход по уникальному admin-ключу (`ADMIN_INITIAL_KEY` или
  любой из ротированных).
- **Dashboard** — KPI + графики выручки и регистраций, последние платежи и юзеры.
- **Users** — список с пагинацией/поиском, детальная карточка с подвкладками
  (платежи, подписки, тикеты, рефералы, история баланса), бан/разбан с
  уведомлением в боте.
- **Subscriptions** — все ключи NorthLine, деактивация, удаление устройств.
- **Tariffs** — CRUD тарифов и длительностей.
- **Promos** — промокоды (на баланс / процент-скидка), лимиты, активация.
- **Broadcasts** — рассылки с TipTap-WYSIWYG, фото, расписанием, очередью и
  отменой; сегментация (все / только с подпиской / etc).
- **Texts** — редактор всех текстов бота (HTML).
- **Logs** — фильтруемые событийные логи + технические (отдельная вкладка),
  стрим через SSE.
- **Settings → Admin Keys** — просмотр, ротация (старый действует ещё
  `ADMIN_KEY_GRACE_HOURS`), отзыв.

JWT хранится в `localStorage` через Zustand persist. На каждый запрос
идут заголовки `Authorization: Bearer ...` и `X-Trace-ID: <uuidv4>`.
401 → автоматический logout и редирект на `/login`.

## Стек

| Слой          | Технология                                            |
|---------------|-------------------------------------------------------|
| Build tool    | Vite                                                  |
| Язык          | TypeScript 5                                          |
| UI            | React 18 + shadcn/ui (Radix)                          |
| Стили         | Tailwind CSS                                          |
| State         | Zustand (глобальный) + TanStack Query (server cache)  |
| Forms         | react-hook-form + zod                                 |
| Routing       | react-router-dom v6                                   |
| Charts        | Recharts                                              |
| Tables        | TanStack Table                                        |
| WYSIWYG       | TipTap                                                |
| HTTP          | axios + interceptors                                  |
| Realtime      | Server-Sent Events для графиков и логов               |
| Иконки        | lucide-react                                          |

## Локально

Требования: Node.js 20+, npm 10+.

```bash
cd admin
npm install
npm run dev          # http://localhost:5173, /api/* проксируется на :8000
```

Если бэкенд на другом адресе:

```bash
echo "VITE_API_BASE_URL=http://localhost:8000/api" > .env.local
```

| Команда            | Что делает                                |
|--------------------|-------------------------------------------|
| `npm run dev`      | Vite dev-server с HMR                     |
| `npm run build`    | Production-сборка в `dist/`               |
| `npm run preview`  | Просмотр прод-сборки локально             |
| `npm run lint`     | ESLint                                    |
| `npm run format`   | Prettier                                  |

Из корня репо есть алиасы: `make admin-dev`, `make admin-build`, `make lint-admin`.

## Production-сборка (Docker)

Multi-stage `Dockerfile`:

1. `node:20-alpine` — `npm ci` + `npm run build`.
   `VITE_API_BASE_URL` и `VITE_BASE_PATH` задаются через `--build-arg`.
2. `nginx:1.27-alpine` — статика + SPA-фоллбэк (`try_files $uri $uri/ /index.html`).

Аргументы сборки прокидываются из `.env` через `infra/docker-compose.yml`.
SPA отдаётся nginx'ом по пути `/<ADMIN_PATH_SLUG>/` — slug секретный, в
`infra/DEPLOY.md` описано как менять.

## Структура

```
src/
├── api/
│   ├── client.ts          axios instance, interceptors, X-Trace-ID
│   └── endpoints/         модули по фичам
├── components/
│   ├── ui/                shadcn-стиль примитивы
│   ├── layout/            Sidebar, Header, AppShell
│   └── ProtectedRoute.tsx
├── lib/                   утилиты
├── pages/
│   ├── Dashboard.tsx
│   ├── Login.tsx
│   ├── users/             список + детальная
│   ├── subscriptions/
│   ├── tariffs/
│   ├── promos/
│   ├── broadcasts/
│   ├── texts/
│   ├── logs/
│   └── settings/          (admin keys и пр.)
├── stores/                Zustand
├── App.tsx                роутинг
└── main.tsx               провайдеры
```
