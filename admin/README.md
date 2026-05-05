# VPN PIX — Admin SPA

Минимальная админ-панель Stage 1 (React 18 + Vite + TypeScript + Tailwind + shadcn/ui).

На текущем этапе:
- Страница **Login** — вход по уникальному admin-ключу из `.env` (`ADMIN_INITIAL_KEY`).
- Пустой **Dashboard** с заголовком «Готово» и карточками-заглушками.
- Страница **Settings → Admin Keys** — просмотр ключей, ротация, отзыв.

Полный функционал админки (юзеры, тарифы, рассылки, графики и т.д.) — в Stage 5.

---

## Локальная разработка

Требования: Node.js 20+, npm 10+.

```bash
cd admin
npm install
npm run dev
```

Dev-сервер слушает на `http://localhost:5173`. Запросы `/api/*` проксируются
на `http://localhost:8000` (Backend FastAPI). Перенастроить можно в `vite.config.ts`.

Если бэкенд работает на другом адресе — задайте переменную окружения:

```bash
echo "VITE_API_BASE_URL=http://localhost:8000/api" > .env.local
```

### Команды

| Команда           | Что делает                                |
|-------------------|-------------------------------------------|
| `npm run dev`     | Vite dev-server с HMR                     |
| `npm run build`   | Production-сборка в `dist/`               |
| `npm run preview` | Просмотр прод-сборки локально             |
| `npm run lint`    | ESLint                                    |
| `npm run format`  | Prettier                                  |

---

## Production-сборка (Docker)

Используется multi-stage `Dockerfile`:

1. `node:20-alpine` — `npm ci` + `npm run build`. `VITE_API_BASE_URL` задаётся через `--build-arg`.
2. `nginx:1.27-alpine` — статика + SPA-фоллбэк (`try_files $uri $uri/ /index.html`).

Из корня проекта:

```bash
docker build \
  --build-arg VITE_API_BASE_URL=https://admin.pixio.icu/api \
  -t vpn-pix-admin ./admin
docker run -p 8080:80 vpn-pix-admin
```

В `docker-compose.yml` (см. `infra/docker-compose.yml`) аргумент сборки
прокидывается из переменной окружения `VITE_API_BASE_URL` из `.env`.

---

## Архитектура

```
src/
├── api/
│   ├── client.ts          # axios instance, interceptors, X-Trace-ID
│   └── endpoints/auth.ts  # login / me / rotate / list / revoke
├── components/
│   ├── ui/                # shadcn-стиль примитивы
│   ├── layout/            # Sidebar, Header, AppShell
│   └── ProtectedRoute.tsx
├── lib/utils.ts           # cn(), uuidv4()
├── pages/                 # Login, Dashboard, AdminKeys, NotFound
├── stores/authStore.ts    # Zustand + persist (localStorage)
├── App.tsx                # роутинг
├── main.tsx               # провайдеры
└── index.css              # Tailwind + CSS variables (dark theme)
```

JWT хранится в `localStorage` через Zustand persist. На каждый запрос
добавляются заголовки `Authorization: Bearer ...` и `X-Trace-ID: <uuidv4>`.
При ответе 401 автоматически делается logout и редирект на `/login`.
